"""Download paintings and put them on the desktop.

Files
  Pictures\\Masterpiece\\<id>.jpg           the collection (labelled if enabled); also the
                                            folder the Windows slideshow uses
  %LOCALAPPDATA%\\Masterpiece\\originals    unlabelled originals (downloaded once)
  %LOCALAPPDATA%\\Masterpiece\\current      per-screen renders that are on the desktop now

Modes
  slideshow  Windows' own slideshow on the collection folder (configured for you)
  rotate     Masterpiece shows the next painting every N minutes (scheduled task),
             rendered to each screen's exact size so nothing important is cropped
  once       show one painting now, no rotation
"""

from __future__ import annotations

import ctypes
import functools
import math
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import backup, cache, monitors, schedule
from .filters import ratio_close
from .models import Artwork
from .net import fetch
from .sources import SOURCES

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
except ImportError:  # labels and exact-fit renders need Pillow
    Image = None

# Files we manage look like "aic-12345.jpg"; anything else in the folder is left alone.
OWN_FILE = re.compile(rf"^({'|'.join(map(re.escape, SOURCES))})-[\w-]+\.jpg$", re.I)
MODES = ("slideshow", "rotate", "curator", "once")


def default_folder() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Pictures" / "Masterpiece"


def resolve_folder(folder: str | Path | None) -> Path:
    return Path(folder) if folder else default_folder()


def app_dir() -> Path:
    return cache.cache_dir().parent


def originals_dir() -> Path:
    return app_dir() / "originals"


def current_dir() -> Path:
    return app_dir() / "current"


def filename_for(a: Artwork) -> str:
    return re.sub(r"[^\w-]+", "-", a.id) + ".jpg"


def label_text(a: Artwork | dict) -> str:
    g = (lambda k: a.get(k, "")) if isinstance(a, dict) else (lambda k: getattr(a, k))
    return f"{g('title')} — {g('maker')} · {g('museum')}"


# ---------------------------------------------------------------- labels & renders

FONT_FILES = {   # (family, role) -> Windows font files to try, in order
    ("sans", "body"): ("segoeui.ttf", "arial.ttf"),
    ("sans", "title"): ("seguisb.ttf", "segoeui.ttf", "arialbd.ttf"),
    ("serif", "body"): ("georgia.ttf", "pala.ttf", "times.ttf"),
    ("serif", "title"): ("georgiai.ttf", "palai.ttf", "timesi.ttf", "georgia.ttf"),
}


@functools.lru_cache(maxsize=64)
def _font(size: int, family: str = "sans", role: str = "body"):
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in FONT_FILES.get((family, role), ()) + ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(str(Path(windir) / "Fonts" / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


# Label style: look, font family, size and which text to show
LABEL_LOOKS = ("dark", "light", "plaque", "shadow", "subtle")
LABEL_FONTS = ("sans", "serif")
LABEL_SIZES = {"s": 72, "m": 55, "l": 40}          # screen's short side / this = font px
LABEL_TEXTS = ("full", "two", "artist", "title")
DEFAULT_LABEL_STYLE = {"look": "dark", "font": "sans", "size": "m", "text": "full"}


def label_style(value) -> dict:
    """Settings value -> a complete, valid style dict."""
    v = value if isinstance(value, dict) else {}
    allowed = {"look": LABEL_LOOKS, "font": LABEL_FONTS, "size": tuple(LABEL_SIZES), "text": LABEL_TEXTS}
    return {k: (v.get(k) if v.get(k) in allowed[k] else DEFAULT_LABEL_STYLE[k]) for k in allowed}


def label_lines(a: Artwork | dict, mode: str = "full") -> list[str]:
    """The label's line(s) for one painting, depending on the chosen text."""
    g = (lambda k: (a.get(k) or "")) if isinstance(a, dict) else (lambda k: getattr(a, k) or "")
    title, maker, year, museum = g("title"), g("maker"), str(g("year")), g("museum")
    if mode == "title":
        return [title]
    if mode == "artist":
        return [" — ".join(x for x in (title, maker) if x)]
    if mode == "two":
        details = ", ".join(x for x in (maker, year) if x)
        return [title, " · ".join(x for x in (details, museum) if x)]
    return [label_text(a)]


DEFAULT_LABEL_POS = (0.5, 0.93)   # centre of the label, as fractions of the screen: bottom-centre


def label_pos(value) -> tuple[float, float]:
    """Settings value {"x": .., "y": ..} -> (x, y) clamped to 0..1."""
    try:
        x, y = float(value["x"]), float(value["y"])
    except (TypeError, KeyError, ValueError):
        return DEFAULT_LABEL_POS
    return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))


def _label_key(label: bool, pos, style: dict | None = None) -> str | bool:
    """What a labelled file was rendered with, so a change re-renders it (no re-download)."""
    if not label:
        return False
    st = label_style(style)
    return (f"v2|{pos[0]:.3f},{pos[1]:.3f}|"        # v2: label kept inside the area every screen shows
            + ",".join(st[k] for k in ("look", "font", "size", "text")))


