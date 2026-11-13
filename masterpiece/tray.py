"""Tray icon next to the clock, with the web UI server running in the background.

The rotation itself is a scheduled task and keeps working when this is closed;
the tray is just quick control.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
import webbrowser

import pystray
from pystray import Menu, MenuItem

from . import UPDATE_REPO, backup, desktop, schedule, server, settings, wallpaper


class Tray:
    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        self._status = {"active": False}
        self._status_at = 0.0
        self.icon = pystray.Icon("Masterpiece", desktop.icon_image(64), "Masterpiece", menu=self._menu())

    # ------------------------------------------------------------ helpers
    def status(self) -> dict:
        if time.monotonic() - self._status_at > 20:          # schtasks is slow-ish; cache briefly
            self._status, self._status_at = schedule.status(), time.monotonic()
        return self._status

    def refresh(self) -> None:
        self._status_at = 0
        shown = wallpaper.currently_shown()
        self.icon.title = ("Masterpiece — " + shown[0]["title"])[:120] if shown else "Masterpiece"
        self.icon.update_menu()

    def _safe(self, fn):
        def run(icon, item):
            try:
                fn()
            except Exception as e:  # never let a click crash the tray
                icon.notify(f"{type(e).__name__}: {e}", "Masterpiece")
            finally:
                self.refresh()
        return run

    # ------------------------------------------------------------ actions
    win = None             # AppWindow, or None = use the browser

    def open_app(self, path: str = ""):
        if self.win:
            self.win.show(path)
        else:
            webbrowser.open(self.url + path.lstrip("/"))

    def next_painting(self):
        shown = wallpaper.show_from_settings()
        if shown:
            self.icon.notify(" · ".join(shown.values())[:200], "Now on your desktop")
        else:
            self.icon.notify("Your collection is empty. Open Masterpiece to choose paintings.", "Masterpiece")

    def skip(self, name: str | None = None):
        r = wallpaper.skip(name)
        now = " · ".join(r["wallpapers"].values())
        self.icon.notify((f"Now: {now}" if now else "Your collection is empty now.")[:200],
                         f"Skipped {', '.join(r['skipped'])}"[:60])

    def toggle_favourite(self, c: dict):
        on = c["id"] not in (settings.load().get("favourites") or [])
        wallpaper.set_favourite(c["id"], on)
        self.icon.notify(f"“{c['title'][:80]}” comes up about three times as often." if on
                         else f"“{c['title'][:80]}” is no longer a favourite.", "Favourite" if on else "Masterpiece")

    def about(self, name: str):
        self.open_app(f"painting.html?name={urllib.parse.quote(name)}")

    # ------------------------------------------------------------ updates
    _update: dict | None = None

    def check_updates(self, force: bool = False, quiet: bool = True):
        from . import cache, update
        st = update.check(force)
        self._update = st
        if st["available"]:
            seen = cache.kv().get("update:notified", 1e12)
            if not quiet or (seen != st["latest"] and settings.load().get("skipVersion") != st["latest"]):
                cache.kv().set("update:notified", st["latest"])
                self.icon.notify(f"Masterpiece {st['latest']} is available. Choose “Install update” in this menu.",
                                 "Update available")
        elif not quiet:
            self.icon.notify(st["error"] or (f"You have the newest version ({st['current']})."
                                             if st["enabled"] else "Update checks aren't set up in this copy."),
                             "Masterpiece")

    def install_update(self):
        from . import update
        st = self._update if self._update and self._update.get("available") else update.check()
        if not st["available"]:
            self.icon.notify("You have the newest version.", "Masterpiece")
            return
        if not st["canInstall"]:
            self.icon.notify("Running from source: update with git pull.", "Masterpiece")
            return
        update.start_install(st["release"])
        self.icon.notify(f"Downloading Masterpiece {st['latest']}. It restarts by itself when it's done.",
                         "Updating")

        def watch():                       # tell the user if the download or check fails
            while update.progress()["state"] == "downloading":
                time.sleep(1)
            p = update.progress()
            if p["state"] == "error":
                self.icon.notify(f"The update didn't work: {p['error']}"[:200], "Masterpiece")
        threading.Thread(target=watch, daemon=True).start()

    def toggle_pause(self):
        if self.status().get("paused"):
            schedule.resume()
            self.icon.notify("The rotation continues.", "Masterpiece")
        else:
            schedule.pause()
            self.icon.notify("Paused: the current painting stays until you resume.", "Masterpiece")

    def restore(self):
        r = backup.restore()
        msg = {"previous": "Your previous wallpaper is back.",
               "default": "Windows' default wallpaper is back."}.get(r["restored"], "Masterpiece stopped.")
        self.icon.notify(msg, "Masterpiece stopped")

    def toggle_startup(self):
        desktop.start_with_windows(not desktop.starts_with_windows())

    def quit(self):
        self.icon.stop()
        if self.win:
            self.win.quit()

    # ------------------------------------------------------------ menu
    def _on_screen(self):
        shown = wallpaper.shown_summary()
        if not shown:
            return [MenuItem("Nothing from Masterpiece yet", None, enabled=False)]
        favs = set(settings.load().get("favourites") or [])
        items = []
        for c in shown:
            label = f"{c['screen']}:  {c['title'][:48]}" + (f" — {c['maker'][:24]}" if c.get("maker") else "")
            sub = [
                MenuItem("About this painting", self._safe(lambda n=c["name"]: self.about(n)), default=True),
                MenuItem("Favourite", self._safe(lambda c=c: self.toggle_favourite(c)),
                         checked=lambda item, i=c["id"]: i in favs),
                MenuItem("Skip (remove from my collection)", self._safe(lambda n=c["name"]: self.skip(n))),
            ]
            if c.get("link"):
                sub.append(MenuItem("Museum page", self._safe(lambda u=c["link"]: webbrowser.open(u))))
            items.append(MenuItem(label, Menu(*sub)))
        return items

    def _skip_items(self):
        return [MenuItem(f"{c['screen']}:  {c['title'][:48]}", self._safe(lambda n=c["name"]: self.skip(n)))
                for c in wallpaper.shown_summary()]

    def _menu(self) -> Menu:
        count = lambda: len(wallpaper.shown_summary())
        return Menu(
            MenuItem("Open Masterpiece", self._safe(self.open_app), default=True),
            MenuItem("Next painting", self._safe(self.next_painting)),
            # Skip = remove from the collection + show another one; per screen when several are shown
            MenuItem("Skip this painting", self._safe(lambda: self.skip()), visible=lambda item: count() == 1),
            MenuItem("Skip", Menu(self._skip_items), visible=lambda item: count() > 1),
            MenuItem("On screen now", Menu(self._on_screen)),
            Menu.SEPARATOR,
            MenuItem(lambda item: "Resume rotation" if self.status().get("paused") else "Pause rotation",
                     self._safe(self.toggle_pause), visible=lambda item: self.status().get("active", False)),
            MenuItem("Restore my wallpaper", self._safe(self.restore)),
            Menu.SEPARATOR,
            MenuItem("Start with Windows", self._safe(self.toggle_startup),
                     checked=lambda item: desktop.starts_with_windows()),
            MenuItem(lambda item: f"Install update {self._update['latest']}" if self._update else "Install update",
                     self._safe(self.install_update),
                     visible=lambda item: bool(self._update and self._update.get("available"))),
            MenuItem("Check for updates", self._safe(lambda: self.check_updates(force=True, quiet=False)),
                     visible=lambda item: bool(UPDATE_REPO)),
            MenuItem("Quit Masterpiece", lambda icon, item: self.quit()),
        )

    def _keep_fresh(self):
        next_update_check = time.monotonic() + 30           # shortly after start, then every 6 hours
        while True:                       # pick up changes made from the web page / the rotation task
            time.sleep(60)
            try:
                if UPDATE_REPO and time.monotonic() >= next_update_check:
                    next_update_check = time.monotonic() + 6 * 3600
                    self.check_updates()     # GitHub is asked at most every 12 h (cached)
                if UPDATE_REPO and self._update and self._update.get("available"):
                    from . import update
                    if update.maybe_auto_install():          # only when switched on and the PC is idle
                        next_update_check = time.monotonic() + 3600
                self.refresh()
            except Exception:
                pass


def _app_window(url: str):
    """The app window, or None if pywebview / WebView2 isn't there (then: browser)."""
    try:
        from . import window
        return window.AppWindow(url) if window.available() else None
    except Exception:                     # ImportError, pythonnet/.NET problems, …
        return None


