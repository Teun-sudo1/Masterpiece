"""How much disk space Masterpiece uses, and freeing what can be downloaded again."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import cache, wallpaper


def _size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def _parts(folder: Path) -> list[dict]:
    app = wallpaper.app_dir()
    cdir = cache.cache_dir()
    collection = sum(p.stat().st_size for p in wallpaper.own_files(folder))
    return [
        {"key": "collection", "label": "Your paintings", "bytes": collection, "path": str(folder),
         "note": "The paintings you chose. Removed only via My collection or “Keep max”."},
        {"key": "originals", "label": "Originals", "bytes": _size(wallpaper.originals_dir()),
         "note": "Unlabelled copies, so a new label or screen never needs a new download."},
        {"key": "previews", "label": "Previews", "bytes": _size(cdir / "img"), "free": True,
         "note": "Search-result pictures. Downloaded again when you need them."},
        {"key": "thumbs", "label": "Thumbnails", "bytes": _size(cdir / "thumbs"), "free": True,
         "note": "Small pictures for My collection. Made again when needed."},
        {"key": "updates", "label": "Update downloads", "bytes": _size(app / "updates"), "free": True,
         "note": "Installers of updates that are already installed."},
        {"key": "other", "label": "Other", "bytes": _size(cdir / "cache.sqlite") + _size(wallpaper.current_dir())
         + _size(app / "lockscreen") + _size(app / "window"),
         "note": "Search results, what's on screen now, the app window's data."},
    ]


def usage(folder: Path) -> dict:
    parts = _parts(folder)
    return {"parts": parts, "total": sum(p["bytes"] for p in parts),
            "freeable": sum(p["bytes"] for p in parts if p.get("free"))}


def free_space() -> int:
    """Delete previews, thumbnails and old update installers. Returns bytes freed."""
    app = wallpaper.app_dir()
    freed = 0
    for d in (cache.cache_dir() / "img", cache.cache_dir() / "thumbs", app / "updates"):
        freed += _size(d)
        shutil.rmtree(d, ignore_errors=True)
    return freed
