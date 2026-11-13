"""Shared artwork format used by every source adapter."""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Artwork:
    id: str            # globally unique, "<source>-<museum id>"
    source: str        # adapter key, e.g. "aic"
    title: str
    maker: str
    year: str
    museum: str
    image_url: str     # largest downloadable JPEG
    preview_url: str   # small image for the grid / lightbox
    width: int         # pixel size of image_url
    height: int
    license: str
    link: str = ""     # artwork page on the museum website (for attribution)
    text: str = ""     # short description snippet, used by the content filters
    thumb_url: str = ""  # ~400 px image for the grid (falls back to preview_url)

    @property
    def ratio(self) -> float:
        return self.width / self.height if self.height else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        # camelCase for the JSON API / web UI
        d["imageUrl"] = d.pop("image_url")
        d["previewUrl"] = d.pop("preview_url")
        d["thumbUrl"] = d.pop("thumb_url") or d["previewUrl"]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Artwork":
        return cls(
            id=str(d["id"]),
            source=str(d["source"]),
            title=str(d.get("title", "")),
            maker=str(d.get("maker", "")),
            year=str(d.get("year", "")),
            museum=str(d.get("museum", "")),
            image_url=str(d.get("imageUrl") or d.get("image_url")),
            preview_url=str(d.get("previewUrl") or d.get("preview_url") or ""),
            width=int(d.get("width") or 0),
            height=int(d.get("height") or 0),
            license=str(d.get("license", "")),
            link=str(d.get("link", "")),
            text=str(d.get("text", "")),
            thumb_url=str(d.get("thumbUrl") or d.get("thumb_url") or ""),
        )


class Results(list):
    """What an adapter's search() returns: a list of Artwork plus `more`
    (True if the museum has further pages, independent of our own filtering)."""

    def __init__(self, items=(), more: bool = False):
        super().__init__(items)
        self.more = more
