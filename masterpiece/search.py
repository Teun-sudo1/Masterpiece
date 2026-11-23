"""Search several sources in parallel and merge the results.

Our own filters (shape, resolution, hide) can reject a whole page of museum
results. So per source we keep fetching pages until enough paintings survive
the filters (or the museum runs out), and hand the next page number back to
the client as a per-source cursor.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest

from . import cache, content, filters
from .models import Artwork, Results
from .net import Blocked, Unavailable
from .sources import SOURCES

TARGET_PER_SOURCE = 12     # stop once this many results passed the filters…
MAX_PAGES_PER_CALL = 3     # …or after this many API pages per source
PAGE_TTL = 6 * cache.HOUR  # museum search results are reused for this long


def _page(mod, page: int, api_args: dict) -> Results:
    """One page of museum results, from the local cache when possible.
    Our own filters (shape, size, hide) run afterwards, so changing them is free."""
    key = f"page:{mod.KEY}:{page}:{json.dumps(api_args, sort_keys=True)}"
    hit = cache.kv().get(key, PAGE_TTL)
    if hit is not None:
        return Results([Artwork.from_dict(d) for d in hit["items"]], more=hit["more"])
    raw = mod.search(page=page, **api_args)
    more = getattr(raw, "more", len(raw) >= mod.PAGE_SIZE)
    cache.kv().set(key, {"items": [a.to_dict() for a in raw], "more": more})
    return Results(raw, more=more)


def _collect(mod, start_page: int, api_args: dict, filter_args: dict, seen: set[str],
             max_pages: int = MAX_PAGES_PER_CALL) -> dict:
    found, page, more, scanned = [], start_page, True, 0
    while more and len(found) < TARGET_PER_SOURCE and page < start_page + max_pages:
        raw = _page(mod, page, api_args)
        page += 1
        more = raw.more
        scanned += len(raw)
        for a in filters.apply(raw, **filter_args):
            if a.id not in seen:
                seen.add(a.id)
                found.append(a)
    return {"found": found, "next": page, "more": more, "scanned": scanned}


def search_all(source_keys: list[str], *, cursors: dict[str, int] | None = None,
               query: str = "", color: str | None = None, top_only: bool = False,
               subject: str | None = None, period: str | None = None, hide=(),
               region: str | None = None,
               min_width: int = 0, orientation: str = "any",
               targets: list[tuple[int, int]] | None = None, sharp: bool = False,
               max_pages: int = MAX_PAGES_PER_CALL) -> dict:
    cursors = cursors or {}
    keys = [k for k in source_keys if k in SOURCES and cursors.get(k, 1) > 0]
    # Several regions can be chosen. A museum with (almost) nothing from any of them is skipped;
    # the others get only the chosen regions they have (none at all = no filter needed).
    chosen = content.regions_of(region)
    per_region: dict[str, str | None] = {}
    skipped = []
    for k in keys:
        has = set(getattr(SOURCES[k], "REGIONS", ()))
        if not chosen:
            per_region[k] = None
        elif not chosen & has:
            skipped.append(k)
        else:
            per_region[k] = None if has <= chosen else ",".join(sorted(chosen & has))
    keys = [k for k in keys if k not in skipped]
    api_args = dict(query=query, color=color, top_only=top_only,
                    subject=subject, period=period, hide=tuple(hide))

    def args_for(k: str) -> dict:
        return {**api_args, "region": per_region[k]} if per_region.get(k) else api_args
    filter_args = dict(min_width=min_width, orientation=orientation,
                       targets=targets, sharp=sharp, hide=tuple(hide))

    per_source: dict[str, list] = {}
    errors: dict[str, str] = {}
    new_cursors: dict[str, int] = {}   # 0 = this source has nothing more
    scanned = 0

    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as ex:
        futures = {k: ex.submit(_collect, SOURCES[k], cursors.get(k, 1), args_for(k), filter_args, set(), max_pages)
                   for k in keys}
        for k, fut in futures.items():
            try:
                r = fut.result()
            except Exception as e:  # one failing museum must not break the others
                if isinstance(e, TimeoutError) or "timed out" in str(e):
                    errors[k] = "is responding very slowly right now. “Load more” tries again."
                elif isinstance(e, Unavailable):
                    errors[k] = "isn't available right now: its website only lets web browsers in. Masterpiece tries again later."
                elif isinstance(e, Blocked):
                    errors[k] = "is limiting requests right now. Try again in a few minutes."
                else:
                    errors[k] = f"failed: {type(e).__name__}: {e}"
                new_cursors[k] = cursors.get(k, 1)   # retry the same page next time
                continue
            per_source[k] = r["found"]
            new_cursors[k] = r["next"] if r["more"] else 0
            scanned += r["scanned"]

    # Interleave so every museum is represented at the top of the grid
    merged = [a for group in zip_longest(*per_source.values()) for a in group if a]
    for k in skipped:
        new_cursors[k] = 0
    return {
        "results": [a.to_dict() for a in merged],
        "errors": errors,
        "cursors": new_cursors,
        "scanned": scanned,
        "skipped": skipped,
    }
