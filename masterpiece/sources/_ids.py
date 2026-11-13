"""Shared helper for museums whose search returns only object IDs (Rijksmuseum, The Met).

A *stream* is one search, paged lazily. A *union* concatenates several streams
(e.g. creator / title / description, or several departments), removes duplicates
and hands out stable slices, so page N always means the same IDs.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable


class Stream:
    """`fetch(state) -> (ids, next_state)`; next_state None = no more pages."""

    def __init__(self, fetch: Callable, first_state):
        self._fetch = fetch
        self.state = first_state
        self.ids: list[str] = []

    @property
    def done(self) -> bool:
        return self.state is None

    def fetch_page(self) -> None:
        ids, self.state = self._fetch(self.state)
        self.ids += [str(i) for i in ids]


class Union:
    """interleave=False: stream 1, then stream 2, … (e.g. creator matches before title matches)
    interleave=True:  round-robin across streams (e.g. mix Asian, Islamic and European art).
    In both modes earlier positions never move, so paging stays consistent."""

    def __init__(self, streams: list[Stream], interleave: bool = False):
        self.streams = streams
        self.interleave = interleave
        self.lock = threading.Lock()

    def _ordered(self):
        if not self.interleave:
            for s in self.streams:
                yield from s.ids
            return
        # Round-robin only up to where every unfinished stream has data, so later
        # page loads append instead of reshuffling what was already shown.
        live = [s for s in self.streams if not s.done]
        limit = min((len(s.ids) for s in live), default=None)
        for k in range(max((len(s.ids) for s in self.streams), default=0)):
            if limit is not None and k >= limit:
                break
            for s in self.streams:
                if k < len(s.ids):
                    yield s.ids[k]

    def _unique(self) -> list[str]:
        seen, out = set(), []
        for i in self._ordered():
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def _next_stream(self) -> Stream | None:
        live = [s for s in self.streams if not s.done]
        if not live:
            return None
        return min(live, key=lambda s: len(s.ids)) if self.interleave else live[0]

    def slice(self, start: int, end: int) -> tuple[list[str], bool]:
        with self.lock:
            ids = self._unique()
            while len(ids) < end:
                s = self._next_stream()
                if s is None:
                    break
                s.fetch_page()
                ids = self._unique()
            more = len(ids) > end or any(not s.done for s in self.streams)
            return ids[start:end], more


class UnionCache:
    """Keeps recent unions so paging continues where it left off."""

    def __init__(self, size: int = 64):
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.size = size

    def get(self, key: str, factory: Callable[[], Union]) -> Union:
        with self._lock:
            u = self._d.get(key)
            if u is None:
                u = self._d[key] = factory()
                while len(self._d) > self.size:
                    self._d.popitem(last=False)
            self._d.move_to_end(key)
            return u
