"""J. Paul Getty Museum adapter (Linked Art + SPARQL, no key).

Search:  https://data.getty.edu/museum/collection/sparql  (paintings, AAT 300033618, with an
         image; text matches the title or the artist in the production's label)
Object:  the Linked Art record (title, artist, date, links) + its IIIF v3 manifest at
         media.getty.edu (image size, IIIF service, rights)
Images:  IIIF Image API at media.getty.edu, often 6000-9000 px
License: Getty Open Content. Only works whose manifest says the images are "believed to be in
         the public domain" under CC0 are used (the record's own CC0 covers the metadata only),
         and, to be safe, nothing made after 1930.
HTTPS:   data.getty.edu doesn't send its intermediate certificate; net.py uses `truststore`
         (Windows' own certificate check), which fills it in like a browser does.
"""

from __future__ import annotations

import re
import threading
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .. import cache, content
from ..models import Artwork, Results
from ..net import get_json
from ._ids import Stream, Union, UnionCache

KEY = "getty"
NAME = "J. Paul Getty Museum"
LICENSE = "CC0 (Open Content)"
HOMEPAGE = "https://www.getty.edu/projects/open-content-program/"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("media.getty.edu",)
REGIONS = {"europe"}            # almost entirely European paintings

SPARQL = "https://data.getty.edu/museum/collection/sparql"
PAGE_SIZE = 16
BATCH = 50
MAX_WIDTH = 3840
PREVIEW_WIDTH = 843
LATEST_YEAR = 1930
OBJECT_TTL = 30 * cache.DAY
PAINTING = "http://vocab.getty.edu/aat/300033618"


# ------------------------------------------------------------------ ID stream

def _escape(s: str) -> str:
    """For a SPARQL string literal: no quotes, backslashes or line breaks."""
    return re.sub(r"[\"\\\n\r]", " ", s)[:80]


def _sparql(words: list[str], offset: int) -> str:
    filters = "".join(
        f'FILTER(CONTAINS(LCASE(STR(?label)), "{w}") || CONTAINS(LCASE(STR(?prodLabel)), "{w}"))\n'
        for w in (_escape(content.fold(w)) for w in words) if w)
    return f"""PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?obj WHERE {{
  ?obj a crm:E22_Human-Made_Object ; crm:P2_has_type <{PAINTING}> ;
       rdfs:label ?label ; crm:P138i_has_representation ?rep .
  OPTIONAL {{ ?obj crm:P108i_was_produced_by ?prod . ?prod rdfs:label ?prodLabel }}
  {filters}}} ORDER BY ?obj LIMIT {BATCH} OFFSET {offset}"""


def _fetch_ids(state):
    words, offset = state
    data = get_json(SPARQL, params={"query": _sparql(words, offset), "format": "json"})
    ids = [b["obj"]["value"] for b in (data.get("results") or {}).get("bindings") or []]
    return ids, ((words, offset + BATCH) if len(ids) == BATCH else None)


_unions = UnionCache()


def _union_for(words: list[str]) -> Union:
    return _unions.get(repr(words), lambda: Union([Stream(_fetch_ids, (words, 0))]))


# ------------------------------------------------------------------ objects

_objects: OrderedDict = OrderedDict()
_objects_lock = threading.Lock()


def _title(o: dict) -> str:
    for n in o.get("identified_by") or []:
        if n.get("type") == "Name" and n.get("content"):
            return n["content"]
    return re.sub(r"\s*\([\w.]+\)\s*$", "", o.get("_label") or "") or "Untitled"     # drop "(77.PA.127)"


def _maker(o: dict) -> str:
    pb = o.get("produced_by") or {}
    people = list(pb.get("carried_out_by") or [])
    for part in pb.get("part") or []:
        people += part.get("carried_out_by") or []
    if people and people[0].get("_label"):
        return people[0]["_label"]
    m = re.match(r"Production of Artwork by (.+)$", pb.get("_label") or "")
    return m.group(1) if m else "Unknown artist"


