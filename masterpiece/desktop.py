"""Windows integration: app icon, Start-menu / desktop / startup shortcuts.

Shortcuts run `Masterpiece.exe` (or `pythonw.exe -m masterpiece` when run from source),
without a console window. Remove them with `Masterpiece.exe uninstall`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import cache

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

LINK_NAME = "Masterpiece.lnk"
_NO_WINDOW = 0x08000000


def icon_image(size: int = 256) -> "Image.Image":
    """A tiny landscape painting in a gold frame."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = s // 7
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=(21, 19, 15, 255))
    f = s // 9                                                     # gold frame
    d.rounded_rectangle((f, f, s - f, s - f), radius=r // 2, fill=(212, 162, 76, 255))
    i = f + s // 16                                                # the canvas
    d.rectangle((i, i, s - i, s - i), fill=(40, 58, 74, 255))
    d.rectangle((i, int(s * .52), s - i, s - i), fill=(60, 72, 54, 255))
    sun = s * .62, s * .36, s * .09
    d.ellipse((sun[0] - sun[2], sun[1] - sun[2], sun[0] + sun[2], sun[1] + sun[2]), fill=(243, 215, 146, 255))
    d.polygon([(i, s * .66), (s * .36, s * .40), (s * .58, s * .66)], fill=(28, 36, 33, 255))
    d.polygon([(s * .40, s * .66), (s * .66, s * .48), (s - i, s * .66)], fill=(46, 54, 44, 255))
    return img


def icon_path() -> Path:
    """masterpiece.ico in the app folder (created on first use)."""
    p = cache.cache_dir().parent / "masterpiece.ico"
    if not p.exists() and Image is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        icon_image(256).save(p, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return p


FROZEN = bool(getattr(sys, "frozen", False))       # running as Masterpiece.exe (PyInstaller)


def pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def launcher(args: str = "") -> tuple[str, str, Path]:
    """How to start Masterpiece without a console: (program, arguments, working folder).
    Masterpiece.exe when running as the .exe, otherwise `pythonw -m masterpiece`."""
    if FROZEN:
        exe = Path(sys.executable)
        return str(exe), args, exe.parent
    return pythonw(), f"-m masterpiece {args}".strip(), Path(__file__).resolve().parent.parent


def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
    if r.returncode:
        raise OSError(r.stderr.strip() or "PowerShell failed")
    return r.stdout.strip()


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _programs() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def startup_dir() -> Path:
    return _programs() / "Startup"


def folders() -> dict[str, Path]:
    desktop = Path(_ps("[Environment]::GetFolderPath('Desktop')"))   # may be redirected to OneDrive
    return {"start": _programs(), "desktop": desktop, "startup": startup_dir()}


def create_shortcut(path: Path, args: str, description: str) -> None:
    """args: Masterpiece's own arguments, e.g. '' or '--background'."""
    program, arguments, workdir = launcher(args)
    icon = f"{program},0" if FROZEN else f"{icon_path()},0"     # the .exe carries its own icon
    _ps(
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_q(path)});"
        f"$s.TargetPath = {_q(program)}; $s.Arguments = {_q(arguments)};"
        f"$s.WorkingDirectory = {_q(workdir)}; $s.IconLocation = {_q(icon)};"
        f"$s.Description = {_q(description)}; $s.Save()"
    )


def install(desktop: bool = True) -> list[str]:
    f = folders()
    made = []
    targets = [f["start"] / LINK_NAME] + ([f["desktop"] / LINK_NAME] if desktop else [])
    if starts_with_windows():
        targets.append(f["startup"] / LINK_NAME)            # keep it pointing at this copy too
    for p in targets:
        create_shortcut(p, "--background" if p.parent == f["startup"] else "",
                        "Public-domain paintings as your Windows wallpaper")
        made.append(str(p))
    return made


def uninstall() -> list[str]:
    removed = []
    for p in (folders()[k] / LINK_NAME for k in ("start", "desktop", "startup")):
        try:
            p.unlink()
            removed.append(str(p))
        except OSError:
            pass
    return removed


def start_with_windows(on: bool) -> None:
    p = startup_dir() / LINK_NAME
    if on:
        create_shortcut(p, "--background", "Masterpiece tray icon")
    else:
        try:
            p.unlink()
        except OSError:
            pass


def starts_with_windows() -> bool:
    return (startup_dir() / LINK_NAME).exists()
