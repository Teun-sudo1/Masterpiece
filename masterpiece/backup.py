"""Remember the wallpaper you had before Masterpiece, and put it back on request.

capture()  is called right before Masterpiece changes the desktop. It snapshots the
           current background (per-screen pictures, fit, colour, or Windows slideshow)
           and copies the pictures, unless the desktop already shows a Masterpiece
           painting (then the earlier snapshot is kept).
restore()  stops the rotation and puts the snapshot back. Without a snapshot it falls
           back to the Windows default wallpaper.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from . import cache, monitors, schedule

KEY = "backup:state"


def _dir() -> Path:
    return cache.cache_dir().parent / "backup"


def _is_ours(path: str, ours: list[Path]) -> bool:
    if not path:
        return False
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    return any(d.resolve() in p.parents for d in ours if d)


def _transcoded() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"


def capture(ours: list[Path]) -> bool:
    """Snapshot the current wallpaper unless it's already one of ours. Returns True if saved."""
    try:
        snap = monitors.snapshot()
    except OSError:
        return False
    ss = snap.get("slideshow")
    if ss and _is_ours(ss.get("folder", "") + os.sep + "x", ours):
        return False
    paths = [p for p in snap["wallpapers"].values() if p]
    if not ss and any(_is_ours(p, ours) for p in paths):
        return False                       # Masterpiece is already on the desktop

    d = _dir()
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for i, (mid, path) in enumerate(snap["wallpapers"].items()):
        src = Path(path) if path and Path(path).is_file() else None
        if src is None and path:
            src = _transcoded() if _transcoded().is_file() else None   # Windows' own copy
        if src:
            dst = d / f"screen-{i}{src.suffix or '.jpg'}"
            try:
                shutil.copy2(src, dst)
                files[mid] = str(dst)
            except OSError:
                pass
    cache.kv().set(KEY, {"snap": snap, "files": files, "time": time.time()})
    return True


def has_backup() -> bool:
    return bool(cache.kv().get(KEY, 1e12))


def _windows_default() -> str | None:
    web = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Web" / "Wallpaper" / "Windows"
    for name in ("img0.jpg", "img19.jpg"):
        if (web / name).is_file():
            return str(web / name)
    return None


def restore() -> dict:
    """Stop the rotation and bring back the wallpaper (and lock screen) from before Masterpiece."""
    schedule.disable()
    try:
        from . import lockscreen
        lockscreen.restore()
    except Exception:
        pass                                  # the desktop wallpaper matters most
    state = cache.kv().get(KEY, 1e12)
    if state:
        monitors.restore(state["snap"], state["files"])
        cache.kv().set(KEY, None)
        return {"restored": "previous"}
    default = _windows_default()
    if default:
        monitors.set_all(default)
        return {"restored": "default"}
    return {"restored": None}
