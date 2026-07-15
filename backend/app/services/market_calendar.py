from datetime import UTC, datetime

import exchange_calendars as xcals
import pandas as pd


_calendar = xcals.get_calendar("XNYS", start="2000-01-01", end="2100-12-31")


def market_status(moment: datetime | None = None) -> dict:
    now = (moment or datetime.now(UTC)).astimezone(UTC)
    session_date = pd.Timestamp(now.date())
    session = None
    is_open = False
    if session_date in _calendar.schedule.index:
        schedule = _calendar.schedule.loc[session_date]
        session = str(now.date())
        is_open = bool(schedule["open"] <= pd.Timestamp(now) <= schedule["close"])
    return {"is_open": is_open, "session": session, "checked_at": now.isoformat()}
