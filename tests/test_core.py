import os
from pathlib import Path

import pytest

from masterpiece import filters, wallpaper
from masterpiece.models import Artwork
from masterpiece.sources import SOURCES, aic, cleveland


def art(w, h, id="aic-1"):
    return Artwork(id=id, source="aic", title="T", maker="M", year="1900", museum="X",
                   image_url="https://www.artic.edu/x.jpg", preview_url="", width=w,
                   height=h, license="CC0")


@pytest.mark.parametrize("w,h,orientation,min_width,expected", [
    (1920, 1080, "widescreen", 0, True),
    (1920, 1200, "widescreen", 0, True),
    (1500, 1200, "widescreen", 0, False),
    (3000, 1000, "panorama", 0, True),
    (1000, 1500, "landscape", 0, False),
    (1000, 1500, "any", 0, True),
    (1000, 600, "any", 1920, False),
    (1000, 0, "any", 0, False),
])
def test_filters(w, h, orientation, min_width, expected):
    assert filters.matches(art(w, h), orientation=orientation, min_width=min_width) is expected


SCREENS = [(1920, 1080), (1080, 1920)]   # landscape + portrait monitor


@pytest.mark.parametrize("w,h,sharp,expected", [
    (3000, 1800, False, True),    # landscape fits the 1920×1080 screen
    (1800, 3000, False, True),    # portrait fits the 1080×1920 screen
    (3000, 3000, False, False),   # square fits neither well
    (1500, 900, True, False),     # right shape but would be upscaled
    (2000, 1150, True, True),
    (1000, 1800, True, True),     # ≥ 90 % of 1080×1920
])
def test_screen_filters(w, h, sharp, expected):
    assert filters.matches(art(w, h), orientation="screens", targets=SCREENS, sharp=sharp) is expected


def test_portrait_and_span():
    assert filters.matches(art(1000, 1500), orientation="portrait")
    assert not filters.matches(art(1500, 1000), orientation="portrait")
    # span of both screens above = 3000×1920
    assert filters.matches(art(3000, 1900), orientation="screens", targets=[(3000, 1920)], sharp=True)


def test_hide_uses_title_and_text():
    a = art(2000, 1000)
    a.title = "The Crucifixion"
    assert not filters.matches(a, hide=["religious"])
    a.title, a.text = "Evening", "A nude figure reclines by the river."
    assert not filters.matches(a, hide=["nudes"])
    assert filters.matches(a, hide=["religious"])


def test_search_keeps_paging_until_filters_match(monkeypatch):
    """Regression: 'load more' showed nothing when a whole page was filtered out."""
    from masterpiece import search as s
    from masterpiece.models import Results

    calls = []

    class Fake:
        KEY, PAGE_SIZE = "fake", 2

        @staticmethod
        def search(page=1, **kw):
            calls.append(page)
            # pages 1–2 only portraits, page 3 landscapes
            if page < 3:
                return Results([art(500, 900, id=f"fake-{page}-{i}") for i in range(2)], more=True)
            return Results([art(1600, 900, id=f"fake-{page}-{i}") for i in range(2)], more=False)

    monkeypatch.setitem(s.SOURCES, "fake", Fake)
    r = s.search_all(["fake"], orientation="landscape")
    assert calls == [1, 2, 3]
    assert len(r["results"]) == 2 and r["cursors"]["fake"] == 0


def test_cleveland_query_must_match_searchable_fields():
    d = {"title": "Ruin by the Sea", "creators": [{"description": "Arnold Böcklin (Swiss)"}],
         "description": "", "culture": [], "technique": "oil on canvas"}
    assert cleveland._matches_query(d, cleveland._fold("bocklin sea").split())
    assert not cleveland._matches_query(d, ["rosenthal"])   # e.g. only in provenance


def test_aic_query_is_required_not_just_ranked(monkeypatch):
    sent = {}
    monkeypatch.setattr(aic, "get_json", lambda url, body=None, **k: sent.update(body) or {"data": []})
    aic.search(query="rosenthal")
    assert "q" not in sent
    assert sent["query"]["bool"]["must"][0]["multi_match"]["operator"] == "and"


EDM_SAMPLE = b"""<rdf:RDF xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:edm="http://www.europeana.eu/schemas/edm/" xmlns:ore="http://www.openarchives.org/ore/terms/"
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:skos="http://www.w3.org/2004/02/skos/core#">
 <ore:Aggregation rdf:about="x#aggregation">
  <edm:isShownAt rdf:resource="https://www.rijksmuseum.nl/nl/collectie/object/SK-A-2344"/>
  <edm:isShownBy rdf:resource="https://iiif.micr.io/QkOGy/full/max/0/default.jpg"/>
  <edm:rights rdf:resource="http://creativecommons.org/publicdomain/mark/1.0/"/>
 </ore:Aggregation>
 <edm:ProvidedCHO rdf:about="https://id.rijksmuseum.nl/200108369">
  <dcterms:created xml:lang="nl">ca. 1660</dcterms:created><dcterms:created xml:lang="en">c. 1660</dcterms:created>
  <dc:creator rdf:resource="https://id.rijksmuseum.nl/2101778"/>
  <dc:title xml:lang="nl">Het melkmeisje</dc:title><dc:title xml:lang="en">The Milkmaid</dc:title>
 </edm:ProvidedCHO>
 <edm:Agent rdf:about="https://id.rijksmuseum.nl/2101778"><skos:prefLabel xml:lang="en">Johannes Vermeer</skos:prefLabel></edm:Agent>
</rdf:RDF>"""


