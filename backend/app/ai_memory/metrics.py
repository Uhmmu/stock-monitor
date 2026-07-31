from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any


class AIMemoryMetrics:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._totals: Counter[str] = Counter()
        self._samples: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, category: str, status: str) -> None:
        self.increment_by(category, status, 1)

    def increment_by(self, category: str, status: str, value: int) -> None:
        with self._lock:
            self._counts[f"{category}.{status}"] += value

    def observe(self, category: str, metric: str, value: float) -> None:
        key = f"{category}.{metric}"
        with self._lock:
            self._totals[key] += value
            self._samples[key] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = dict(self._counts)
            for key, total in self._totals.items():
                samples = self._samples[key]
                result[f"{key}.average"] = (
                    round(total / samples, 4) if samples else 0
                )
                result[f"{key}.samples"] = samples
            return result


ai_memory_metrics = AIMemoryMetrics()
