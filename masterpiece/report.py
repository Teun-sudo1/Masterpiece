"""Problem reports: a log of what went wrong, and a pre-filled GitHub issue to send it.

Nothing is sent by itself. Settings → "Something not working?" shows the report first
(editable), then opens GitHub's "new issue" page with it filled in; the user presses
"Submit" there (a free GitHub account is needed), or copies the text instead.

The report contains: version, Windows version, screen sizes, which museums/mode are on,
and the last lines of the log. Personal details are removed: the Windows user name, the
home folder, e-mail addresses and the computer name.
"""

from __future__ import annotations

import os
import platform
import re
import sys
import threading
import traceback
import urllib.parse
from pathlib import Path

from . import UPDATE_REPO, __version__, cache

LOG_MAX = 1024 * 1024            # keep the log under 1 MB
LOG_LINES = 80                   # lines of log in a report
URL_MAX = 7500                   # GitHub's "new issue" link must stay under ~8 KB


def log_path() -> Path:
    return cache.cache_dir().parent / "masterpiece.log"


def trim_log() -> None:
    """At start: keep only the newest part of a big log."""
    p = log_path()
    try:
        if p.stat().st_size > LOG_MAX:
            data = p.read_bytes()[-LOG_MAX // 2:]
            p.write_bytes(data[data.find(b"\n") + 1:])
    except OSError:
        pass


def install_hooks() -> None:
    """Write unexpected errors (also in background threads) to the log with their trace."""
    def log_exc(kind, value, tb, where=""):
        try:
            print(f"--- Unexpected error{where}:", file=sys.stderr)
            traceback.print_exception(kind, value, tb, file=sys.stderr)
        except Exception:
            pass

    previous = sys.excepthook

    def hook(kind, value, tb):
        log_exc(kind, value, tb)
        if previous not in (None, sys.__excepthook__):
            previous(kind, value, tb)
    sys.excepthook = hook
    threading.excepthook = lambda a: log_exc(a.exc_type, a.exc_value, a.exc_traceback,
                                             f" in {getattr(a.thread, 'name', 'a thread')}")


def anonymise(text: str) -> str:
    home = str(Path.home())
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    computer = os.environ.get("COMPUTERNAME") or ""
    for value, repl in ((home, "~"), (home.replace("\\", "/"), "~")):
        if value:
            text = re.sub(re.escape(value), repl, text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)
    for value, repl in ((user, "<user>"), (computer, "<computer>")):
        if value and len(value) > 2:
            text = re.sub(rf"\b{re.escape(value)}\b", repl, text, flags=re.I)
    return text


def _log_tail(n: int = LOG_LINES) -> str:
    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log)"
    return "\n".join(lines[-n:]) or "(empty log)"


def build(what_happened: str = "") -> dict:
    from . import monitors, settings
    s = settings.load()
    try:
        screens = ", ".join(f"{m['width']}×{m['height']}" for m in monitors.layout()["monitors"])
    except Exception:
        screens = "?"
    lines = [
        "**What happened?**",
        what_happened.strip() or "(please describe what you did and what went wrong)",
        "",
        "**About this PC**",
        f"- Masterpiece {__version__} ({'installed' if getattr(sys, 'frozen', False) else 'from source'})",
        f"- {platform.platform()} · Python {platform.python_version()}",
        f"- Screens: {screens}",
        f"- Show as: {s.get('mode')}, every {s.get('interval')} min, screens: {s.get('screens')}, "
        f"label: {'on' if s.get('label') else 'off'}, lock screen: {'on' if s.get('lockScreen') else 'off'}",
        f"- Museums on: {', '.join(s.get('enabledSources') or [])}",
        "",
        "**Last lines of the log**",
        "```",
        _log_tail(),
        "```",
    ]
    return {"title": "Problem report: ", "body": anonymise("\n".join(lines))}


def issue_url(title: str, body: str) -> str:
    """GitHub "new issue" link. A long log is shortened from the top (the end is the
    interesting part) until the encoded link fits."""
    def url(b: str) -> str:
        q = urllib.parse.urlencode({"title": title, "body": b, "labels": "bug"})
        return f"https://github.com/{UPDATE_REPO}/issues/new?{q}"
    head, sep, tail = body.partition("**Last lines of the log**")
    keep, out = len(tail), url(body)
    while len(out) > URL_MAX and keep > 200:
        keep = int(keep * 0.8)
        out = url(head + sep + "\n```\n…\n" + tail[-keep:] if sep else body[-keep:])
    return out
