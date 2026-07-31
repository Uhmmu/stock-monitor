from datetime import UTC, date, datetime, timedelta
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.auth import create_token
from app.database import Base, get_db
from app.models import PriceSnapshot, Security, StockGroup, User, WatchlistItem
from app.services.market_data import LiveQuote
from app.services.market_calendar import market_data_collection_status
from app.services.price_snapshots import (
    PriceSnapshotInput,
    build_ai_price_snapshot_context,
    fetch_standardized_price_snapshot,
    get_latest_persisted_price_snapshot,
    normalize_finnhub_quote,
    normalize_yfinance_quote,
    persist_price_snapshot,
    price_snapshot_out,
    snapshot_freshness,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[PriceSnapshot.__table__])
    with Session(engine) as session:
        yield session


def yahoo_quote(**updates):
    values = {
        "ticker": "MSFT",
        "quote_time": datetime(2026, 7, 30, 19, 59, tzinfo=UTC),
        "retrieved_at": datetime(2026, 7, 30, 20, 0, tzinfo=UTC),
        "trading_date": date(2026, 7, 30),
        "price": 105.0,
        "regular_market_price": 104.0,
        "previous_close": 100.0,
        "open": 101.0,
        "day_high": 106.0,
        "day_low": 99.0,
        "volume": 1_000,
        "currency": "USD",
        "exchange": "NasdaqGS",
        "average_volume_10d": 1_200.0,
        "average_volume_20d": 1_250.0,
        "market_status": "after_hours",
        "quote_session": "after_hours",
        "is_delayed": True,
        "delay_seconds": 900,
        "raw_payload": {"regularMarketPrice": 104.0},
    }
    values.update(updates)
    return LiveQuote(**values)


def candidate(**updates):
    values = {
        "symbol": "MSFT",
        "provider": "yfinance",
        "provider_symbol": "MSFT",
        "last_price": 105.0,
        "fetched_at": datetime(2026, 7, 30, 20, 0, tzinfo=UTC),
        "market_timestamp": datetime(2026, 7, 30, 19, 59, tzinfo=UTC),
        "trading_date": date(2026, 7, 30),
        "market_session": "regular",
        "previous_close": 100.0,
        "day_high": 106.0,
        "day_low": 99.0,
        "day_volume": 1_000,
        "average_volume_20d": 1_250.0,
    }
    values.update(updates)
    return PriceSnapshotInput(**values)


def test_yfinance_normalization_keeps_provider_timestamp_and_volume_fields():
    value = normalize_yfinance_quote("MSFT", "MSFT", yahoo_quote())
    assert value.provider == "yfinance"
    assert value.market_timestamp == datetime(2026, 7, 30, 19, 59, tzinfo=UTC)
    assert value.timestamp_source == "provider"
    assert value.day_high == 106
    assert value.day_low == 99
    assert value.average_volume_10d == 1200
    assert value.average_volume_20d == 1250
    assert value.market_session == "after_hours"


def test_collection_window_includes_pre_and_after_hours_but_not_overnight():
    assert market_data_collection_status(
        datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
    )["market_session"] == "pre_market"
    assert market_data_collection_status(
        datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    )["market_session"] == "after_hours"
    assert market_data_collection_status(
        datetime(2026, 7, 31, 2, 0, tzinfo=UTC)
    )["market_session"] == "closed"
    # In US standard time the post-market session crosses into the next UTC
    # date, while it still belongs to the previous New York trading date.
    assert market_data_collection_status(
        datetime(2026, 1, 31, 0, 30, tzinfo=UTC)
    )["market_session"] == "after_hours"


def test_finnhub_normalization_preserves_missing_values_as_none():
    value = normalize_finnhub_quote(
        "MSFT",
        "MSFT",
        {"c": 105, "h": None, "l": None, "o": 101, "pc": 100, "t": 1785441540},
        fetched_at=datetime(2026, 7, 30, 20, 0, tzinfo=UTC),
    )
    assert value.provider == "finnhub"
    assert value.day_high is None and value.day_low is None
    assert value.day_volume is None
    assert value.market_timestamp is not None


def test_provider_failure_falls_back_without_mislabeling_provider():
    def yahoo_failure(_symbol):
        raise TimeoutError

    value = fetch_standardized_price_snapshot(
        "MSFT",
        yahoo_symbol="MSFT",
        finnhub_symbol="MSFT",
        provider_order=["yfinance", "finnhub"],
        yahoo_fetcher=yahoo_failure,
        finnhub_fetcher=lambda _symbol: {
            "c": 105, "h": 106, "l": 99, "o": 101, "pc": 100, "t": 1785441540,
        },
    )
    assert value.provider == "finnhub"
    assert value.provider_symbol == "MSFT"


