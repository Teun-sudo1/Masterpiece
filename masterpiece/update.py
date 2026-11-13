"""Updates "over the air" via GitHub Releases.

- check():   asks GitHub for the newest release (one small request, cached 12 hours)
- download(): fetches its Masterpiece-Setup-<version>.exe over HTTPS and verifies the
              SHA-256 checksum GitHub publishes for it (or a .sha256 file next to it);
              a file that doesn't match is deleted and never run
- install(): runs that Setup silently. It quits Masterpiece, updates it in place and
              starts it again; settings, collection and rotation are kept.

Nothing is installed without the user clicking "Install now". Publishing a release is
described in README.md ("Releasing an update").
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from . import UPDATE_REPO, __version__, cache

API = "https://api.github.com/repos/{repo}/releases/latest"
CHECK_TTL = 12 * 3600
HEADERS = {"User-Agent": f"Masterpiece/{__version__} (update check)",
           "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
SETUP_NAME = re.compile(r"^Masterpiece-Setup-[\d.]+\.exe$", re.I)
DOWNLOAD_HOSTS = (".github.com", ".githubusercontent.com")
MAX_SETUP_BYTES = 200 * 1024 * 1024

_lock = threading.Lock()
_progress = {"state": "idle", "done": 0, "total": 0, "error": ""}


def version_tuple(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (v or "").split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def enabled() -> bool:
    return bool(UPDATE_REPO)


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse(release: dict) -> dict | None:
    if release.get("draft") or release.get("prerelease"):
        return None
    assets = release.get("assets") or []
    setup = next((a for a in assets if SETUP_NAME.match(a.get("name") or "")), None)
    if not setup:
        return None
    sha = ""
    digest = setup.get("digest") or ""                   # GitHub: "sha256:<hex>"
    if digest.lower().startswith("sha256:"):
        sha = digest.split(":", 1)[1].lower()
    side = next((a for a in assets if (a.get("name") or "") == setup["name"] + ".sha256"), None)
    return {
        "version": (release.get("tag_name") or "").lstrip("vV"),
        "name": release.get("name") or release.get("tag_name") or "",
        "notes": (release.get("body") or "").strip()[:4000],
        "page": release.get("html_url") or "",
        "asset": setup["name"],
        "url": setup.get("browser_download_url") or "",
        "size": int(setup.get("size") or 0),
        "sha256": sha,
        "shaUrl": (side or {}).get("browser_download_url") or "",
    }


def check(force: bool = False) -> dict:
    """{"current", "latest", "available", "release", "error"}. Cached for 12 hours."""
    out = {"current": __version__, "latest": None, "available": False, "release": None,
           "enabled": enabled(), "canInstall": frozen(), "error": ""}
    if not enabled():
        return out
    rel = None if force else cache.kv().get("update:latest", CHECK_TTL)
    if rel is None:
        try:
            rel = _parse(json.loads(_get(API.format(repo=UPDATE_REPO)))) or {}
        except Exception as e:                 # offline, rate-limited, no release yet, …
            out["error"] = f"Couldn't check for updates ({type(e).__name__})."
            return out
        cache.kv().set("update:latest", rel)
    if rel:
        out["latest"] = rel["version"]
        out["release"] = rel
        out["available"] = version_tuple(rel["version"]) > version_tuple(__version__)
    return out


def updates_dir() -> Path:
    return cache.cache_dir().parent / "updates"


def progress() -> dict:
    return dict(_progress)


def _allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and any(host == h.lstrip(".") or host.endswith(h) for h in DOWNLOAD_HOSTS)


def download(rel: dict) -> Path:
    """Download and verify the Setup. Raises ValueError if it doesn't check out."""
    if not _allowed(rel.get("url", "")):
        raise ValueError("Unexpected download address")
    expected = rel.get("sha256") or ""
    if not expected and rel.get("shaUrl") and _allowed(rel["shaUrl"]):
        expected = _get(rel["shaUrl"]).decode("ascii", "ignore").split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("The release has no checksum, so it can't be verified")

    d = updates_dir()
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*"):                              # keep only this download
        try:
            old.unlink()
        except OSError:
            pass
    dest = d / Path(rel["asset"]).name
    tmp = dest.with_suffix(".part")
    h = hashlib.sha256()
    _progress.update(state="downloading", done=0, total=rel.get("size") or 0, error="")
    req = urllib.request.Request(rel["url"], headers={**HEADERS, "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        if not _allowed(r.geturl()):                     # after GitHub's redirect to its file server
            raise ValueError("Unexpected download address")
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            _progress["done"] += len(chunk)
            if _progress["done"] > MAX_SETUP_BYTES:
                raise ValueError("Download too large")
    if h.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise ValueError("The download doesn't match its checksum and was deleted")
    tmp.replace(dest)
    return dest


def install(path: Path) -> None:
    """Start the verified Setup silently, detached; it will quit and restart Masterpiece."""
    DETACHED, NEW_GROUP = 0x00000008, 0x00000200
    subprocess.Popen([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     creationflags=DETACHED | NEW_GROUP, close_fds=True)


def start_install(rel: dict) -> None:
    """Download + verify + install in the background; see progress()."""
    def run():
        try:
            path = download(rel)
            _progress.update(state="installing")
            install(path)
        except Exception as e:
            _progress.update(state="error", error=str(e) or type(e).__name__)
    with _lock:
        if _progress["state"] in ("downloading", "installing"):
            return
        _progress.update(state="downloading", done=0, total=rel.get("size") or 0, error="")
    threading.Thread(target=run, daemon=True).start()