def test_rijks_edm_parsing():
    from masterpiece.sources import rijks
    m = rijks._parse_edm("200108369", EDM_SAMPLE)
    assert (m["title"], m["maker"], m["year"]) == ("The Milkmaid", "Johannes Vermeer", "c. 1660")
    assert m["iiif"] == "https://iiif.micr.io/QkOGy"
    assert rijks._parse_edm("1", EDM_SAMPLE.replace(b"publicdomain/mark", b"licenses/by")) is None


def test_rijks_query_searches_creator_title_description():
    from masterpiece.sources import rijks
    sets = rijks._param_sets("vermeer", None, "1850")
    assert {tuple(k for k in s if k in ("creator", "title", "description")) for s in sets} == \
        {("creator",), ("title",), ("description",)}
    assert {s["creationDate"] for s in sets} == {"185?", "186?", "187?", "188?", "189?"}


def test_smk_mapping_and_palette():
    from masterpiece import content
    from masterpiece.sources import smk
    a = smk._to_artwork({
        "id": "x", "object_number": "KMS1", "public_domain": True, "has_image": True,
        "image_iiif_id": "https://iip.smk.dk/iiif/jp2/k.jp2", "image_width": 9000, "image_height": 6000,
        "titles": [{"title": "Skov", "language": "dansk"}, {"title": "Forest", "language": "engelsk"}],
        "production": [{"creator": "Ring, L.A.", "creator_forename": "L.A.", "creator_surname": "Ring"}],
        "production_date": [{"period": "1893"}],
    })
    assert (a.title, a.maker, a.width, a.height) == ("Forest", "L.A. Ring", 3840, 2560)
    assert content.hex_palette_matches(["#222222", "#3060c0"], "blue")
    assert not content.hex_palette_matches(["#222222", "#3060c0"], "red")


def test_new_sources_get_enabled(tmp_path, monkeypatch):
    import json
    from masterpiece import settings
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = settings.settings_path()
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"enabledSources": ["aic"]}))      # saved by an older version
    s = settings.load()
    assert "aic" in s["enabledSources"] and "cleveland" not in s["enabledSources"]  # user turned it off
    assert {"rijks", "smk"} <= set(s["enabledSources"])                              # new museums on


def test_search_pages_are_cached(monkeypatch):
    """Changing only our own filters must not hit the museum API again."""
    from masterpiece import search as s
    from masterpiece.models import Results

    calls = []

    class Fake:
        KEY, PAGE_SIZE = "fake", 2

        @staticmethod
        def search(page=1, **kw):
            calls.append(page)
            return Results([art(1600, 900, id=f"fake-{page}-{i}") for i in range(2)], more=False)

    monkeypatch.setitem(s.SOURCES, "fake", Fake)
    s.search_all(["fake"], orientation="landscape")
    s.search_all(["fake"], orientation="any", min_width=1000)
    assert calls == [1]


def test_image_cache_roundtrip():
    from masterpiece import cache
    url = "https://www.artic.edu/iiif/2/x/full/400,/0/default.jpg"
    assert cache.image_get(url) is None
    cache.image_put(url, b"\xff\xd8jpeg", "image/jpeg")
    assert cache.image_get(url) == (b"\xff\xd8jpeg", "image/jpeg")


def _fake_screens(monkeypatch, calls):
    from masterpiece import monitors
    lay = {"monitors": [
        {"id": "A", "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": True},
        {"id": "B", "x": -1080, "y": -429, "width": 1080, "height": 1920, "primary": False}],
        "span": {"width": 3000, "height": 1920}}
    monkeypatch.setattr(monitors, "layout", lambda: lay)
    monkeypatch.setattr(monitors, "set_each", lambda mapping: calls.append(("each", dict(mapping))))
    monkeypatch.setattr(monitors, "set_all", lambda path, span=False: calls.append(("span" if span else "all", path)))
    monkeypatch.setattr(monitors, "snapshot", lambda: {"position": 4, "color": 0, "slideshow": None,
                                                       "wallpapers": {"A": "", "B": ""}})


