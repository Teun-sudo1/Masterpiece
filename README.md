# Masterpiece

**Public-domain paintings as your Windows wallpaper**

Masterpiece searches the open-access collections of great museums, fits the paintings to
each of your screens, and changes them as often as you like. Or let the **Curator** choose:
every day it adds a few new paintings that suit your taste.

![Masterpiece screenshot](docs/screenshot.png)

> **Not an official app.** Masterpiece is an independent open-source project. It is not
> made, endorsed or supported by any of the museums whose public APIs it uses.

## Four tabs

A bar along the bottom of every tab shows whether the rotation runs, with ◀ previous, pause, ▶ next,
**Restore my wallpaper**, and a switch between *Curator chooses* and *My collection*.

**Search art** — search ten sources at once. The filter panel on the left (collapsible) has
museums, a clickable world map (choose one or more regions), subject, period, colour, highlights, shape ("fits my screens", "spans all
my screens", portrait, panorama…), resolution ("sharp on my screens") and *hide* religious scenes /
nudes / death & war. Click a painting for a large preview; select with **+** and press
**Add to collection** in the bar that appears. New additions come first in the rotation.

**My collection** — your paintings, with their own filters (favourites, the Curator's picks, on
screen now, subject, period, shape, museum) and ordering. **♥ Favourite** paintings come up about
three times as often and are never cleaned up. *Show now*, *Skip* (remove it and show another on
that screen), *Remove* or *Never* (never show it in results again; undo under "Hidden paintings").
Click a painting for its info card with the museum's description or facts.

**Curator** — the control centre for your desktop:
- what's on each screen now (**Restore my wallpaper** in the bottom bar puts back exactly what you
  had before, including the lock screen);
- *what to show*: **Curator chooses** (new paintings every day, plus your collection) or
  **My collection** only;
- change every 10 minutes … once a day (or any interval), screens (a matching painting per screen,
  the same on all, or one spanned across all), the **label** (dark/light box, museum plaque, shadow,
  subtle; sans or serif; three sizes; drag it anywhere on a preview of your screens), *match time of
  day*, *follow the seasons*, and the **lock screen**;
- **your taste**: sliders from *never* to *a lot* for subjects, periods, regions and museums, the
  artists you like (from your collection and favourites), and how often you want to be surprised.
  Each pick says why it was chosen ("Because you like Claude Monet", "A winter scene for December").

The first time you open Masterpiece a short **tour** shows you around; after an update it shows only
what's new (Settings → *Take the tour* plays it all again).

**Settings** — dark or light look (or as Windows), how many paintings to keep, start with Windows, updates (*install automatically*
while you're away), storage (what takes how much space, *Free up space*), the guide, and a problem
report (anonymised, opened as a pre-filled GitHub issue).

The rotation runs as a per-user Windows scheduled task (`Masterpiece.exe next`), so it keeps going
when the app is closed. Each screen gets a painting of matching shape, rendered at its exact
resolution so the label stays sharp and visible. Only public-domain / open-access works are shown,
and Masterpiece is gentle on the museums' servers: search pages are cached for 6 hours, images and
object data on disk, a few requests per museum at a time, nothing is downloaded twice.

## Install & run

Requires Windows 10/11 and Python 3.10+.

```powershell
git clone <repo-url> masterpiece
cd masterpiece
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m masterpiece install  # Start-menu + desktop shortcut "Masterpiece"
python -m masterpiece          # opens http://127.0.0.1:8765 and a tray icon
```

After `install`, just double-click **Masterpiece**. It opens in its own app window (Edge
WebView2, built into Windows 11; without it Masterpiece uses your browser) and puts an icon next to
the clock. Closing the window keeps Masterpiece running in the tray. Tray menu: *Next painting*, *Skip*,
*On screen now* (info card, favourite, skip, museum page), *Ask the Curator now*, *Pause rotation*,
*Restore my wallpaper*, *Start with Windows*, *Report a problem* and *Quit*. Starting it again while it runs
simply opens the app.

### As a Windows program (Setup.exe)

```powershell
pip install -e .[build]
winget install JRSoftware.InnoSetup
python packaging\build.py --setup   # -> dist\Masterpiece-Setup-<version>.exe (≈17 MB, no Python needed)
```

The setup installs for the current user only (no admin rights) into
`%LOCALAPPDATA%\Programs\Masterpiece`, with a Start-menu entry, an optional desktop shortcut
and optional *Start with Windows*. Running a newer setup updates in place and keeps a running
rotation pointing at the new version. Uninstall via Windows Settings → Apps: it stops the
rotation, puts your previous wallpaper back and removes the shortcuts; your paintings and
settings are kept.

### Releasing an update

Installed copies check this repository's GitHub Releases (`UPDATE_REPO` in
`masterpiece/__init__.py`) about once a day and offer *Install now*. To publish one:

1. Raise `__version__` in `masterpiece/__init__.py` (and `version` in `pyproject.toml`).
2. `python packaging\build.py --setup`
3. On GitHub: *Releases → Draft a new release*, tag `v<version>`, write what's new, and attach
   `dist\Masterpiece-Setup-<version>.exe` and its `.sha256` file. Publish.

