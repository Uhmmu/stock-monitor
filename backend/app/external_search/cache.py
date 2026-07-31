from __future__ import annotations

import copy
import threading
import time
from typing import Any


class ExternalSearchCache:
    def __init__(self):
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires, value = item
            if expires <= time.monotonic():
                self._items.pop(key, None)
                return None
            return copy.deepcopy(value)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            if len(self._items) >= 1024:
                self._items.pop(next(iter(self._items)))
            self._items[key] = (time.monotonic() + ttl_seconds, copy.deepcopy(value))


external_search_cache = ExternalSearchCache()
