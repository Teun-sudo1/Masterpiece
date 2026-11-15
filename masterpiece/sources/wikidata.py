"""Wikidata adapter: paintings from Latin America and Oceania (local index, no live queries).

Data:    packaging/wikidata_index.py asks Wikidata once for public-domain paintings in museums in
         Latin America, Australia and New Zealand, and by artists from those countries (painters
         who died before 1925). It keeps only images that Wikimedia Commons marks as public
         domain / CC0, and writes masterpiece/data/wikidata.json.gz, which ships with the app.
Images:  upload.wikimedia.org (original, or a Commons thumbnail in one of its standard widths).
Regions: by the painter's nationality where known ("latam", "oceania", "europe", …), else where
         the museum is.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from pathlib import Path

from .. import content
from ..models import Artwork, Results

KEY = "wikidata"
NAME = "Wikidata: Latin America & Oceania"
LICENSE = "Public domain (Wikimedia Commons)"
HOMEPAGE = "https://www.wikidata.org/"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("upload.wikimedia.org",)
REGIONS = {"latam", "oceania", "europe", "americas", "asia"}

INDEX = Path(__file__).resolve().parent.parent / "data" / "wikidata.json.gz"
PAGE_SIZE = 60
# Commons serves thumbnails efficiently in these standard widths
THUMB_STEPS = (500, 960, 1280, 1920, 3840)

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
                    r["url"] = r["url"].split("?", 1)[0]           # drop Commons tracking parameters
                    r["_hay"] = content.fold(f"{r['title']} {r['maker']} {r['museum']}")
                    r["_title"] = content.fold(r["title"])
            except (OSError, ValueError, KeyError):
                _rows = []
        return _rows


def _thumb(url: str, width: int, want: int) -> str:
    """Commons thumbnail URL in a standard width, or the original if that's not bigger."""
    step = next((s for s in THUMB_STEPS if s >= want), THUMB_STEPS[-1])
    if step >= width:
        return url
    base, name = url.rsplit("/", 1)
    return f"{base.replace('/commons/', '/commons/thumb/', 1)}/{name}/{step}px-{name}"


def _to_artwork(r: dict) -> Artwork:
    w, h = int(r["width"]), int(r["height"])
    dl = _thumb(r["url"], w, 3840)
    dl_w = min(w, 3840) if dl != r["url"] else w
    return Artwork(
        id=f"{KEY}-{r['qid']}", source=KEY, title=r["title"], maker=r["maker"], year=r["date"],
        museum=r["museum"] or "Unknown collection",
        image_url=dl, preview_url=_thumb(r["url"], w, 960), thumb_url=_thumb(r["url"], w, 500),
        width=dl_w, height=round(h * dl_w / w), license="Public domain",
        link=f"https://www.wikidata.org/wiki/{r['qid']}",
        text=r["title"][:content.TEXT_CHARS],
    )


def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    words = content.fold(query).split()
    s = content.SUBJECTS.get(subject)
    subj = [content.fold(w) for w in [s["keyword"], *s["aic"]]] if s else []
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
    seed = f"{query}|{subject}|{period}|{region}"
    hits.sort(key=lambda r: hashlib.md5(f"{seed}{r['qid']}".encode()).digest())
    start = (max(1, page) - 1) * limit
    return Results([_to_artwork(r) for r in hits[start:start + limit]], more=start + limit < len(hits))
