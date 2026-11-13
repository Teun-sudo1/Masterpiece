"""Cleveland Museum of Art adapter.

API:    https://openaccess-api.clevelandart.org/  (no key)
Images: "print" JPEG (≈3400 px longest side) and "web" JPEG (≈900 px).
License: only works with share_license_status == "CC0" are used.
Limits: no colour filter (`color` is ignored) and no subject tags — subjects
        use the API's `description` text search, so they are approximate.
"""

from __future__ import annotations

from .. import content
from ..models import Artwork, Results
from ..net import get_json

KEY = "cleveland"
NAME = "Cleveland Museum of Art"
LICENSE = "CC0"
HOMEPAGE = "https://www.clevelandart.org/open-access"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("openaccess-cdn.clevelandart.org",)
# CMA accepts only one department per request, so regions are filtered on the results.
REGION_DEPARTMENTS = {
    "europe": {"European Painting and Sculpture", "Modern European Painting and Sculpture"},
    "americas": {"American Painting and Sculpture", "Art of the Americas"},
    "asia": {"Chinese Art", "Japanese Art", "Korean Art", "Indian and South East Asian Art"},
}
REGIONS = set(REGION_DEPARTMENTS)

API = "https://openaccess-api.clevelandart.org/api/artworks/"
PAGE_SIZE = 60
TIMEOUT = 45
FIELDS = ("id,accession_number,title,creators,creation_date,images,"
          "share_license_status,url,description,culture,technique,department")


def _maker(creators: list[dict]) -> str:
    if not creators:
        return "Unknown artist"
    desc = creators[0].get("description") or ""
    # "Jan Gossaert (Flemish, c. 1475/78–1532)" -> "Jan Gossaert"
    return desc.split(" (")[0].strip() or "Unknown artist"


_fold = content.fold


def _matches_query(d: dict, words: list[str]) -> bool:
    """CMA's `q` also hits provenance, credit lines, citations… which gives
    surprising results. Require every word in the fields people search for."""
    if not words:
        return True
    creators = " ".join(c.get("description") or "" for c in d.get("creators") or [])
    hay = _fold(" ".join([d.get("title") or "", creators, d.get("description") or "",
                          " ".join(d.get("culture") or []), d.get("technique") or ""]))
    return all(w in hay for w in words)


def _to_artwork(d: dict) -> Artwork | None:
    if d.get("share_license_status") != "CC0":
        return None
    images = d.get("images") or {}
    big = images.get("print") or images.get("web")
    small = images.get("web") or big
    if not big or not big.get("url"):
        return None
    try:
        w, h = int(big.get("width") or 0), int(big.get("height") or 0)
    except ValueError:
        return None
    if not w or not h:
        return None
    return Artwork(
        id=f"{KEY}-{d['id']}",
        source=KEY,
        title=d.get("title") or "Untitled",
        maker=_maker(d.get("creators") or []),
        year=d.get("creation_date") or "",
        museum=NAME,
        image_url=big["url"],
        preview_url=small["url"],
        width=w,
        height=h,
        license="CC0",
        link=d.get("url") or f"https://clevelandart.org/art/{d.get('accession_number', '')}",
        text=(d.get("description") or "")[:content.TEXT_CHARS],
    )


def details(artwork_id: str) -> dict:
    """Description and facts for the info card (one request, cached by the caller)."""
    n = artwork_id.split("-", 1)[1]
    d = get_json(f"{API}{n}", timeout=TIMEOUT).get("data") or {}
    desc = "\n\n".join(x for x in (d.get("description"), d.get("did_you_know")) if x)
    return {
        "description": content.html_to_text(desc),
        "facts": [[k, v] for k, v in (("Medium", d.get("technique")),
                                      ("Size", d.get("measurements")),
                                      ("Culture", ", ".join(d.get("culture") or [])),
                                      ("Credit", d.get("creditline"))) if v],
        "credit": "Text: Cleveland Museum of Art, CC0" if desc else "",
    }


def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    skip = (max(1, page) - 1) * limit
    params = {
        "q": query or None,
        "cc0": 1,
        "has_image": 1,
        "type": "Painting",
        "limit": limit,
        "skip": skip,
        "fields": FIELDS,
        "highlight": 1 if top_only else None,
    }
    if subject in content.SUBJECTS:
        params["description"] = content.SUBJECTS[subject]["keyword"]
    if period in content.PERIODS:
        p = content.PERIODS[period]
        params["created_after"] = p["start"]
        params["created_before"] = p["end"]
    # `hide` is handled centrally on title + description (filters.py)
    # CMA's API is erratic (same request: 1 s … 60 s+), so allow it more time.
    # The UI loads museums independently, so a slow CMA doesn't block the others.
    data = get_json(API, params=params, timeout=TIMEOUT)
    total = int((data.get("info") or {}).get("total") or 0)
    words = _fold(query).split()
    depts = REGION_DEPARTMENTS.get(region)
    items = (_to_artwork(d) for d in data.get("data") or []
             if _matches_query(d, words) and (not depts or d.get("department") in depts))
    return Results((a for a in items if a), more=skip + limit < total)
