from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base
from app.models import (
    AppSetting,
    Investigation,
    PriceAlert,
    PriceSnapshot,
    User,
    UserPriceAlert,
    WatchlistItem,
)
from app.services.alerting import (
    _change,
    _event_key,
    _runtime_settings,
    evaluate_quote,
    evaluate_user_price_alerts,
)
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


def test_event_key_is_stable_within_market_day():
    # 同一美东交易日内不同时刻共享同一事件键 → 一天一家公司只触发一个异动。
    moment = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
    assert _event_key("AAPL", moment) == _event_key("AAPL", moment + timedelta(hours=3))


def test_event_key_changes_across_market_days():
    day_one = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
    day_two = day_one + timedelta(days=1)
    assert _event_key("AAPL", day_one) != _event_key("AAPL", day_two)


def test_event_key_is_ticker_scoped():
    moment = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
    assert _event_key("AAPL", moment) != _event_key("MSFT", moment)


def test_cross_provider_implausible_snapshot_without_previous_close_is_ignored():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    moment = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
    with Session(engine) as db:
        item = WatchlistItem(ticker="MSFT")
        baseline = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment - timedelta(minutes=20),
            price=100,
            source="yfinance",
        )
        current = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment,
            price=150,
            previous_close=None,
            source="alpaca",
            feed="iex",
            provider_role="realtime_market_data",
        )
        db.add_all([item, baseline, current])
        db.flush()

        assert evaluate_quote(db, item, current) == []
        assert db.scalars(select(PriceAlert)).all() == []
        assert db.scalars(select(Investigation)).all() == []


def test_same_provider_threshold_move_still_triggers():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    moment = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
    with Session(engine) as db:
        item = WatchlistItem(ticker="MSFT")
        baseline = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment - timedelta(minutes=20),
            price=100,
            source="yfinance",
        )
        current = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment,
            price=110,
            previous_close=None,
            source="yfinance",
        )
        db.add_all([item, baseline, current])
        db.flush()

        triggered = evaluate_quote(db, item, current)

        assert len(triggered) == 1
        assert triggered[0].period == "20m"
        assert triggered[0].change_percent == 10
        assert db.scalar(select(Investigation).where(Investigation.alert_id == triggered[0].id))


def test_large_cross_provider_move_is_allowed_with_recent_corroboration():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    moment = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
    with Session(engine) as db:
        item = WatchlistItem(ticker="MSFT")
        baseline = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment - timedelta(minutes=20),
            price=100,
            source="yfinance",
        )
        corroborating = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment - timedelta(minutes=2),
            price=150,
            source="tiingo",
        )
        current = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment,
            price=150,
            previous_close=None,
            source="alpaca",
            feed="iex",
            provider_role="realtime_market_data",
        )
        db.add_all([item, baseline, corroborating, current])
        db.flush()

        triggered = evaluate_quote(db, item, current)

        assert len(triggered) == 1
        assert triggered[0].period == "20m"
        assert triggered[0].change_percent == 50


def test_source_native_previous_close_supports_legitimate_day_change():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    moment = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
    with Session(engine) as db:
        item = WatchlistItem(ticker="MSFT")
        current = PriceSnapshot(
            ticker="MSFT",
            quote_time=moment,
            price=150,
            previous_close=100,
            source="alpaca",
            feed="iex",
            provider_role="realtime_market_data",
        )
        db.add_all([item, current])
        db.flush()

        triggered = evaluate_quote(db, item, current)

        assert len(triggered) == 1
        assert triggered[0].period == "day"
        assert triggered[0].baseline_price == 100
        assert triggered[0].change_percent == 50


def test_market_status_supports_future_dates():
    status = market_status(datetime(2026, 7, 14, 15, tzinfo=UTC))
    assert status["is_open"] is True
    assert status["session"] == "2026-07-14"


def test_user_price_alert_uses_existing_alert_and_investigation_pipeline():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            username="price-target-user",
            password_hash="test",
            role="user",
            status="active",
        )
        db.add(user)
        db.flush()
        target = UserPriceAlert(
            user_id=user.id,
            ticker="AAPL",
            target_price=150,
            direction="above",
        )
        current = PriceSnapshot(
            ticker="AAPL",
            quote_time=datetime(2026, 7, 14, 15, tzinfo=UTC),
            price=151,
            previous_close=149,
            source="test",
        )
        db.add_all([target, current])
        db.flush()

        triggered = evaluate_user_price_alerts(db, current)
        assert len(triggered) == 1
        assert triggered[0].period == "price_target"
        assert target.enabled is False
        assert target.triggered_at == current.quote_time
        assert db.scalar(
            select(Investigation).where(
                Investigation.alert_id == triggered[0].id
            )
        )

        assert evaluate_user_price_alerts(db, current) == []
        assert len(db.scalars(select(PriceAlert)).all()) == 1
