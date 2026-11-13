"""Source-independent filters that work on the shared Artwork format."""

from __future__ import annotations

import math

from . import content
from .models import Artwork

SCREEN_RATIO_TOLERANCE = 0.35   # "fits my screen": at most ~35% gets cropped by Fill
SHARP_FACTOR = 0.9              # "sharp": at most ~10% upscaling


def ratio_close(r: float, target: float, tol: float = SCREEN_RATIO_TOLERANCE) -> bool:
    return r > 0 and target > 0 and abs(math.log(r / target)) <= math.log(1 + tol)


def covers(a: Artwork, w: int, h: int) -> bool:
    """True if the image fills a w×h screen ('Fill' mode) without noticeable upscaling."""
    return a.width >= w * SHARP_FACTOR and a.height >= h * SHARP_FACTOR


def matches(a: Artwork, *, min_width: int = 0, orientation: str = "any",
            targets: list[tuple[int, int]] | None = None, sharp: bool = False,
            hide: list[str] | tuple[str, ...] = ()) -> bool:
    """
    orientation: any | landscape | portrait | widescreen | panorama |
                 screens (ratio close to one of `targets`)
    sharp:       image must cover one of `targets` (the matching one, for 'screens')
    targets:     screen sizes [(w, h), ...]; for spanning pass the whole desktop
    """
    if not a.width or not a.height or a.width < (min_width or 0):
        return False
    if hide and content.hidden(f"{a.title}\n{a.text}", hide):
        return False

    r = a.ratio
    targets = targets or []
    if orientation == "landscape" and not r > 1.05:
        return False
    if orientation == "portrait" and not r < 0.95:
        return False
    if orientation == "widescreen" and not 1.6 <= r <= 1.95:     # 16:10 … 16:9 and a bit
        return False
    if orientation == "panorama" and not r >= 2.0:
        return False
    if orientation == "screens":
        targets = [t for t in targets if ratio_close(r, t[0] / t[1])]
        if not targets:
            return False
    if sharp and targets and not any(covers(a, w, h) for w, h in targets):
        return False
    return True


def apply(items: list[Artwork], **kw) -> list[Artwork]:
    return [a for a in items if matches(a, **kw)]
