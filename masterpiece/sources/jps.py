"""Japan Search (ジャパンサーチ) adapter — Japan's national portal across many museums.

API:    https://jpsearch.go.jp/api/item/search/jps-cross  (no key)
        f-type=paint (paintings), f-rights=pdm (public domain), keyword, from/size
License: only items whose contentsRightsType is "pdm" are used.
Images: links point to each institution's own server; today the usable public-domain
        paintings with a direct JPEG come mostly from the Tokyo Museum Collection
        (ukiyo-e by Hiroshige, Kuniyoshi, …). Records with only a IIIF manifest or
        without an image are skipped. Pixel size: first bytes of the JPEG.
Titles are in Japanese. Subjects are searched with Japanese keywords.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .. import cache, content
from ..models import Artwork, Results
from ..net import DEFAULT_HEADERS, Blocked, _slot, get_json

try:
    from PIL import ImageFile
except ImportError:
    ImageFile = None

KEY = "jps"
NAME = "Japan Search"
LICENSE = "Public domain (PDM)"
HOMEPAGE = "https://jpsearch.go.jp/"
SUPPORTS_COLOR = False
IMAGE_HOSTS = ("museumcollection.tokyo",)   # more are added as results come in (see extra_hosts)
REGIONS = {"asia"}
NOTE = "smaller images (≈1000 px): shown with Resolution “Any size” or “≥ 1280 px”"

API = "https://jpsearch.go.jp/api/item/search/jps-cross"
PAGE_SIZE = 60
SIZE_TTL = 30 * cache.DAY
HOSTS_KEY = "jps:hosts"

SUBJECT_JA = {
    "landscape": "風景", "water": "海", "city": "名所", "seasons": "雪", "flowers": "花",
    "stilllife": "静物", "animals": "鳥", "dailylife": "風俗", "portraits": "美人",
    "mythology": "神話", "religious": "仏",
}
_IMG = re.compile(r"\.(jpe?g|png)(\?|$)", re.I)
_YEAR = re.compile(r"(1[0-9]{3}|20[0-2][0-9])")
_hosts_lock = threading.Lock()
_sizes: OrderedDict = OrderedDict()


def extra_hosts() -> set[str]:
    """Image hosts seen in Japan Search results (persisted, so downloads work after a restart)."""
    return set(cache.kv().get(HOSTS_KEY, 1e12) or [])


def _remember_hosts(urls: list[str]) -> None:
    new = {urllib.parse.urlsplit(u).hostname for u in urls if u.startswith("https://")} - {None}
    with _hosts_lock:
        known = extra_hosts()
        if not new <= known:
            cache.kv().set(HOSTS_KEY, sorted(known | new))


def _image_size(url: str) -> tuple[int, int] | None:
    if ImageFile is None:
        return None
    hit = cache.kv().get(f"jps:size:{url}", SIZE_TTL)
    if hit:
        return tuple(hit)
    req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, "Range": "bytes=0-131071"})
    try:
        with _slot(url), urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(131_072)                 # stop reading even if Range is ignored
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"{urllib.parse.urlsplit(url).hostname} is limiting requests") from e
        return None
    except OSError:
        return None
    p = ImageFile.Parser()
    try:
        p.feed(data)
    except Exception:
        return None
    if not p.image:
        return None
    cache.kv().set(f"jps:size:{url}", list(p.image.size))
    return p.image.size


def _clean_maker(s: str) -> str:
    return re.sub(r"[/／](画|筆|作)$", "", s or "").strip() or "Unknown artist"


def _candidate(item: dict) -> dict | None:
    c = item.get("common") or {}
    if c.get("contentsRightsType") != "pdm":
        return None
    urls = [u for u in c.get("contentsUrl") or [] if u.startswith("https://") and _IMG.search(u)]
    if not urls:
        return None
    thumbs = [u for u in c.get("thumbnailUrl") or [] if u.startswith("https://")]
    return {"c": c, "image": urls[0], "thumb": thumbs[0] if thumbs else urls[0]}


def _to_artwork(cand: dict) -> Artwork | None:
    c = cand["c"]
    size = _image_size(cand["image"])
    if not size:
        return None
    w, h = size
    return Artwork(
        id=f"{KEY}-{re.sub(r'[^\w-]+', '-', c.get('id', ''))[:80]}",
        source=KEY,
        title=c.get("title") or "Untitled",
        maker=_clean_maker((c.get("contributor") or [""])[0]),
        year=(c.get("temporal") or [""])[0],
        museum="Japan Search · " + ("Tokyo Museum Collection" if "museumcollection.tokyo" in cand["image"]
                                    else c.get("database", "")),
        image_url=cand["image"],
        preview_url=cand["image"],
        thumb_url=cand["thumb"],
        width=w,
        height=h,
        license="Public domain",
        link=c.get("linkUrl") or f"https://jpsearch.go.jp/item/{c.get('id', '')}",
        text=" ".join(c.get("subCategory") or [])[:content.TEXT_CHARS],
    )


def search(query: str = "", page: int = 1, color: str | None = None,
           top_only: bool = False, subject: str | None = None, period: str | None = None,
           hide=(), region: str | None = None, limit: int = PAGE_SIZE) -> Results:
    offset = (max(1, page) - 1) * limit
    keyword = " ".join(x for x in [query, SUBJECT_JA.get(subject, "")] if x)
    params = {"f-type": "paint", "f-rights": "pdm", "f-contents": "image",
              "from": offset, "size": limit, "keyword": keyword or None}
    data = get_json(API, params=params)
    cands = [x for x in map(_candidate, data.get("list") or []) if x]
    _remember_hosts([x["image"] for x in cands] + [x["thumb"] for x in cands])
    with ThreadPoolExecutor(max_workers=4) as ex:
        arts = [a for a in ex.map(_to_artwork, cands) if a]
    if period in content.PERIODS:                      # no date filter in the API
        p = content.PERIODS[period]
        def in_period(a):
            m = _YEAR.search(a.year)
            return bool(m) and p["start"] <= int(m.group(1)) < p["end"]
        arts = [a for a in arts if in_period(a)]
    return Results(arts, more=offset + limit < int(data.get("hit") or 0))
