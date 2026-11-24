"""Settings › Your screens: the crop sliders sit beside or under the preview, never on a picture.

Opens the real page in a headless Edge against an in-process server with made-up screens and
paintings (portrait, panorama, 16:9) in every layout: one screen, a painting per screen and
across all screens. Measures every slider at two window sizes. Nothing on the real desktop
changes and no museum is contacted. Skipped without Edge.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from masterpiece import backup, cache, monitors, server, settings

EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
CHECK = Path(__file__).with_name("desk_check.html")

SHAPES = {"tall": (600, 900), "pano": (2000, 500), "wide": (1600, 900)}
LEFT = {"id": "L", "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": False}
RIGHT = {"id": "R", "x": 1920, "y": 0, "width": 1920, "height": 1080, "primary": True}
ONE = {"id": "A", "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": True}

# name, screens setting, monitors, what each screen shows (None = across all), expected sliders
CASES = [
    ("two screens, two portraits", "each", [LEFT, RIGHT], {"L": "tall", "R": "tall"}, ["left", "right"]),
    ("two screens, panorama + portrait", "each", [LEFT, RIGHT], {"L": "pano", "R": "tall"}, ["below", "right"]),
    ("two screens, two panoramas", "each", [LEFT, RIGHT], {"L": "pano", "R": "pano"}, ["below", "below"]),
    ("across all screens", "span", [LEFT, RIGHT], {"span": "wide"}, ["left"]),
    ("across all screens, panorama", "span", [LEFT, RIGHT], {"span": "pano"}, ["below"]),
    ("one screen, portrait", "each", [ONE], {"A": "tall"}, ["left"]),
    ("one screen, panorama", "each", [ONE], {"A": "pano"}, ["below"]),
    ("one screen, fits", "each", [ONE], {"A": "wide"}, []),
]


def _setup(tmp_path, monkeypatch, screens, mons, shown):
    PIL = pytest.importorskip("PIL.Image")
    folder = tmp_path / "pictures"
    folder.mkdir()
    entries = []
    for key, shape in shown.items():
        name = f"aic-{key}{shape}.jpg"
        PIL.new("RGB", SHAPES[shape], (90, 110, 80)).save(folder / name)
        cache.kv().set(f"art:{name}", {"id": name[:-4], "title": f"P {key}{shape}", "maker": "M", "museum": "X"})
        cache.kv().set(f"labelled:{name}", False)
        entries.append({"screen": key, "key": key, "name": name, "id": name[:-4], "title": f"P {key}{shape}"})
    cache.kv().set("current:shown", entries)
    lay = {"monitors": mons, "span": {"width": 3840, "height": 1080} if len(mons) > 1 else None}
    monkeypatch.setattr(monitors, "layout", lambda: lay)
    monkeypatch.setattr(monitors, "set_each", lambda *a, **k: None)     # never the real desktop
    monkeypatch.setattr(monitors, "set_all", lambda *a, **k: None)
    monkeypatch.setattr(backup, "capture", lambda *a, **k: None)
    settings.save({"introSeen": True, "tourVersion": "9.9.9", "folder": str(folder), "screens": screens,
                   "crop": "middle", "label": False})


def _measure(tmp_path, monkeypatch):
    web = tmp_path / "web"
    shutil.copytree(server.WEB_DIR, web)
    shutil.copy(CHECK, web / CHECK.name)
    monkeypatch.setattr(server, "WEB_DIR", web)
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'edge'}",
             "--window-size=1600,1000", "--virtual-time-budget=30000", "--dump-dom",
             f"http://127.0.0.1:{srv.server_address[1]}/{CHECK.name}"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        srv.shutdown()
        srv.server_close()
    m = re.search(r'<pre id="result">(.+?)</pre>', out.stdout, re.S)
    assert m, f"the check page didn't finish:\n{out.stdout[-1500:]}\n{out.stderr[-1500:]}"
    return json.loads(html.unescape(m.group(1)))


def _overlaps(a, b):
    return a["l"] < b["r"] - 0.5 and a["r"] > b["l"] + 0.5 and a["t"] < b["b"] - 0.5 and a["b"] > b["t"] + 0.5


def _side(s, screens, pictures):
    """Where a slider is, seen from the preview: left / right / below (or inside)."""
    left = min(x["l"] for x in screens + pictures)
    right = max(x["r"] for x in screens + pictures)
    bottom = max(x["b"] for x in screens + pictures)
    if s["vertical"] and s["r"] <= left + 0.5:
        return "left"
    if s["vertical"] and s["l"] >= right - 0.5:
        return "right"
    if not s["vertical"] and s["t"] >= bottom - 0.5:
        return "below"
    return "inside"


@pytest.mark.skipif(not EDGE, reason="needs Microsoft Edge")
@pytest.mark.parametrize("label,screens,mons,shown,expected", CASES, ids=[c[0] for c in CASES])
def test_crop_sliders_stay_off_the_preview(tmp_path, monkeypatch, label, screens, mons, shown, expected):
    _setup(tmp_path, monkeypatch, screens, mons, shown)
    for m in _measure(tmp_path, monkeypatch):
        where = f"{label} at {m['size']}"
        scr, pics, sl = m["screens"], m["pictures"], m["sliders"]
        assert len(scr) == len(mons), f"{where}: {len(scr)} screens drawn"
        # sliders in screen order (left to right), and where each one is
        sl.sort(key=lambda s: (s["l"] if s["vertical"] else s["l"]))
        sides = sorted(_side(s, scr, pics) for s in sl)
        assert sides == sorted(expected), f"{where}: sliders {sides}, expected {sorted(expected)}"
        for s in sl:
            for box in scr + pics:
                assert not _overlaps(s, box), f"{where}: slider {s['label']!r} lies on the preview"
            st = m["stage"]
            assert st["l"] - 0.5 <= s["l"] and s["r"] <= st["r"] + 0.5 and st["t"] - 0.5 <= s["t"] and s["b"] <= st["b"] + 0.5, \
                f"{where}: slider {s['label']!r} sticks out of the preview"
            # next to its own painting: as tall as its screen, or as wide as it
            title = re.search(r"“(.+?)”", s["label"]).group(1)
            own = [x for x in scr if title.endswith(x["name"][4:-4])] or scr
            if s["vertical"]:
                assert abs(s["t"] - min(x["t"] for x in own)) < 2 and abs(s["b"] - max(x["b"] for x in own)) < 2, \
                    f"{where}: {s['label']!r} isn't beside its screen"
            else:
                assert min(x["l"] for x in own) - 4 <= s["l"] and s["r"] <= max(x["r"] for x in own) + 4, \
                    f"{where}: {s['label']!r} isn't under its screen"
        # the preview fits its box: no sideways scrolling
        assert m["stage"]["r"] <= m["main"]["r"] + 0.5 and m["stage"]["l"] >= m["main"]["l"] - 0.5, \
            f"{where}: the preview is wider than its box"
