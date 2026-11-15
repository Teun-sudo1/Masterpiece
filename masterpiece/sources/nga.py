"""National Gallery of Art (Washington) adapter: a local index, no search API.

Data:    the NGA publishes its collection as CSV on GitHub (CC0) but has no search API.
         packaging/nga_index.py turns it into masterpiece/data/nga.json.gz (≈3000 open-access
         paintings, ~170 KB) that ships with the app, so searching costs the NGA nothing.
Images:  IIIF Image API at api.nga.gov/iiif/<uuid> (open-access images only).
License: open-access images are public domain (CC0).
Limits:  searches title, artist and medium; subjects are matched on the title; no colour.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from pathlib import Path

from .. import content
from ..models import Artwork, Results

KEY = "nga"
NAME = "National Gallery of Art, Washington"
LICENSE = "CC0 (open access)"
HOMEPAGE = "https://www.nga.gov/open-access-images.html"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("api.nga.gov",)
REGIONS = {"europe", "americas"}

INDEX = Path(__file__).resolve().parent.parent / "data" / "nga.json.gz"
IIIF = "https://api.nga.gov/iiif"
PAGE_SIZE = 60
MAX_WIDTH = 3840
PREVIEW_WIDTH = 843

_rows: list | None = None
_lock = threading.Lock()


def _index() -> list:
    global _rows
    with _lock:
        if _rows is None:
            try:
                with gzip.open(INDEX, "rt", encoding="utf-8") as f:
                    data = json.load(f)
                keys = data["fields"]
                _rows = [dict(zip(keys, r)) for r in data["rows"]]
                for r in _rows:
                    r["_hay"] = content.fold(f"{r['title']} {r['maker']} {r['medium']}")
                    r["_title"] = content.fold(r["title"])
            except (OSError, ValueError, KeyError):
                _rows = []
        return _rows


def _subject_words(subject: str | None) -> list[str]:
    s = content.SUBJECTS.get(subject)
    if not s:
        return []
    return [content.fold(w) for w in [s["keyword"], *s["aic"]]]


def _to_artwork(r: dict) -> Artwork:
    w, h = int(r["width"]), int(r["height"])
    dl_w = min(w, MAX_WIDTH)
    base = f"{IIIF}/{r['uuid']}"
    return Artwork(
        id=f"{KEY}-{r['objectid']}", source=KEY, title=r["title"], maker=r["maker"], year=r["date"],
        museum=NAME,
        image_url=f"{base}/full/{dl_w},/0/default.jpg",
        preview_url=f"{base}/full/{PREVIEW_WIDTH},/0/default.jpg",
        thumb_url=f"{base}/full/400,/0/default.jpg",
        width=dl_w, height=round(h * dl_w / w), license="CC0",
        link=f"https://www.nga.gov/collection/art-object-page.{r['objectid']}.html",
        text=f"{r['title']} {r['medium']}"[:content.TEXT_CHARS],
    )


def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    words = content.fold(query).split()
    subj = _subject_words(subject)
    p = content.PERIODS.get(period)
    regions = content.regions_of(region)
    hits = []
    for r in _index():
        if words and not all(w in r["_hay"] for w in words):
            continue
        if subj and not any(w in r["_title"] for w in subj):
            continue
        if p and not (r["year"] is not None and p["start"] <= r["year"] < p["end"]):
            continue
        if regions and r["region"] not in regions:
            continue
        hits.append(r)
    # A stable mix (not just accession order), the same for every page of this search
    seed = f"{query}|{subject}|{period}|{region}"
    hits.sort(key=lambda r: hashlib.md5(f"{seed}{r['objectid']}".encode()).digest())
    start = (max(1, page) - 1) * limit
    return Results([_to_artwork(r) for r in hits[start:start + limit]], more=start + limit < len(hits))
