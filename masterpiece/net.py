"""Small HTTP helpers (stdlib only) with an honest, identifying User-Agent."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import UPDATE_REPO, __version__

# Check HTTPS certificates the way Windows does (like a browser). Some museum servers
# (e.g. the Getty) leave out an intermediate certificate; Windows fetches it, Python's
# own check doesn't and fails. truststore makes Python use the Windows check.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:            # not installed / not supported: Python's own check
    pass

# Wikimedia (and good manners) ask for a contact URL in the User-Agent
USER_AGENT = f"Masterpiece/{__version__} (open-source desktop wallpaper tool; https://github.com/{UPDATE_REPO})"

# The Art Institute of Chicago asks API users to identify themselves with
# this header; its IIIF image server refuses anonymous clients without it.
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "AIC-User-Agent": USER_AGENT,
    "Accept": "application/json, image/*;q=0.9, */*;q=0.5",
}

TIMEOUT = 20

# Be gentle with the museums: at most a few simultaneous requests per server,
# and for servers with strict bot protection also a minimum gap between requests.
MAX_PER_HOST = 4
HOST_LIMITS = {   # host: (max simultaneous, min seconds between requests)
    "collectionapi.metmuseum.org": (1, 0.35),
    "images.metmuseum.org": (2, 0.2),
    "lux.collections.yale.edu": (2, 0.1),          # a university service: go easy
    "manifests.collections.yale.edu": (2, 0.1),
    "data.getty.edu": (2, 0.1),
    "media.getty.edu": (2, 0.1),
    "upload.wikimedia.org": (2, 0.1),
}
_host_slots: dict[str, "_Slot"] = {}
_host_lock = threading.Lock()


class _Slot:
    def __init__(self, n: int, gap: float):
        self.sem = threading.BoundedSemaphore(n)
        self.gap = gap
        self.last = 0.0
        self.lock = threading.Lock()

    def __enter__(self):
        self.sem.acquire()
        if self.gap:
            with self.lock:
                wait = self.last + self.gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.sem.release()
        return False


def _slot(url: str) -> _Slot:
    host = urllib.parse.urlsplit(url).hostname or ""
    with _host_lock:
        if host not in _host_slots:
            n, gap = HOST_LIMITS.get(host, (MAX_PER_HOST, 0.0))
            _host_slots[host] = _Slot(n, gap)
        return _host_slots[host]


class Blocked(OSError):
    """The museum's bot protection refused us; back off instead of retrying."""


def _request(url: str, *, params: dict | None = None, body: dict | None = None,
             headers: dict | None = None) -> urllib.request.Request:
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")


def get_json(url: str, *, params: dict | None = None, body: dict | None = None,
             timeout: float = TIMEOUT) -> dict:
    try:
        with _slot(url), urllib.request.urlopen(_request(url, params=params, body=body), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"{urllib.parse.urlsplit(url).hostname} is limiting requests right now (HTTP {e.code})") from e
        raise


def fetch(url: str, *, timeout: float = 60) -> tuple[bytes, str]:
    """Return (content, content_type)."""
    with _slot(url), urllib.request.urlopen(_request(url), timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "application/octet-stream")
