"""Save or share a painting: the full picture, or a postcard with its label underneath.

Saved files go to Pictures\\Saved from Masterpiece, which Masterpiece never cleans up
(the collection folder is cleaned up, so nothing is saved there). "Copy" puts the
postcard on the clipboard, to paste into a chat or an e-mail. Everything is made from
the picture that's already on your computer: nothing is downloaded.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import time
from pathlib import Path

from . import cache, wallpaper

try:
    from PIL import Image, ImageDraw
except ImportError:          # pragma: no cover
    Image = None

KINDS = ("picture", "postcard")
CARD_LONG = 2000             # longest side of the painting on a postcard
COPY_LONG = 1600             # a bit smaller on the clipboard: chats shrink it anyway
PAPER = (244, 239, 230)
INK = (38, 33, 27)
SOFT = (118, 108, 96)


def saved_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Pictures" / "Saved from Masterpiece"


def meta(name: str) -> dict:
    return cache.kv().get(f"art:{name}", 1e12) or {}


def _original(folder: Path, name: str) -> Path:
    if not wallpaper.OWN_FILE.match(name):
        raise FileNotFoundError(name)
    p = wallpaper.originals_dir() / name                  # without the label
    if p.exists():
        return p
    p = folder / name
    if p.exists():
        return p
    raise FileNotFoundError(name)


def file_name(m: dict, kind: str) -> str:
    """'The Bedroom - Vincent van Gogh.jpg' (Windows-safe, not too long)."""
    base = " - ".join(x for x in (m.get("title"), m.get("maker")) if x) or "Painting"
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", base)
    base = " ".join(base.split()).strip(" .")[:110] or "Painting"
    return f"{base}{' (postcard)' if kind == 'postcard' else ''}.jpg"


def caption(m: dict) -> list[str]:
    """Title / artist, year / museum · licence."""
    year = " ".join(str(m.get("year") or "").split())[:24]
    return [x for x in (m.get("title") or "",
                        ", ".join(x for x in (m.get("maker"), year) if x),
                        " · ".join(x for x in (m.get("museum"), m.get("license") or "Public domain") if x)) if x]


def postcard(src: Path, m: dict, long_side: int = CARD_LONG) -> "Image.Image":
    """The painting on a cream card with a margin and its label underneath."""
    with Image.open(src) as im:
        art = im.convert("RGB")
    f = min(1.0, long_side / max(art.size))
    if f < 1:
        art = art.resize((round(art.width * f), round(art.height * f)), Image.LANCZOS)
    w, h = art.size
    pad = round(max(w, h) * 0.06)
    lines = caption(m)
    size = max(18, round(max(w, h * 0.8) / 42))
    fonts = [wallpaper._font(round(size * 1.15), "serif", "title"), wallpaper._font(size, "serif"),
             wallpaper._font(round(size * 0.8), "sans")]
    inks = [INK, INK, SOFT]
    gap = round(size * 0.45)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    fitted, heights = [], []
    for i, line in enumerate(lines):
        font = fonts[min(i, 2)]
        fitted.append(wallpaper._fit_line(probe, line, font, w))
        box = probe.textbbox((0, 0), "Ág", font=font)
        heights.append(box[3] - box[1])
    text_h = sum(heights) + gap * max(0, len(lines) - 1)
    card = Image.new("RGB", (w + 2 * pad, h + pad * 2 + round(pad * 0.4) + text_h), PAPER)
    card.paste(art, (pad, pad))
    d = ImageDraw.Draw(card)
    d.rectangle((pad - 1, pad - 1, pad + w, pad + h), outline=(222, 214, 201))
    y = pad + h + round(pad * 0.55)
    for i, line in enumerate(fitted):
        font = fonts[min(i, 2)]
        d.text((card.width / 2, y), line, font=font, fill=inks[min(i, 2)], anchor="ma")
        y += heights[i] + gap
    return card


def save(folder: Path, name: str, kind: str = "picture") -> Path:
    """Save the full picture or a postcard to Pictures\\Saved from Masterpiece."""
    if kind not in KINDS:
        raise ValueError(kind)
    src, m = _original(folder, name), meta(name)
    out = saved_dir()
    out.mkdir(parents=True, exist_ok=True)
    dest = out / file_name(m, kind)
    tmp = dest.with_suffix(".tmp")
    if kind == "picture":
        tmp.write_bytes(src.read_bytes())
    else:
        postcard(src, m).save(tmp, "JPEG", quality=92)
    tmp.replace(dest)
    return dest


def reveal(path: Path) -> None:
    """Open Explorer with the saved file selected (only files in the saved folder)."""
    path = Path(path).resolve()
    if path.parent != saved_dir().resolve() or not path.exists():
        raise FileNotFoundError(path)
    subprocess.Popen(["explorer", f"/select,{path}"])


def copy(folder: Path, name: str, kind: str = "postcard") -> None:
    """Put the postcard (or the picture) on the clipboard."""
    src, m = _original(folder, name), meta(name)
    if kind == "postcard":
        img = postcard(src, m, COPY_LONG)
    else:
        with Image.open(src) as im:
            img = im.convert("RGB")
        img.thumbnail((COPY_LONG * 2, COPY_LONG * 2))
    to_clipboard(img)


def dib(img: "Image.Image") -> bytes:
    """The picture as a Windows device-independent bitmap (a BMP without its file header)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    return buf.getvalue()[14:]


def to_clipboard(img: "Image.Image") -> None:
    import ctypes
    from ctypes import wintypes
    data = dib(img)
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.argtypes, k32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
    k32.GlobalLock.argtypes, k32.GlobalLock.restype = [wintypes.HGLOBAL], wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.SetClipboardData.argtypes, u32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
    h = k32.GlobalAlloc(0x0002, len(data))               # GMEM_MOVEABLE
    if not h:
        raise OSError("Not enough memory to copy the picture")
    ptr = k32.GlobalLock(h)
    ctypes.memmove(ptr, data, len(data))
    k32.GlobalUnlock(h)
    for _ in range(20):                                   # another app may hold the clipboard for a moment
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        k32.GlobalFree(h)
        raise OSError("The clipboard is busy; try again")
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(8, h):                # CF_DIB; Windows owns the memory now
            k32.GlobalFree(h)
            raise OSError("Couldn't copy the picture")
    finally:
        u32.CloseClipboard()
