from __future__ import annotations

import time
from collections import OrderedDict
from copy import deepcopy

from .schemas import ToolExecutionResult


class BoundedTTLCache:
    """Small optional optimization fallback; never an authority or freshness source."""
    def __init__(self, capacity: int = 256):
        self.capacity = min(max(capacity, 1), 1024)
        self._values: OrderedDict[str, tuple[float, ToolExecutionResult]] = OrderedDict()

    def get(self, key: str) -> ToolExecutionResult | None:
        row = self._values.get(key)
        if not row: return None
        expires, value = row
        if expires <= time.monotonic(): self._values.pop(key, None); return None
        self._values.move_to_end(key)
        return deepcopy(value)

    def set(self, key: str, value: ToolExecutionResult, ttl: int) -> None:
        self._values[key] = (time.monotonic() + min(max(ttl, 1), 600), deepcopy(value))
        self._values.move_to_end(key)
        while len(self._values) > self.capacity: self._values.popitem(last=False)

    def clear_prefix(self, prefix: str) -> int:
        keys = [key for key in self._values if key.startswith(prefix)]
        for key in keys:
            self._values.pop(key, None)
        return len(keys)


tool_cache = BoundedTTLCache()