def _year(o: dict) -> tuple[str, int | None]:
    ts = (o.get("produced_by") or {}).get("timespan") or {}
    shown = next((n.get("content") for n in ts.get("identified_by") or [] if n.get("content")), "")
    m = re.match(r"-?\d{1,4}", ts.get("begin_of_the_begin") or "") or re.search(r"\d{4}", shown or "")
    return shown, (int(m.group()) if m else None)


def _manifest_url(o: dict) -> str | None:
    for s in o.get("subject_of") or []:
        for url in (s.get("has_format"), s.get("id")):
            if url and url.startswith("https://media.getty.edu/iiif/manifest/3/"):
                return url
    return None


def _homepage(o: dict) -> str:
    for s in o.get("subject_of") or []:
        if (s.get("id") or "").startswith("https://www.getty.edu/art/collection/"):
            return s["id"]
    return o.get("id") or ""


def _open_content(m: dict) -> bool:
    if "publicdomain/zero" not in (m.get("rights") or ""):
        return False
    stmt = " ".join(((m.get("requiredStatement") or {}).get("value") or {}).get("en") or [])
    return "public domain" in stmt.lower()


def _to_artwork(o: dict, m: dict) -> Artwork | None:
    shown, year = _year(o)
    if not _open_content(m) or (year is not None and year > LATEST_YEAR):
        return None
    canvas = (m.get("items") or [{}])[0]
    try:
        body = canvas["items"][0]["items"][0]["body"]
        service = (body.get("service") or [{}])[0]
        iiif = service.get("id") or service.get("@id")
        w, h = int(canvas.get("width") or body.get("width")), int(canvas.get("height") or body.get("height"))
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not iiif or not iiif.startswith("https://media.getty.edu/") or not w or not h:
        return None
    dl_w = min(w, MAX_WIDTH)
    oid = (o.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
    title = _title(o)
    return Artwork(
        id=f"{KEY}-{oid}", source=KEY, title=title, maker=_maker(o), year=shown, museum=NAME,
        image_url=f"{iiif}/full/{dl_w},/0/default.jpg",
        preview_url=f"{iiif}/full/{PREVIEW_WIDTH},/0/default.jpg",
        thumb_url=f"{iiif}/full/400,/0/default.jpg",
        width=dl_w, height=round(h * dl_w / w), license="CC0",
        link=_homepage(o), text=title[:content.TEXT_CHARS],
    )


def _resolve(obj_url: str) -> tuple[Artwork | None, int | None]:
    with _objects_lock:
        if obj_url in _objects:
            return _objects[obj_url]
    key = f"getty:obj:{obj_url.rsplit('/', 1)[-1]}"
    hit = cache.kv().get(key, OBJECT_TTL)
    if hit is not None:
        res = (Artwork.from_dict(hit["art"]) if hit.get("art") else None, hit.get("year"))
    else:
        try:
            o = get_json(obj_url)
            man = _manifest_url(o)
            art = _to_artwork(o, get_json(man)) if man else None
            res = (art, _year(o)[1])
        except Exception:
            return None, None                    # transient: don't cache
        cache.kv().set(key, {"art": res[0].to_dict() if res[0] else None, "year": res[1]})
    with _objects_lock:
        _objects[obj_url] = res
        while len(_objects) > 5000:
            _objects.popitem(last=False)
    return res


# ------------------------------------------------------------------ search

def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    words = content.fold(query).split()
    if subject in content.SUBJECTS:
        words.append(content.SUBJECTS[subject]["keyword"])
    union = _union_for(words)
    start = (max(1, page) - 1) * limit
    ids, more = union.slice(start, start + limit)
    with ThreadPoolExecutor(max_workers=2) as ex:      # = the host limit in net.py
        found = list(ex.map(_resolve, ids))
    p = content.PERIODS.get(period)
    out = [a for a, year in found if a and (not p or (year is not None and p["start"] <= year < p["end"]))]
    return Results(out, more=more)
