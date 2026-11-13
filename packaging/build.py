"""Build Masterpiece.exe with PyInstaller, and optionally the installer.

    pip install -e .[build]
    python packaging\\build.py            # build\\app\\Masterpiece\\Masterpiece.exe
    python packaging\\build.py --setup    # + dist\\Masterpiece-Setup-<version>.exe (needs Inno Setup)

The program is a folder (not a single file): a one-file .exe unpacks itself to a temp
folder on every start, which would slow down every painting change of the rotation and
trips antivirus scanners more often. Share the Setup.exe.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
# The program folder is built here, never in a place Masterpiece runs from: a running
# Masterpiece.exe keeps its files open, and rebuilding over it would break it.
APP = BUILD / "app"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import PyInstaller.__main__
    from masterpiece import __version__, desktop

    BUILD.mkdir(exist_ok=True)
    ico = BUILD / "masterpiece.ico"
    desktop.icon_image(256).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                             (64, 64), (128, 128), (256, 256)])
    version = BUILD / "version.txt"
    v = tuple(int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4])
    version.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('ProductName', 'Masterpiece'),
    StringStruct('FileDescription', 'Masterpiece - public-domain paintings as your wallpaper'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductVersion', '{__version__}'),
    StringStruct('OriginalFilename', 'Masterpiece.exe'),
    StringStruct('LegalCopyright', 'MIT licence')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")

    shutil.rmtree(APP / "Masterpiece", ignore_errors=True)
    PyInstaller.__main__.run([
        str(ROOT / "packaging" / "launcher.py"),
        "--name", "Masterpiece",
        "--onedir",
        "--windowed",                      # no console window (output goes to masterpiece.log)
        "--noconfirm", "--clean",
        "--icon", str(ico),
        "--version-file", str(version),
        "--add-data", f"{ROOT / 'masterpiece' / 'web'};masterpiece/web",
        "--hidden-import", "pystray._win32",
        # app window: pywebview's Edge WebView2 backend runs through pythonnet (.NET)
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "clr",
        "--collect-data", "webview",
        "--collect-submodules", "masterpiece",
        "--distpath", str(APP),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
    ])
    exe = APP / "Masterpiece" / "Masterpiece.exe"
    if not exe.exists():
        print("\nBuild failed")
        return 1
    print(f"\nBuilt {exe}")
    if "--setup" in sys.argv:
        return setup(__version__)
    return 0


def _iscc() -> Path | None:
    import os
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        p = Path(base) / ("Programs" if base == os.environ.get("LOCALAPPDATA") else "") / "Inno Setup 6" / "ISCC.exe"
        if p.exists():
            return p
    found = shutil.which("ISCC")
    return Path(found) if found else None


def setup(version: str) -> int:
    """dist\\Masterpiece-Setup-<version>.exe with Inno Setup (winget install JRSoftware.InnoSetup)."""
    import subprocess
    iscc = _iscc()
    if not iscc:
        print("Inno Setup not found. Install it with:  winget install JRSoftware.InnoSetup")
        return 1
    r = subprocess.run([str(iscc), "/Q", f"/DAppVersion={version}", str(ROOT / "packaging" / "masterpiece.iss")])
    out = ROOT / "dist" / f"Masterpiece-Setup-{version}.exe"
    if r.returncode or not out.exists():
        print("Setup build failed")
        return r.returncode or 1
    # Checksum for the in-app updater (GitHub also publishes one; this is the fallback)
    import hashlib
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + ".sha256").write_text(f"{sha}  {out.name}\n", encoding="ascii")
    print(f"Built {out}\n      {out.name}.sha256  ({sha[:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
