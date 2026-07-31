from __future__ import annotations

from collections import Counter
from threading import Lock


class ExternalSearchMetrics:
    def __init__(self):
        self._counts = Counter()
        self._lock = Lock()

    def record(self, kind: str, status: str, *, effort: str | None = None, cache_hit: bool = False) -> None:
        with self._lock:
            self._counts[(kind, status)] += 1
            if effort: self._counts[("effort", effort)] += 1
            if cache_hit: self._counts[(kind, "cache_hit")] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {f"{kind}.{status}": value for (kind, status), value in sorted(self._counts.items())}


external_search_metrics = ExternalSearchMetrics()
