"""Small HTTP helpers (stdlib only) with an honest, identifying User-Agent."""

from __future__ import annotations

import json
import socket
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
    "upload.wikimedia.org": (1, 1.0),              # rare files are rendered on request: one a second
}
_host_slots: dict[str, "_Slot"] = {}
_host_lock = threading.Lock()


MAX_WAIT = 20          # wait at most this long for a server that asked us to slow down; else give up


class _Slot:
    def __init__(self, host: str, n: int, gap: float):
        self.host = host
        self.sem = threading.BoundedSemaphore(n)
        self.gap = gap
        self.last = 0.0
        self.lock = threading.Lock()
        self.paused_until = 0.0
        self.unavailable = False

    def pause(self, seconds: float, unavailable: bool = False) -> None:
        """The server said "too many requests" (or only lets browsers in): leave it alone for a while."""
        self.paused_until = max(self.paused_until, time.monotonic() + seconds)
        self.unavailable = unavailable

    def __enter__(self):
        rest = self.paused_until - time.monotonic()
        if rest > MAX_WAIT:
            if self.unavailable:
                raise Unavailable(f"{self.host} only lets web browsers in right now")
            raise Blocked(f"{self.host} asked us to slow down; trying again in {round(rest)} s")
        if rest > 0:
            time.sleep(rest)
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
            _host_slots[host] = _Slot(host, n, gap)
        return _host_slots[host]


class Blocked(OSError):
    """The museum's bot protection refused us; back off instead of retrying."""


class Unavailable(Blocked):
    """The museum's website now asks every visitor to prove it is a web browser (a "challenge").
    Masterpiece doesn't pretend to be one: it leaves the museum alone and tries again hours later."""


UNAVAILABLE_PAUSE = 6 * 3600


class Offline(OSError):
    """No internet: names don't resolve, the network is unreachable. Masterpiece keeps rotating
    the paintings it already has and looks for new ones when you're back online."""


# Windows / POSIX: network down or unreachable, host unreachable
_DOWN_ERRNOS = {10050, 10051, 10065, 50, 51, 65, 101, 113}
_offline = {"since": 0.0, "probed": 0.0}


def _is_offline_error(e: BaseException) -> bool:
    reason = getattr(e, "reason", e)
    if isinstance(reason, socket.gaierror):
        return True
    return isinstance(reason, OSError) and getattr(reason, "errno", None) in _DOWN_ERRNOS


def _mark(offline: bool) -> None:
    """Remember (also for the other Masterpiece process) whether we're offline. Writes only on a change."""
    if offline == bool(_offline["since"]):
        return
    _offline["since"] = time.time() if offline else 0.0
    try:
        from . import cache
        cache.kv().set("net:offline", _offline["since"] or None)
    except Exception:
        pass


def offline_since() -> float:
    """When Masterpiece found it was offline (0 = online). If that was a while ago, a DNS lookup
    (no request to any museum) checks whether the internet is back."""
    from . import cache
    since = cache.kv().get("net:offline", 1e12) or 0.0
    _offline["since"] = since
    if since and time.time() - max(since, _offline["probed"]) > 60:
        _offline["probed"] = time.time()
        ok = []
        t = threading.Thread(target=lambda: ok.append(socket.getaddrinfo("upload.wikimedia.org", 443)), daemon=True)
        t.start()
        t.join(3)
        if ok:
            _mark(False)
            return 0.0
    return since


def _open(url: str, req, timeout: float):
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        _mark(False)                     # the server answered: we're online
        raise
    except (urllib.error.URLError, OSError) as e:
        if _is_offline_error(e):
            _mark(True)
            raise Offline(f"{urllib.parse.urlsplit(url).hostname} can't be reached: no internet connection") from e
        raise
    _mark(False)
    return r


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


def _refused(url: str, e: urllib.error.HTTPError) -> Blocked:
    """403/429: pause that server (as long as it asks, else a minute) and report it."""
    try:
        wait = float(e.headers.get("Retry-After") or 60)
    except (TypeError, ValueError):
        wait = 60.0
    _slot(url).pause(min(max(wait, 10.0), 600.0))
    return Blocked(f"{urllib.parse.urlsplit(url).hostname} is limiting requests right now (HTTP {e.code})")


def get_json(url: str, *, params: dict | None = None, body: dict | None = None,
             timeout: float = TIMEOUT) -> dict:
    try:
        with _slot(url), _open(url, _request(url, params=params, body=body), timeout) as r:
            raw = r.read()
            if r.headers.get("x-amzn-waf-action") or (r.status == 202 and not raw):
                _slot(url).pause(UNAVAILABLE_PAUSE, unavailable=True)
                raise Unavailable(f"{urllib.parse.urlsplit(url).hostname} only lets web browsers in right now")
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError:
                raise OSError(f"{urllib.parse.urlsplit(url).hostname} sent something other than data") from None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise _refused(url, e) from e
        raise


def fetch(url: str, *, timeout: float = 60) -> tuple[bytes, str]:
    """Return (content, content_type)."""
    try:
        with _slot(url), _open(url, _request(url), timeout) as r:
            return r.read(), r.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _refused(url, e) from e
        raise
