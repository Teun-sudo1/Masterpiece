"""Make docs/screenshot.png, the picture at the top of the README.

Starts Masterpiece's web UI on a free port with temporary settings (no personal collection,
nothing changes on the desktop), searches a few museums for highlights, and photographs
Search art in a headless Microsoft Edge. Run it after every redesign:

    python packaging\\screenshot.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshot.png"
SIZE = (1440, 920)
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)

# what the picture shows: highlights from a few museums, Europe chosen on the map
SCENE = {"introSeen": True, "tourVersion": "999", "theme": "dark", "enabledSources": ["aic", "cleveland", "rijks"],
         "topOnly": True, "subject": "landscape", "region": "europe", "orientation": "any", "minWidth": "0"}


def main() -> int:
    if not EDGE:
        print("Microsoft Edge is needed for the screenshot.")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="masterpiece-shot-"))
    os.environ.update(APPDATA=str(tmp / "roaming"), MASTERPIECE_CACHE=str(tmp / "cache"))
    sys.path.insert(0, str(ROOT))
    from masterpiece import server, settings      # after the environment points at the temp folder

    settings.save({**SCENE, "folder": str(tmp / "pictures")})
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # twice: the first pass fetches every picture (the server keeps them), the second photographs
        for shot in (tmp / "warm-up.png", OUT):
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                            f"--user-data-dir={tmp / 'edge'}", f"--window-size={SIZE[0]},{SIZE[1]}",
                            "--virtual-time-budget=45000", f"--screenshot={shot}",
                            f"http://127.0.0.1:{srv.server_address[1]}/"], check=True, timeout=180,
                           capture_output=True)
    finally:
        srv.shutdown()
        srv.server_close()
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
