"""Build masterpiece/data/wikidata.json.gz: public-domain paintings from Latin America, Oceania, Africa, Russia.

Wikidata knows paintings in museums all over the world, with photos on Wikimedia Commons.
This script asks it (once, at build time) for paintings
  - in museums in Latin America, Australia, New Zealand, Africa and Russia, and
  - by artists from those countries, wherever the painting is now,
by painters who died before 1925. Every photo is then checked on Commons: only JPEG/PNG
files of at least 1000 px that Commons itself marks as public domain or CC0 are kept.
The result ships with Masterpiece, so searching costs Wikidata nothing.

    python packaging\\wikidata_index.py
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "masterpiece" / "data" / "wikidata.json.gz"
UA = "Masterpiece index builder (open-source desktop wallpaper tool; https://github.com/Teun-sudo1/Masterpiece)"
SPARQL = "https://query.wikidata.org/sparql"
COMMONS = "https://commons.wikimedia.org/w/api.php"

LATAM = {"Q155": "Brazil", "Q414": "Argentina", "Q96": "Mexico", "Q298": "Chile", "Q419": "Peru",
         "Q739": "Colombia", "Q77": "Uruguay", "Q717": "Venezuela", "Q241": "Cuba", "Q736": "Ecuador",
         "Q750": "Bolivia", "Q774": "Guatemala", "Q800": "Costa Rica", "Q733": "Paraguay", "Q804": "Panama",
         "Q786": "Dominican Republic", "Q1183": "Puerto Rico", "Q783": "Honduras", "Q792": "El Salvador",
         "Q811": "Nicaragua"}
OCEANIA = {"Q408": "Australia", "Q664": "New Zealand"}
AFRICA = {"Q258": "South Africa", "Q79": "Egypt", "Q1028": "Morocco", "Q262": "Algeria", "Q948": "Tunisia",
          "Q1033": "Nigeria", "Q115": "Ethiopia", "Q1041": "Senegal", "Q114": "Kenya", "Q117": "Ghana",
          "Q1009": "Cameroon", "Q1019": "Madagascar", "Q1029": "Mozambique", "Q1049": "Sudan"}
# Russia, and for painters' nationality also the Russian Empire and the Soviet Union
RUSSIA = {"Q159": "Russia", "Q34266": "the Russian Empire", "Q15180": "the Soviet Union"}
RUSSIA_MUSEUMS = {"Q159": "Russia"}
CONTINENT_REGION = {"Q46": "europe", "Q48": "asia", "Q18": "latam", "Q538": "oceania", "Q3960": "oceania",
                    "Q55643": "oceania"}
US_CANADA = {"Q30", "Q16"}
MIN_WIDTH = 1000
# a painter with several nationalities counts for the rarest region
PRIORITY = ("africa", "oceania", "latam", "russia", "americas", "asia", "europe")


def get_json(url: str, params: dict, accept: str = "application/json") -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(15 * (attempt + 1))
                continue
            raise


def sparql(where: str) -> list[dict]:
    q = f"""SELECT ?p ?pLabel ?creatorLabel ?inception ?img ?collLabel ?collCountry ?cc ?cont WHERE {{
  ?p wdt:P31 wd:Q3305213 ; wdt:P18 ?img ; wdt:P170 ?creator .
  ?creator wdt:P570 ?died . FILTER(YEAR(?died) < 1925)
  {where}
  OPTIONAL {{ ?p wdt:P571 ?inception }}
  OPTIONAL {{ ?p wdt:P195 ?coll . OPTIONAL {{ ?coll wdt:P17 ?collCountry }} }}
  OPTIONAL {{ ?creator wdt:P27 ?cc . OPTIONAL {{ ?cc wdt:P30 ?cont }} }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,pt,es,mul". }}
}} LIMIT 4000"""
    return get_json(SPARQL, {"query": q, "format": "json"}, "application/sparql-results+json")["results"]["bindings"]


def qid(b: dict, key: str) -> str:
    return (b.get(key) or {}).get("value", "").rsplit("/", 1)[-1]


def main() -> int:
    paintings: dict[str, dict] = {}

    def add(rows: list[dict], fallback_region: str) -> None:
        for b in rows:
            pid = qid(b, "p")
            title = b["pLabel"]["value"]
            if re.fullmatch(r"Q\d+", title):              # no readable title
                continue
            entry = paintings.setdefault(pid, {
                "id": pid, "title": title, "maker": b.get("creatorLabel", {}).get("value", "Unknown artist"),
                "inception": b.get("inception", {}).get("value", ""), "img": b["img"]["value"],
                "museum": b.get("collLabel", {}).get("value", ""), "regions": set(), "fallback": fallback_region})
            if qid(b, "collCountry") in AFRICA:  # so little is open from Africa: count all that hangs there
                entry["regions"].add("africa")
            cc, cont = qid(b, "cc"), qid(b, "cont")
            if cc in LATAM:
                entry["regions"].add("latam")
            elif cc in OCEANIA:
                entry["regions"].add("oceania")
            elif cc in AFRICA:
                entry["regions"].add("africa")
            elif cc in RUSSIA:
                entry["regions"].add("russia")
            elif cc in US_CANADA:
                entry["regions"].add("americas")
            elif cont in CONTINENT_REGION:
                entry["regions"].add(CONTINENT_REGION[cont])
            if not entry["museum"] and b.get("collLabel"):
                entry["museum"] = b["collLabel"]["value"]

    groups = (("latam", LATAM, LATAM), ("oceania", OCEANIA, OCEANIA), ("africa", AFRICA, AFRICA),
              ("russia", RUSSIA_MUSEUMS, RUSSIA))
    for region, museum_countries, artist_countries in groups:
        jobs = [("in museums in", name, f"?p wdt:P195 ?c0 . ?c0 wdt:P17 wd:{q} .") for q, name in museum_countries.items()]
        jobs += [("by artists from", name, f"?creator wdt:P27 wd:{q} .") for q, name in artist_countries.items()]
        for kind, name, where in jobs:
            try:
                rows = sparql(where)
                add(rows, region)
                print(f"  {kind} {name}: {len(rows)} rows", flush=True)
            except Exception as e:
                print(f"  {kind} {name}: skipped ({type(e).__name__})", flush=True)
            time.sleep(2)
    print(f"{len(paintings)} paintings found; checking their images on Commons …")

    # Commons: size, type and licence of each image (50 per request)
    by_file = {}
    for p in paintings.values():
        name = urllib.parse.unquote(p["img"].rsplit("/", 1)[-1]).replace("_", " ")
        by_file.setdefault(f"File:{name}", []).append(p)
    titles = list(by_file)
    kept = []
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = get_json(COMMONS, {"action": "query", "format": "json", "prop": "imageinfo",
                                  "iiprop": "url|size|mime|extmetadata",
                                  "iiextmetadatafilter": "LicenseShortName|License", "titles": "|".join(batch)})
        norm = {n["to"]: n["from"] for n in data.get("query", {}).get("normalized", [])}
        for page in data.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = ((meta.get("LicenseShortName") or {}).get("value") or "").lower()
            code = ((meta.get("License") or {}).get("value") or "").lower()
            if info.get("mime") not in ("image/jpeg", "image/png") or int(info.get("width") or 0) < MIN_WIDTH:
                continue
            if not ("public domain" in lic or lic.startswith("pd") or "cc0" in lic or code.startswith("pd") or code == "cc0"):
                continue
            for p in by_file.get(norm.get(page["title"], page["title"]), []):
                m = re.match(r"[+-]?(\d{4})", p["inception"])
                region = next((x for x in PRIORITY if x in p["regions"]), p["fallback"])
                kept.append([p["id"], p["title"], p["maker"], m.group(1) if m else "", int(m.group(1)) if m else None,
                             p["museum"], info["url"].split("?", 1)[0], int(info["width"]), int(info["height"]), region])
        print(f"  {min(i + 50, len(titles))}/{len(titles)} checked, {len(kept)} kept")
        time.sleep(1)

    kept.sort(key=lambda r: r[0])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": "Wikidata (CC0) + Wikimedia Commons (public-domain images only)",
               "fields": ["qid", "title", "maker", "date", "year", "museum", "url", "width", "height", "region"],
               "rows": kept}
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    from collections import Counter
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {len(kept)} paintings):",
          dict(Counter(r[9] for r in kept)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
