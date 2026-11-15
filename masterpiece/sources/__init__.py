"""Source adapter registry.

Every adapter module exposes the same interface:

    KEY, NAME, LICENSE, HOMEPAGE, SUPPORTS_COLOR, IMAGE_HOSTS, PAGE_SIZE
    search(query="", page=1, color=None, top_only=False,
           subject=None, period=None, hide=()) -> Results   (a list[Artwork] with .more)

subject / period / hide keys are defined in content.py; an adapter maps them
onto its API as well as it can and ignores what it can't support.

To add a museum, create sources/<name>.py and add it to SOURCES below.
"""

from . import aic, cleveland, getty, jps, met, nga, rijks, smk, yale

SOURCES = {m.KEY: m for m in (aic, cleveland, getty, jps, met, nga, rijks, smk, yale)}


def describe() -> list[dict]:
    return [
        {"key": m.KEY, "name": m.NAME, "license": m.LICENSE,
         "homepage": m.HOMEPAGE, "supportsColor": m.SUPPORTS_COLOR,
         "regions": sorted(getattr(m, "REGIONS", ())), "note": getattr(m, "NOTE", "")}
        for m in SOURCES.values()
    ]


def image_hosts() -> set[str]:
    """Hosts the image proxy / downloader may fetch from (static + seen in results)."""
    hosts = {h for m in SOURCES.values() for h in m.IMAGE_HOSTS}
    for m in SOURCES.values():
        if hasattr(m, "extra_hosts"):
            hosts |= m.extra_hosts()
    return hosts
