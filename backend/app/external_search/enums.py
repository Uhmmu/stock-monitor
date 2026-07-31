from enum import StrEnum


class WebAccessMode(StrEnum):
    off = "off"
    search = "search"
    deep_minimal = "deep_minimal"
    deep_low = "deep_low"
    deep_medium = "deep_medium"
    deep_high = "deep_high"
    deep_xhigh = "deep_xhigh"

    @property
    def is_deep(self) -> bool:
        return self.value.startswith("deep_")

    @property
    def effort(self) -> "DeepSearchEffort | None":
        return DeepSearchEffort(self.value.removeprefix("deep_")) if self.is_deep else None


class DeepSearchEffort(StrEnum):
    minimal = "minimal"
    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"


class SearchType(StrEnum):
    auto = "auto"
    fast = "fast"
    instant = "instant"
    deep_lite = "deep-lite"
    deep = "deep"
    deep_reasoning = "deep-reasoning"


class SearchFreshness(StrEnum):
    balanced = "balanced"
    fresh = "fresh"
    live = "live"
    cached = "cached"


class AgentRunStatus(StrEnum):
    pending = "pending"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_RUN_STATUSES = {AgentRunStatus.completed, AgentRunStatus.failed, AgentRunStatus.cancelled}


EFFORT_BASE_COST_USD = {
    DeepSearchEffort.minimal: 0.012,
    DeepSearchEffort.low: 0.025,
    DeepSearchEffort.medium: 0.10,
    DeepSearchEffort.high: 0.50,
    DeepSearchEffort.xhigh: 1.00,
}