def test_show_next_matches_each_screen_and_renders_exact_size(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    from masterpiece import cache
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    PIL.new("RGB", (1600, 900), "navy").save(folder / "aic-1.jpg")      # landscape
    PIL.new("RGB", (900, 1600), "olive").save(folder / "aic-2.jpg")     # portrait
    for n in ("aic-1.jpg", "aic-2.jpg"):
        cache.kv().set(f"art:{n}", {"title": n, "maker": "M", "museum": "X"})
        cache.kv().set(f"labelled:{n}", False)
    calls = []
    _fake_screens(monkeypatch, calls)

    shown = wallpaper.show_next(folder, "each", label=True)
    kind, mapping = calls[-1]
    assert kind == "each" and set(mapping) == {"A", "B"}
    assert PIL.open(mapping["A"]).size == (1920, 1080)
    assert PIL.open(mapping["B"]).size == (1080, 1920)
    assert shown == {"1920×1080": "aic-1.jpg", "1080×1920": "aic-2.jpg"}   # shape-matched

    wallpaper.show_next(folder, "span", label=True)
    kind, path = calls[-1]
    assert kind == "span" and PIL.open(path).size == (3000, 1920)


def _two_paintings(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    from masterpiece import cache
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    wallpaper.originals_dir().mkdir(parents=True, exist_ok=True)
    for n, size, colour in (("aic-1.jpg", (1600, 900), "navy"), ("aic-2.jpg", (900, 1600), "olive"),
                            ("aic-3.jpg", (1600, 900), "white")):
        PIL.new("RGB", size, colour).save(folder / n)
        PIL.new("RGB", size, colour).save(wallpaper.originals_dir() / n)
        cache.kv().set(f"art:{n}", {"id": n[:-4], "title": n, "maker": "M", "museum": "X"})
    return folder


def test_same_painting_gets_an_exact_render_per_screen(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    folder = _two_paintings(tmp_path)
    calls = []
    _fake_screens(monkeypatch, calls)
    shown = wallpaper.show_next(folder, "same", label=True)
    kind, mapping = calls[-1]
    assert kind == "each" and PIL.open(mapping["A"]).size == (1920, 1080)
    assert PIL.open(mapping["B"]).size == (1080, 1920)             # not one image stretched over both
    names = {c["name"] for c in wallpaper.currently_shown()}
    assert len(names) == 1 and list(shown) == ["All screens"]
    assert len(wallpaper.shown_summary()) == 1


def test_refresh_keeps_the_paintings_and_skip_replaces_one(tmp_path, monkeypatch):
    from masterpiece import monitors, settings
    folder = _two_paintings(tmp_path)
    settings.save({"folder": str(folder), "screens": "each"})
    calls = []
    _fake_screens(monkeypatch, calls)
    wallpaper.show_from_settings()
    before = {c["key"]: c["name"] for c in wallpaper.currently_shown()}
    ours = calls[-1][1]
    monkeypatch.setattr(monitors, "snapshot", lambda: {"slideshow": None, "wallpapers": dict(ours)})
    settings.save({"labelStyle": {"look": "plaque"}})
    wallpaper.refresh_labels()
    assert {c["key"]: c["name"] for c in wallpaper.currently_shown()} == before   # same paintings

    r = wallpaper.skip(before["B"])                                # the portrait one
    after = {c["key"]: c["name"] for c in wallpaper.currently_shown()}
    assert after["A"] == before["A"] and after["B"] != before["B"]
    assert not (folder / before["B"]).exists() and r["skipped"]


def test_refresh_leaves_your_own_wallpaper_alone(tmp_path, monkeypatch):
    from masterpiece import monitors
    folder = _two_paintings(tmp_path)
    calls = []
    _fake_screens(monkeypatch, calls)
    wallpaper.show_next(folder, "each")
    n = len(calls)
    monkeypatch.setattr(monitors, "snapshot", lambda: {"slideshow": None, "wallpapers": {"A": r"C:\me.jpg"}})
    assert wallpaper.refresh_labels() == {"wallpapers": {}} and len(calls) == n


def test_favourites_and_time_of_day_weights(tmp_path, monkeypatch):
    folder = _two_paintings(tmp_path)
    paths = [wallpaper.originals_dir() / n for n in ("aic-1.jpg", "aic-3.jpg")]   # navy, white
    day = wallpaper.time_of_day_weights(paths, "day")
    night = wallpaper.time_of_day_weights(paths, "evening")
    assert day[paths[1]] > day[paths[0]] and night[paths[0]] > night[paths[1]]
    assert wallpaper.time_of_day_weights(paths, "between") == {}
    assert wallpaper.daypart(12) == "day" and wallpaper.daypart(22) == "evening"
    assert wallpaper.set_favourite("aic-1", True) == ["aic-1"]
    assert wallpaper.fav_names(["aic-1"]) == {"aic-1.jpg"}
    assert wallpaper.set_favourite("aic-1", False) == []


def test_visible_region_and_slideshow_copy_keep_label_on_every_screen():
    PIL = pytest.importorskip("PIL.Image")
    # 16:9 picture on a 16:9 and a 9:16 screen: only the central 9:16 strip is visible on both
    x0, y0, x1, y1 = wallpaper._visible_region(1600, 900, [(1920, 1080), (1080, 1920)])
    assert (y0, y1) == (0, 900) and abs((x1 - x0) - 900 * 9 / 16) < 2
    big = wallpaper._label_copy(PIL.new("RGB", (800, 450), "white"),
                                {"title": "T", "maker": "M", "museum": "X"}, (0.5, 0.93), None)
    assert big.size[0] >= 1920                                    # enlarged: text drawn sharp


def test_kv_prune_keeps_collection_data():
    from masterpiece import cache
    import time as _t
    kv = cache.kv()
    kv.set("art:aic-1.jpg", {"title": "T"})
    kv.set("aic:page", [1])
    kv.db.execute("UPDATE kv SET t = ?", (_t.time() - 400 * cache.DAY,))
    kv.prune(60 * cache.DAY)
    assert kv.get("art:aic-1.jpg", 1e12) == {"title": "T"} and kv.get("aic:page", 1e12) is None


def test_launcher_uses_the_exe_when_frozen(monkeypatch, tmp_path):
    import sys
    from masterpiece import desktop, schedule
    prog, args, _ = desktop.launcher("next")
    assert prog.lower().endswith(("pythonw.exe", "python.exe")) and args == "-m masterpiece next"
    exe = tmp_path / "Masterpiece" / "Masterpiece.exe"
    monkeypatch.setattr(desktop, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert desktop.launcher("next") == (str(exe), "next", exe.parent)
    xml = schedule.task_xml(60)
    assert f"<Command>{exe}</Command>" in xml and "<Arguments>next</Arguments>" in xml


def test_relink_keeps_interval_and_pause(monkeypatch):
    from masterpiece import schedule
    calls = []
    monkeypatch.setattr(schedule, "enable", lambda m, name=schedule.TASK: calls.append(("enable", m)))
    monkeypatch.setattr(schedule, "pause", lambda name=schedule.TASK: calls.append(("pause",)))
    monkeypatch.setattr(schedule, "status", lambda name=schedule.TASK: {"active": False})
    assert schedule.relink(30) is False and calls == []
    monkeypatch.setattr(schedule, "status", lambda name=schedule.TASK: {"active": True, "paused": True})
    assert schedule.relink(30) is True and calls == [("enable", 30), ("pause",)]


def _release(data: bytes, digest: str | None = None, tag="v9.1.0"):
    import hashlib
    name = f"Masterpiece-Setup-{tag.lstrip('v')}.exe"
    return {"tag_name": tag, "name": tag, "body": "New things", "html_url": "https://github.com/o/r/releases/x",
            "draft": False, "prerelease": False,
            "assets": [{"name": name, "size": len(data),
                        "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/{name}",
                        "digest": "sha256:" + (digest or hashlib.sha256(data).hexdigest())}]}


class _FakeResp:
    def __init__(self, data: bytes, url: str):
        import io
        self._b, self._url = io.BytesIO(data), url
    def read(self, n=-1): return self._b.read(n)
    def geturl(self): return self._url
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_update_check_and_verified_download(monkeypatch):
    import json
    from masterpiece import update
    setup = b"MZ fake installer bytes"
    rel = _release(setup)
    monkeypatch.setattr(update, "UPDATE_REPO", "o/r")
    monkeypatch.setattr(update, "__version__", "0.2.0")

    def urlopen(req, timeout=None):
        url = req.full_url
        if url.startswith("https://api.github.com/"):
            return _FakeResp(json.dumps(rel).encode(), url)
        return _FakeResp(setup, "https://release-assets.githubusercontent.com/file")   # after redirect
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)

    st = update.check()
    assert st["available"] and st["latest"] == "9.1.0" and st["release"]["sha256"]
    path = update.download(st["release"])
    assert path.read_bytes() == setup

    bad = update._parse(_release(setup, digest="0" * 64))
    with pytest.raises(ValueError):
        update.download(bad)                                  # wrong checksum: refused, deleted
    assert not list(update.updates_dir().glob("*.part"))
    no_sum = {**update._parse(_release(setup)), "sha256": "", "shaUrl": ""}
    with pytest.raises(ValueError):
        update.download(no_sum)                               # no checksum at all: refused
    with pytest.raises(ValueError):
        update.download({**st["release"], "url": "https://evil.example.com/x.exe"})


def test_update_versions():
    from masterpiece import update
    assert update.version_tuple("v0.10.0") > update.version_tuple("0.9.9")
    assert update.version_tuple("1.0.0-beta") == (1, 0, 0)
    assert update._parse({"tag_name": "v1", "draft": True, "assets": []}) is None


def test_nga_local_index_search():
    from masterpiece.sources import nga
    assert len(nga._index()) > 1000
    r = nga.search("", subject="landscape", limit=10)
    assert r and r.more and all(a.image_url.startswith("https://api.nga.gov/iiif/") for a in r)
    assert all("landscape" in content_fold(a.title) or "mountain" in content_fold(a.title) for a in r)
    assert [a.id for a in nga.search("", subject="landscape", limit=10)] == [a.id for a in r]   # stable pages
    eu = nga.search("", region="europe", period="1850", limit=20)
    assert eu and all(1850 <= int(re.match(r"\d{4}", a.year or "0000").group()) < 1900 for a in eu
                      if re.match(r"\d{4}", a.year or ""))


def content_fold(s):
    from masterpiece import content
    return content.fold(s)


import re  # noqa: E402


def test_yale_only_public_domain_paintings():
    from masterpiece.sources import yale
    obj = {"_label": "Sunset at Sea", "produced_by": {"timespan": {"identified_by": [{"content": "ca. 1824"}],
           "begin_of_the_begin": "1824-01-01T00:00:00Z"},
           "part": [{"classified_as": [{"_label": "Primary Artist"}], "carried_out_by": [{"_label": "Artist: Francis Danby"}]}]}}
    url = "https://manifests.collections.yale.edu/ycba/obj/123"

    def manifest(copyright, medium):
        return {"metadata": [{"label": {"en": ["Copyright Statement"]}, "value": {"en": [copyright]}},
                             {"label": {"en": ["Medium"]}, "value": {"en": [medium]}}],
                "rights": "https://creativecommons.org/publicdomain/zero/1.0/",
                "items": [{"width": 4000, "height": 2500, "items": [{"items": [{"body": {
                    "service": [{"@id": "https://images.collections.yale.edu/iiif/2/ycba:abc"}]}}]}]}]}
    a = yale._to_artwork("https://lux.collections.yale.edu/data/object/x", obj, url, manifest("Public Domain", "Oil on canvas"))
    assert a and a.maker == "Francis Danby" and a.width == 3840 and a.museum == "Yale Center for British Art"
    assert yale._to_artwork("x", obj, url, manifest("© Estate of the Artist", "Oil on canvas")) is None   # CC0 rights ignored
    assert yale._to_artwork("x", obj, url, manifest("Public Domain", "Brown ink and gray wash")) is None  # a drawing


def test_storage_usage_and_free_space(tmp_path):
    from masterpiece import cache, storage
    (cache.cache_dir() / "img" / "ab").mkdir(parents=True)
    (cache.cache_dir() / "img" / "ab" / "x.jpg").write_bytes(b"x" * 5000)
    (wallpaper.originals_dir()).mkdir(parents=True, exist_ok=True)
    (wallpaper.originals_dir() / "aic-1.jpg").write_bytes(b"y" * 7000)
    u = storage.usage(tmp_path / "Masterpiece")
    parts = {p["key"]: p for p in u["parts"]}
    assert parts["previews"]["bytes"] == 5000 and parts["originals"]["bytes"] == 7000 and u["freeable"] == 5000
    assert storage.free_space() == 5000
    assert not (cache.cache_dir() / "img").exists() and (wallpaper.originals_dir() / "aic-1.jpg").exists()


def test_whats_new_after_an_update(monkeypatch):
    from masterpiece import cache, settings, update
    monkeypatch.setattr(update, "UPDATE_REPO", "")               # no network for the notes
    monkeypatch.setattr(update, "__version__", "0.3.0")
    assert update.note_start() is None                            # fresh install: nothing to show
    monkeypatch.setattr(update, "__version__", "0.4.0")
    cache.kv().set("update:installing", {"version": "0.4.0", "notes": "Lock screen!", "page": "https://x"})
    w = update.note_start()
    assert w["version"] == "0.4.0" and w["from"] == "0.3.0" and w["notes"] == "Lock screen!"
    assert update.whats_new()["notes"] == "Lock screen!" and update.note_start() is None   # only once
    update.dismiss_whats_new()
    assert update.whats_new() is None and settings.load()["lastVersion"] == "0.4.0"


def test_auto_update_only_when_on_installed_and_idle(monkeypatch):
    from masterpiece import settings, update
    started = []
    monkeypatch.setattr(update, "start_install", lambda rel, background=False: started.append(background))
    monkeypatch.setattr(update, "check", lambda force=False: {"available": True, "latest": "9.0.0", "release": {}})
    monkeypatch.setattr(update, "frozen", lambda: True)
    monkeypatch.setattr(update, "idle_seconds", lambda: 3600)
    assert update.maybe_auto_install() is None                    # switched off by default
    settings.save({"autoUpdate": True})
    monkeypatch.setattr(update, "idle_seconds", lambda: 30)
    assert update.maybe_auto_install() is None                    # someone is using the PC
    monkeypatch.setattr(update, "idle_seconds", lambda: 3600)
    assert update.maybe_auto_install() == "9.0.0" and started == [True]   # restarts in the tray only


def test_html_to_text():
    from masterpiece import content
    assert content.html_to_text("<p>One &amp; <em>two</em></p><p>Three</p>") == "One & two\n\nThree"


def test_download_once_and_relabel_without_refetch(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    import io
    buf = io.BytesIO()
    PIL.new("RGB", (800, 500), "white").save(buf, "JPEG")
    fetches = []
    monkeypatch.setattr(wallpaper, "fetch", lambda url: fetches.append(url) or (buf.getvalue(), "image/jpeg"))
    folder = tmp_path / "Masterpiece"
    a = art(800, 500)
    wallpaper.download(a, folder, label=True)
    wallpaper.download(a, folder, label=True)
    wallpaper.download(a, folder, label=False)      # label switched off: re-render from original
    assert len(fetches) == 1
    assert PIL.open(folder / "aic-1.jpg").getpixel((700, 450)) == (255, 255, 255)


def test_saved_ids_lists_collection(tmp_path):
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    (folder / "aic-12.jpg").write_bytes(b"x")
    (folder / "smk-KMS8914.jpg").write_bytes(b"x")
    (folder / "holiday.jpg").write_bytes(b"x")            # not ours
    assert sorted(wallpaper.saved_ids(folder)) == ["aic-12", "smk-KMS8914"]


def test_label_position_moves_the_box():
    PIL = pytest.importorskip("PIL.Image")
    base = PIL.new("RGB", (1600, 900), "white")
    centre = wallpaper.add_label(base, "Title — Artist · Museum", pos=(0.5, 0.5))
    assert centre.getpixel((800, 450)) != (255, 255, 255)          # box in the middle
    assert centre.getpixel((1550, 860)) == (255, 255, 255)         # not in the corner
    corner = wallpaper.add_label(base, "Title — Artist · Museum", pos=(1.0, 1.0))
    assert corner.getpixel((1560, 870)) != (255, 255, 255)         # clamped inside the edge
    assert wallpaper.label_pos({"x": 2, "y": -1}) == (1.0, 0.0)
    assert wallpaper.label_pos(None) == wallpaper.DEFAULT_LABEL_POS


def test_label_styles():
    PIL = pytest.importorskip("PIL.Image")
    assert wallpaper.label_style(None) == wallpaper.DEFAULT_LABEL_STYLE
    assert wallpaper.label_style({"look": "plaque", "size": "xxl"}) == {
        **wallpaper.DEFAULT_LABEL_STYLE, "look": "plaque"}             # unknown values fall back
    a = {"title": "The Harvesters", "maker": "Bruegel", "year": "1565", "museum": "The Met"}
    assert wallpaper.label_lines(a, "two") == ["The Harvesters", "Bruegel, 1565 · The Met"]
    assert wallpaper.label_lines(a, "title") == ["The Harvesters"]
    assert wallpaper.label_lines(a, "artist") == ["The Harvesters — Bruegel"]
    base = PIL.new("RGB", (1600, 900), (90, 120, 160))
    for look in wallpaper.LABEL_LOOKS:
        for text in wallpaper.LABEL_TEXTS:
            out = wallpaper.add_label(base, wallpaper.label_lines(a, text), pos=(0.5, 0.5),
                                      style={"look": look, "font": "serif", "text": text})
            assert out.size == base.size and out.tobytes() != base.tobytes()
    # a style change re-renders the stored file
    assert wallpaper._label_key(True, (0.5, 0.9), {"look": "dark"}) != \
        wallpaper._label_key(True, (0.5, 0.9), {"look": "light"})


def test_interleaved_union_is_stable_across_pages():
    from masterpiece.sources._ids import Stream, Union

    def make(prefix, total):
        def fetch(off):
            ids = [f"{prefix}{i}" for i in range(off, min(off + 3, total))]
            return ids, (off + 3 if off + 3 < total else None)
        return Stream(fetch, 0)

    u = Union([make("a", 9), make("b", 4)], interleave=True)
    first, more = u.slice(0, 4)
    second, _ = u.slice(4, 8)
    again, _ = u.slice(0, 4)
    assert first == ["a0", "b0", "a1", "b1"] and more
    assert again == first                         # earlier pages never reshuffle
    assert len(set(first + second)) == 8


def test_region_skips_museums_without_that_region(monkeypatch):
    from masterpiece import search as s
    calls = []

    class Euro:
        KEY, PAGE_SIZE, REGIONS = "euro", 2, {"europe"}

        @staticmethod
        def search(**kw):
            calls.append(kw)
            from masterpiece.models import Results
            return Results([], more=False)

    monkeypatch.setitem(s.SOURCES, "euro", Euro)
    r = s.search_all(["euro"], region="asia")
    assert calls == [] and r["skipped"] == ["euro"] and r["cursors"]["euro"] == 0


def test_met_keeps_islamic_paintings_but_not_papyri(monkeypatch):
    from masterpiece.sources import met
    monkeypatch.setattr(met, "_image_size", lambda url: (3000, 2000))
    base = {"objectID": 1, "isPublicDomain": True, "primaryImage": "https://images.metmuseum.org/x.jpg",
            "department": "Islamic Art", "title": "Siyavush", "artistDisplayName": ""}
    assert met._to_artwork({**base, "objectName": "Folio from an illustrated manuscript"})
    assert met._to_artwork({**base, "objectName": "Papyrus Fragment"}) is None
    assert met._to_artwork({**base, "objectName": "Painting", "isPublicDomain": False}) is None


def test_backup_restores_previous_wallpaper(tmp_path, monkeypatch):
    from masterpiece import backup, monitors, schedule
    old = tmp_path / "my-wallpaper.jpg"
    old.write_bytes(b"jpeg")
    ours = tmp_path / "current"
    ours.mkdir()
    snap = {"position": 4, "color": 0, "slideshow": None, "wallpapers": {"A": str(old)}}
    monkeypatch.setattr(monitors, "snapshot", lambda: snap)
    restored = []
    monkeypatch.setattr(monitors, "restore", lambda s, files: restored.append((s, files)))
    monkeypatch.setattr(schedule, "disable", lambda: None)

    assert backup.capture([ours]) is True
    # Masterpiece is now on the desktop: a second capture must keep the original
    monkeypatch.setattr(monitors, "snapshot", lambda: {**snap, "wallpapers": {"A": str(ours / "1.jpg")}})
    assert backup.capture([ours]) is False
    r = backup.restore()
    assert r["restored"] == "previous"
    s, files = restored[0]
    assert s["wallpapers"]["A"] == str(old) and open(files["A"], "rb").read() == b"jpeg"
    assert not backup.has_backup()


def test_collection_remove_and_thumbnail(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    from masterpiece import cache
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    PIL.new("RGB", (1600, 900), "navy").save(folder / "aic-1.jpg")
    cache.kv().set("art:aic-1.jpg", {"id": "aic-1", "title": "Night", "maker": "M", "museum": "AIC"})
    items = wallpaper.collection(folder)
    assert [(i["id"], i["title"], i["width"]) for i in items] == [("aic-1", "Night", 1600)]
    t = wallpaper.thumbnail(folder, "aic-1.jpg")
    assert t and PIL.open(t).size[0] == 480
    assert wallpaper.thumbnail(folder, "../secret.jpg") is None          # only our own files
    assert wallpaper.remove(folder, "aic-1.jpg") and not (folder / "aic-1.jpg").exists()


def test_show_now_puts_painting_on_matching_screen(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    for i in range(3):
        PIL.new("RGB", (1600, 900), "navy").save(folder / f"aic-{i}.jpg")
    PIL.new("RGB", (900, 1600), "olive").save(folder / "aic-tall.jpg")
    calls = []
    _fake_screens(monkeypatch, calls)
    wallpaper.show_next(folder, "each", label=False, force="aic-tall.jpg")
    _, mapping = calls[-1]
    assert PIL.open(mapping["B"]).getpixel((5, 5))[1] > 100          # olive one on the portrait screen
    assert {c["name"] for c in wallpaper.currently_shown()} >= {"aic-tall.jpg"}


def test_icon_renders():
    pytest.importorskip("PIL.Image")
    from masterpiece import desktop
    im = desktop.icon_image(64)
    assert im.size == (64, 64) and im.getpixel((32, 4))[3] == 255


def test_jps_keeps_only_public_domain_with_direct_images():
    from masterpiece.sources import jps
    ok = {"common": {"contentsRightsType": "pdm", "id": "x",
                     "contentsUrl": ["https://museumcollection.tokyo/a-L.jpg"]}}
    assert jps._candidate(ok)
    assert jps._candidate({"common": {**ok["common"], "contentsRightsType": "ccby"}}) is None
    assert jps._candidate({"common": {**ok["common"], "contentsUrl": ["https://x.jp/manifest.json"]}}) is None
    assert jps._clean_maker("歌川広重/画") == "歌川広重"


def test_task_xml_is_valid():
    import xml.etree.ElementTree as ET
    from masterpiece import schedule
    root = ET.fromstring(schedule.task_xml(60).replace('encoding="UTF-16"', ""))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:Repetition/t:Interval", ns).text == "PT60M"
    assert root.find(".//t:Exec/t:Arguments", ns).text == "-m masterpiece next"
    assert schedule.task_xml(1440).count("<Interval>P1D</Interval>") == 1


def test_roundtrip():
    a = art(100, 50)
    assert Artwork.from_dict(a.to_dict()) == a


def test_aic_mapping_caps_width():
    a = aic._to_artwork({"id": 5, "title": "X", "artist_title": None, "artist_display": "Ann\nDutch",
                         "date_display": "1650", "image_id": "abc", "is_public_domain": True,
                         "thumbnail": {"width": 6000, "height": 4000}})
    assert a.width == 3000 and a.height == 2000
    assert a.image_url.endswith("/abc/full/3000,/0/default.jpg")
    assert a.maker == "Ann"


def test_aic_skips_non_public_domain():
    assert aic._to_artwork({"id": 5, "image_id": "x", "is_public_domain": False,
                            "thumbnail": {"width": 10, "height": 10}}) is None


def test_cleveland_mapping():
    a = cleveland._to_artwork({
        "id": 1, "title": "Sea", "creation_date": "1900", "share_license_status": "CC0",
        "creators": [{"description": "Winslow Homer (American, 1836–1910)"}],
        "images": {"web": {"url": "https://openaccess-cdn.clevelandart.org/w.jpg", "width": "900", "height": "500"},
                   "print": {"url": "https://openaccess-cdn.clevelandart.org/p.jpg", "width": "3400", "height": "1900"}},
    })
    assert (a.maker, a.width, a.height) == ("Winslow Homer", 3400, 1900)
    assert a.preview_url.endswith("w.jpg")


def test_cleanup_only_touches_own_files(tmp_path: Path):
    for i in range(5):
        p = tmp_path / f"aic-{i}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (i, i))
    (tmp_path / "my-holiday.jpg").write_bytes(b"x")
    removed = wallpaper.cleanup(tmp_path, 2)
    assert sorted(p.name for p in removed) == ["aic-0.jpg", "aic-1.jpg", "aic-2.jpg"]
    assert (tmp_path / "my-holiday.jpg").exists()


def test_label_draws():
    PIL = pytest.importorskip("PIL.Image")
    img = PIL.new("RGB", (1600, 900), "white")
    out = wallpaper.add_label(img, "A very long title " * 20 + "— Someone · Museum")
    assert out.size == (1600, 900)
    assert out.getpixel((800, 837)) != (255, 255, 255)    # default: bottom-centre
    assert out.getpixel((60, 837)) == (255, 255, 255)     # truncated to ~60 % width


@pytest.mark.live
@pytest.mark.parametrize("key", list(SOURCES))
def test_live_search(key):
    from masterpiece.net import Blocked
    try:
        results = SOURCES[key].search(query="landscape")
    except (TimeoutError, Blocked) as e:
        pytest.skip(f"{key} is slow or limiting requests right now: {e}")
    assert results, f"{key} returned nothing"
    a = results[0]
    assert a.source == key and a.width > 0 and a.image_url.startswith("https://")


# ---------------------------------------------------------------- seasons, Curator, reports, Getty

def test_seasons():
    assert wallpaper.season_now(1) == "winter" and wallpaper.season_now(4) == "spring"
    assert wallpaper.season_now(7) == "summer" and wallpaper.season_now(10) == "autumn"
    assert wallpaper.season_weight("Skaters on a Frozen Canal", "winter") == 3.0
    assert wallpaper.season_weight("A Summer Day at the Beach", "winter") == 0.3
    assert wallpaper.season_weight("Portrait of a Lady", "winter") == 1.0
    assert wallpaper.seasons_of("Orchard in bloom") == {"spring"}


def test_cleanup_never_removes_favourites(tmp_path):
    import time as _t
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    for i in range(5):
        p = folder / f"aic-{i}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (_t.time() - 1000 + i, _t.time() - 1000 + i))      # aic-0 is the oldest
    removed = {p.name for p in wallpaper.cleanup(folder, 2, keep_ids=["aic-0"])}
    assert removed == {"aic-1.jpg", "aic-2.jpg"} and (folder / "aic-0.jpg").exists()


def test_curator_picks_new_paintings_with_reasons(tmp_path, monkeypatch):
    import random
    from masterpiece import cache, curator, settings
    folder = tmp_path / "Masterpiece"
    folder.mkdir()
    (folder / "aic-1.jpg").write_bytes(b"x")
    cache.kv().set("art:aic-1.jpg", {"id": "aic-1", "title": "Haystacks", "maker": "Claude Monet", "museum": "X"})
    settings.save({"folder": str(folder), "favourites": ["aic-1"], "enabledSources": ["aic", "nga"],
                   "mode": "curator", "curatorDaily": 3, "banned": [{"id": "nga-9"}]})
    monkeypatch.setattr(curator.monitors, "layout", lambda: {"monitors": [{"width": 1920, "height": 1080}], "span": None})
    searches = []

    def fake_search(keys, **kw):
        searches.append((tuple(keys), kw["query"], kw["subject"]))
        n = len(searches)
        return {"results": [art(3000, 2000, id="aic-1").to_dict(),                      # already have it
                            art(3000, 2000, id="nga-9").to_dict(),                      # hidden
                            art(3000, 2000, id=f"nga-{100 + n}").to_dict()]}
    monkeypatch.setattr(curator, "search_all", fake_search)
    def fake_download(a, folder, **kw):
        path = folder / f"{a.id}.jpg"
        path.write_bytes(b"y")
        return path
    monkeypatch.setattr(curator.wallpaper, "download", fake_download)

    added = curator.discover(rng=random.Random(4))
    assert len(added) == 3 and all(a["id"].startswith("nga-1") for a in added)
    assert all(a["reason"] for a in added) and len(searches) == 3
    assert set(curator.picks()) == {a["name"] for a in added}
    assert curator.due(settings.load())
    assert curator.run_if_due() is not None and not curator.due(settings.load())   # once a day


def test_curator_plan_uses_taste():
    import random
    from collections import Counter
    from masterpiece import curator
    plans = curator.plan({"seasons": True}, Counter({"Claude Monet": 5}), 40, random.Random(1))
    reasons = " | ".join(p["reason"] for p in plans)
    assert "Because you like Claude Monet" in reasons and "picked for you" in reasons
    assert any(p.get("surprise") for p in plans) and (" for " in reasons)          # season plans


def test_report_is_anonymous(monkeypatch):
    from masterpiece import report
    monkeypatch.setenv("USERNAME", "jandevries")
    monkeypatch.setenv("COMPUTERNAME", "DESKTOP-JAN")
    home = str(Path.home())
    pic = os.path.join(home, "Pictures", "x.jpg")
    text = report.anonymise(f"error in {pic} for jandevries (jan@example.com) on DESKTOP-JAN")
    assert home not in text and "jandevries" not in text and "jan@example.com" not in text and "DESKTOP-JAN" not in text
    url = report.issue_url("Problem", "**Last lines of the log**\n```\n" + "line\n" * 5000 + "```")
    assert url.startswith("https://github.com/") and len(url) < 8000


def test_getty_open_content_only():
    from masterpiece.sources import getty
    o = {"id": "https://data.getty.edu/museum/collection/object/abc", "_label": "Irises (90.PA.20)",
         "identified_by": [{"type": "Name", "content": "Irises"}],
         "produced_by": {"_label": "Production of Artwork by Vincent van Gogh",
                         "timespan": {"identified_by": [{"content": "1889"}], "begin_of_the_begin": "1889-01-01"}},
         "subject_of": [{"id": "https://www.getty.edu/art/collection/object/103JNH"}]}

    def man(rights, stmt):
        return {"rights": rights, "requiredStatement": {"value": {"en": [stmt]}},
                "items": [{"width": 9000, "height": 7000, "items": [{"items": [{"body": {
                    "service": [{"id": "https://media.getty.edu/iiif/image/xyz"}]}}]}]}]}
    a = getty._to_artwork(o, man("http://creativecommons.org/publicdomain/zero/1.0/",
                                 "Images provided here are believed to be in the public domain"))
    assert a and a.title == "Irises" and a.maker == "Vincent van Gogh" and a.width == 3840
    assert getty._to_artwork(o, man("http://rightsstatements.org/vocab/InC/1.0/", "")) is None
    late = {**o, "produced_by": {**o["produced_by"], "timespan": {"begin_of_the_begin": "1955-01-01"}}}
    assert getty._to_artwork(late, man("http://creativecommons.org/publicdomain/zero/1.0/", "public domain")) is None
    assert '"' not in getty._escape('a "quoted" word') and "\n" not in getty._escape("x\ny")