# look -> box fill, border, first-line colour, second-line colour (RGBA; None = no box)
_LOOKS = {
    "dark":   ((0, 0, 0, 140), None, (255, 255, 255, 235), (255, 255, 255, 185)),
    "light":  ((250, 248, 244, 205), None, (22, 20, 18, 240), (70, 66, 60, 225)),
    "plaque": ((240, 234, 221, 240), (176, 160, 128, 255), (34, 28, 20, 255), (96, 86, 70, 255)),
    "shadow": (None, None, (255, 255, 255, 240), (255, 255, 255, 205)),
    "subtle": (None, None, (255, 255, 255, 180), (255, 255, 255, 150)),
}


def _fit_line(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def add_label(img: "Image.Image", text: str | list[str],
              region: tuple[int, int, int, int] | None = None,
              pos: tuple[float, float] = DEFAULT_LABEL_POS,
              style: dict | None = None) -> "Image.Image":
    """Label centred on `pos` (fractions of `region`, default the whole image),
    kept inside the edges. `text` is one line or a list of lines (title first)."""
    st = label_style(style)
    lines = [l for l in ([text] if isinstance(text, str) else list(text)) if l] or [""]
    img = img.convert("RGB")
    rx0, ry0, rx1, ry1 = region or (0, 0, *img.size)
    RW, RH = rx1 - rx0, ry1 - ry0
    size = max(13, min(RW, RH) // LABEL_SIZES[st["size"]])
    if st["look"] == "subtle":
        size = max(12, int(size * 0.85))
    fill, border, ink1, ink2 = _LOOKS[st["look"]]

    two = len(lines) > 1
    fonts = ([_font(int(size * 1.08), st["font"], "title")] + [_font(int(size * 0.84), st["font"])] * (len(lines) - 1)
             if two else [_font(size, st["font"])])
    inks = [ink1] + [ink2] * (len(lines) - 1)
    draw = ImageDraw.Draw(img)

    # Truncate so the label never covers more than ~60% of the width
    max_w = int(RW * 0.6)
    lines = [_fit_line(draw, t, f, max_w) for t, f in zip(lines, fonts)]
    # Line boxes from the font, not the text, so all labels have the same height
    metrics = [f.getbbox("Hgjy", anchor="ls") for f in fonts]       # (l, top<0, r, bottom>0)
    heights = [b - t for _, t, _, b in metrics]
    widths = [draw.textlength(t, font=f) for t, f in zip(lines, fonts)]
    gap = int(size * 0.25)

    padx = size * (0.9 if st["look"] == "plaque" else 0.6) if fill else 0
    pady = size * (0.6 if st["look"] == "plaque" else 0.35) if fill else 0
    margin = size
    bw = int(max(widths) + 2 * padx)
    bh = int(sum(heights) + gap * (len(lines) - 1) + 2 * pady)
    cx, cy = rx0 + pos[0] * RW, ry0 + pos[1] * RH
    x0 = int(min(max(cx - bw / 2, rx0 + margin), rx1 - margin - bw))
    y0 = int(min(max(cy - bh / 2, ry0 + margin), ry1 - margin - bh))
    x1, y1 = x0 + bw, y0 + bh
    # Text aligns with the side of the screen it is on (looks tidy without a box, too)
    align = "left" if pos[0] < 0.34 else "right" if pos[0] > 0.66 else "centre"

    base = img.convert("RGBA")
    if fill:
        box = Image.new("RGBA", img.size, (0, 0, 0, 0))
        radius = max(2, size // 6) if st["look"] == "plaque" else int(size * 0.45)
        ImageDraw.Draw(box).rounded_rectangle(
            (x0, y0, x1, y1), radius=radius, fill=fill,
            outline=border, width=max(1, size // 14) if border else 0)
        if st["look"] == "plaque":                  # a soft drop shadow lifts the card off the painting
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            off = max(2, size // 8)
            ImageDraw.Draw(sh).rounded_rectangle((x0 + off, y0 + off, x1 + off, y1 + off),
                                                 radius=radius, fill=(0, 0, 0, 110))
            base = Image.alpha_composite(base, sh.filter(ImageFilter.GaussianBlur(size / 3)))
        base = Image.alpha_composite(base, box)

    text_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    places = []
    y = y0 + pady
    for t, f, (_, top, _, _), h, w in zip(lines, fonts, metrics, heights, widths):
        x = x0 + padx if align == "left" else x1 - padx - w if align == "right" else x0 + (bw - w) / 2
        places.append((x, y - top, t, f))
        y += h + gap
    if not fill:                                  # no box: a soft shadow keeps the text readable
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        alpha = 170 if st["look"] == "shadow" else 110
        off = max(1, size // 14)
        for x, yb, t, f in places:
            sd.text((x, yb + off), t, font=f, anchor="ls", fill=(0, 0, 0, alpha))
        base = Image.alpha_composite(base, shadow.filter(ImageFilter.GaussianBlur(max(1.5, size / 7))))
    for (x, yb, t, f), ink in zip(places, inks):
        td.text((x, yb), t, font=f, anchor="ls", fill=ink)
    return Image.alpha_composite(base, text_layer).convert("RGB")


def render(src: Path, w: int, h: int, text: str | list[str] | None = None,
           region: tuple[int, int, int, int] | None = None,
           pos: tuple[float, float] = DEFAULT_LABEL_POS,
           style: dict | None = None) -> "Image.Image":
    """Crop & scale `src` to exactly w×h (like Windows' 'Fill'), then label it.
    Because we crop ourselves, the label always lands on the visible part."""
    with Image.open(src) as im:
        im.draft("RGB", (w, h))            # fast JPEG decode at reduced size when possible
        out = ImageOps.fit(im.convert("RGB"), (w, h), Image.LANCZOS)
    return add_label(out, text, region, pos, style) if text else out


# ---------------------------------------------------------------- collection files

MAX_STORED = 3840      # longest side of stored originals: sharp on 4K and portrait screens


def _cap_size(path: Path) -> None:
    """Some museums serve 9000+ px originals; keep a 4K-sized copy instead."""
    if Image is None:
        return
    try:
        with Image.open(path) as im:
            if max(im.size) <= MAX_STORED * 1.1:
                return
            im.draft("RGB", (MAX_STORED, MAX_STORED))
            small = im.convert("RGB")
        small.thumbnail((MAX_STORED, MAX_STORED), Image.LANCZOS)
        small.save(path, "JPEG", quality=92)
    except OSError:
        pass


def _visible_region(w: int, h: int, screens: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    """Part of a w×h picture that stays visible on *every* screen when Windows
    'Fill' crops it to that screen's shape (centre crop)."""
    x0, y0, x1, y1 = 0.0, 0.0, float(w), float(h)
    for sw, sh in screens:
        r = sw / sh
        if w / h > r:                       # picture wider than the screen: sides are cut
            cut = (w - h * r) / 2
            x0, x1 = max(x0, cut), min(x1, w - cut)
        else:                               # taller: top and bottom are cut
            cut = (h - w / r) / 2
            y0, y1 = max(y0, cut), min(y1, h - cut)
    return int(x0), int(y0), int(x1), int(y1)


def _label_copy(im: "Image.Image", meta, pos, style) -> "Image.Image":
    """Labelled collection copy for the Windows slideshow, which crops & scales by itself.
    The label is kept inside the area every screen shows, and small pictures are enlarged
    first so the text is drawn at (at least) screen resolution instead of being blown up."""
    try:
        screens = [(m["width"], m["height"]) for m in monitors.layout()["monitors"]] or [(1920, 1080)]
    except Exception:
        screens = [(1920, 1080)]
    img = im.convert("RGB")
    w, h = img.size
    # Scale Windows will apply on the most demanding screen ('Fill' = cover)
    need = max(max(sw / w, sh / h) for sw, sh in screens)
    if need > 1:
        f = min(need, MAX_STORED / max(w, h))
        if f > 1:
            img = img.resize((round(w * f), round(h * f)), Image.LANCZOS)
            w, h = img.size
    region = _visible_region(w, h, screens)
    return add_label(img, label_lines(meta, label_style(style)["text"]), region, pos, style)


def _meta_key(name: str) -> str:
    return f"art:{name}"


def download(a: Artwork, folder: Path, *, label: bool = True,
             pos: tuple[float, float] = DEFAULT_LABEL_POS, style: dict | None = None) -> Path:
    """Make sure the painting is in the collection folder. Downloads at most once:
    toggling the label later is re-rendered from the stored original."""
    name = filename_for(a)
    folder.mkdir(parents=True, exist_ok=True)
    originals_dir().mkdir(parents=True, exist_ok=True)
    orig, dest = originals_dir() / name, folder / name
    if not orig.exists() or not orig.stat().st_size:
        if dest.exists() and dest.stat().st_size and cache.kv().get(f"labelled:{name}", 1e12) is False:
            orig.write_bytes(dest.read_bytes())     # known unlabelled copy: reuse, no download
        else:
            data, _ = fetch(a.image_url)
            tmp = orig.with_suffix(".tmp")
            tmp.write_bytes(data)
            _cap_size(tmp)
            tmp.replace(orig)
    cache.kv().set(_meta_key(name), a.to_dict())

    want_label = _label_key(bool(label and Image is not None), pos, style)
    have = cache.kv().get(f"labelled:{name}", 1e12)
    if dest.exists() and dest.stat().st_size and have == want_label:
        os.utime(dest)                               # already there: just mark as recent
        return dest
    if want_label:
        with Image.open(orig) as im:
            _label_copy(im, a.to_dict(), pos, style).save(dest, "JPEG", quality=92)
    else:
        dest.write_bytes(orig.read_bytes())
    cache.kv().set(f"labelled:{name}", want_label)
    return dest


def own_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.is_file() and OWN_FILE.match(p.name)),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def saved_ids(folder: Path) -> list[str]:
    """Artwork IDs of the paintings currently in the collection folder."""
    ids = []
    for p in own_files(folder):
        meta = cache.kv().get(_meta_key(p.name), 1e12) or {}
        ids.append(meta.get("id") or p.stem)     # filename == id for every current source
    return ids


def cleanup(folder: Path, max_files: int, keep_ids=()) -> list[Path]:
    """Delete our oldest files beyond max_files (and their originals). Favourites
    (keep_ids) are never deleted and don't count towards the maximum."""
    removed = []
    keep = fav_names(keep_ids)
    for p in [p for p in own_files(folder) if p.name not in keep][max(0, max_files):]:
        try:
            p.unlink()
            removed.append(p)
        except OSError:
            pass
    keep = {p.name for p in own_files(folder)}
    if originals_dir().is_dir():
        for o in originals_dir().iterdir():
            if o.is_file() and OWN_FILE.match(o.name) and o.name not in keep:
                try:
                    o.unlink()
                except OSError:
                    pass
    return removed


# ---------------------------------------------------------------- Windows

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02


def set_wallpaper(path: Path) -> None:
    """Classic single-image API (fallback when IDesktopWallpaper is unavailable)."""
    if sys.platform != "win32":
        raise OSError("Setting the wallpaper is only supported on Windows")
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, str(path.resolve()), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    if not ok:
        raise ctypes.WinError()


def image_size(p: Path) -> tuple[int, int] | None:
    if Image is None:
        return None
    try:
        with Image.open(p) as im:      # lazy: reads only the header
            return im.size
    except OSError:
        return None


def _pick(files: list[Path], sizes: dict, w: int, h: int, avoid: set, prefer: set,
          weight=lambda p: 1.0) -> Path:
    """Random file whose shape suits a w×h screen, preferring `prefer`, avoiding `avoid`;
    falls back to the closest shapes. `weight` makes some files more likely (favourites,
    time of day)."""
    target = w / h
    fitting = [p for p in files if sizes.get(p) and ratio_close(sizes[p][0] / sizes[p][1], target)]
    for pool in ([p for p in fitting if p.name in prefer and p not in avoid],
                 [p for p in fitting if p not in avoid], fitting):
        if pool:
            return random.choices(pool, weights=[max(1e-3, weight(p)) for p in pool])[0]

    def dist(p):
        s = sizes.get(p)
        return abs(math.log((s[0] / s[1]) / target)) if s else 99
    return random.choice(sorted(files, key=dist)[:3])


def _source_for(p: Path) -> tuple[Path, bool]:
    """(image to render from, whether it still needs a label)."""
    orig = originals_dir() / p.name
    if orig.exists():
        return orig, True
    # unknown (older download) -> assume it already carries a label
    return p, cache.kv().get(f"labelled:{p.name}", 1e12) is False


def _to_lock_screen(paths: dict, chosen: dict, main: dict) -> None:
    """The main screen's painting (with its label) on the lock screen as well."""
    from . import lockscreen
    try:
        if "span" in paths:                          # spanned: cut out the main screen's part
            _, _, _, region = chosen["span"]
            src = current_dir() / "lock-src.jpg"
            with Image.open(paths["span"]) as im:
                im.crop(region).save(src, "JPEG", quality=92)
        else:
            src = paths.get(main.get("id")) or paths.get("all") or next(iter(paths.values()))
        lockscreen.set_image(Path(src))
    except Exception as e:                           # never let this break the wallpaper
        print(f"Lock screen not changed: {e}", file=sys.stderr)


FAVOURITE_WEIGHT = 3.0      # a favourite comes up about 3× as often


def daypart(hour: int | None = None) -> str:
    """'day' (9–17 h), 'evening' (19–7 h) or 'between'."""
    h = time.localtime().tm_hour if hour is None else hour
    return "day" if 9 <= h < 17 else "evening" if (h >= 19 or h < 7) else "between"


def brightness(p: Path) -> float | None:
    """Average brightness 0..1 of an image (computed once, then cached)."""
    if Image is None:
        return None
    try:
        key = f"bright:{p.name}:{int(p.stat().st_mtime)}"
    except OSError:
        return None
    hit = cache.kv().get(key, 1e12)
    if hit is not None:
        return hit
    try:
        with Image.open(p) as im:
            im.draft("L", (128, 128))          # JPEG: decode at 1/8 size, fast
            small = im.convert("L")
        small.thumbnail((128, 128))
        value = round(ImageStat.Stat(small).mean[0] / 255, 4)
    except OSError:
        return None
    cache.kv().set(key, value)
    return value


def time_of_day_weights(paths: list[Path], part: str | None = None) -> dict:
    """Weights that favour bright paintings by day and dark ones in the evening,
    relative to the rest of the collection. Neutral in between."""
    part = part or daypart()
    vals = {p: brightness(p) for p in paths} if part != "between" else {}
    known = sorted((v, p) for p, v in vals.items() if v is not None)
    if len(known) < 2:
        return {}
    n = len(known) - 1
    out = {}
    for i, (_, p) in enumerate(known):
        score = i / n if part == "day" else 1 - i / n         # 1 = best match for now
        out[p] = 0.15 + 1.85 * score ** 2
    return out


# Seasons (northern hemisphere): words in titles/descriptions, also Dutch/French/German
SEASON_WORDS = {
    "winter": r"winter|snow|snowy|ice|icy|skat\w*|frozen|frost\w*|sleigh|blizzard|hiver|neige|sneeuw|ijs|schnee|"
              r"december|january|february",
    "spring": r"spring ?time|springtime|blossom\w*|orchard in bloom|in bloom|cherry tree|tulips?|lente|printemps|"
              r"fr[uü]hling|april|may ?day",
    "summer": r"summer|beach|seaside|haymaking|hay ?stacks?|wheat ?field|bathing|picnic|zomer|[ée]t[ée]|sommer|"
              r"june|july|august",
    "autumn": r"autumn|fall foliage|harvest\w*|vintage|grape|herfst|automne|herbst|october|november|fallen leaves",
}
_SEASON_RE = {k: re.compile(rf"\b({v})\b", re.I) for k, v in SEASON_WORDS.items()}
OPPOSITE = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}


def season_now(month: int | None = None) -> str:
    m = time.localtime().tm_mon if month is None else month
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(m, "autumn")


def seasons_of(text: str) -> set[str]:
    return {k for k, rx in _SEASON_RE.items() if rx.search(text or "")}


def season_weight(text: str, now: str | None = None) -> float:
    """×3 for a painting of this season, ×0.3 for one of the opposite season."""
    now = now or season_now()
    found = seasons_of(text)
    if now in found:
        return 3.0
    if OPPOSITE[now] in found:
        return 0.3
    return 1.0


def fav_names(favourites) -> set[str]:
    """Artwork IDs -> collection file names."""
    return {re.sub(r"[^\w-]+", "-", i) + ".jpg" for i in favourites or ()}


def show_next(folder: Path, screens: str = "each", label: bool = True,
              prefer: list[str] | None = None,
              pos: tuple[float, float] = DEFAULT_LABEL_POS,
              force: str | None = None, style: dict | None = None,
              favourites=None, time_of_day: bool = False,
              keep: dict | None = None, lock_screen: bool = False, seasons: bool = False,
              record: bool = True) -> dict:
    """Put the next painting(s) on the desktop. screens: 'each' | 'same' | 'span'.
    favourites: artwork IDs that come up more often. time_of_day: bright by day, dark at night.
    keep: {screen key: file name} that stay where they are (used by "skip").
    Returns {screen description: artwork title or file}."""
    files = own_files(folder)
    if not files:
        return {}
    sources = {p: _source_for(p) for p in files}
    sizes = {p: image_size(sources[p][0]) for p in files}
    recent = set(cache.kv().get("rotation:recent", 1e12) or [])
    avoid = {p for p in files if p.name in recent}
    prefer = set(prefer or [])
    favs = fav_names(favourites)
    tod = time_of_day_weights([sources[p][0] for p in files]) if time_of_day else {}
    season = {}
    if seasons:
        now = season_now()
        for p in files:
            meta = cache.kv().get(_meta_key(p.name), 1e12) or {}
            season[p] = season_weight(f"{meta.get('title', '')} {meta.get('text', '')}", now)

    def weight(p: Path) -> float:
        return ((FAVOURITE_WEIGHT if p.name in favs else 1.0) * tod.get(sources[p][0], 1.0)
                * season.get(p, 1.0))

    lay = monitors.layout()
    mons = lay["monitors"] or [{"id": None, "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": True}]
    main = next((m for m in mons if m.get("primary")), mons[0])

    # Work out what goes where: (key, width, height, label region)
    if screens == "span" and len(mons) > 1 and lay.get("span"):
        x0 = min(m["x"] for m in mons)
        y0 = min(m["y"] for m in mons)
        region = (main["x"] - x0, main["y"] - y0, main["x"] - x0 + main["width"], main["y"] - y0 + main["height"])
        targets = [("span", lay["span"]["width"], lay["span"]["height"], region)]
    elif len(mons) > 1:
        # 'each' and 'same': a render per screen at its exact resolution, so the label always
        # fits and stays sharp (one image on a differently shaped screen gets cropped + blown up)
        targets = [(m["id"], m["width"], m["height"], None)
                   for m in sorted(mons, key=lambda m: not m.get("primary"))]   # main screen first
    else:
        targets = [("all", main["width"], main["height"], None)]
    same = screens == "same" and len(targets) > 1

    describe = {m["id"]: f"{m['width']}×{m['height']}" for m in mons}
    screen_name = lambda k: ("All screens (spanned)" if k == "span" else "All screens" if k == "all"
                             else describe.get(k, k))

    chosen: dict = {}
    by_name = {p.name: p for p in files}
    for key, w, h, region in targets:                 # paintings that stay (re-rendered)
        k = keep or {}
        name = k.get(key) or k.get(screen_name(key)) or k.get("all") or k.get("All screens")
        if name in by_name:
            chosen[key] = (by_name[name], w, h, region)
            avoid.add(by_name[name])
    forced = by_name.get(force) if force else None
    if forced and sizes.get(forced):
        if same:
            chosen = {}                               # the same painting everywhere
        # "Show now": put it on the screen whose shape suits it best
        r = sizes[forced][0] / sizes[forced][1]
        free = [t for t in targets if t[0] not in chosen] or targets
        key, w, h, region = min(free, key=lambda t: abs(math.log(r / (t[1] / t[2]))))
        chosen[key] = (forced, w, h, region)
        avoid.add(forced)
    for key, w, h, region in targets:
        if key in chosen:
            continue
        if same and chosen:
            p = next(iter(chosen.values()))[0]
        else:
            p = _pick(files, sizes, w, h, avoid, prefer, weight)
        avoid.add(p)
        chosen[key] = (p, w, h, region)
    chosen = {t[0]: chosen[t[0]] for t in targets}   # keep the screens' order

    # Render exact-fit images (or use the files directly without Pillow)
    current_dir().mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    paths: dict = {}
    titles: dict = {}
    for i, (key, (p, w, h, region)) in enumerate(chosen.items()):
        meta = cache.kv().get(_meta_key(p.name), 1e12) or {}
        titles[key] = meta.get("title") or p.stem
        if Image is None:
            paths[key] = p
            continue
        src, needs_label = sources[p]
        text = label_lines(meta, label_style(style)["text"]) if (label and needs_label and meta) else None
        out = current_dir() / f"{stamp}-{i}.jpg"
        render(src, w, h, text, region, pos, style).save(out, "JPEG", quality=90)
        paths[key] = out

    backup.capture([current_dir(), folder, originals_dir()])   # remember your own wallpaper first
    try:
        if "span" in paths:
            monitors.set_all(str(paths["span"]), span=True)
        elif "all" in paths:
            monitors.set_all(str(paths["all"]))
        else:
            monitors.set_each({k: str(v) for k, v in paths.items()})
    except OSError:
        set_wallpaper(next(iter(paths.values())))      # older Windows: one image everywhere
    if lock_screen and Image is not None:
        _to_lock_screen(paths, chosen, main)

    # Remember what was shown, so the next rotation picks something else
    shown = [p.name for p, *_ in chosen.values()]
    limit = max(0, min(30, len(files) - len(targets)))
    cache.kv().set("rotation:recent", (shown + [n for n in recent if n not in shown])[:limit])
    for old in current_dir().glob("*.jpg"):             # previous renders are no longer needed
        if old not in paths.values():
            try:
                old.unlink()
            except OSError:
                pass

    on_screen = []
    for k, (p, *_rest) in chosen.items():
        meta = cache.kv().get(_meta_key(p.name), 1e12) or {}
        on_screen.append({"screen": screen_name(k), "key": k, "name": p.name, "id": meta.get("id", p.stem),
                          "title": titles[k], "maker": meta.get("maker", ""), "link": meta.get("link", "")})
    cache.kv().set("current:shown", on_screen)
    if record:                                          # for "previous painting"
        hist = (cache.kv().get("rotation:history", 1e12) or [])[-19:]
        cache.kv().set("rotation:history", hist + [{c["key"]: c["name"] for c in on_screen}])
    if same:
        return {"All screens": next(iter(titles.values()))}
    return {screen_name(k): titles[k] for k in chosen}


# ---------------------------------------------------------------- collection

def currently_shown() -> list[dict]:
    """One entry per screen (the same painting can be on several)."""
    return cache.kv().get("current:shown", 1e12) or []


def shown_summary() -> list[dict]:
    """currently_shown() with one entry per painting, for display."""
    out: dict = {}
    for c in currently_shown():
        if c["name"] in out:
            out[c["name"]]["screen"] = "All screens"
        else:
            out[c["name"]] = dict(c)
    return list(out.values())


def show_from_settings(s: dict | None = None, **kw) -> dict:
    """show_next() with everything taken from the user's settings. Paintings you just added
    (the "show first" queue) come before the rest."""
    from . import settings as _settings
    s = s or _settings.load()
    folder = resolve_folder(s.get("folder"))
    queue = [n for n in cache.kv().get("rotation:prefer", 1e12) or [] if (folder / n).exists()]
    if queue and "prefer" not in kw and "keep" not in kw:
        kw["prefer"] = queue
    shown = _show_from_settings(s, **kw)
    if queue:
        now = {c["name"] for c in currently_shown()}
        cache.kv().set("rotation:prefer", [n for n in queue if n not in now])
    return shown


def queue_first(names: list[str]) -> None:
    """These paintings come first in the next rotations."""
    old = cache.kv().get("rotation:prefer", 1e12) or []
    cache.kv().set("rotation:prefer", list(names) + [n for n in old if n not in names])


def show_previous(s: dict | None = None) -> dict | None:
    """Put the previous painting(s) back. None if there is no earlier one."""
    hist = cache.kv().get("rotation:history", 1e12) or []
    if len(hist) < 2:
        return None
    cache.kv().set("rotation:history", hist[:-1])
    return _show_from_settings(s, keep=hist[-2], record=False)


def add_to_collection(artworks: list, s: dict | None = None) -> dict:
    """Download paintings into the collection; they're shown first in the coming rounds."""
    from . import settings as _settings
    s = s or _settings.load()
    folder = resolve_folder(s.get("folder"))
    ok, failed = [], []

    def one(a):
        try:
            return a, download(a, folder, label=bool(s.get("label", True)), pos=label_pos(s.get("labelPos")),
                               style=label_style(s.get("labelStyle"))), None
        except Exception as e:
            return a, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=4) as ex:
        for a, path, err in ex.map(one, artworks):
            (ok if path else failed).append({"id": a.id, "title": a.title, "name": path.name if path else None,
                                             "error": err})
    queue_first([d["name"] for d in ok])
    removed = cleanup(folder, int(s.get("maxFiles") or 50), keep_ids=s.get("favourites") or ())
    return {"added": ok, "failed": failed, "removed": [p.name for p in removed]}


def _show_from_settings(s: dict | None = None, **kw) -> dict:
    from . import settings as _settings
    s = s or _settings.load()
    return show_next(resolve_folder(s.get("folder")), s.get("screens", "each"), bool(s.get("label", True)),
                     pos=label_pos(s.get("labelPos")), style=label_style(s.get("labelStyle")),
                     favourites=s.get("favourites") or [], time_of_day=bool(s.get("timeOfDay")),
                     lock_screen=bool(s.get("lockScreen")), seasons=bool(s.get("seasons")), **kw)


def relabel_folder(folder: Path, label: bool, pos=DEFAULT_LABEL_POS, style: dict | None = None) -> int:
    """Re-render the collection copies (used by the Windows slideshow) with the current
    label, from the stored originals. Keeps their dates, so clean-up order is unchanged."""
    if Image is None:
        return 0
    want = _label_key(bool(label), pos, style)
    n = 0
    for p in own_files(folder):
        orig, meta = originals_dir() / p.name, cache.kv().get(_meta_key(p.name), 1e12)
        if not orig.exists() or not meta or cache.kv().get(f"labelled:{p.name}", 1e12) == want:
            continue
        st = p.stat()
        tmp = p.with_suffix(".tmp")
        if want:
            with Image.open(orig) as im:
                _label_copy(im, meta, pos, style).save(tmp, "JPEG", quality=92)
        else:
            tmp.write_bytes(orig.read_bytes())
        tmp.replace(p)
        os.utime(p, (st.st_atime, st.st_mtime))
        cache.kv().set(f"labelled:{p.name}", want)
        n += 1
    return n


def _ours_on_screen(snap: dict | None) -> bool:
    cur = str(current_dir()).lower()
    return any(str(v).lower().startswith(cur) for v in ((snap or {}).get("wallpapers") or {}).values())


def refresh_labels(s: dict | None = None) -> dict:
    """Apply a changed label (on/off, style, position) to what is on screen *now*:
    the same paintings are re-rendered, no new ones are picked."""
    from . import settings as _settings
    s = s or _settings.load()
    folder = resolve_folder(s.get("folder"))
    try:
        snap = monitors.snapshot()
    except OSError:
        snap = None
    if snap and snap.get("slideshow"):                  # Windows' own slideshow on our folder
        n = relabel_folder(folder, bool(s.get("label", True)), label_pos(s.get("labelPos")),
                           label_style(s.get("labelStyle")))
        try:          # restarting the slideshow shows a freshly labelled picture right away
            monitors.set_slideshow(folder, interval_minutes=int(s.get("interval") or 60),
                                   span=s.get("screens") == "span")
        except OSError:
            pass
        return {"slideshow": True, "relabelled": n}
    if snap is not None and not _ours_on_screen(snap):
        return {"wallpapers": {}}       # your own wallpaper is on screen: leave it alone
    shown = currently_shown()
    if not shown:
        return {"wallpapers": {}}
    keep = {(c.get("key") or c["screen"]): c["name"] for c in shown}
    return {"wallpapers": show_from_settings(s, keep=keep)}


def skip(name: str | None = None, s: dict | None = None) -> dict:
    """"Skip": remove a painting that is on screen now from the collection and put
    another one in its place. Other screens keep their painting.
    name=None skips everything on screen now."""
    from . import settings as _settings
    s = s or _settings.load()
    folder = resolve_folder(s.get("folder"))
    shown = currently_shown()
    names = {name} if name else {c["name"] for c in shown}
    ids = {(cache.kv().get(_meta_key(n), 1e12) or {}).get("id") or Path(n).stem for n in names}
    titles = [(cache.kv().get(_meta_key(n), 1e12) or {}).get("title") or n for n in names]
    for n in names:
        remove(folder, n)
    # Also drop it from the selection, so "Set as wallpaper" doesn't bring it back
    _settings.save({"selection": [a for a in s.get("selection") or [] if a.get("id") not in ids],
                    "favourites": [f for f in s.get("favourites") or [] if f not in ids]})
    s = _settings.load()
    keep = {(c.get("key") or c["screen"]): c["name"] for c in shown if c["name"] not in names}
    return {"skipped": titles, "wallpapers": show_from_settings(s, keep=keep) if own_files(folder) else {}}


DETAILS_TTL = 30 * 24 * 3600


def painting_info(folder: Path, name: str, favourites=()) -> dict | None:
    """Everything for the info card of one collection painting. The museum's
    description is fetched once and then cached for 30 days."""
    if not OWN_FILE.match(name) or not (folder / name).exists():
        return None
    item = next((i for i in collection(folder) if i["name"] == name), None)
    if not item:
        return None
    meta = cache.kv().get(_meta_key(name), 1e12) or {}
    mod = SOURCES.get(meta.get("source") or name.split("-", 1)[0])
    info = {**item, "license": meta.get("license", ""), "source": getattr(mod, "KEY", ""),
            "favourite": item["id"] in set(favourites or ()),
            "screens": [c["screen"] for c in shown_summary() if c["name"] == name],
            "details": None}
    if mod is not None and hasattr(mod, "details"):
        key = f"details:{item['id']}"
        det = cache.kv().get(key, DETAILS_TTL)
        if det is None:
            try:
                det = mod.details(item["id"])
                cache.kv().set(key, det)
            except Exception as e:
                info["detailsError"] = f"The museum didn't answer ({type(e).__name__}). Try again later."
        info["details"] = det
    if not info["details"] and meta.get("text") and mod is not None and mod.KEY == "cleveland":
        info["details"] = {"description": meta["text"], "facts": [], "credit": ""}
    return info


def set_favourite(artwork_id: str, on: bool) -> list[str]:
    from . import settings as _settings
    favs = [f for f in _settings.load().get("favourites") or [] if f != artwork_id]
    if on:
        favs.append(artwork_id)
    return _settings.save({"favourites": favs})["favourites"]


def collection(folder: Path) -> list[dict]:
    """Paintings in the collection folder, newest first, with their details."""
    shown = {s["name"] for s in currently_shown()}
    out = []
    for p in own_files(folder):
        meta = cache.kv().get(_meta_key(p.name), 1e12) or {}
        size = image_size(originals_dir() / p.name) or image_size(p) or (0, 0)
        out.append({
            "name": p.name, "id": meta.get("id", p.stem), "title": meta.get("title") or p.stem,
            "maker": meta.get("maker", ""), "year": meta.get("year", ""), "museum": meta.get("museum", ""),
            "link": meta.get("link", ""), "width": size[0], "height": size[1],
            "bytes": p.stat().st_size, "onScreen": p.name in shown,
        })
    return out


def remove(folder: Path, name: str) -> bool:
    """Delete one painting from the collection (and its stored original)."""
    if not OWN_FILE.match(name):
        return False
    removed = False
    for p in (folder / name, originals_dir() / name):
        try:
            p.unlink()
            removed = True
        except OSError:
            pass
    return removed


def thumbnail(folder: Path, name: str, width: int = 480) -> Path | None:
    """Small JPEG of a collection painting for the collection page (cached)."""
    if Image is None or not OWN_FILE.match(name):
        return None
    src = originals_dir() / name if (originals_dir() / name).exists() else folder / name
    if not src.exists():
        return None
    out = cache.cache_dir() / "thumbs" / (name if width == 480 else f"{width}-{name}")
    try:
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.draft("RGB", (width, width))
            small = im.convert("RGB")
        small.thumbnail((width, width * 2), Image.LANCZOS)
        small.save(out, "JPEG", quality=85)
        return out
    except OSError:
        return None


def open_background_settings() -> None:
    if sys.platform == "win32":
        os.startfile("ms-settings:personalization-background")


# ---------------------------------------------------------------- all together

def apply(artworks: list[Artwork], *, folder: Path, label: bool, max_files: int,
          mode: str, screens: str = "each", interval: int = 60, set_now: bool = True,
          pos: tuple[float, float] = DEFAULT_LABEL_POS, style: dict | None = None,
          favourites=None, time_of_day: bool = False, lock_screen: bool = False,
          seasons: bool = False) -> dict:
    if mode == "daily":                    # settings from older versions
        mode, interval = "rotate", 1440
    interval = max(1, min(int(interval), 31 * 1440))
    ok, failed = [], []

    def one(a):
        try:
            return a, download(a, folder, label=label, pos=pos, style=style), None
        except Exception as e:
            return a, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=4) as ex:
        for a, path, err in ex.map(one, artworks):
            (ok if path else failed).append({"id": a.id, "title": a.title,
                                             "path": str(path) if path else None, "error": err})

    removed = cleanup(folder, max_files, keep_ids=favourites or ())
    result = {
        "folder": str(folder),
        "downloaded": ok,
        "failed": failed,
        "removed": [str(p) for p in removed],
        "wallpapers": {},
        "labels": label and Image is not None,
        "mode": mode,
        "slideshow": None,
    }
    if not set_now:
        return result

    fresh = [Path(d["path"]).name for d in ok]
    if mode == "slideshow":
        schedule.disable()                 # don't fight Windows' own slideshow
        backup.capture([current_dir(), folder, originals_dir()])
        try:
            monitors.set_slideshow(folder, interval_minutes=interval, span=screens == "span")
            result["slideshow"] = True
        except OSError as e:
            result["slideshow"] = False
            result["slideshowError"] = str(e)
            open_background_settings()
    elif mode in ("rotate", "curator"):
        if mode == "curator":               # the Curator also chooses new paintings, once a day
            from . import curator
            added = curator.run_if_due(force=True) or []
            result["curator"] = added
            fresh += [a["name"] for a in added]
        result["wallpapers"] = show_next(folder, screens, label, prefer=fresh, pos=pos, style=style,
                                         favourites=favourites, time_of_day=time_of_day,
                                         lock_screen=lock_screen, seasons=seasons)
        schedule.enable(interval)
    else:
        schedule.disable()
        result["wallpapers"] = show_next(folder, screens, label, prefer=fresh, pos=pos, style=style,
                                         favourites=favourites, lock_screen=lock_screen, seasons=seasons)
    result["rotation"] = schedule.status()
    result["backup"] = backup.has_backup()
    return result
