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
from .search import search_all
from .sources import SOURCES

CALM_SUBJECTS = ["landscape", "water", "city", "flowers", "stilllife", "animals", "dailylife", "seasons"]
SEASON_SEARCH = {"winter": ("seasons", "", "A winter scene"), "spring": (None, "spring", "A spring painting"),
                 "summer": (None, "summer", "A summer painting"), "autumn": (None, "autumn", "An autumn painting")}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
SOURCES_PER_SEARCH = 3
RUN_GUARD = 30 * 60              # don't start twice within 30 min (tray + rotation task)


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
        if not m or "unknown" in m.lower() or m.lower() in ("anonymous", "artist"):
            continue
        makers[m] += 3 if item["id"] in favs else 1
    return makers


def plan(s: dict, makers: Counter, count: int, rng: random.Random) -> list[dict]:
    """What to look for today: one search per new painting, varied."""
    strategies = []
    if makers:
        strategies.append(("artist", 4))
    strategies.append(("subject", 3))
    if s.get("seasons"):
        strategies.append(("season", 2))
    strategies.append(("surprise", 2))
    out = []
    top = makers.most_common(8)
    for _ in range(count):
        kind = rng.choices([k for k, _ in strategies], weights=[w for _, w in strategies])[0]
        if kind == "artist":
            maker = rng.choices([m for m, _ in top], weights=[n for _, n in top])[0]
            out.append({"query": maker, "subject": None, "reason": f"Because you like {maker}"})
        elif kind == "subject":
            subj = s.get("subject") if s.get("subject") in content.SUBJECTS else rng.choice(CALM_SUBJECTS)
            label = content.SUBJECTS[subj]["label"]
            out.append({"query": "", "subject": subj, "reason": f"{label}, picked for you"})
        elif kind == "season":
            subj, word, label = SEASON_SEARCH[wallpaper.season_now()]
            out.append({"query": word, "subject": subj,
                        "reason": f"{label} for {MONTHS[time.localtime().tm_mon - 1]}"})
        else:
            out.append({"query": "", "subject": None, "surprise": True, "reason": "A surprise"})
    return out


def _targets(s: dict) -> tuple[str, list[tuple[int, int]]]:
    lay = monitors.layout()
    if s.get("screens") == "span" and lay.get("span") and len(lay["monitors"]) > 1:
        return "screens", [(lay["span"]["width"], lay["span"]["height"])]
    return "screens", [(m["width"], m["height"]) for m in lay["monitors"]] or [(1920, 1080)]


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
    filters = dict(orientation=orientation, targets=targets, sharp=mw == "sharp",
                   min_width=int(mw) if mw.isdigit() else 0, hide=tuple(s.get("hide") or ()),
                   region=s.get("region") or None)

    added: list[dict] = []
    log = picks()
    for p in plan(s, taste(s, folder), count * 2, rng):    # spare searches for ones that find nothing new
        if len(added) >= count:
            break
        keys = rng.sample(enabled, 1 if p.get("surprise") else min(SOURCES_PER_SEARCH, len(enabled)))
        pages = (1, 6) if p.get("surprise") else (1, 2)
        try:
            r = search_all(keys, cursors={k: rng.randint(*pages) for k in keys},
                           query=p["query"], subject=p["subject"], **filters)
        except Exception:
            continue
        fresh = [d for d in r["results"] if d["id"] not in have and d["id"] not in hidden]
        if not fresh:
            continue
        d = rng.choice(fresh[:8])
        art = Artwork.from_dict(d)
        try:
            path = wallpaper.download(art, folder, label=bool(s.get("label", True)),
                                      pos=wallpaper.label_pos(s.get("labelPos")),
                                      style=wallpaper.label_style(s.get("labelStyle")))
        except Exception:
            continue
        reason = p["reason"]
        if p.get("surprise"):
            reason = f"A surprise from the {art.museum}" if not art.museum.startswith("The ") else f"A surprise from {art.museum}"
        have.add(art.id)
        log[path.name] = {"reason": reason, "date": _today()}
        added.append({"name": path.name, "id": art.id, "title": art.title, "maker": art.maker,
                      "museum": art.museum, "reason": reason})
    # forget reasons of paintings that are gone
    names = {p.name for p in wallpaper.own_files(folder)}
    cache.kv().set("curator:picks", {k: v for k, v in log.items() if k in names})
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
        added = discover(s)
        cache.kv().set("curator:last", _today())
        cache.kv().set("curator:latest", added)
        return added
    finally:
        cache.kv().set("curator:running", None)


def latest() -> list[dict]:
    return cache.kv().get("curator:latest", 1e12) or []
