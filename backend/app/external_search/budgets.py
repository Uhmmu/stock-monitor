from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ExternalSearchRun

from .enums import EFFORT_BASE_COST_USD, AgentRunStatus, DeepSearchEffort
from .exceptions import ExternalSearchError

SEARCH_REQUEST_ESTIMATE_USD = Decimal("0.007")


def estimated_effort_cost(effort: DeepSearchEffort) -> Decimal:
    return Decimal(str(EFFORT_BASE_COST_USD[effort]))


def _daily_search_key(user_id: int) -> str:
    return f"external-search:cost:{datetime.now(UTC).date().isoformat()}:user:{user_id}"


def enforce_search_budget(*, user_id: int) -> None:
    """Enforce provider-call cost guards; cache hits never call this function."""
    settings = get_settings()
    per_request = Decimal(str(min(max(settings.exa_max_cost_per_ai_request_usd, 0), 10)))
    if SEARCH_REQUEST_ESTIMATE_USD > per_request:
        raise ExternalSearchError("WEB_SEARCH_BUDGET_EXCEEDED", "External search exceeds the per-request budget.", status_code=402)
    daily = settings.exa_max_cost_per_user_day_usd
    if daily is None:
        return
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.25, socket_timeout=0.25)
        spent = Decimal(str(client.get(_daily_search_key(user_id)) or b"0", "utf-8"))
    except (redis.RedisError, OSError, ValueError, InvalidOperation, TypeError):
        # Normal Search retains the in-process per-answer call limit when Redis
        # is unavailable. Expensive High/X-High Agent runs are guarded in SQL.
        return
    if spent + SEARCH_REQUEST_ESTIMATE_USD > Decimal(str(max(daily, 0))):
        raise ExternalSearchError("WEB_SEARCH_BUDGET_EXCEEDED", "Daily external search budget has been reached.", status_code=402)


def record_search_cost(*, user_id: int, cost_usd: Decimal | None) -> None:
    if get_settings().exa_max_cost_per_user_day_usd is None:
        return
    amount = cost_usd if cost_usd is not None else SEARCH_REQUEST_ESTIMATE_USD
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.25, socket_timeout=0.25)
        key = _daily_search_key(user_id)
        pipe = client.pipeline(transaction=True)
        pipe.incrbyfloat(key, float(max(amount, Decimal(0))))
        pipe.expire(key, 172800)
        pipe.execute()
    except (redis.RedisError, OSError, ValueError, TypeError):
        return


def enforce_deep_budget(db: Session, *, user_id: int, effort: DeepSearchEffort) -> None:
    settings = get_settings()
    estimate = estimated_effort_cost(effort)
    if estimate > Decimal(str(min(max(settings.exa_max_cost_per_ai_request_usd, 0), 10))):
        raise ExternalSearchError("DEEP_SEARCH_BUDGET_EXCEEDED", "Selected Deep Search mode exceeds the per-request budget.", status_code=402)
    active = {AgentRunStatus.pending.value, AgentRunStatus.queued.value, AgentRunStatus.running.value}
    user_active = db.scalar(select(func.count(ExternalSearchRun.id)).where(ExternalSearchRun.user_id == user_id, ExternalSearchRun.status.in_(active))) or 0
    global_active = db.scalar(select(func.count(ExternalSearchRun.id)).where(ExternalSearchRun.status.in_(active))) or 0
    if user_active >= min(max(settings.exa_deep_max_active_runs_per_user, 1), 5):
        raise ExternalSearchError("DEEP_SEARCH_ALREADY_RUNNING", "A Deep Search run is already active for this user.", status_code=409)
    if global_active >= min(max(settings.exa_deep_max_active_runs_global, 1), 20):
        raise ExternalSearchError("DEEP_SEARCH_CONCURRENCY_LIMIT", "Deep Search concurrency is currently full.", status_code=429, retryable=True)
    today = datetime.now(UTC).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    actual = db.scalar(select(func.coalesce(func.sum(ExternalSearchRun.cost_usd), 0)).where(ExternalSearchRun.user_id == user_id, ExternalSearchRun.created_at >= start)) or 0
    daily = settings.exa_max_cost_per_user_day_usd
    if daily is not None and Decimal(str(actual)) + estimate > Decimal(str(max(daily, 0))):
        raise ExternalSearchError("DEEP_SEARCH_BUDGET_EXCEEDED", "Daily external research budget has been reached.", status_code=402)
    cap = settings.exa_deep_high_max_per_user_day if effort == DeepSearchEffort.high else settings.exa_deep_xhigh_max_per_user_day if effort == DeepSearchEffort.xhigh else None
    if cap is not None:
        count = db.scalar(select(func.count(ExternalSearchRun.id)).where(ExternalSearchRun.user_id == user_id, ExternalSearchRun.effort == effort.value, ExternalSearchRun.created_at >= start)) or 0
        if count >= max(cap, 0):
            raise ExternalSearchError("DEEP_SEARCH_BUDGET_EXCEEDED", "Daily Deep Search mode limit has been reached.", status_code=402)
