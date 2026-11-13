"""SMK – Statens Museum for Kunst (National Gallery of Denmark) adapter.

API:    https://api.smk.dk/api/v1/art/search/  (no key)
        filters=[has_image:true],[public_domain:true],[object_names:painting] with lang=en
        range=[production_dates_start:{<iso>;<iso>}] for periods
Images: IIIF at iip.smk.dk (full native size available), thumbnails at iip-thumb.smk.dk.
License: public-domain works are released with the Public Domain Mark.
Limits: `keys` matches one term only (multi-word queries return nothing), so we
        send one word and check the rest ourselves. No colour search, but each
        record has a dominant-colour palette, so `color` is approximated from it.
"""

from __future__ import annotations

from .. import content
from ..models import Artwork, Results
from ..net import get_json

KEY = "smk"
NAME = "SMK – National Gallery of Denmark"
LICENSE = "Public domain (PDM)"
HOMEPAGE = "https://open.smk.dk/"
SUPPORTS_COLOR = True          # approximate, from the palette
IMAGE_HOSTS = ("iip.smk.dk", "iip-thumb.smk.dk")
REGIONS = {"europe"}           # Danish & European paintings

API = "https://api.smk.dk/api/v1/art/search/"
PAGE_SIZE = 60
MAX_WIDTH = 3840               # native files are often 9000+ px and very slow
FILTERS = "[has_image:true],[public_domain:true],[object_names:painting]"


def _title(titles: list[dict]) -> str:
    for t in titles or []:
        if t.get("language") == "engelsk" and t.get("title"):
            return t["title"]
    return (titles or [{}])[0].get("title") or "Untitled"


def _maker(production: list[dict]) -> str:
    if not production:
        return "Unknown artist"
    p = production[0]
    fn, sn = p.get("creator_forename"), p.get("creator_surname")
    return f"{fn} {sn}" if fn and sn else (p.get("creator") or "Unknown artist")


def _to_artwork(d: dict) -> Artwork | None:
    if not d.get("public_domain") or not d.get("has_image"):
        return None
    iiif = d.get("image_iiif_id")
    w, h = int(d.get("image_width") or 0), int(d.get("image_height") or 0)
    if not iiif or not w or not h:
        return None
    dl_w = min(w, MAX_WIDTH)
    dates = d.get("production_date") or [{}]
    return Artwork(
        id=f"{KEY}-{d.get('object_number') or d['id']}",
        source=KEY,
        title=_title(d.get("titles")),
        maker=_maker(d.get("production")),
        year=dates[0].get("period") or "",
        museum="SMK – National Gallery of Denmark",
        image_url=f"{iiif}/full/{dl_w},/0/default.jpg",
        preview_url=d.get("image_thumbnail") or f"{iiif}/full/!1024,/0/default.jpg",
        thumb_url=(d.get("image_thumbnail") or "").replace("/full/!1024,/", "/full/!400,/"),
        width=dl_w,
        height=round(h * dl_w / w),
        license="Public domain",
        link=d.get("frontend_url") or "",
        text=" ".join(d.get("content_subject") or [])[:content.TEXT_CHARS],
    )


def _iso(year: int) -> str:
    return f"{max(1, min(year, 9999)):04d}-01-01T00:00:00.000Z"


def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    words = content.fold(query).split()
    if subject in content.SUBJECTS:
        keys, rest = content.SUBJECTS[subject]["keyword"], words
    elif words:
        keys, rest = words[0], words[1:]
    else:
        keys, rest = "*", []

    offset = (max(1, page) - 1) * limit
    params = {"keys": keys, "lang": "en", "offset": offset, "rows": limit, "filters": FILTERS}
    if period in content.PERIODS:
        p = content.PERIODS[period]
        params["range"] = f"[production_dates_start:{{{_iso(p['start'])};{_iso(p['end'])}}}]"
    data = get_json(API, params=params)

    out = []
    for d in data.get("items") or []:
        a = _to_artwork(d)
        if not a:
            continue
        if rest:
            hay = content.fold(f"{a.title} {a.maker} {a.text} {' '.join(d.get('techniques') or [])}")
            if not all(w in hay for w in rest):
                continue
        if color and not content.hex_palette_matches(d.get("colors") or [], color):
            continue
        out.append(a)
    return Results(out, more=offset + limit < int(data.get("found") or 0))
