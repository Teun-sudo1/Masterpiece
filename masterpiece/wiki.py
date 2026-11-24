"""A few lines from Wikipedia about a painting and its artist, for "About this painting".

Gentle on Wikipedia: only when you open a painting's page, at most three small requests,
and the answer (also "nothing found") is kept for 30 days. An artist is looked up once
for all of their paintings. Text from Wikipedia is CC BY-SA 4.0; the page says so and links
to the article.
"""

from __future__ import annotations

import re
import urllib.parse

from . import cache, content
from .net import Offline, get_json

TTL = 30 * 24 * 3600
API = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKIDATA = "https://www.wikidata.org/w/api.php"
CREDIT = "Text from Wikipedia, CC BY-SA 4.0"
MAX_CHARS = 900

ARTIST_WORDS = re.compile(r"\b(painter|artist|draughtsman|draftsman|printmaker|illustrator|engraver|"
                          r"watercolou?rist|sculptor|miniaturist|etcher|lithographer|muralist|calligrapher)\b", re.I)
PAINTING_WORDS = re.compile(r"\b(painting|portrait|canvas|panel|oil|fresco|triptych|watercolou?r|artwork|work by)\b", re.I)
UNKNOWN = re.compile(r"^(unknown|anonymous|unidentified|attributed|workshop of|circle of|follower of|after )", re.I)
_QID = re.compile(r"^Q\d+$")


def _summary(title: str) -> dict | None:
    """Wikipedia's summary of one article (None if it isn't a normal article)."""
    try:
        d = get_json(SUMMARY + urllib.parse.quote(title.replace(" ", "_"), safe=""), timeout=10)
    except Offline:
        raise
    except Exception:
        return None
    if d.get("type") != "standard" or not d.get("extract"):
        return None
    return {"title": d.get("title") or title, "description": d.get("description") or "",
            "text": _short(d["extract"]),
            "url": ((d.get("content_urls") or {}).get("desktop") or {}).get("page")
            or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"}


def _short(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[:end + 1] if end > MAX_CHARS // 3 else cut.rsplit(" ", 1)[0] + " …"


def _surname(maker: str) -> str:
    words = [w for w in re.split(r"[\s,]+", content.fold(maker)) if len(w) > 2 and w not in ("van", "von", "der", "den", "the")]
    return words[-1] if words else ""


def _clean_maker(maker: str) -> str:
    """'Claude Monet (French, 1840–1926)' -> 'Claude Monet'; '' for unknown makers."""
    m = re.split(r"\s*[(\n;]|,\s*(?:\d|born|active|died)", maker or "", maxsplit=1)[0].strip(" ,")
    return "" if not m or UNKNOWN.match(m) else m


def _from_wikidata(qid: str) -> str:
    """The English Wikipedia article linked from a Wikidata item, if any."""
    try:
        d = get_json(WIKIDATA, params={"action": "wbgetentities", "ids": qid, "props": "sitelinks",
                                       "sitefilter": "enwiki", "format": "json"}, timeout=10)
    except Offline:
        raise
    except Exception:
        return ""
    return ((((d.get("entities") or {}).get(qid) or {}).get("sitelinks") or {}).get("enwiki") or {}).get("title", "")


def _find_painting(title: str, maker: str) -> dict | None:
    """Search Wikipedia for an article about this painting. Only accepted when the
    article's title contains the painting's title and it's about the same painter."""
    t, sur = content.fold(title), _surname(maker)
    if len(t) < 4 or not sur:
        return None
    try:
        d = get_json(API, params={"action": "query", "list": "search", "srsearch": f"{title} {maker}",
                                  "srlimit": 3, "format": "json"}, timeout=10)
    except Offline:
        raise
    except Exception:
        return None
    for hit in (d.get("query") or {}).get("search") or []:
        if t in content.fold(hit.get("title", "")) and sur in content.fold(hit.get("snippet", "") + hit["title"]):
            s = _summary(hit["title"])
            if s and sur in content.fold(s["text"]) and PAINTING_WORDS.search(f"{s['description']} {s['text']}"):
                return s
            return None
    return None


def artist(maker: str) -> dict | None:
    """A short Wikipedia text about the artist (cached for all their paintings)."""
    name = _clean_maker(maker)
    if not name:
        return None
    key = f"wiki:artist:{content.fold(name)}"
    hit = cache.kv().get(key, TTL)
    if hit is not None:
        return hit or None
    s = _summary(name)
    ok = s and ARTIST_WORDS.search(f"{s['description']} {s['text'][:300]}") and _surname(name) in content.fold(s["title"] + s["text"][:200])
    cache.kv().set(key, s if ok else {})
    return s if ok else None


def painting(artwork_id: str, title: str, maker: str) -> dict | None:
    """A short Wikipedia text about the painting itself, if it has an article."""
    key = f"wiki:painting:{artwork_id}"
    hit = cache.kv().get(key, TTL)
    if hit is not None:
        return hit or None
    s = None
    qid = artwork_id.split("-", 1)[1] if artwork_id.startswith("wikidata-") else ""
    if _QID.match(qid):
        article = _from_wikidata(qid)
        s = _summary(article) if article else None
    else:
        s = _find_painting(title, _clean_maker(maker))
    cache.kv().set(key, s or {})
    return s


def about(artwork_id: str, title: str, maker: str) -> dict:
    """{"painting": …, "artist": …, "credit": …}; empty parts are None. Offline: nothing, not cached."""
    try:
        p = painting(artwork_id, title, maker)
        a = artist(maker)
    except Offline:
        return {"painting": None, "artist": None, "credit": "", "offline": True}
    if p and a and p["url"] == a["url"]:
        p = None
    return {"painting": p, "artist": a, "credit": CREDIT if (p or a) else ""}
