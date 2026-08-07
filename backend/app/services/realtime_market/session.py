"""US equity trading-session and freshness helpers.

Session decisions are made from UTC instants and the XNYS calendar, never from
the host/container timezone.  The public values use ``premarket`` and
``afterhours``; aliases used by the existing price_snapshot layer are accepted
at boundaries and normalized by :func:`canonical_session`.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import MarketSession, RealtimeQuote, ensure_utc, normalize_market_session


def canonical_session(value: str | MarketSession | None) -> str:
    return normalize_market_session(value)


def _calendar_schedule(moment: datetime) -> Any | None:
    """Return the XNYS schedule row for the local trading date if available."""

    try:
        import exchange_calendars as xcals
        import pandas as pd

        calendar = xcals.get_calendar("XNYS")
        local_date = moment.astimezone(ZoneInfo("America/New_York")).date()
        index = pd.Timestamp(local_date)
        if index not in calendar.schedule.index:
            # The calendar object may be bounded in tests/deployments.  Ask for
            # a short range only when the date is outside its initial index.
            calendar = xcals.get_calendar("XNYS", start="2000-01-01", end="2100-12-31")
        if index not in calendar.schedule.index:
            return None
        return calendar.schedule.loc[index]
    except Exception:
        return None


def market_session_at(moment: datetime | None = None, *, timezone: str = "America/New_York") -> str:
    """Classify a UTC instant as premarket, regular, afterhours, or closed.

    Premarket starts at 04:00 local and afterhours ends at 20:00 local, which
    matches the project's Yahoo collection window.  On holidays and weekends
    the result is ``closed`` even if the wall-clock time is within those hours.
    """

    current = ensure_utc(moment)
    try:
        local = current.astimezone(ZoneInfo(timezone))
    except Exception:
        local = current.astimezone(ZoneInfo("America/New_York"))

    schedule = _calendar_schedule(current)
    if schedule is not None:
        try:
            open_at = ensure_utc(schedule["open"].to_pydatetime())
            close_at = ensure_utc(schedule["close"].to_pydatetime())
            pre_start = open_at - timedelta(hours=5, minutes=30)
            after_end = close_at + timedelta(hours=4)
            if pre_start <= current < open_at:
                return MarketSession.PREMARKET.value
            if open_at <= current <= close_at:
                return MarketSession.REGULAR.value
            if close_at < current <= after_end:
                return MarketSession.AFTERHOURS.value
            return MarketSession.CLOSED.value
        except (KeyError, TypeError, ValueError):
            pass

    # Deterministic fallback for environments without exchange_calendars.  Do
    # not call this a trading day on weekends; holidays remain best effort.
    if local.weekday() >= 5:
        return MarketSession.CLOSED.value
    current_time = local.timetz().replace(tzinfo=None)
    if time(4, 0) <= current_time < time(9, 30):
        return MarketSession.PREMARKET.value
    if time(9, 30) <= current_time <= time(16, 0):
        return MarketSession.REGULAR.value
    if time(16, 0) < current_time <= time(20, 0):
        return MarketSession.AFTERHOURS.value
    return MarketSession.CLOSED.value


def is_market_open(moment: datetime | None = None) -> bool:
    return market_session_at(moment) == MarketSession.REGULAR.value


def quote_age_seconds(quote: RealtimeQuote, now: datetime | None = None) -> float:
    current = ensure_utc(now)
    return max(0.0, (current - ensure_utc(quote.received_at)).total_seconds())


def provider_timestamp_age_seconds(quote: RealtimeQuote, now: datetime | None = None) -> float:
    current = ensure_utc(now)
    return max(0.0, (current - ensure_utc(quote.timestamp)).total_seconds())


def is_quote_stale(
    quote: RealtimeQuote | None,
    *,
    now: datetime | None = None,
    max_age_seconds: float = 30.0,
    include_provider_timestamp: bool = False,
) -> bool:
    if quote is None:
        return True
    age = quote_age_seconds(quote, now)
    if include_provider_timestamp:
        age = max(age, provider_timestamp_age_seconds(quote, now))
    return age > max(0.0, float(max_age_seconds))


def stale_after(moment: datetime, seconds: float, *, now: datetime | None = None) -> bool:
    current = ensure_utc(now)
    return (current - ensure_utc(moment)).total_seconds() > max(0.0, seconds)


def session_metadata(moment: datetime | None = None) -> dict[str, Any]:
    current = ensure_utc(moment)
    session = market_session_at(current)
    return {
        "market_session": session,
        "is_open": session == MarketSession.REGULAR.value,
        "checked_at": current.isoformat(),
    }
