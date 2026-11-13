"""Build masterpiece/data/nga.json.gz: the National Gallery of Art's open-access paintings.

The NGA has no search API; its collection data is published as CSV files on GitHub
(https://github.com/NationalGalleryOfArt/opendata, CC0). This script streams them once
(about 220 MB), keeps only paintings with an open-access image, and writes a compact
index (a few hundred KB) that ships with Masterpiece. Searching is then done locally,
so the NGA's servers only see the image requests.

    python packaging\\nga_index.py          # re-run now and then to pick up new images
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/main/data/"
OUT = Path(__file__).resolve().parent.parent / "masterpiece" / "data" / "nga.json.gz"
H = {"User-Agent": "Masterpiece index builder (open-source desktop wallpaper tool)"}

csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)

REGION_OF = {   # visualbrowsernationality -> Masterpiece region
    **{n: "americas" for n in ("American", "Canadian", "Mexican", "Brazilian", "Argentine", "Cuban",
                               "Peruvian", "Chilean", "Colombian", "Venezuelan", "Uruguayan")},
    **{n: "asia" for n in ("Chinese", "Japanese", "Korean", "Indian", "Thai", "Vietnamese", "Indonesian",
                           "Tibetan", "Nepalese", "Cambodian")},
    **{n: "middleeast" for n in ("Persian", "Iranian", "Turkish", "Ottoman", "Egyptian", "Syrian", "Iraqi",
                                 "Lebanese", "Arab", "Afghan")},
    **{n: "europe" for n in ("French", "Italian", "Dutch", "Flemish", "German", "British", "English",
                             "Spanish", "Netherlandish", "Belgian", "Austrian", "Swiss", "Danish", "Swedish",
                             "Norwegian", "Russian", "Polish", "Czech", "Hungarian", "Scottish", "Irish",
                             "Portuguese", "Greek", "Finnish", "Welsh", "Bohemian", "Venetian", "Florentine",
                             "Sienese", "Lombard", "Genoese", "Roman", "Bolognese", "Neapolitan", "Ferrarese",
                             "Umbrian", "Croatian", "Romanian", "Byzantine")},
}


def rows(name: str):
    req = urllib.request.Request(BASE + name, headers=H)
    r = urllib.request.urlopen(req, timeout=120)
    yield from csv.DictReader(io.TextIOWrapper(r, encoding="utf-8", newline=""))


def main() -> int:
    print("objects.csv …")
    paintings = {}
    for o in rows("objects.csv"):
        if o.get("classification") == "Painting" and o.get("isvirtual") != "1":
            paintings[o["objectid"]] = o
    print(f"  {len(paintings)} paintings")

    print("published_images.csv …")
    images = {}
    for im in rows("published_images.csv"):
        oid = im.get("depictstmsobjectid")
        if oid in paintings and im.get("viewtype") == "primary" and im.get("openaccess") == "1":
            try:
                w, h = int(im["width"]), int(im["height"])
            except (KeyError, ValueError):
                continue
            if w and h and oid not in images:
                images[oid] = (im["uuid"], w, h)
    print(f"  {len(images)} with an open-access image")

    print("objects_constituents.csv …")
    artist_of = {}
    for oc in rows("objects_constituents.csv"):
        if oc.get("objectid") in images and oc.get("roletype") == "artist" and oc["objectid"] not in artist_of:
            artist_of[oc["objectid"]] = oc.get("constituentid")
    print("constituents.csv …")
    wanted = set(artist_of.values())
    nationality = {c["constituentid"]: c.get("visualbrowsernationality") or c.get("nationality") or ""
                   for c in rows("constituents.csv") if c["constituentid"] in wanted}

    out = []
    for oid, (uuid, w, h) in images.items():
        o = paintings[oid]
        try:
            year = int(o.get("beginyear") or "")
        except ValueError:
            year = None
        region = REGION_OF.get(nationality.get(artist_of.get(oid), ""), "")
        out.append([int(oid), o.get("title") or "Untitled", o.get("attribution") or "Unknown artist",
                    o.get("displaydate") or "", year, (o.get("medium") or "")[:80], uuid, w, h, region])
    out.sort(key=lambda r: r[0])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": "https://github.com/NationalGalleryOfArt/opendata (CC0)",
               "fields": ["objectid", "title", "maker", "date", "year", "medium", "uuid", "width", "height", "region"],
               "rows": out}
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {len(out)} paintings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
