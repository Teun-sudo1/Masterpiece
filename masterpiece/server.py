"""Local web UI server (stdlib only). Binds to 127.0.0.1.

Routes
  GET  /                      web UI (static files from ./web)
  GET  /api/sources           available museums
  GET  /api/search            ?q=&page=&color=&top=&sources=a,b&minWidth=&orientation=
  GET  /api/img?u=<url>       image proxy (museum image hosts only)
  GET  /api/settings          current settings
  POST /api/settings          merge settings
  POST /api/apply             download selection, label, prune, set wallpaper
"""

from __future__ import annotations

import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import backup, cache, content, monitors, schedule, settings, sources, wallpaper
from .models import Artwork
from .net import fetch
from .search import search_all

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 5 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "Masterpiece"

    # --------------------------------------------------------- helpers
    def log_request(self, code="-", size="-"):  # only log problems (keeps the log file small)
        try:
            if int(code) < 400:
                return
        except (TypeError, ValueError):
            pass
        super().log_request(code, size)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _error(self, code: int, msg: str):
        self._json({"error": msg}, code)

    def _host_ok(self) -> bool:
        """Reject DNS-rebinding / cross-site requests to the local API."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.removeprefix("http://") in allowed

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large")
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ValueError("Expected application/json")
        return json.loads(self.rfile.read(n) or b"{}")

    # --------------------------------------------------------- GET
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        qs = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path.startswith("/api/"):
            if not self._host_ok():
                return self._error(403, "Forbidden")
            try:
                if url.path == "/api/sources":
                    return self._json(sources.describe())
                if url.path == "/api/options":
                    lay = monitors.layout()
                    return self._json({
                        **content.describe(),
                        "screens": [{k: m[k] for k in ("x", "y", "width", "height", "primary")}
                                    for m in lay["monitors"]],
                        "span": lay["span"],
                    })
                if url.path == "/api/settings":
                    s = settings.load()
                    s["defaultFolder"] = str(wallpaper.default_folder())
                    return self._json(s)
                if url.path == "/api/collection":
                    s = settings.load()
                    folder = wallpaper.resolve_folder(s.get("folder"))
                    favs = set(s.get("favourites") or [])
                    from . import curator
                    reasons = curator.picks()
                    items = [{**i, "favourite": i["id"] in favs, "curator": (reasons.get(i["name"]) or {}).get("reason", "")}
                             for i in wallpaper.collection(folder)]
                    return self._json({"folder": str(folder), "items": items,
                                       "banned": s.get("banned") or [],
                                       "timeOfDay": bool(s.get("timeOfDay")),
                                       "current": wallpaper.shown_summary(),
                                       "rotation": schedule.status(), "backup": backup.has_backup()})
                if url.path == "/api/painting":
                    s = settings.load()
                    info = wallpaper.painting_info(wallpaper.resolve_folder(s.get("folder")),
                                                   qs.get("name", ""), s.get("favourites") or [])
                    if not info:
                        return self._error(404, "This painting is no longer in your collection")
                    from . import curator
                    info["curator"] = curator.reason_for(info["name"])
                    return self._json(info)
                if url.path == "/api/thumb":
                    folder = wallpaper.resolve_folder(settings.load().get("folder"))
                    w = 1200 if qs.get("size") == "large" else 480
                    p = wallpaper.thumbnail(folder, qs.get("name", ""), w)
                    if not p:
                        return self._error(404, "Not found")
                    return self._send(200, p.read_bytes(), "image/jpeg", {"Cache-Control": "no-cache"})
                if url.path == "/api/saved":
                    folder = wallpaper.resolve_folder(settings.load().get("folder"))
                    return self._json(wallpaper.saved_ids(folder))
                if url.path == "/api/rotation":
                    return self._json(self._rotation_status())
                if url.path == "/api/update":
                    return self._json(self._update_status())
                if url.path == "/api/system":
                    return self._json(self._system_status())
                if url.path == "/api/report":
                    from . import report
                    r = report.build()
                    return self._json({**r, "repo": f"https://github.com/{report.UPDATE_REPO}"})
                if url.path == "/api/search":
                    return self._search(qs)
                if url.path == "/api/img":
                    return self._img(qs.get("u", ""))
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._error(502, f"{type(e).__name__}: {e}")
            return self._error(404, "Not found")
        self._static(url.path)

    def _search(self, qs: dict):
        keys = [k for k in (qs.get("sources") or "").split(",") if k]
        cursors = {}
        for part in (qs.get("cursors") or "").split(","):
            k, _, v = part.partition(":")
            if k and v.lstrip("-").isdigit():
                cursors[k] = int(v)

        # Screen-aware filters use the real monitor layout
        lay = monitors.layout()
        targets = [(m["width"], m["height"]) for m in lay["monitors"]] or [(1920, 1080)]
        orientation = qs.get("orientation") or "any"
        if orientation == "span":
            span = lay.get("span") or {"width": 1920, "height": 1080}
            targets, orientation = [(span["width"], span["height"])], "screens"
        mw = qs.get("minWidth") or "0"

        result = search_all(
            keys,
            cursors=cursors,
            query=qs.get("q", "").strip(),
            color=qs.get("color") or None,
            top_only=qs.get("top") in ("1", "true"),
            subject=qs.get("subject") or None,
            period=qs.get("period") or None,
            hide=[h for h in (qs.get("hide") or "").split(",") if h],
            region=qs.get("region") or None,
            min_width=int(mw) if mw.isdigit() else 0,
            sharp=mw == "sharp",
            orientation=orientation,
            targets=targets,
        )
        banned = {b.get("id") for b in settings.load().get("banned") or []}
        if banned:                                    # "never show again"
            result["results"] = [a for a in result["results"] if a["id"] not in banned]
        self._json(result)

    def _img(self, u: str):
        parts = urllib.parse.urlsplit(u)
        if parts.scheme != "https" or parts.hostname not in sources.image_hosts():
            return self._error(400, "Image host not allowed")
        hit = cache.image_get(u)            # each image is fetched from a museum only once
        if hit:
            data, ctype = hit
        else:
            data, ctype = fetch(u)
            if not ctype.startswith("image/"):
                return self._error(502, "Upstream did not return an image")
            cache.image_put(u, data, ctype)
        self._send(200, data, ctype, {"Cache-Control": "public, max-age=2592000, immutable"})

    def _static(self, path: str):
        if path == "/favicon.ico":
            from . import desktop
            ico = desktop.icon_path()
            if ico.exists():
                return self._send(200, ico.read_bytes(), "image/x-icon", {"Cache-Control": "max-age=86400"})
        rel = path.lstrip("/") or "index.html"
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    # --------------------------------------------------------- POST
    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._host_ok():
            return self._error(403, "Forbidden")
        try:
            body = self._body()
        except ValueError as e:
            return self._error(400, str(e))
        try:
            if path == "/api/settings":
                return self._json(settings.save(body))
            if path == "/api/apply":
                return self._apply(body)
            if path == "/api/rotation":
                return self._rotation(body.get("action"), body.get("name") or None, body)
            if path == "/api/collection":
                return self._collection(body)
            if path == "/api/update":
                return self._update(body)
            if path == "/api/system":
                return self._system(body)
            if path == "/api/report":                # the (edited) report -> GitHub "new issue" link
                from . import report
                title = str(body.get("title") or "Problem report")[:200]
                text = report.anonymise(str(body.get("body") or ""))
                return self._json({"url": report.issue_url(title, text)})
            if path == "/api/window":           # a second start of Masterpiece: show our window
                app = getattr(self.server, "app", None)
                if not app or not getattr(app, "win", None):
                    return self._error(404, "No app window")
                app.open_app(str(body.get("path") or ""))
                return self._json({"ok": True})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._error(500, f"{type(e).__name__}: {e}")
        self._error(404, "Not found")

    def _rotation_status(self) -> dict:
        from . import curator
        s = settings.load()
        folder = wallpaper.resolve_folder(s.get("folder"))
        return {**schedule.status(), "folder": str(folder), "count": len(wallpaper.own_files(folder)),
                "backup": backup.has_backup(), "mode": s.get("mode"), "interval": s.get("interval"),
                "shown": wallpaper.shown_summary(),
                "hasPrevious": len(cache.kv().get("rotation:history", 1e12) or []) > 1,
                "curatorLatest": curator.latest(), "curatorLast": cache.kv().get("curator:last", 1e12) or "",
                "curatorBusy": bool(cache.kv().get("curator:running", curator.RUN_GUARD))}

    def _rotation(self, action: str | None, name: str | None = None, body: dict | None = None):
        s = settings.load()
        body = body or {}
        if action == "start":                    # start (or restart) the rotation
            from . import curator
            interval = max(1, min(31 * 1440, int(body.get("interval") or s.get("interval") or 60)))
            settings.save({"interval": interval})
            s = settings.load()
            added = []
            if s.get("mode") == "curator":
                added = curator.run_if_due(s, force=not wallpaper.own_files(wallpaper.resolve_folder(s.get("folder")))) or []
            shown = wallpaper.show_from_settings(s)
            schedule.enable(interval)
            return self._json({**self._rotation_status(), "wallpapers": shown, "curator": added})
        if action == "interval":
            interval = max(1, min(31 * 1440, int(body.get("interval") or 60)))
            settings.save({"interval": interval})
            if schedule.status().get("active"):
                schedule.relink(interval)            # re-register with the new interval, keeps "paused"
            return self._json(self._rotation_status())
        if action == "source":                   # "curator" or "rotate" (my collection)
            settings.save({"mode": "curator" if body.get("mode") == "curator" else "rotate"})
            return self._json(self._rotation_status())
        if action == "pause":
            schedule.pause()
            return self._json(self._rotation_status())
        if action == "resume":
            schedule.resume()
            return self._json(self._rotation_status())
        if action == "previous":
            shown = wallpaper.show_previous(s)
            if shown is None:
                return self._error(400, "There is no earlier painting yet")
            return self._json({**self._rotation_status(), "wallpapers": shown})
        if action == "curator":                  # "Ask the Curator now"
            from . import curator
            added = curator.run_if_due(s, force=True) or []
            shown = wallpaper.show_from_settings() if added else {}
            return self._json({**self._rotation_status(), "curator": added, "wallpapers": shown})
        if action == "next":
            shown = wallpaper.show_from_settings(s)
            return self._json({**self._rotation_status(), "wallpapers": shown,
                               "rotation": schedule.status()})
        if action == "refresh":                  # label changed: re-render what's on screen now
            return self._json(wallpaper.refresh_labels(s))
        if action == "skip":
            return self._json(wallpaper.skip(name, s))
        if action == "stop":
            schedule.disable()
            return self._json({**self._rotation_status(), "rotation": schedule.status()})
        if action == "restore":
            r = backup.restore()
            return self._json({**self._rotation_status(), **r, "rotation": schedule.status()})
        self._error(400, "Unknown action")

    def _collection(self, body: dict):
        s = settings.load()
        folder = wallpaper.resolve_folder(s.get("folder"))
        action, name = body.get("action"), str(body.get("name") or "")
        items = {i["name"]: i for i in wallpaper.collection(folder)}
        if action == "add":                      # from Search art: download, show these first
            arts = [Artwork.from_dict(d) for d in body.get("artworks") or []]
            if not arts:
                return self._error(400, "Nothing selected")
            hosts = {urllib.parse.urlsplit(a.image_url).hostname for a in arts}
            if not hosts <= sources.image_hosts():
                return self._error(400, "Image host not allowed")
            r = wallpaper.add_to_collection(arts, s)
            settings.save({"selection": []})
            return self._json({**r, "rotation": self._rotation_status()})
        if action == "show":
            if name not in items:
                return self._error(404, "Not in your collection")
            return self._json({"wallpapers": wallpaper.show_from_settings(s, force=name)})
        if action == "favourite":
            item = items.get(name)
            if not item:
                return self._error(404, "Not in your collection")
            favs = wallpaper.set_favourite(item["id"], bool(body.get("on", True)))
            return self._json({"ok": True, "favourite": item["id"] in favs})
        if action == "skip":
            if name not in items:
                return self._error(404, "Not in your collection")
            return self._json(wallpaper.skip(name, s))
        if action in ("remove", "ban"):
            item = items.get(name)
            if not item:
                return self._error(404, "Not in your collection")
            wallpaper.remove(folder, name)
            if action == "ban":
                banned = [b for b in s.get("banned") or [] if b.get("id") != item["id"]]
                banned.append({k: item[k] for k in ("id", "title", "maker", "museum")})
                selection = [a for a in s.get("selection") or [] if a.get("id") != item["id"]]
                settings.save({"banned": banned, "selection": selection})
            return self._json({"ok": True})
        if action == "unban":
            banned = [b for b in s.get("banned") or [] if b.get("id") != body.get("id")]
            settings.save({"banned": banned})
            return self._json({"ok": True})
        self._error(400, "Unknown action")

    def _system_status(self) -> dict:
        from . import __version__, desktop, storage
        s = settings.load()
        folder = wallpaper.resolve_folder(s.get("folder"))
        return {"version": __version__, "startWithWindows": desktop.starts_with_windows(),
                "screens": len(monitors.layout()["monitors"]), "folder": str(folder),
                "storage": storage.usage(folder), "installed": desktop.FROZEN}

    def _system(self, body: dict):
        from . import desktop, storage
        action = body.get("action")
        if action == "startup":
            desktop.start_with_windows(bool(body.get("on")))
            return self._json(self._system_status())
        if action == "freeSpace":
            freed = storage.free_space()
            return self._json({**self._system_status(), "freed": freed})
        if action == "openFolder":
            import os
            s = settings.load()
            target = {"paintings": wallpaper.resolve_folder(s.get("folder")),
                      "data": wallpaper.app_dir()}.get(body.get("which"))
            if not target:
                return self._error(400, "Unknown folder")
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))                 # opens Explorer
            return self._json({"ok": True})
        if action == "lockScreen":
            on = bool(body.get("on"))
            settings.save({"lockScreen": on})
            if on:                                    # show it there right away
                wallpaper.refresh_labels()
            else:
                from . import lockscreen
                lockscreen.restore()
            return self._json({"ok": True, "lockScreen": on})
        self._error(400, "Unknown action")

    def _update_status(self, force: bool = False) -> dict:
        from . import update
        st = update.check(force)
        s = settings.load()
        st["skipped"] = s.get("skipVersion") or ""
        st["autoUpdate"] = bool(s.get("autoUpdate"))
        st["progress"] = update.progress()
        st["whatsNew"] = update.whats_new()
        return st

    def _update(self, body: dict):
        from . import update
        action = body.get("action")
        if action == "check":
            return self._json(self._update_status(force=True))
        if action == "skip":
            settings.save({"skipVersion": str(body.get("version") or "")})
            return self._json(self._update_status())
        if action == "seenWhatsNew":
            update.dismiss_whats_new()
            return self._json(self._update_status())
        if action == "install":
            st = update.check()
            if not st["available"]:
                return self._error(400, "No update available")
            if not st["canInstall"]:
                return self._error(400, "Running from source: update with git pull instead")
            update.start_install(st["release"])
            return self._json(self._update_status())
        self._error(400, "Unknown action")

    def _apply(self, body: dict):
        artworks = [Artwork.from_dict(d) for d in body.get("artworks") or []]
        if not artworks and body.get("mode") != "curator":     # the Curator can start from nothing
            return self._error(400, "Nothing selected")
        hosts = {urllib.parse.urlsplit(a.image_url).hostname for a in artworks}
        if not hosts <= sources.image_hosts():
            return self._error(400, "Image host not allowed")
        s = settings.load()
        result = wallpaper.apply(
            artworks,
            folder=wallpaper.resolve_folder(s.get("folder")),
            label=bool(body.get("label", s["label"])),
            max_files=int(body.get("maxFiles", s["maxFiles"])),
            mode=body.get("mode", s["mode"]),
            screens=body.get("screens", s["screens"]),
            interval=int(body.get("interval", s["interval"])),
            pos=wallpaper.label_pos(body.get("labelPos", s.get("labelPos"))),
            style=wallpaper.label_style(body.get("labelStyle", s.get("labelStyle"))),
            favourites=s.get("favourites") or [],
            time_of_day=bool(body.get("timeOfDay", s.get("timeOfDay"))),
            lock_screen=bool(s.get("lockScreen")),
            seasons=bool(s.get("seasons")),
            set_now=bool(body.get("setNow", True)),
        )
        self._json(result)


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port and
    # silently steal requests, so a stale instance keeps serving old code.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def make_server(port: int = 8765) -> Server:
    """Raises OSError if the port is taken."""
    return Server(("127.0.0.1", port), Handler)


def already_running(port: int = 8765) -> bool:
    """Is a Masterpiece server already answering on this port?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sources", timeout=2) as r:
            return r.headers.get("Server", "").startswith("Masterpiece")
    except OSError:
        return False


def show_running(port: int = 8765) -> bool:
    """Ask a running Masterpiece to bring its app window to the front."""
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/window", data=b'{"action": "show"}',
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def serve(port: int = 8765, open_browser: bool = True) -> None:
    try:
        httpd = make_server(port)
    except OSError:
        print(f"Port {port} is already in use - is Masterpiece already running?\n"
              f"Close that window, or start on another port: python -m masterpiece serve --port {port + 1}",
              file=sys.stderr)
        raise SystemExit(1)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Masterpiece running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
