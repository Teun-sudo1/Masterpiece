"""The Metropolitan Museum of Art adapter.

API:    https://metmuseum.github.io/  (no key; asks for <= 80 requests/second — we do far less)
        /public/collection/v1.1/search  (paginated; /v1/search is retired)
        /public/collection/v1/objects/<id>
Images: images.metmuseum.org — "original" (often 4000+ px) and "web-large".
        Pixel size isn't in the record, so we read just the first 64 KB of the JPEG.
License: Open Access objects (isPublicDomain = true) are CC0.

Strong in Asian art (Chinese & Japanese paintings, Japanese woodblock prints) and
the Islamic world (Persian & Mughal manuscript paintings), plus European and American paintings.
Search returns only IDs, so each painting costs 2 small requests; results are cached 30 days.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .. import cache, content
from ..models import Artwork, Results
from ..net import DEFAULT_HEADERS, Blocked, _open, _slot, get_json
from ._ids import Stream, Union, UnionCache

try:
    from PIL import ImageFile
except ImportError:
    ImageFile = None

KEY = "met"
NAME = "The Metropolitan Museum of Art"
LICENSE = "CC0 (Open Access)"
HOMEPAGE = "https://www.metmuseum.org/hubs/open-access"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("images.metmuseum.org",)
REGIONS = {"europe", "americas", "asia", "middleeast"}

SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{id}"
PAGE_SIZE = 12          # each object costs 2 requests; the Met has strict bot protection
ID_PAGE = 100
OBJECT_TTL = 30 * cache.DAY
CACHE_VERSION = "met:obj:v2"     # bump when _to_artwork's filtering changes

# (departmentId, medium) streams per region. A pipe in `medium` narrows rather than
# widens the search, so every medium is its own stream.
DEPARTMENTS = {   # region: [(departmentId, medium, extra search words)]
    "europe": [(11, "Paintings", "")],                     # European Paintings
    "americas": [(1, "Paintings", "")],                    # The American Wing
    "asia": [(6, "Paintings", ""), (6, "Prints", "")],     # Asian Art (incl. ukiyo-e)
    # Islamic Art: paintings, and manuscript folios that are *illustrated* (not text pages/papyri)
    "middleeast": [(14, "Paintings", ""), (14, "Codices", "illustrated")],
}
DEFAULT_ORDER = ["europe", "asia", "middleeast", "americas"]


# ------------------------------------------------------------------ ID streams

def _stream(params: dict) -> Stream:
    def fetch(offset: int):
        data = get_json(SEARCH, params={**params, "offset": offset, "limit": ID_PAGE})
        ids = data.get("objectIDs") or []
        nxt = offset + ID_PAGE
        total = int(data.get("total") or 0)
        return ids, (nxt if nxt < min(total, 10_000) and ids else None)
    return Stream(fetch, 0)


_unions = UnionCache()


def _param_sets(query: str, subject: str | None, period: str | None,
                top_only: bool, region: str | None) -> list[dict]:
    words = [query, content.SUBJECTS.get(subject, {}).get("keyword", "")]
    base = {"hasImages": "true"}
    if top_only:
        base["isHighlight"] = "true"
    if period in content.PERIODS:
        p = content.PERIODS[period]
        base["dateBegin"], base["dateEnd"] = p["start"], p["end"]
    chosen = content.regions_of(region)
    regions = [r for r in DEFAULT_ORDER if r in chosen] or [r for r in DEPARTMENTS if r in chosen] or DEFAULT_ORDER
    sets = []
    for r in regions:
        for d, m, extra in DEPARTMENTS[r]:
            q = " ".join(x for x in [extra, *words] if x)
            sets.append(dict(base, departmentId=d, medium=m, **({"q": q} if q else {})))
    return sets


# ------------------------------------------------------------------ objects

_objects: OrderedDict = OrderedDict()
_objects_lock = threading.Lock()


def _image_size(url: str) -> tuple[int, int] | None:
    """Pixel size from the first bytes of the JPEG (one small Range request)."""
    if ImageFile is None:
        return None
    for nbytes in (65_536, 262_144):
        req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, "Range": f"bytes=0-{nbytes - 1}"})
        try:
            with _slot(url), _open(url, req, 30) as r:
                data = r.read(nbytes)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked("images.metmuseum.org is limiting requests right now") from e
            raise
        p = ImageFile.Parser()
        try:
            p.feed(data)
        except Exception:
            return None
        if p.image:
            return p.image.size
    return None


# The Islamic Art department's "Codices" also contain papyri and text pages;
# keep illustrated pages, paintings and album leaves only.
_ISLAMIC_KEEP = re.compile(r"illustrat|painting|album|miniature", re.I)
_ISLAMIC_DROP = re.compile(r"fragment|papyrus|binding|frieze|calligraph", re.I)


def _to_artwork(o: dict) -> Artwork | None:
    if not o.get("isPublicDomain") or not o.get("primaryImage"):
        return None
    if o.get("department") == "Islamic Art":
        kind = f"{o.get('objectName') or ''} {o.get('title') or ''}"
        if not _ISLAMIC_KEEP.search(kind) or _ISLAMIC_DROP.search(kind):
            return None
    size = _image_size(o["primaryImage"])
    if not size:
        return None
    w, h = size
    tags = " ".join(t.get("term", "") for t in o.get("tags") or [])
    maker = o.get("artistDisplayName") or (f"{o['culture']} artist" if o.get("culture") else "Unknown artist")
    return Artwork(
        id=f"{KEY}-{o['objectID']}",
        source=KEY,
        title=o.get("title") or "Untitled",
        maker=maker,
        year=o.get("objectDate") or "",
        museum=NAME,
        image_url=o["primaryImage"],
        preview_url=o.get("primaryImageSmall") or o["primaryImage"],
        thumb_url=o.get("primaryImageSmall") or "",
        width=w,
        height=h,
        license="CC0",
        link=o.get("objectURL") or "",
        text=" ".join([o.get("objectName") or "", o.get("classification") or "", tags])[:content.TEXT_CHARS],
    )


def _resolve(obj_id: str) -> Artwork | None:
    with _objects_lock:
        if obj_id in _objects:
            return _objects[obj_id]
    hit = cache.kv().get(f"{CACHE_VERSION}:{obj_id}", OBJECT_TTL)
    if hit is not None:
        art = Artwork.from_dict(hit) if hit else None
    else:
        try:
            art = _to_artwork(get_json(OBJECT.format(id=obj_id)))
        except Blocked:
            raise                           # stop this search; the UI says "try again later"
        except Exception:
            return None                     # transient: don't cache
        cache.kv().set(f"{CACHE_VERSION}:{obj_id}", art.to_dict() if art else {})
    with _objects_lock:
        _objects[obj_id] = art
        while len(_objects) > 5000:
            _objects.popitem(last=False)
    return art


def details(artwork_id: str) -> dict:
    """Facts for the info card. The Met's API has no description text."""
    o = get_json(OBJECT.format(id=artwork_id.split("-", 1)[1]))
    return {
        "description": "",
        "facts": [[k, o.get(f)] for k, f in (("Medium", "medium"), ("Size", "dimensions"),
                                             ("Culture", "culture"), ("Period", "period"),
                                             ("Department", "department"), ("Credit", "creditLine"))
                  if o.get(f)],
        "credit": "",
    }


# ------------------------------------------------------------------ search

def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    sets = _param_sets(query.strip(), subject, period, top_only, region)
    union = _unions.get(repr(sets), lambda: Union([_stream(p) for p in sets], interleave=True))
    start = (max(1, page) - 1) * limit
    ids, more = union.slice(start, start + limit)
    with ThreadPoolExecutor(max_workers=2) as ex:      # net.HOST_LIMITS throttles further
        arts = list(ex.map(_resolve, ids))
    return Results([a for a in arts if a], more=more)
