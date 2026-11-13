"""Rijksmuseum adapter (new Data Services — no key; the old key-based API is not used).

Search: https://data.rijksmuseum.nl/search/collection  (Linked Art Search)
        type=painting&imageAvailable=true + creator / title / description / creationDate
        Returns only object IDs, 100 per page, paged with `next` links (pageToken).
Object: https://id.rijksmuseum.nl/<id>?_profile=edm  (EDM RDF/XML: English title,
        creator name, date, description, image URL, rights)
Images: IIIF at iiif.micr.io — /info.json gives the pixel size.
License: public-domain works carry the Public Domain Mark (or CC0).

Limits: no free-text search, so a query searches creator, title and description
        and merges the results; periods use creationDate year wildcards (e.g. "185?").
        No colour filter. Each painting costs 2 extra requests, so results are cached.
"""

from __future__ import annotations

import threading
import urllib.parse
import xml.etree.ElementTree as ET
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .. import cache, content
from ..models import Artwork, Results
from ..net import get_json, fetch
from ._ids import Stream, Union, UnionCache

KEY = "rijks"
NAME = "Rijksmuseum"
LICENSE = "Public domain (PDM) / CC0"
HOMEPAGE = "https://data.rijksmuseum.nl/"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("iiif.micr.io",)
REGIONS = {"europe"}          # almost entirely Dutch / European paintings

SEARCH = "https://data.rijksmuseum.nl/search/collection"
OBJECT = "https://id.rijksmuseum.nl/{id}?_profile=edm"
PAGE_SIZE = 24          # objects resolved per page (each needs 2 requests)
MAX_WIDTH = 3840
PREVIEW_WIDTH = 843

# creationDate only supports wildcards, so each period is a set of year patterns
PERIOD_PATTERNS = {
    "pre1600": [f"{c}??" for c in range(15, 9, -1)],
    "1600": ["16??"] + [f"17{d}?" for d in range(0, 5)],
    "1750": [f"17{d}?" for d in range(5, 10)] + [f"18{d}?" for d in range(0, 5)],
    "1850": [f"18{d}?" for d in range(5, 10)],
    "1900": ["19??", "20??"],
}

NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "edm": "http://www.europeana.eu/schemas/edm/",
    "ore": "http://www.openarchives.org/ore/terms/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
}
RDF_RES = f"{{{NS['rdf']}}}resource"
RDF_ABOUT = f"{{{NS['rdf']}}}about"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


# ------------------------------------------------------------------ ID streams

def _fetch_ids(url: str):
    """One Linked Art Search page -> (ids, next page url)."""
    data = get_json(url)
    ids = [it["id"].rsplit("/", 1)[-1] for it in data.get("orderedItems") or []]
    return ids, (data.get("next") or {}).get("id")


_unions = UnionCache()


def _union_for(param_sets: list[dict]) -> Union:
    return _unions.get(repr(param_sets), lambda: Union(
        [Stream(_fetch_ids, f"{SEARCH}?{urllib.parse.urlencode(p)}") for p in param_sets]))


def _param_sets(query: str, subject: str | None, period: str | None) -> list[dict]:
    base = {"type": "painting", "imageAvailable": "true"}
    keyword = content.SUBJECTS[subject]["keyword"] if subject in content.SUBJECTS else None
    if query:
        variants = [{"creator": query}, {"title": query}]
        if not keyword:                       # description is taken by the subject otherwise
            variants.append({"description": query})
    else:
        variants = [{}]
    if keyword:
        variants = [dict(v, description=keyword) for v in variants]
    if period in PERIOD_PATTERNS:
        variants = [dict(v, creationDate=p) for v in variants for p in PERIOD_PATTERNS[period]]
    return [dict(base, **v) for v in variants]


# ------------------------------------------------------------------ objects

_objects: OrderedDict = OrderedDict()      # id -> Artwork | None
_objects_lock = threading.Lock()


