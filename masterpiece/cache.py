"""Local cache, so we ask the museums' servers for the same thing as rarely as possible.

- kv():        small SQLite key/value store with per-read max age (search pages, object data)
- image files: preview/thumbnail images on disk (see server.py)

Location: %LOCALAPPDATA%\\Masterpiece\\cache (override with MASTERPIECE_CACHE).
Deleting the folder is always safe.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

HOUR = 3600
DAY = 24 * HOUR


def cache_dir() -> Path:
    override = os.environ.get("MASTERPIECE_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "Masterpiece" / "cache"


class KV:
    def __init__(self, path: str):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, t REAL, v TEXT)")
        self.db.commit()

    def get(self, key: str, max_age: float):
        with self.lock:
            row = self.db.execute("SELECT t, v FROM kv WHERE k = ?", (key,)).fetchone()
        if row and time.time() - row[0] < max_age:
            return json.loads(row[1])
        return None

    def set(self, key: str, value) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv (k, t, v) VALUES (?, ?, ?)",
                            (key, time.time(), json.dumps(value, ensure_ascii=False)))
            self.db.commit()

    # Not a cache: details of your own collection and wallpaper. Never pruned.
    KEEP = ("art:", "labelled:", "bright:", "current:", "rotation:", "backup:")

    def prune(self, max_age: float) -> None:
        keep = " AND ".join("k NOT LIKE ?" for _ in self.KEEP)
        with self.lock:
            self.db.execute(f"DELETE FROM kv WHERE t < ? AND {keep}",
                            (time.time() - max_age, *(p + "%" for p in self.KEEP)))
            self.db.commit()


_kv: KV | None = None
_kv_lock = threading.Lock()


def kv() -> KV:
    global _kv
    with _kv_lock:
        if _kv is None:
            try:
                d = cache_dir()
                d.mkdir(parents=True, exist_ok=True)
                _kv = KV(str(d / "cache.sqlite"))
                _kv.prune(60 * DAY)
            except (OSError, sqlite3.Error):
                _kv = KV(":memory:")       # cache is an optimisation, never a requirement
        return _kv


# ------------------------------------------------------------------ images

IMAGE_TTL = 30 * DAY
IMAGE_MAX_BYTES = 500 * 1024 * 1024
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
_writes = 0
_img_lock = threading.Lock()


def _image_dir() -> Path:
    return cache_dir() / "img"


def _image_path(url: str, ext: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return _image_dir() / h[:2] / f"{h}{ext}"


def image_get(url: str) -> tuple[bytes, str] | None:
    for ctype, ext in _EXT.items():
        p = _image_path(url, ext)
        try:
            if time.time() - p.stat().st_mtime < IMAGE_TTL:
                return p.read_bytes(), ctype
        except OSError:
            continue
    return None


def image_put(url: str, data: bytes, ctype: str) -> None:
    global _writes
    ext = _EXT.get(ctype.split(";")[0].strip())
    if not ext:
        return
    p = _image_path(url, ext)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    except OSError:
        return
    with _img_lock:
        _writes += 1
        if _writes % 200 == 1:
            _prune_images()


def _prune_images() -> None:
    """Keep the image cache under IMAGE_MAX_BYTES, oldest first."""
    try:
        files = [(f.stat().st_mtime, f.stat().st_size, f) for f in _image_dir().rglob("*") if f.is_file()]
    except OSError:
        return
    total = sum(s for _, s, _ in files)
    for _, size, f in sorted(files):
        if total <= IMAGE_MAX_BYTES:
            break
        try:
            f.unlink()
            total -= size
        except OSError:
            pass


def reset() -> None:
    """For tests: forget the current store."""
    global _kv
    with _kv_lock:
        _kv = None