The app only installs a Setup whose SHA-256 matches the checksum GitHub publishes for it
(or the `.sha256` file), downloaded over HTTPS from GitHub. Drafts and pre-releases are ignored.

Neither file is code-signed, so Windows shows "Windows protected your PC" the first time:
*More info → Run anyway*. The same commands work with the .exe (`Masterpiece.exe next`, `stop`, …).

Other commands:

```powershell
python -m masterpiece serve --port 9000 --no-browser
python -m masterpiece daily     # set a random downloaded painting as wallpaper
```

Settings are stored in `%APPDATA%\Masterpiece\settings.json` (never in the repo).

## Sources & licences

| Museum | API | Key | Licence of images used |
|---|---|---|---|
| [Art Institute of Chicago](https://www.artic.edu/open-access) | [api.artic.edu](https://api.artic.edu/docs/) | none | CC0 (public-domain works only) |
| [Cleveland Museum of Art](https://www.clevelandart.org/open-access) | [openaccess-api.clevelandart.org](https://openaccess-api.clevelandart.org/) | none | CC0 |
| [Rijksmuseum](https://www.rijksmuseum.nl/) | [data.rijksmuseum.nl](https://data.rijksmuseum.nl/) | none | Public Domain Mark / CC0 |
| [SMK – National Gallery of Denmark](https://open.smk.dk/) | [api.smk.dk](https://api.smk.dk/api/v1/) | none | Public Domain Mark |
| [The Metropolitan Museum of Art](https://www.metmuseum.org/hubs/open-access) | [collectionapi.metmuseum.org](https://metmuseum.github.io/) | none | CC0 (Open Access) |
| [Japan Search](https://jpsearch.go.jp/) (Tokyo Museum Collection and others) | jpsearch.go.jp/api | none | Public Domain Mark only; images ≈1000 px |
| [National Gallery of Art, Washington](https://www.nga.gov/open-access-images.html) | [open data on GitHub](https://github.com/NationalGalleryOfArt/opendata) (no search API: a local index of ≈2900 paintings ships with the app, `packaging/nga_index.py`) | none | CC0 (open-access images) |
| [Wikidata](https://www.wikidata.org/) + [Wikimedia Commons](https://commons.wikimedia.org/) — Latin America, Oceania, Africa & Russia | SPARQL at build time (`packaging/wikidata_index.py`); a local index ships with the app | none | Painters who died before 1925; only images Commons marks as public domain / CC0 |
| [J. Paul Getty Museum](https://www.getty.edu/projects/open-content-program/) | [Linked Art + SPARQL](https://data.getty.edu/museum/collection/docs/) | none | Getty Open Content (CC0), only works the manifest marks as public domain, made before 1930 |
| [Yale Center for British Art](https://britishart.yale.edu/) & [Yale University Art Gallery](https://artgallery.yale.edu/) | [LUX](https://lux.collections.yale.edu/) (Linked Art) + IIIF manifests | none | Only works marked "Copyright Statement: Public domain" |

The **Region** filter (Europe, Russia, North America, Latin America, Africa, East & South Asia,
Middle East & Islamic world, Oceania) works across museums, and you can combine regions; the Met adds Chinese & Japanese paintings, Japanese woodblock prints
and Persian/Mughal manuscript paintings. Museums with little from a region are skipped.

Planned: Europeana and Paris Musées (both need a free personal key, which would be entered in
the app and never stored in the repository).

Local data: settings in `%APPDATA%\Masterpiece`, cache / originals / current renders in
`%LOCALAPPDATA%\Masterpiece` (safe to delete), paintings in `Pictures\Masterpiece`.

Artwork metadata is provided by the museums under their own terms (mostly CC0; AIC
descriptions are CC BY 4.0). Please credit the museum when you share an image.

## How it works

```
masterpiece/
  sources/        one adapter per museum, same interface:
                  search(query, page, color, top_only, subject, period, hide) -> list[Artwork]
  models.py       shared Artwork format
  content.py      subject / period / hide definitions, mapped per source
  filters.py      source-independent filters (size, shape, screens, hide)
  monitors.py     monitor layout + per-monitor wallpaper (IDesktopWallpaper)
  search.py       queries enabled sources in parallel and interleaves results
  wallpaper.py    download, label (Pillow), clean up, set wallpaper (Win32)
  server.py       small local web server (127.0.0.1 only) + image proxy
  web/            the UI (vanilla HTML/CSS/JS)
```

Adding a museum = one new file in `masterpiece/sources/` plus one line in
`sources/__init__.py`.

## Development

```powershell
pip install -e .[dev]
pytest -m "not live"   # offline tests
pytest                 # including live API tests
```

New features get a tour step in `masterpiece/web/tour.js` (`since` = the version that adds them).
`tests/test_tour.py` plays the whole tour in a headless Edge and fails if a spotlight misses its target.
After a redesign, `python packaging\screenshot.py` remakes `docs/screenshot.png` (the picture at the top),
with temporary settings, so it never shows your own collection.

## Licence

[MIT](LICENSE)
