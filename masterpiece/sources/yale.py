"""Yale adapter: Yale Center for British Art + Yale University Art Gallery, via LUX.

Search:  https://lux.collections.yale.edu/api/search/item?q=<JSON>  (Linked Art search, no key)
         classification "paintings", memberOf the museum, hasDigitalImage, optional text
Object:  the LUX record (title, artist, date, links) + its IIIF manifest at
         manifests.collections.yale.edu/<ycba|yuag>/obj/<n> (image size, IIIF service)
Images:  IIIF Image API 2 at images.collections.yale.edu
License: only works whose manifest says "Copyright Statement: Public domain". (The manifest's
         `rights` field is CC0 for every record: that covers the metadata, not the image,
         and is also set for paintings still under copyright, so it is not used.)
Limits:  no colour or period search: periods are checked on the dates afterwards.
         Each painting costs 2 requests, so results are cached for 30 days.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .. import cache, content
from ..models import Artwork, Results
from ..net import get_json
from ._ids import Stream, Union, UnionCache

KEY = "yale"
NAME = "Yale (British Art & Art Gallery)"
LICENSE = "Public domain"
HOMEPAGE = "https://lux.collections.yale.edu/"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("images.collections.yale.edu",)
REGIONS = {"europe", "americas"}

SEARCH = "https://lux.collections.yale.edu/api/search/item"
PAGE_SIZE = 16           # objects resolved per page (each needs 2 requests the first time)
MAX_WIDTH = 3840
PREVIEW_WIDTH = 843
OBJECT_TTL = 30 * cache.DAY
MUSEUMS = {"ycba": "Yale Center for British Art", "yuag": "Yale University Art Gallery"}
REGION_MUSEUMS = {"europe": ["ycba"], "americas": ["yuag"]}
MANIFEST = re.compile(r"^https://manifests\.collections\.yale\.edu/(ycba|yuag)/obj/\d+$")
# LUX's "paintings" also holds ink drawings and prints: keep only works made with paint
PAINT = re.compile(r"\b(oil|oils|tempera|acrylic|gouache|watercolou?rs?|encaustic|distemper|casein)\b", re.I)


# ------------------------------------------------------------------ ID streams

def _fetch_ids(state):
    q, page = state
    data = get_json(SEARCH, params={"q": json.dumps(q), "page": page, "pageLength": 50})
    ids = [it["id"] for it in data.get("orderedItems") or [] if it.get("id")]
    total = int(((data.get("partOf") or [{}])[0]).get("totalItems") or 0)
    return ids, ((q, page + 1) if ids and page * 50 < total else None)


_unions = UnionCache()


def _queries(query: str, subject: str | None, region: str | None) -> list[dict]:
    words = [w for w in [query.strip(), content.SUBJECTS.get(subject, {}).get("keyword")] if w]
    out = []
    chosen = [m for r in sorted(content.regions_of(region)) for m in REGION_MUSEUMS.get(r, [])]
    for museum in list(dict.fromkeys(chosen)) or list(MUSEUMS):
        terms = [{"classification": {"name": "paintings"}}, {"memberOf": {"name": MUSEUMS[museum]}},
                 {"hasDigitalImage": 1}] + [{"text": w} for w in words]
        out.append({"AND": terms})
    return out


def _union_for(queries: list[dict]) -> Union:
    return _unions.get(json.dumps(queries, sort_keys=True), lambda: Union(
        [Stream(_fetch_ids, (q, 1)) for q in queries], interleave=True))


# ------------------------------------------------------------------ objects

_objects: OrderedDict = OrderedDict()
_objects_lock = threading.Lock()


def _maker(o: dict) -> str:
    pb = o.get("produced_by") or {}
    people = [p for p in pb.get("carried_out_by") or []]
    for part in pb.get("part") or []:
        primary = any((c.get("_label") or "") == "Primary Artist" for c in part.get("classified_as") or [])
        for p in part.get("carried_out_by") or []:
            people.insert(0, p) if primary else people.append(p)
    name = re.sub(r"^(artist|maker|painter)\s*:\s*", "", (people[0].get("_label") if people else "") or "", flags=re.I)
    return "Unknown artist" if not name or name.lower() == "unknown" else name


def _year(o: dict) -> tuple[str, int | None]:
    ts = (o.get("produced_by") or {}).get("timespan") or {}
    shown = next((n.get("content") for n in ts.get("identified_by") or [] if n.get("content")), "")
    m = re.match(r"-?\d{1,4}", ts.get("begin_of_the_begin") or "")
    return shown, (int(m.group()) if m else None)


def _links(o: dict) -> list[str]:
    return [ap.get("id") or "" for s in o.get("subject_of") or [] for d in s.get("digitally_carried_by") or []
            for ap in d.get("access_point") or []]


def _metadata(manifest: dict) -> dict:
    out = {}
    for x in manifest.get("metadata") or []:
        label = ((x.get("label") or {}).get("en") or [""])[0]
        value = ((x.get("value") or {}).get("en") or [""])[0]
        out[label.lower()] = value
    return out


def _to_artwork(lux_id: str, o: dict, manifest_url: str, m: dict) -> Artwork | None:
    md = _metadata(m)
    if md.get("copyright statement", "").strip().lower() != "public domain":
        return None                              # still under copyright, or unknown
    if not PAINT.search(md.get("medium", "")):
        return None                              # a drawing or print, not a painting
    canvas = (m.get("items") or [{}])[0]
    try:
        body = canvas["items"][0]["items"][0]["body"]
        service = (body.get("service") or [{}])[0]
        iiif = service.get("@id") or service.get("id")
        w, h = int(canvas.get("width") or body.get("width")), int(canvas.get("height") or body.get("height"))
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not iiif or not iiif.startswith("https://images.collections.yale.edu/") or not w or not h:
        return None
    museum = MANIFEST.match(manifest_url).group(1)
    shown, _ = _year(o)
    dl_w = min(w, MAX_WIDTH)
    page = next((l for l in _links(o) if l.startswith(("https://collections.britishart.yale.edu/",
                                                      "https://artgallery.yale.edu/"))), "")
    return Artwork(
        id=f"{KEY}-{museum}-{manifest_url.rsplit('/', 1)[-1]}", source=KEY,
        title=o.get("_label") or md.get("title") or "Untitled", maker=_maker(o), year=shown,
        museum=MUSEUMS[museum],
        image_url=f"{iiif}/full/{dl_w},/0/default.jpg",
        preview_url=f"{iiif}/full/{PREVIEW_WIDTH},/0/default.jpg",
        thumb_url=f"{iiif}/full/400,/0/default.jpg",
        width=dl_w, height=round(h * dl_w / w), license="Public domain",
        link=page or lux_id.replace("/data/object/", "/view/object/"),
        text=f"{o.get('_label', '')} {md.get('medium', '')}"[:content.TEXT_CHARS],
    )


def _resolve(lux_id: str) -> tuple[Artwork | None, int | None]:
    """(painting, start year) for one LUX object: memory → disk cache (30 days) → 2 requests."""
    with _objects_lock:
        if lux_id in _objects:
            return _objects[lux_id]
    key = f"yale:obj:{lux_id.rsplit('/', 1)[-1]}"
    hit = cache.kv().get(key, OBJECT_TTL)
    if hit is not None:
        res = (Artwork.from_dict(hit["art"]) if hit.get("art") else None, hit.get("year"))
    else:
        try:
            o = get_json(lux_id)
            manifest = next((l for l in _links(o) if MANIFEST.match(l)), None)
            art = _to_artwork(lux_id, o, manifest, get_json(manifest)) if manifest else None
            res = (art, _year(o)[1])
        except Exception:
            return None, None                    # transient: don't cache
        cache.kv().set(key, {"art": res[0].to_dict() if res[0] else None, "year": res[1]})
    with _objects_lock:
        _objects[lux_id] = res
        while len(_objects) > 5000:
            _objects.popitem(last=False)
    return res


# ------------------------------------------------------------------ search

def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    union = _union_for(_queries(query, subject, region))
    start = (max(1, page) - 1) * limit
    ids, more = union.slice(start, start + limit)
    with ThreadPoolExecutor(max_workers=2) as ex:      # = the host limit in net.py
        found = list(ex.map(_resolve, ids))
    p = content.PERIODS.get(period)
    out = [a for a, year in found if a and (not p or (year is not None and p["start"] <= year < p["end"]))]
    return Results(out, more=more)
