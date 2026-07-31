from __future__ import annotations

from collections import Counter
from threading import Lock


class RichContentMetrics:
    """Small process-local counters for debug/health inspection.

    Production logging remains the durable telemetry path; this object avoids
    adding a monitoring dependency and deliberately stores counts only.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Counter[str] = Counter()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_composition(
        self,
        *,
        candidate_count: int,
        used_count: int,
        invalid_count: int,
        duplicate_count: int,
        auto_inserted_count: int,
        duration_ms: int,
    ) -> None:
        with self._lock:
            self._counters.update(
                {
                    "compositions": 1,
                    "candidate_blocks": candidate_count,
                    "used_blocks": used_count,
                    "invalid_placeholders": invalid_count,
                    "duplicate_placeholders": duplicate_count,
                    "auto_inserted_blocks": auto_inserted_count,
                    "composition_duration_ms": duration_ms,
                }
            )

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)


rich_content_metrics = RichContentMetrics()
