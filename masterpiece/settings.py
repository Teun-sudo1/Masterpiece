"""User settings, stored outside the repo in %APPDATA%\\Masterpiece\\settings.json.

API keys for later sources (e.g. Europeana) will live here too — never in the repo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .sources import SOURCES

DEFAULTS: dict = {
    "enabledSources": list(SOURCES),
    "knownSources": list(SOURCES),    # museums that existed when settings were saved
    "query": "",
    "color": "",
    "topOnly": False,
    "subject": "",
    "period": "",
    "hide": [],                   # keys from content.HIDE
    "minWidth": "sharp",          # px as string, or "sharp" = sharp on my screens
    "orientation": "screens",     # any|landscape|portrait|widescreen|panorama|screens|span
    "label": True,
    "labelPos": {"x": 0.5, "y": 0.93},   # centre of the label, fractions of the screen
    # look: dark|light|plaque|shadow|subtle · font: sans|serif · size: s|m|l · text: full|two|artist|title
    "labelStyle": {"look": "dark", "font": "sans", "size": "m", "text": "full"},
    "region": "",
    "maxFiles": 50,
    "mode": "rotate",             # "rotate" (my collection) | "curator" (the Curator adds new ones daily)
    "interval": 60,               # minutes between paintings (slideshow / rotate), 1 … 44640
    "screens": "each",            # multi-monitor: "each" | "same" | "span"
    "crop": "middle",             # a painting cut to fit the screen keeps its "middle" | "bottom" | "top"
    "introSeen": False,
    "tourVersion": "",            # version whose tour was seen; after an update the tour shows only what's new
    "folder": "",                 # empty = default %USERPROFILE%\Pictures\Masterpiece
    "selection": [],              # list of Artwork dicts
    "banned": [],                 # "never show again": [{id, title, maker, museum}]
    "favourites": [],             # artwork IDs that come up more often in the rotation
    "timeOfDay": False,           # brighter paintings by day, darker in the evening
    "trayAtLogin": False,
    "skipVersion": "",            # "Later" on an update notice: don't mention this version again
    "autoUpdate": False,          # install updates by itself while the PC is idle
    "lastVersion": "",            # version seen at the previous start ("What's new" after an update)
    "lockScreen": False,          # also put the painting on the Windows lock screen
    "seasons": False,             # winter scenes in winter, blossom in spring, …
    "theme": "dark",              # the app's look: "dark" | "light" | "system" (as Windows)
    "curatorDaily": 3,            # Curator mode: new paintings it adds per day
    # Curator taste: 0 never · 1 less · 2 normal (default) · 3 more · 4 a lot
    "curatorTaste": {"subjects": {}, "periods": {}, "regions": {}, "museums": {}},
    "curatorSurprise": 2,         # how often the Curator surprises you (0 never … 4 often)
    "curatorMutedArtists": [],    # artists from your collection the Curator shouldn't look for
    "apiKeys": {},
}


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "Masterpiece" / "settings.json"


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
        s.update({k: v for k, v in stored.items() if k in DEFAULTS})
        # Museums added in a newer version start switched on
        known = stored.get("knownSources") or ["aic", "cleveland"]
        s["enabledSources"] = list(s["enabledSources"]) + [
            k for k in SOURCES if k not in known and k not in s["enabledSources"]]
        s["knownSources"] = list(SOURCES)
        if s["mode"] == "daily":              # older name
            s["mode"], s["interval"] = "rotate", 1440
        if s["mode"] not in ("rotate", "curator"):  # Windows slideshow / "just once" were dropped in 0.4
            s["mode"] = "rotate"
    except (OSError, ValueError):
        pass
    return s


def save(updates: dict) -> dict:
    s = load()
    s.update({k: v for k, v in updates.items() if k in DEFAULTS})
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return s
