"""The Curator: Masterpiece picks new paintings for you, once a day.

With "Show as: Curator" the rotation works as usual, but every day the Curator also goes
looking in the museums and adds a few new paintings (setting "curatorDaily", default 3) to
your collection. What it looks for comes from your own taste:

- artists you saved or marked as favourite ("Because you like Claude Monet")
- a subject (your chosen one, or one of the calm wallpaper subjects)
- the season, when "Follow the seasons" is on ("A winter scene for December")
- now and then a surprise from one museum ("A surprise from the Rijksmuseum")

It uses your filters (fits your screens, sharp, hidden subjects, region), never picks a
painting you already have or hid, and stays gentle: a handful of searches per day, in a
few museums at a time. Paintings you mark as favourite are never cleaned up.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from pathlib import Path

from . import cache, content, monitors, settings, wallpaper
from .models import Artwork
from .net import Offline
from .search import search_all
from .sources import SOURCES

CALM_SUBJECTS = ["landscape", "water", "city", "flowers", "stilllife", "animals", "dailylife", "seasons"]
SEASON_SEARCH = {"winter": ("seasons", "", "A winter scene"), "spring": (None, "spring", "A spring painting"),
                 "summer": (None, "summer", "A summer painting"), "autumn": (None, "autumn", "An autumn painting")}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
SOURCES_PER_SEARCH = 3
UNKNOWN = __import__("re").compile(r"unknown|anonym|ubekendt|onbekend|unbekannt|inconnu|sconosciuto|desconocido", 2)
RUN_GUARD = 30 * 60
TIME_BUDGET = 90                 # seconds: stop starting new searches after this (the rest comes next time)              # don't start twice within 30 min (tray + rotation task)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def picks() -> dict:
    """{file name: {"reason", "date"}} for paintings the Curator added."""
    return cache.kv().get("curator:picks", 1e12) or {}


def reason_for(name: str) -> str:
    return (picks().get(name) or {}).get("reason", "")


def taste(s: dict, folder: Path) -> Counter:
    """Artists you like: favourites count 3×, other saved paintings 1×."""
    favs = set(s.get("favourites") or [])
    makers: Counter = Counter()
    for item in wallpaper.collection(folder):
        m = (item.get("maker") or "").strip()
        if not m or UNKNOWN.search(m) or m.lower() == "artist":
            continue
        makers[m] += 3 if item["id"] in favs else 1
    for m, n in learned(s)["makers"].items():           # thumbs: up adds, down takes away
        makers[m] += 4 * n
    return Counter({m: n for m, n in makers.items() if n > 0})


# ------------------------------------------------------------------ thumbs up / down
# "More like this" / "Less like this" on a painting you see. Each thumb remembers the painting's
# artist, subjects, period and museum; the Curator leans towards (or away from) those.
THUMBS_KEEP = 300
NUDGE = 1.6                        # one thumb = ×1.6 (or ÷1.6) on that subject/period/museum
NUDGE_RANGE = (0.3, 4.0)


def subjects_of(title: str) -> list[str]:
    import re as _re
    t = content.fold(title or "")
    return [k for k, v in content.SUBJECTS.items()
            if any(_re.search(r"\b" + _re.escape(content.fold(w)) + r"\b", t) for w in [v["keyword"], *v["aic"]])]


def period_of(year) -> str | None:
    import re as _re
    m = _re.search(r"-?\d{3,4}", str(year or ""))
    if not m:
        return None
    y = int(m.group())
    return next((k for k, p in content.PERIODS.items() if p["start"] <= y < p["end"]), None)


def thumb_entry(meta: dict, value: int) -> dict:
    """What a thumb remembers about a painting (meta: the collection's text for it)."""
    aid = str(meta.get("id") or "")
    maker = (meta.get("maker") or "").strip()
    return {"v": 1 if value > 0 else -1, "title": meta.get("title") or "",
            "maker": "" if not maker or UNKNOWN.search(maker) else maker,
            "subjects": subjects_of(meta.get("title") or ""), "period": period_of(meta.get("year")),
            "museum": aid.split("-", 1)[0] if "-" in aid else "", "date": _today()}


def set_thumb(meta: dict, value: int) -> dict:
    """value 1 = more like this, -1 = less like this, 0 = forget the thumb. Returns all thumbs."""
    aid = str(meta.get("id") or "")
    thumbs = dict(settings.load().get("thumbs") or {})
    thumbs.pop(aid, None)
    if value and aid:
        thumbs[aid] = thumb_entry(meta, value)
    thumbs = dict(list(thumbs.items())[-THUMBS_KEEP:])
    return settings.save({"thumbs": thumbs})["thumbs"]


def thumb(name: str, value: int) -> dict:
    """A thumb on a painting from your collection. Down: the Curator leans away from it, and the
    painting itself goes (off your screen, out of your collection, never shown again).
    Returns {"thumb": the new value, "wallpapers": what replaced it (thumb down on screen)}."""
    s = settings.load()
    folder = wallpaper.resolve_folder(s.get("folder"))
    meta = dict(cache.kv().get(wallpaper._meta_key(name), 1e12) or {})
    meta.setdefault("id", Path(name).stem)
    value = 1 if value > 0 else -1 if value < 0 else 0
    set_thumb(meta, value)
    out: dict = {"thumb": value}
    if value < 0:
        banned = [b for b in s.get("banned") or [] if b.get("id") != meta["id"]]
        banned.append({"id": meta["id"], "title": meta.get("title") or name, "maker": meta.get("maker") or "",
                       "museum": meta.get("museum") or ""})
        settings.save({"banned": banned,
                       "selection": [a for a in s.get("selection") or [] if a.get("id") != meta["id"]]})
        wallpaper.skip_upcoming(name)
        if name in {c["name"] for c in wallpaper.currently_shown()}:
            out["wallpapers"] = wallpaper.skip(name).get("wallpapers", {})
        else:
            wallpaper.remove(folder, name)
    return out


def thumb_of(s: dict, name: str) -> int:
    meta = cache.kv().get(wallpaper._meta_key(name), 1e12) or {}
    t = (s.get("thumbs") or {}).get(str(meta.get("id") or Path(name).stem)) or {}
    return 1 if t.get("v", 0) > 0 else -1 if t.get("v", 0) < 0 else 0


def learned(s: dict) -> dict:
    """Sums of the thumbs per artist, subject, period and museum (+ more, − less)."""
    out = {"makers": Counter(), "subjects": Counter(), "periods": Counter(), "museums": Counter()}
    for t in (s.get("thumbs") or {}).values():
        v = 1 if t.get("v", 0) > 0 else -1
        if t.get("maker"):
            out["makers"][t["maker"]] += v
        for k in t.get("subjects") or ():
            out["subjects"][k] += v
        if t.get("period"):
            out["periods"][t["period"]] += v
        if t.get("museum"):
            out["museums"][t["museum"]] += v
    return out


def learned_summary(s: dict) -> dict:
    """For the Curator tab: what the thumbs taught, in words."""
    L = learned(s)
    names = {"subjects": {k: v["label"] for k, v in content.SUBJECTS.items()},
             "periods": {k: v["label"] for k, v in content.PERIODS.items()},
             "museums": {k: getattr(m, "NAME", k) for k, m in SOURCES.items()}}
    more, less = [], []
    for group in ("makers", "subjects", "periods", "museums"):
        for k, n in L[group].most_common():
            label = k if group == "makers" else names[group].get(k, k)
            (more if n > 0 else less if n < 0 else []).append(label)
    thumbs = s.get("thumbs") or {}
    return {"up": sum(1 for t in thumbs.values() if t.get("v", 0) > 0),
            "down": sum(1 for t in thumbs.values() if t.get("v", 0) < 0),
            "more": more[:5], "less": less[:5]}


def _nudged(w: dict, sums: Counter) -> dict:
    """Slider weights moved by the thumbs. "Never" stays never."""
    lo, hi = NUDGE_RANGE
    return {k: (v if not v or not sums.get(k) else min(hi, max(lo, v * NUDGE ** sums[k]))) for k, v in w.items()}


LEVEL_WEIGHT = [0.0, 0.4, 1.0, 2.5, 5.0]       # slider 0 never · 1 less · 2 normal · 3 more · 4 a lot
SURPRISE_WEIGHT = [0.0, 1.0, 2.0, 4.0, 7.0]


def _level(v) -> int:
    try:
        return max(0, min(4, int(v)))
    except (TypeError, ValueError):
        return 2


def weights(s: dict, group: str, keys) -> dict:
    """Slider weights for one group (subjects / periods / regions / museums)."""
    taste = (s.get("curatorTaste") or {}).get(group) or {}
    return {k: LEVEL_WEIGHT[_level(taste.get(k, 2))] for k in keys}


def _pick(rng: random.Random, w: dict, only_if_personal: bool = False):
    """Weighted choice. only_if_personal: None while every slider is still on "normal"."""
    if only_if_personal and all(v == 1.0 for v in w.values()):
        return None
    keys = [k for k, v in w.items() if v > 0]
    return rng.choices(keys, weights=[w[k] for k in keys])[0] if keys else None


def plan(s: dict, makers: Counter, count: int, rng: random.Random) -> list[dict]:
    """What to look for: one search per new painting, varied, following your sliders."""
    muted = {m.lower() for m in s.get("curatorMutedArtists") or []}
    top = [(m, n) for m, n in makers.most_common(12) if m.lower() not in muted][:8]
    L = learned(s)
    subj_w = _nudged(weights(s, "subjects", content.SUBJECTS), L["subjects"])
    period_w = _nudged(weights(s, "periods", content.PERIODS), L["periods"])
    region_w = weights(s, "regions", content.REGIONS)
    strategies = [("subject", 3.0)]
    if top:
        strategies.append(("artist", 4.0))
    if s.get("seasons"):
        strategies.append(("season", 2.0))
    surprise = SURPRISE_WEIGHT[_level(s.get("curatorSurprise", 2))]
    if surprise:
        strategies.append(("surprise", surprise))
    out = []
    for _ in range(count):
        kind = rng.choices([k for k, _ in strategies], weights=[w for _, w in strategies])[0]
        p = {"query": "", "subject": None, "period": _pick(rng, period_w, True),
             "region": _pick(rng, region_w, True)}
        if kind == "artist":
            maker = rng.choices([m for m, _ in top], weights=[n for _, n in top])[0]
            p.update(query=maker, period=None, region=None, reason=f"Because you like {maker}")
        elif kind == "subject":
            subj = _pick(rng, subj_w) or "landscape"
            p.update(subject=subj, reason=f"{content.SUBJECTS[subj]['label']}, picked for you")
        elif kind == "season":
            subj, word, label = SEASON_SEARCH[wallpaper.season_now()]
            p.update(query=word, subject=subj, reason=f"{label} for {MONTHS[time.localtime().tm_mon - 1]}")
        else:
            p.update(surprise=True, period=None, region=None, reason="A surprise")
        out.append(p)
    return out


def _targets(s: dict) -> tuple[str, list[tuple[int, int]]]:
    lay = monitors.layout()
    if s.get("screens") == "span" and lay.get("span") and len(lay["monitors"]) > 1:
        return "screens", [(lay["span"]["width"], lay["span"]["height"])]
    return "screens", [(m["width"], m["height"]) for m in lay["monitors"]] or [(1920, 1080)]


def _never_filter(s: dict):
    """Drop results that clearly belong to a subject or period you set to "never"."""
    never_subj = [k for k, v in weights(s, "subjects", content.SUBJECTS).items() if v == 0]
    words = [content.fold(w) for k in never_subj for w in [content.SUBJECTS[k]["keyword"], *content.SUBJECTS[k]["aic"]]]
    never_periods = [content.PERIODS[k] for k, v in weights(s, "periods", content.PERIODS).items() if v == 0]
    less_makers = {m.lower() for m, n in learned(s)["makers"].items() if n <= -2}
    import re as _re

    def ok(d: dict) -> bool:
        if (d.get("maker") or "").strip().lower() in less_makers:
            return False
        title = content.fold(d.get("title") or "")
        if any(_re.search(r"\b" + _re.escape(w) + r"\b", title) for w in words):
            return False
        m = _re.search(r"\d{4}", str(d.get("year") or ""))
        if m and any(p["start"] <= int(m.group()) < p["end"] for p in never_periods):
            return False
        return True
    return ok


def _museums(s: dict, enabled: list[str], n: int, rng: random.Random) -> list[str]:
    """Up to n museums, weighted by your museum sliders (never = left out)."""
    w = _nudged(weights(s, "museums", enabled), learned(s)["museums"])
    pool = [k for k in enabled if w[k] > 0]
    chosen = []
    while pool and len(chosen) < n:
        k = rng.choices(pool, weights=[w[x] for x in pool])[0]
        chosen.append(k)
        pool.remove(k)
    return chosen


def discover(s: dict | None = None, count: int | None = None, rng: random.Random | None = None) -> list[dict]:
    """Find and download `count` new paintings. Returns what was added (with reasons)."""
    s = s or settings.load()
    rng = rng or random.Random()
    count = max(1, min(10, int(count or s.get("curatorDaily") or 3)))
    folder = wallpaper.resolve_folder(s.get("folder"))
    have = set(wallpaper.saved_ids(folder))
    hidden = {b.get("id") for b in s.get("banned") or []}
    enabled = [k for k in s.get("enabledSources") or list(SOURCES) if k in SOURCES]
    if not enabled:
        return []
    orientation, targets = _targets(s)
    mw = str(s.get("minWidth") or "sharp")
    hide = set(s.get("hide") or ())
    if weights(s, "subjects", ["religious"])["religious"] == 0:
        hide.add("religious")
    filters = dict(orientation=orientation, targets=targets, sharp=mw == "sharp",
                   min_width=int(mw) if mw.isdigit() else 0, hide=tuple(hide))
    keep = _never_filter(s)

    added: list[dict] = []
    log = picks()
    deadline = time.monotonic() + TIME_BUDGET
    for p in plan(s, taste(s, folder), count * 2, rng):    # spare searches for ones that find nothing new
        if len(added) >= count or (added and time.monotonic() > deadline):
            break
        keys = _museums(s, enabled, 1 if p.get("surprise") else SOURCES_PER_SEARCH, rng)
        if not keys:
            break
        pages = (1, 6) if p.get("surprise") else (1, 2)
        try:
            r = search_all(keys, cursors={k: rng.randint(*pages) for k in keys}, query=p["query"],
                           subject=p["subject"], period=p.get("period"), region=p.get("region"),
                           max_pages=1, **filters)          # one page per museum: modest and quick
        except Offline:
            raise
        except Exception:
            continue
        if not r["results"] and r["errors"] and all("offline" in e for e in r["errors"].values()):
            raise Offline("no internet connection")
        fresh = [d for d in r["results"] if d["id"] not in have and d["id"] not in hidden and keep(d)]
        if not fresh:
            continue
        d = rng.choice(fresh[:8])
        art = Artwork.from_dict(d)
        try:
            path = wallpaper.download(art, folder, label=bool(s.get("label", True)),
                                      pos=wallpaper.label_pos(s.get("labelPos")),
                                      style=wallpaper.label_style(s.get("labelStyle")))
        except Offline:
            if added:
                break
            raise
        except Exception:
            continue
        reason = p["reason"]
        if p.get("surprise"):
            reason = f"A surprise from {art.museum}" if art.museum.startswith("The ") else f"A surprise from the {art.museum}"
        have.add(art.id)
        log[path.name] = {"reason": reason, "date": _today()}
        added.append({"name": path.name, "id": art.id, "title": art.title, "maker": art.maker,
                      "museum": art.museum, "reason": reason})
    names = {p.name for p in wallpaper.own_files(folder)}
    cache.kv().set("curator:picks", {k: v for k, v in log.items() if k in names})
    wallpaper.queue_first([a["name"] for a in added])
    wallpaper.cleanup(folder, int(s.get("maxFiles") or 50), keep_ids=set(s.get("favourites") or []))
    return added


def due(s: dict) -> bool:
    return s.get("mode") == "curator" and cache.kv().get("curator:last", 1e12) != _today()


def run_if_due(s: dict | None = None, force: bool = False) -> list[dict] | None:
    """Once a day (or when forced): look for new paintings. None = not run now."""
    s = s or settings.load()
    if not force and not due(s):
        return None
    started = cache.kv().get("curator:running", RUN_GUARD)
    if started and not force:
        return None                                  # another process is already at it
    cache.kv().set("curator:running", time.time())
    try:
        try:
            added = discover(s)
        except Offline:
            # No internet: keep rotating what you have. Today's look isn't used up: the next
            # rotation (or "Ask the Curator now") tries again.
            cache.kv().set("curator:waiting", True)
            return []
        cache.kv().set("curator:waiting", None)
        cache.kv().set("curator:last", _today())
        cache.kv().set("curator:latest", added)
        return added
    finally:
        cache.kv().set("curator:running", None)


def latest() -> list[dict]:
    return cache.kv().get("curator:latest", 1e12) or []