def run(port: int = 8765, open_browser: bool = True) -> None:
    """open_browser: show the app (window or browser) right away; False = tray only."""
    httpd = server.make_server(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    tray = Tray(httpd.server_address[1])
    tray.win = _app_window(tray.url)
    try:
        from . import update
        updated = update.note_start()            # "What's new" after an update
    except Exception:
        updated = None
    if updated:
        def tell():
            time.sleep(4)                        # let the icon appear first
            tray.icon.notify(f"Masterpiece is updated to {updated['version']}. Open it to see what's new.",
                             "Updated")
        threading.Thread(target=tell, daemon=True).start()
    httpd.app = tray                      # a second start asks this one to show its window
    threading.Thread(target=tray._keep_fresh, daemon=True).start()
    tray.refresh()
    try:
        if tray.win:
            tray.win.on_first_hide = lambda: tray.icon.notify(
                "Masterpiece keeps running here, next to the clock. Quit it from this icon's menu.",
                "Still running")
            tray.win.create(hidden=not open_browser)
            threading.Thread(target=tray.icon.run, daemon=True).start()
            tray.win.run()                # the window's loop needs the main thread; blocks until Quit
        else:
            if open_browser:
                tray.open_app()
            tray.icon.run()               # blocks until "Quit"
    finally:
        try:
            tray.icon.stop()
        except Exception:
            pass
        httpd.shutdown()
        httpd.server_close()
