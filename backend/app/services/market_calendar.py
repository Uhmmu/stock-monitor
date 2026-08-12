from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


_calendar = xcals.get_calendar("XNYS", start="2000-01-01", end="2100-12-31")
_MARKET_TIMEZONE = ZoneInfo("America/New_York")


def market_status(moment: datetime | None = None) -> dict:
    now = (moment or datetime.now(UTC)).astimezone(UTC)
    market_date = now.astimezone(_MARKET_TIMEZONE).date()
    session_date = pd.Timestamp(market_date)
    session = None
    is_open = False
    if session_date in _calendar.schedule.index:
        schedule = _calendar.schedule.loc[session_date]
        session = str(market_date)
        is_open = bool(schedule["open"] <= pd.Timestamp(now) <= schedule["close"])
    return {"is_open": is_open, "session": session, "checked_at": now.isoformat()}


def expected_latest_market_session(moment: datetime | None = None):
    """Most recent NYSE session whose regular close has completed."""
    now = pd.Timestamp((moment or datetime.now(UTC)).astimezone(UTC))
    position = _calendar.schedule["close"].searchsorted(now, side="right") - 1
    return _calendar.schedule.index[position].date() if position >= 0 else None


def market_data_collection_status(moment: datetime | None = None) -> dict:
    """US quote collection window including Yahoo pre/post-market sessions."""
    now = (moment or datetime.now(UTC)).astimezone(UTC)
    market_date = now.astimezone(_MARKET_TIMEZONE).date()
    session_date = pd.Timestamp(market_date)
    phase = "closed"
    if session_date in _calendar.schedule.index:
        schedule = _calendar.schedule.loc[session_date]
        open_time, close_time = pd.Timestamp(schedule["open"]), pd.Timestamp(schedule["close"])
        now_time = pd.Timestamp(now)
        pre_start = open_time - timedelta(hours=5, minutes=30)
        post_end = close_time + timedelta(hours=4)
        if pre_start <= now_time < open_time:
            phase = "pre_market"
        elif open_time <= now_time <= close_time:
            phase = "regular"
        elif close_time < now_time <= post_end:
            phase = "after_hours"
    return {
        "is_collecting": phase != "closed",
        "market_session": phase,
        "checked_at": now.isoformat(),
    }
