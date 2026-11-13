"""Masterpiece in its own app window (Edge WebView2 via pywebview) instead of a browser tab.

The window shows the same local pages as before. Closing it only hides it: Masterpiece
keeps running in the tray, and "Open Masterpiece" brings the window back. Links to
museum websites open in your normal browser.

Without pywebview / WebView2, Masterpiece falls back to the browser (see tray.py).
"""

from __future__ import annotations

import threading

import webview

from . import cache

TITLE = "Masterpiece"


def available() -> bool:
    """Is the Edge WebView2 runtime installed? (It is on every Windows 11 and most Windows 10.)"""
    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        ]
        for root, path in keys:
            try:
                with winreg.OpenKey(root, path) as k:
                    if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                        return True
            except OSError:
                continue
    except ImportError:
        pass
    return False


class AppWindow:
    def __init__(self, url: str):
        self.base = url
        self.window = None
        self.quitting = False
        self.on_first_hide = None          # set by the tray: "still running in the tray" note
        self._hidden_once = False

    def create(self, hidden: bool = False) -> None:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # museum pages -> your browser
        self.window = webview.create_window(
            TITLE, self.base, width=1440, height=920, min_size=(860, 560),
            hidden=hidden, background_color="#000000", text_select=True)
        self.window.events.closing += self._on_closing

    def _on_closing(self):
        if self.quitting:
            return True
        # Close button = hide; the tray keeps Masterpiece (and the server) running
        threading.Thread(target=self.window.hide, daemon=True).start()
        if not self._hidden_once and self.on_first_hide:
            self._hidden_once = True
            self.on_first_hide()
        return False

    def show(self, path: str = "") -> None:
        if path:
            self.window.load_url(self.base + path.lstrip("/"))
        self.window.show()
        self.window.restore()               # un-minimise
        try:
            self.window.on_top = True       # bring to front, then behave normally again
            self.window.on_top = False
        except Exception:
            pass

    def quit(self) -> None:
        self.quitting = True
        if self.window:
            self.window.destroy()

    def run(self, on_start=None) -> None:
        """Blocks (must be the main thread) until quit()."""
        webview.start(on_start, private_mode=False,
                      storage_path=str(cache.cache_dir().parent / "window"))