def test_invalid_high_low_is_rejected():
    with pytest.raises(ValueError, match="day_high"):
        normalize_yfinance_quote(
            "MSFT",
            "MSFT",
            yahoo_quote(day_high=90, day_low=99),
        )


def test_persistence_is_idempotent_and_computes_change_and_relative_volume(db):
    first, created = persist_price_snapshot(db, candidate())
    duplicate, duplicate_created = persist_price_snapshot(db, candidate())
    db.commit()
    assert created and not duplicate_created and duplicate.id == first.id
    assert first.price_change == 5
    assert first.price_change_percent == 5
    assert first.relative_volume_20d == .8
    assert db.query(PriceSnapshot).count() == 1


def test_latest_query_orders_by_market_time_not_insert_order(db):
    newer, _ = persist_price_snapshot(
        db,
        candidate(
            last_price=110,
            market_timestamp=datetime(2026, 7, 30, 20, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 30, 20, 1, tzinfo=UTC),
        ),
    )
    older, _ = persist_price_snapshot(
        db,
        candidate(
            last_price=90,
            market_timestamp=datetime(2026, 7, 30, 19, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 30, 20, 2, tzinfo=UTC),
        ),
    )
    db.commit()
    assert older.id > newer.id
    assert get_latest_persisted_price_snapshot(db, "msft").id == newer.id


def test_stale_closed_and_ai_context_are_derived_from_same_row(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.price_snapshots.get_settings",
        lambda: type("Settings", (), {
            "price_snapshot_stale_seconds": 900,
            "market_timezone": "America/New_York",
        })(),
    )
    row, _ = persist_price_snapshot(db, candidate())
    db.commit()
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assert snapshot_freshness(row, now=now)["is_stale"] is True
    output = price_snapshot_out(row, now=now)
    assert output["market_session"] == "closed"
    assert output["trading_date"] == date(2026, 7, 30)
    context = build_ai_price_snapshot_context(row)
    snapshot = context["latest_price_snapshot"]
    assert snapshot["last_price"] == 105
    assert snapshot["day_high"] == 106
    assert snapshot["day_low"] == 99
    assert snapshot["day_volume"] == 1000
    assert snapshot["average_volume_20d"] == 1250


def test_missing_snapshot_context_degrades_safely(db):
    assert get_latest_persisted_price_snapshot(db, "MSFT") is None
    assert build_ai_price_snapshot_context(None) == {"latest_price_snapshot": None}


def test_migration_preserves_legacy_fetch_time_without_faking_market_time():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    spec = importlib.util.spec_from_file_location(
        "migration_0042",
        "backend/alembic/versions/0042_price_market_snapshots.py",
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE price_snapshots ("
            "id INTEGER PRIMARY KEY, ticker VARCHAR(16) NOT NULL, "
            "quote_time DATETIME NOT NULL, price FLOAT NOT NULL, "
            "previous_close FLOAT, volume INTEGER, source VARCHAR(32) NOT NULL, "
            "UNIQUE(ticker, quote_time))"
        )
        connection.exec_driver_sql(
            "INSERT INTO price_snapshots(ticker, quote_time, price, source) "
            "VALUES ('MSFT', '2026-07-31 01:00:00', 100, 'yfinance')"
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        row = connection.execute(sa.text(
            "SELECT quote_time, fetched_at, source_type FROM price_snapshots"
        )).mappings().one()
        assert row["quote_time"] is None
        assert str(row["fetched_at"]).startswith("2026-07-31 01:00:00")
        assert row["source_type"] == "price_snapshot"
        migration.downgrade()
        restored = connection.execute(sa.text(
            "SELECT quote_time, price, source FROM price_snapshots"
        )).mappings().one()
        assert str(restored["quote_time"]).startswith("2026-07-31 01:00:00")


def test_latest_snapshot_api_returns_only_persisted_standardized_data():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Security.__table__,
            StockGroup.__table__,
            WatchlistItem.__table__,
            PriceSnapshot.__table__,
        ],
    )
    session = Session(engine)
    user = User(username="snapshot-api", password_hash="x", status="active", role="user")
    session.add_all([user, WatchlistItem(ticker="MSFT", enabled=True)])
    session.flush()
    persist_price_snapshot(session, candidate())
    session.commit()
    app = FastAPI()
    app.include_router(router)

    def session_override():
        yield session

    app.dependency_overrides[get_db] = session_override
    client = TestClient(app)
    response = client.get(
        "/api/stocks/MSFT/price-snapshot/latest",
        headers={"Authorization": f"Bearer {create_token(user.id)}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "price_snapshot"
    assert body["last_price"] == 105
    assert body["day_high"] == 106
    assert body["day_volume"] == 1000
    assert client.get(
        "/api/stocks/AAPL/price-snapshot/latest",
        headers={"Authorization": f"Bearer {create_token(user.id)}"},
    ).status_code == 404
    session.close()
