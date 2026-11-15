"""Content filters shared by all sources: subject, period and "hide" categories.

Each adapter maps these onto whatever its API supports natively:
  - AIC has curated subject tags (subject_titles) -> exact filtering.
  - Other museums have no usable subject tags -> a text search on "keyword"
    (Cleveland/Rijksmuseum: description, SMK: free text) — approximate.
On top of that, the "hide" patterns below are applied centrally to every
source's title + description, as a safety net.
"""

from __future__ import annotations

import colorsys
import re
import unicodedata

# Dominant-colour hue ranges in degrees (0–360)
HUES = {
    "red": [(345, 361), (0, 15)],
    "orange": [(15, 45)],
    "yellow": [(45, 70)],
    "green": [(70, 170)],
    "blue": [(170, 260)],
    "purple": [(260, 345)],
}


def hex_palette_matches(hexes: list[str], color: str, top: int = 4) -> bool:
    """True if one of the first `top` clearly coloured palette entries has the hue."""
    ranges = HUES.get(color)
    if not ranges:
        return True
    for hx in hexes[:top]:
        try:
            r, g, b = (int(hx.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        except ValueError:
            continue
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s < 0.25 or v < 0.2:
            continue          # greys, near-black
        deg = h * 360
        if any(a <= deg < b for a, b in ranges):
            return True
    return False


def html_to_text(s: str) -> str:
    """Museum descriptions often come as HTML: keep paragraphs, drop tags."""
    import html
    s = re.sub(r"(?i)<\s*(br|/p|/div|/li)\s*/?>", "\n\n", s or "")
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def fold(s: str) -> str:
    """Lower-case and strip accents, so 'Böcklin' matches 'bocklin'."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))

SUBJECTS: dict[str, dict] = {
    "landscape": {"label": "Landscapes", "aic": ["landscape", "landscapes", "mountain", "mountains"],
                  "keyword":"landscape"},
    "water": {"label": "Sea, rivers & boats", "aic": ["sea", "seas", "seascapes", "boats", "ships",
                                                     "river", "rivers", "water"],
              "keyword":"water"},
    "city": {"label": "Cities & buildings", "aic": ["cityscapes", "city", "street", "urban life",
                                                    "building", "buildings"],
             "keyword":"city"},
    "seasons": {"label": "Winter & seasons", "aic": ["winter", "snow", "seasons", "weather/seasons"],
                "keyword":"winter"},
    "flowers": {"label": "Flowers & gardens", "aic": ["flowers", "garden", "gardens"],
                "keyword":"flowers"},
    "stilllife": {"label": "Still life", "aic": ["still life"], "keyword":"still life"},
    "animals": {"label": "Animals", "aic": ["animals", "horses", "horse", "dog", "dogs", "birds", "bird"],
                "keyword":"animals"},
    "dailylife": {"label": "Daily life & interiors", "aic": ["everyday life (genre)", "leisure",
                                                             "interior", "interiors"],
                  "keyword":"daily life"},
    "portraits": {"label": "Portraits", "aic": ["portraits", "portrait"], "keyword":"portrait"},
    "mythology": {"label": "Mythology", "aic": ["mythology", "mythological figures", "Greek mythology"],
                  "keyword":"mythology"},
    "religious": {"label": "Religious scenes", "aic": ["religion", "religious scenes", "Christian subjects",
                                                       "biblical", "saints"],
                  "keyword":"religious"},
}

REGIONS: dict[str, dict] = {
    "europe": {"label": "Europe"},
    "americas": {"label": "The Americas"},
    "asia": {"label": "East & South Asia"},
    "middleeast": {"label": "Middle East & Islamic world"},
}

PERIODS: dict[str, dict] = {
    "pre1600": {"label": "Before 1600", "start": -3000, "end": 1600},
    "1600": {"label": "1600 – 1750", "start": 1600, "end": 1750},
    "1750": {"label": "1750 – 1850", "start": 1750, "end": 1850},
    "1850": {"label": "1850 – 1900", "start": 1850, "end": 1900},
    "1900": {"label": "1900 and later", "start": 1900, "end": 2100},
}

HIDE: dict[str, dict] = {
    "religious": {
        "label": "Religious scenes",
        "aic": ["religion", "religious", "religious scenes", "religious figures", "Christian subjects",
                "Christianity", "biblical", "saints", "Jesus"],
        "pattern": r"\b(christ|jesus|madonna|virgin|saints?|st\.|holy|apostles?|crucifixion|crucified|"
                   r"annunciation|nativity|biblical|angels?|piet[àa]|adoration|evangelist|resurrection|"
                   r"baptism|magi|lamentation|deposition|altarpiece|prophet|moses|magdalene)\b",
    },
    "nudes": {
        "label": "Nudes",
        "aic": ["nudes", "nude"],
        "pattern": r"\b(nudes?|naked|bathers?|odalisque)\b",
    },
    "violence": {
        "label": "Death & war",
        "aic": ["death", "war", "battles", "violence"],
        "pattern": r"\b(battles?|wars?|death|dead|dying|murder|execution|massacre|martyrdom|slaughter|"
                   r"killed|killing|corpse|skull|vanitas|wounded|siege)\b",
    },
}

_HIDE_RE = {k: re.compile(v["pattern"], re.I) for k, v in HIDE.items()}
TEXT_CHARS = 400   # how much description text adapters keep for the hide check


def hidden(text: str, hide: list[str] | tuple[str, ...]) -> bool:
    return any(_HIDE_RE[k].search(text) for k in hide if k in _HIDE_RE)


def describe() -> dict:
    return {
        "subjects": [{"key": k, "label": v["label"], "terms": [v["keyword"], *v["aic"]]} for k, v in SUBJECTS.items()],
        "regions": [{"key": k, "label": v["label"]} for k, v in REGIONS.items()],
        "periods": [{"key": k, "label": v["label"]} for k, v in PERIODS.items()],
        "hide": [{"key": k, "label": v["label"]} for k, v in HIDE.items()],
    }
