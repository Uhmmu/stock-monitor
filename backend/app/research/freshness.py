from datetime import UTC, date, datetime

from .enums import FreshnessStatus
from .schemas import ResearchFreshness

FRESHNESS_RULES: dict[str, int | None] = {
    "capability_registry": None,
    "price_snapshot": 5 * 60,
    "market_indices": 2 * 60,
    "fx_rate": 30 * 60,
    "news": 6 * 60 * 60,
    "valuation_snapshot": 36 * 60 * 60,
    "technical_analysis": 24 * 60 * 60,
    "fred_rate": 24 * 60 * 60,
    "financial_statement": 120 * 24 * 60 * 60,
    "sec_filing": None,
    "portfolio_position": 10 * 60,
    "calendar_event": 24 * 60 * 60,
    "discovery_run": 7 * 24 * 60 * 60,
}


def aware(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def calculate_freshness(kind: str, as_of: datetime | date | None, reason: str) -> ResearchFreshness:
    timestamp = aware(as_of)
    ttl = FRESHNESS_RULES.get(kind)
    if timestamp is None:
        return ResearchFreshness(status=FreshnessStatus.unknown, reason=f"{reason}; data time unavailable")
    age = max(0, int((datetime.now(UTC) - timestamp).total_seconds()))
    if ttl is None:
        status = FreshnessStatus.fresh
    elif age <= ttl:
        status = FreshnessStatus.live if kind in {"price_snapshot", "market_indices"} and age <= ttl else FreshnessStatus.fresh
    elif age <= ttl * 2:
        status = FreshnessStatus.stale
    else:
        status = FreshnessStatus.expired
    return ResearchFreshness(as_of=timestamp, status=status, age_seconds=age, ttl_seconds=ttl, reason=reason)


def unknown_freshness(reason: str) -> ResearchFreshness:
    return ResearchFreshness(status=FreshnessStatus.unknown, reason=reason)
