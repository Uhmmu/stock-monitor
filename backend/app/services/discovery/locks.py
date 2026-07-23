from __future__ import annotations

from contextlib import contextmanager

import redis

from app.config import get_settings


@contextmanager
def discovery_lock(user_id: int, *, timeout: int = 900):
    """Cross-worker lock; DB idempotency remains the second line of defense."""
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)
        lock = client.lock(f"stock-discovery:user:{user_id}", timeout=timeout, blocking_timeout=0)
        acquired = bool(lock.acquire(blocking=False))
    except redis.RedisError:
        # An unavailable lock service must not fabricate exclusivity. A nullable
        # result tells the caller to use the database row lock fallback.
        yield None
        return
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.RedisError:
                pass
