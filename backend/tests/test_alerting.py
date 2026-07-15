from datetime import UTC, datetime, timedelta

from app.services.alerting import _change, _event_key
from app.services.market_calendar import market_status


def test_change_percent():
    assert _change(105, 100) == 5
    assert _change(90, 100) == -10


def test_event_key_is_stable_inside_cooldown_bucket():
    moment = datetime(2026, 1, 1, 12, 5, tzinfo=UTC)
    assert _event_key("AAPL", "20m", moment, 60) == _event_key("AAPL", "20m", moment + timedelta(minutes=10), 60)


def test_event_key_changes_by_period():
    moment = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert _event_key("AAPL", "20m", moment, 60) != _event_key("AAPL", "1h", moment, 60)


def test_market_status_supports_future_dates():
    status = market_status(datetime(2026, 7, 14, 15, tzinfo=UTC))
    assert status["is_open"] is True
    assert status["session"] == "2026-07-14"
