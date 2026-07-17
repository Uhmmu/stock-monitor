from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.models import AppSetting
from app.services.alerting import _change, _event_key, _runtime_settings
from app.services.market_calendar import market_status


class _StubScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, _stmt):
        return _StubScalars(self._rows)


def test_runtime_settings_falls_back_to_config_defaults():
    defaults = get_settings()
    resolved = _runtime_settings(_StubDB([]))
    assert resolved["threshold_20m"] == defaults.default_threshold_20m
    assert resolved["threshold_1h"] == defaults.default_threshold_1h
    assert resolved["threshold_day"] == defaults.default_threshold_day


def test_runtime_settings_app_setting_overrides_defaults():
    rows = [
        AppSetting(key="threshold_20m", value="5"),
        AppSetting(key="threshold_1h", value="5"),
        AppSetting(key="threshold_day", value="5"),
    ]
    resolved = _runtime_settings(_StubDB(rows))
    assert resolved["threshold_20m"] == 5.0
    assert resolved["threshold_1h"] == 5.0
    assert resolved["threshold_day"] == 5.0


def test_runtime_settings_ignores_malformed_values():
    rows = [AppSetting(key="threshold_20m", value="not-a-number")]
    resolved = _runtime_settings(_StubDB(rows))
    assert resolved["threshold_20m"] == get_settings().default_threshold_20m


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