def _text(root, path: str, prefer: str = "en") -> str:
    els = root.findall(path, NS)
    for el in els:
        if el.get(XML_LANG) == prefer and (el.text or "").strip():
            return el.text.strip()
    for el in els:
        if (el.text or "").strip():
            return el.text.strip()
    return ""


def _res(parent, path: str) -> str:
    """rdf:resource of the first matching child ('' if absent).
    (Note: an Element without children is falsy, so no `find() or default`.)"""
    el = parent.find(path, NS)
    return el.get(RDF_RES, "") if el is not None else ""


def _parse_edm(obj_id: str, xml: bytes) -> dict | None:
    root = ET.fromstring(xml)
    agg = root.find("ore:Aggregation", NS)
    cho = root.find("edm:ProvidedCHO", NS)
    if agg is None or cho is None:
        return None
    rights = _res(agg, "edm:rights")
    if "publicdomain" not in rights:
        return None
    shown_by = _res(agg, "edm:isShownBy")
    if "/full/" not in shown_by:
        return None
    creator_ref = _res(cho, "dc:creator")
    maker = ""
    for agent in root.findall("edm:Agent", NS):
        if agent.get(RDF_ABOUT) == creator_ref:
            maker = _text(agent, "skos:prefLabel")
            break
    return {
        "title": _text(cho, "dc:title") or "Untitled",
        "maker": ("Anonymous" if maker.lower() == "anonymous" else maker) or "Unknown artist",
        "year": _text(cho, "dcterms:created"),
        "text": _text(cho, "dc:description")[:content.TEXT_CHARS],
        "iiif": shown_by.split("/full/")[0],
        "link": _res(agg, "edm:isShownAt") or f"https://id.rijksmuseum.nl/{obj_id}",
        "license": "CC0" if "zero" in rights else "Public domain",
    }


OBJECT_TTL = 30 * cache.DAY


def _resolve(obj_id: str) -> Artwork | None:
    """Painting data for one ID: memory cache → disk cache (30 days) → 2 requests."""
    with _objects_lock:
        if obj_id in _objects:
            return _objects[obj_id]
    hit = cache.kv().get(f"rijks:obj:{obj_id}", OBJECT_TTL)
    if hit is not None:
        art = Artwork.from_dict(hit) if hit else None     # {} = known non-public-domain / no image
        with _objects_lock:
            _objects[obj_id] = art
        return art
    art = None
    try:
        xml, _ = fetch(OBJECT.format(id=obj_id))
        meta = _parse_edm(obj_id, xml)
        if meta:
            info = get_json(f"{meta['iiif']}/info.json")
            w, h = int(info.get("width") or 0), int(info.get("height") or 0)
            if w and h:
                dl_w = min(w, MAX_WIDTH)
                art = Artwork(
                    id=f"{KEY}-{obj_id}", source=KEY, title=meta["title"], maker=meta["maker"],
                    year=meta["year"], museum=NAME,
                    image_url=f"{meta['iiif']}/full/{dl_w},/0/default.jpg",
                    preview_url=f"{meta['iiif']}/full/{PREVIEW_WIDTH},/0/default.jpg",
                    thumb_url=f"{meta['iiif']}/full/400,/0/default.jpg",
                    width=dl_w, height=round(h * dl_w / w), license=meta["license"],
                    link=meta["link"], text=meta["text"],
                )
    except Exception:
        return None            # don't cache transient failures
    cache.kv().set(f"rijks:obj:{obj_id}", art.to_dict() if art else {})
    with _objects_lock:
        _objects[obj_id] = art
        while len(_objects) > 5000:
            _objects.popitem(last=False)
    return art


# ------------------------------------------------------------------ search

def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    union = _union_for(_param_sets(query.strip(), subject, period))
    start = (max(1, page) - 1) * limit
    ids, more = union.slice(start, start + limit)
    with ThreadPoolExecutor(max_workers=4) as ex:     # = net.MAX_PER_HOST
        arts = list(ex.map(_resolve, ids))
    return Results([a for a in arts if a], more=more)
