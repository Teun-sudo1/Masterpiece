"""Art Institute of Chicago adapter.

API:    https://api.artic.edu/docs/  (no key; Elasticsearch-style search)
Images: IIIF Image API 2.0 at https://www.artic.edu/iiif/2 — max 3000 px wide,
        requires an identifying AIC-User-Agent header (see net.py).
License: public-domain works' images and metadata are CC0.
"""

from __future__ import annotations

from .. import content
from ..models import Artwork, Results
from ..net import get_json

KEY = "aic"
NAME = "Art Institute of Chicago"
LICENSE = "CC0 (public-domain works)"
HOMEPAGE = "https://www.artic.edu/open-access"
SUPPORTS_COLOR = True
IMAGE_HOSTS = ("www.artic.edu",)
REGIONS = {"europe", "americas", "asia", "middleeast"}

API = "https://api.artic.edu/api/v1/artworks/search"
IIIF = "https://www.artic.edu/iiif/2"
MAX_IIIF_WIDTH = 3000
PREVIEW_WIDTH = 843          # AIC's recommended (CDN-cached) size
PAGE_SIZE = 60
MAX_RESULT_WINDOW = 10_000   # Elasticsearch limit on page * limit
PAINTING_TYPE_ID = 1

FIELDS = ["id", "title", "artist_title", "artist_display", "date_display",
          "image_id", "thumbnail", "is_public_domain"]

HUES = content.HUES   # AIC "color.h" is 0–360 too


MIDDLE_EAST = ["iran", "persia", "turkey", "ottoman empire", "egypt", "iraq", "syria",
               "lebanon", "afghanistan", "uzbekistan", "saudi arabia", "yemen", "jordan"]
REGION_FILTERS = {
    "europe": {"terms": {"department_title.keyword": ["Painting and Sculpture of Europe"]}},
    "americas": {"terms": {"department_title.keyword": ["Arts of the Americas"]}},
    "asia": {"bool": {"filter": [{"terms": {"department_title.keyword": ["Arts of Asia"]}}],
                      "must_not": [{"terms": {"place_of_origin.keyword": MIDDLE_EAST}}]}},
    "middleeast": {"terms": {"place_of_origin.keyword": MIDDLE_EAST}},
}


def _query(color: str | None, top_only: bool, subject: str | None = None,
           period: str | None = None, hide=(), region: str | None = None) -> dict:
    filters: list[dict] = [
        {"term": {"is_public_domain": True}},
        {"term": {"artwork_type_id": PAINTING_TYPE_ID}},
        {"exists": {"field": "image_id"}},
    ]
    must_not: list[dict] = []
    if top_only:
        filters.append({"term": {"is_boosted": True}})
    if subject in content.SUBJECTS:
        filters.append({"terms": {"subject_titles.keyword": content.SUBJECTS[subject]["aic"]}})
    if period in content.PERIODS:
        p = content.PERIODS[period]
        filters.append({"range": {"date_start": {"gte": p["start"], "lt": p["end"]}}})
    if region in REGION_FILTERS:
        filters.append(REGION_FILTERS[region])
    for h in hide:
        if h in content.HIDE:
            must_not.append({"terms": {"subject_titles.keyword": content.HIDE[h]["aic"]}})
    if color in HUES:
        filters.append({"bool": {
            "should": [{"range": {"color.h": {"gte": a, "lt": b}}} for a, b in HUES[color]],
            "minimum_should_match": 1,
        }})
        filters.append({"range": {"color.s": {"gte": 25}}})
    q: dict = {"bool": {"filter": filters}}
    if must_not:
        q["bool"]["must_not"] = must_not
    return q


def _to_artwork(d: dict) -> Artwork | None:
    image_id = d.get("image_id")
    thumb = d.get("thumbnail") or {}
    w, h = int(thumb.get("width") or 0), int(thumb.get("height") or 0)
    if not image_id or not w or not h or not d.get("is_public_domain"):
        return None
    dl_w = min(w, MAX_IIIF_WIDTH)
    maker = d.get("artist_title") or (d.get("artist_display") or "").split("\n")[0]
    return Artwork(
        id=f"{KEY}-{d['id']}",
        source=KEY,
        title=d.get("title") or "Untitled",
        maker=maker or "Unknown artist",
        year=d.get("date_display") or "",
        museum=NAME,
        image_url=f"{IIIF}/{image_id}/full/{dl_w},/0/default.jpg",
        preview_url=f"{IIIF}/{image_id}/full/{PREVIEW_WIDTH},/0/default.jpg",
        thumb_url=f"{IIIF}/{image_id}/full/400,/0/default.jpg",
        width=dl_w,
        height=round(h * dl_w / w),
        license="CC0",
        link=f"https://www.artic.edu/artworks/{d['id']}",
    )


def details(artwork_id: str) -> dict:
    """Description and facts for the info card (one request, cached by the caller)."""
    n = artwork_id.split("-", 1)[1]
    d = get_json(f"https://api.artic.edu/api/v1/artworks/{n}", params={
        "fields": "description,short_description,medium_display,dimensions,place_of_origin,credit_line"
    }).get("data") or {}
    return {
        "description": content.html_to_text(d.get("description") or d.get("short_description") or ""),
        "facts": [[k, d.get(f)] for k, f in (("Medium", "medium_display"), ("Size", "dimensions"),
                                             ("Place", "place_of_origin"), ("Credit", "credit_line")) if d.get(f)],
        "credit": "Text © Art Institute of Chicago, CC BY 4.0" if d.get("description") else "",
    }


def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    page = max(1, page)
    body = {
        "limit": limit,
        "page": page,
        "fields": FIELDS,
        "query": _query(color, top_only, subject, period, hide, region),
    }
    if query:
        # AIC's `q` only *ranks* results (everything still matches), so require
        # every search word to appear in one of these fields instead.
        body["query"]["bool"]["must"] = [{"multi_match": {
            "query": query,
            "type": "cross_fields",
            "operator": "and",
            "fields": ["title^3", "artist_title^3", "artist_display^2", "alt_titles",
                       "subject_titles", "style_titles", "term_titles",
                       "classification_titles", "place_of_origin", "description"],
        }}]
    data = get_json(API, body=body)
    pag = data.get("pagination") or {}
    more = page < int(pag.get("total_pages") or 0) and page * limit < MAX_RESULT_WINDOW
    return Results((a for a in map(_to_artwork, data.get("data") or []) if a), more=more)
