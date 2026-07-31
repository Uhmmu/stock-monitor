from __future__ import annotations

from collections import Counter
from threading import Lock


class AIMetrics:
    def __init__(self) -> None:
        self._lock = Lock(); self.counts = Counter(); self.duration_ms: list[int] = []

    def record(self, *, status: str, model: str, duration_ms: int, model_rounds: int = 0, tool_calls: int = 0, tool_names: list[str] | None = None, invalid_citations: int = 0, repaired: bool = False, error_code: str | None = None) -> None:
        with self._lock:
            self.counts[("request", status)] += 1; self.counts[("model", model)] += 1
            self.counts[("model_rounds", "total")] += model_rounds; self.counts[("tool_calls", "total")] += tool_calls
            self.counts[("provider_requests", "total")] += model_rounds
            for tool_name in tool_names or []:
                self.counts[("tool", tool_name)] += 1
            self.counts[("citation_invalid", "total")] += invalid_citations
            if repaired: self.counts[("citation_repair", "total")] += 1
            if error_code: self.counts[("error", error_code)] += 1
            self.duration_ms.append(duration_ms)
            if len(self.duration_ms) > 1000: del self.duration_ms[:-1000]

    def snapshot(self) -> dict:
        with self._lock:
            requests = sum(value for (kind, _), value in self.counts.items() if kind == "request")
            return {
                "requests": requests,
                "status": {name: value for (kind, name), value in self.counts.items() if kind == "request"},
                "models": {name: value for (kind, name), value in self.counts.items() if kind == "model"},
                "tools": {name: value for (kind, name), value in self.counts.items() if kind == "tool"},
                "errors": {name: value for (kind, name), value in self.counts.items() if kind == "error"},
                "provider_requests": self.counts[("provider_requests", "total")],
                "average_duration_ms": sum(self.duration_ms) / len(self.duration_ms) if self.duration_ms else None,
                "average_model_rounds": self.counts[("model_rounds", "total")] / requests if requests else None,
                "average_tool_calls": self.counts[("tool_calls", "total")] / requests if requests else None,
                "invalid_citations": self.counts[("citation_invalid", "total")],
                "citation_repairs": self.counts[("citation_repair", "total")],
            }


ai_metrics = AIMetrics()
