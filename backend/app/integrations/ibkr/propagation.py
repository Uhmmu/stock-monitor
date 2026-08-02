from __future__ import annotations

from datetime import UTC, datetime

import redis

from app.config import get_settings


def portfolio_generation(user_id: int) -> str:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=.25, socket_timeout=.25)
        value = client.get(f"portfolio-authority-generation:{user_id}")
        return value.decode() if value else "0"
    except (redis.RedisError, OSError, ValueError):
        return "0"


def invalidate_portfolio_consumers(user_id: int) -> dict:
    """Precisely bump caches whose payload contains private portfolio facts."""
    generation = datetime.now(UTC).isoformat()
    invalidated = ["portfolio-authority-generation"]
    warnings: list[str] = []
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=.5, socket_timeout=.5)
        client.set(f"portfolio-authority-generation:{user_id}", generation, ex=60 * 60 * 24 * 30)
    except (redis.RedisError, OSError, ValueError):
        warnings.append("Redis 组合缓存代次更新失败；数据库权威值已更新，API 直读不受影响")
    try:
        from app.ai_tools.cache import tool_cache
        tool_cache.clear_prefix(f"ai-tool:v1:user:{user_id}:")
        invalidated.append("ai-tool-private-cache")
    except Exception:
        warnings.append("当前进程 AI Tool 内存缓存失效失败")
    return {"generation": generation, "invalidated": invalidated, "warnings": warnings}
