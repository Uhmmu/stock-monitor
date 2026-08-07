from datetime import UTC, datetime, timedelta
import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import IntradayBar as IntradayBarRow, MarketMonitorEvent
from app.services.intraday_market import (
    aggregate_from_one_minute,
    evaluate_bar_events,
    intraday_summary,
    persist_intraday_bar,
)
from app.services.realtime_market.contracts import IntradayBar


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[IntradayBarRow.__table__, MarketMonitorEvent.__table__])
    return Session(engine)


def _bar(minute: int, price: float, *, volume: int = 100, vwap: float | None = None):
    return IntradayBar(
        symbol="MSFT", timestamp=datetime(2026, 8, 6, 14, minute, tzinfo=UTC),
        interval="1m", open=price, high=price + .2, low=price - .2,
        close=price + .1, volume=volume, vwap=vwap or price,
        trade_count=10, provider="alpaca", feed="iex", market_session="regular",
    )


def test_persist_bar_is_idempotent_and_aggregates_without_fake_volume():
    with _db() as db:
        first, created = persist_intraday_bar(db, _bar(30, 100))
        duplicate, duplicate_created = persist_intraday_bar(db, _bar(30, 100))
        assert created is True and duplicate_created is False and first.id == duplicate.id
        for minute in range(31, 35):
            persist_intraday_bar(db, _bar(minute, 100 + minute / 10))
        aggregated = aggregate_from_one_minute(
            db, "MSFT", "5m", datetime(2026, 8, 6, 14, 30, tzinfo=UTC),
            datetime(2026, 8, 6, 14, 35, tzinfo=UTC),
        )
        assert len(aggregated) == 1
        assert aggregated[0].volume == 500
        assert aggregated[0].is_partial is False


def test_monitor_event_cooldown_and_summary():
    with _db() as db:
        old, _ = persist_intraday_bar(db, _bar(30, 100, vwap=100.2))
        current, _ = persist_intraday_bar(db, _bar(31, 102, vwap=101.5))
        created = evaluate_bar_events(db, current)
        assert any(row.event_type == "rapid_move" for row in created)
        assert evaluate_bar_events(db, current) == []
        result = intraday_summary(db, "MSFT", now=current.timestamp + timedelta(minutes=1))
        assert result["available"] is True
        assert result["bar_count"] == 2
        assert result["providers"] == ["alpaca"]


def test_volume_spike_requires_real_same_session_baseline():
    with _db() as db:
        latest = None
        for minute in range(20):
            latest, _ = persist_intraday_bar(
                db, _bar(minute, 100 + minute / 100, volume=100 if minute >= 15 else 10),
            )
        events = evaluate_bar_events(db, latest)
        spike = next(row for row in events if row.event_type == "5m_volume_spike")
        assert spike.value >= 1.8
        assert spike.metadata_json["basis"] == "prior_same_session_windows"


def test_0049_migration_upgrade_and_downgrade_sqlite():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    spec = importlib.util.spec_from_file_location(
        "migration_0049", "backend/alembic/versions/0049_realtime_market_data.py",
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE price_snapshots (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE news_items (id INTEGER PRIMARY KEY)")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert {"intraday_bars", "market_monitor_events"} <= set(inspector.get_table_names())
        assert "feed" in {column["name"] for column in inspector.get_columns("price_snapshots")}
        assert "provider_metadata" in {column["name"] for column in inspector.get_columns("news_items")}
        migration.downgrade()
        inspector = sa.inspect(connection)
        assert "intraday_bars" not in inspector.get_table_names()
        assert "feed" not in {column["name"] for column in inspector.get_columns("price_snapshots")}
        assert "provider_metadata" not in {column["name"] for column in inspector.get_columns("news_items")}
