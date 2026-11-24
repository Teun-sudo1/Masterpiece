"""Command line entry point.

  python -m masterpiece                 open Masterpiece (app window + tray icon); if it's
                                        already running, bring its window to the front
  python -m masterpiece --background    tray icon only, no window (used at Windows start)
  python -m masterpiece serve           web UI in the browser from this console, no tray icon
  python -m masterpiece next            show the next painting(s) now (used by the rotation task)
  python -m masterpiece stop            stop the rotation and put your previous wallpaper back
  python -m masterpiece install         add Start-menu and desktop shortcuts
  python -m masterpiece uninstall       remove the shortcuts (and start-with-Windows)
"""

from __future__ import annotations

import argparse
import sys
import webbrowser

from . import settings, wallpaper

PORT = 8765


def _quiet_streams() -> None:
    """pythonw.exe has no console: send output to a log file instead of crashing."""
    if sys.stdout is None or sys.stderr is None:
        from . import cache
        log = cache.cache_dir().parent / "masterpiece.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        f = open(log, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def main(argv: list[str] | None = None) -> int:
    _quiet_streams()
    from . import report
    report.trim_log()
    report.install_hooks()            # unexpected errors go to the log with their trace
    p = argparse.ArgumentParser(prog="masterpiece",
                                description="Public-domain paintings as your Windows wallpaper")
    p.add_argument("--background", action="store_true", help="start in the tray without opening the window")
    p.add_argument("--port", type=int, default=PORT)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the web UI in this console (no tray icon)")
    s.add_argument("--port", type=int, default=PORT)
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("next", aliases=["daily"], help="show the next painting(s) now")
    sub.add_parser("stop", help="stop the rotation and put your previous wallpaper back")
    i = sub.add_parser("install", help="add Start-menu and desktop shortcuts")
    i.add_argument("--no-desktop", action="store_true", help="Start menu only")
    sub.add_parser("uninstall", help="remove the shortcuts")
    sub.add_parser("relink", help="point the rotation and start-with-Windows at this copy (after an update)")
    sub.add_parser("cleanup", help="used by the uninstaller: stop, restore your wallpaper, remove shortcuts")
    args = p.parse_args(argv)

    if args.cmd in ("next", "daily"):
        s = settings.load()
        folder = wallpaper.resolve_folder(s.get("folder"))
        if s.get("mode") == "curator":
            from . import curator
            try:
                curator.run_if_due(s)                # new ones go to the front of "Coming next"
            except Exception as e:                   # offline etc.: just rotate what we have
                print(f"Curator: {e}", file=sys.stderr)
        chosen = wallpaper.show_from_settings(s)     # follows "Coming next"
        if not chosen:
            print(f"No paintings in {folder}. Open Masterpiece first.", file=sys.stderr)
            return 1
        for screen, title in chosen.items():
            print(f"{screen}: {title}")
        return 0
    if args.cmd == "stop":
        from . import backup
        r = backup.restore()
        print({"previous": "Rotation stopped, your previous wallpaper is back.",
               "default": "Rotation stopped, Windows' default wallpaper is back."}.get(
            r["restored"], "Rotation stopped."))
        return 0
    if args.cmd == "install":
        from . import desktop
        for path in desktop.install(desktop=not args.no_desktop):
            print(f"Created {path}")
        return 0
    if args.cmd == "uninstall":
        from . import desktop
        for path in desktop.uninstall():
            print(f"Removed {path}")
        return 0
    if args.cmd == "relink":
        from . import desktop, schedule
        if schedule.relink(int(settings.load().get("interval") or 60)):
            print("Rotation now uses this copy.")
        if desktop.starts_with_windows():
            desktop.start_with_windows(True)
        return 0
    if args.cmd == "cleanup":
        # Uninstaller: nothing may keep pointing at the removed program. Your paintings,
        # settings and cache stay (delete them by hand if you like).
        from . import backup, desktop, monitors, schedule
        try:
            try:
                ours = wallpaper._ours_on_screen(monitors.snapshot())
            except OSError:
                ours = False
            if ours or schedule.status().get("active"):
                backup.restore()                    # also stops the rotation
        finally:
            schedule.disable()
            desktop.start_with_windows(False)
        return 0

    from . import server
    if args.cmd == "serve":
        server.serve(port=args.port, open_browser=not args.no_browser)
        return 0

    # Default: web UI + tray icon (single instance)
    if server.already_running(args.port):
        if not args.background and not server.show_running(args.port):
            webbrowser.open(f"http://127.0.0.1:{args.port}/")      # older version / no app window
        return 0
    try:
        from . import tray
    except ImportError:                       # pystray not installed: plain server
        server.serve(port=args.port, open_browser=not args.background)
        return 0
    try:
        tray.run(port=args.port, open_browser=not args.background)
    except OSError:
        print(f"Port {args.port} is in use by another program. Try: python -m masterpiece --port {args.port + 1}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
