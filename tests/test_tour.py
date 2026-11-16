"""The guided tour: every spotlight lands on its target (Search art in a headless Edge).

Runs the real web UI against an in-process server with fake search results, so no museum is
contacted and the user's settings and wallpaper are never touched. Skipped without Edge.
Run it after adding tour steps for a new version.
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

from masterpiece import server, settings
from masterpiece.models import Artwork

EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
CHECK = Path(__file__).with_name("tour_check.html")


def fake_results(keys, **_):
    arts = [Artwork(id=f"aic-{n}", source="aic", title=f"Painting {n}", maker="Artist", year="1880",
                    museum="Art Institute of Chicago", image_url="https://www.artic.edu/x.jpg",
                    preview_url="", width=3000, height=2000, license="CC0").to_dict() for n in range(12)]
    return {"results": arts, "errors": {}, "cursors": {k: 0 for k in keys}, "scanned": len(arts), "skipped": []}


@pytest.mark.skipif(not EDGE, reason="needs Microsoft Edge")
def test_tour_spotlights_land_on_their_targets(tmp_path, monkeypatch):
    web = tmp_path / "web"
    shutil.copytree(server.WEB_DIR, web)
    shutil.copy(CHECK, web / CHECK.name)
    monkeypatch.setattr(server, "WEB_DIR", web)
    monkeypatch.setattr(server, "search_all", fake_results)
    # no tour by itself: the check page plays it
    settings.save({"introSeen": True, "tourVersion": "9.9.9", "folder": str(tmp_path / "pictures")})

    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'edge'}",
             "--window-size=1500,950", "--virtual-time-budget=180000", "--dump-dom",
             f"http://127.0.0.1:{srv.server_address[1]}/{CHECK.name}"],
            capture_output=True, text=True, encoding="utf-8", timeout=240)
    finally:
        srv.shutdown()
        srv.server_close()

    m = re.search(r'<pre id="result">(.+?)</pre>', out.stdout, re.S)
    assert m, f"the check page didn't finish:\n{out.stdout[-1500:]}\n{out.stderr[-1500:]}"
    res = json.loads(html.unescape(m.group(1)))
    assert not res["problems"], "\n".join(res["problems"])
    assert res["checked"] >= 2 * 2 * 9, res                     # 2 sizes × 2 looks × the whole tour, at least
