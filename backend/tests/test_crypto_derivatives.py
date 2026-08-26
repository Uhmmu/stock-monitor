"""WP 4.3 — funding and typed derivatives persistence."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CryptoAsset, CryptoDerivativesMetric, CryptoFundingRate, CryptoInstrument, MarketCandle
from app.services.crypto import derivatives

UTC = timezone.utc
ROOT = Path(__file__).parents[1]


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in (CryptoAsset, CryptoInstrument, MarketCandle, CryptoFundingRate, CryptoDerivativesMetric):
        table.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin"),
            CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token"),
        ])
        session.flush()
        session.add(CryptoInstrument(
            venue="binance", market="usdm_futures", provider_symbol="BTCUSDT",
            kind="perpetual", base_asset_id=1, quote_asset_id=2, settlement_asset_id=2,
            filters={},
        ))
        session.commit()
        yield session


def test_normalization_keeps_decimal_and_utc_and_definitions():
    row = derivatives.normalize_derivatives_metric({
        "instrument_id": 1,
        "timestamp": 1_700_000_000_000,
        "markPrice": "100.123456789012345678",
        "indexPrice": "100.000000000000000000",
        "openInterest": "12.000000000000000001",
        "longShortRatio": "1.2",
    })
    assert row["observed_at"].tzinfo == UTC
    assert row["mark_price"] == Decimal("100.123456789012345678")
    assert row["open_interest_base"] == Decimal("12.000000000000000001")
    assert row["metadata_json"]["metric_definitions"]["basis"]["unit"] == "quote_per_base"
    assert row["basis"] == Decimal("0.123456789012345678")


def test_funding_upsert_is_idempotent_and_revisions_source_changes(db):
    event_row = {
        "instrument_id": 1, "fundingTime": 1_700_000_000_000,
        "fundingRate": "0.000100000000000001", "markPrice": "100.000000000000000001",
        "source_hash": "a" * 64,
    }
    first = derivatives.persist_funding_rates(db, [event_row])
    second = derivatives.persist_funding_rates(db, [event_row])
    assert (first.inserted, second.unchanged, db.query(CryptoFundingRate).count()) == (1, 1, 1)

    revised = {**event_row, "fundingRate": "-0.000100000000000001", "source_hash": "b" * 64}
    result = derivatives.persist_funding_rates(db, [revised])
    row = db.query(CryptoFundingRate).one()
    assert result.updated == 1 and row.revision == 1
    assert row.funding_rate == Decimal("-0.000100000000000001")


def test_metric_merge_aligned_basis_and_partial_last_good(db):
    stamp = datetime(2026, 8, 26, 1, tzinfo=UTC)
    first = derivatives.persist_derivatives_metrics(db, [{
        "instrument_id": 1, "observed_at": stamp, "mark_price": "101",
        "mark_timestamp": stamp, "source_hash": "mark" * 16,
    }])
    second = derivatives.persist_derivatives_metrics(db, [{
        "instrument_id": 1, "observed_at": stamp, "index_price": "100",
        "index_timestamp": stamp, "openInterest": "2.000000000000000001",
        "source_hash": "index" * 16,
    }])
    row = db.query(CryptoDerivativesMetric).one()
    assert first.inserted == 1 and second.updated == 1
    assert row.basis == Decimal("1")
    assert row.basis_rate == Decimal("0.01")
    assert row.mark_price == Decimal("101")
    assert row.open_interest_base == Decimal("2.000000000000000001")

    # Missing endpoint fields do not erase the last-good mark/index/basis.
    derivatives.persist_derivatives_metrics(db, [{
        "instrument_id": 1, "observed_at": stamp, "openInterest": None,
        "source_hash": "partial" * 10 + "1234",
    }])
    row = db.query(CryptoDerivativesMetric).one()
    assert row.mark_price == Decimal("101") and row.basis == Decimal("1")


def test_metric_only_merges_identical_time_and_rejects_incompatible_definition(db):
    stamp = datetime(2026, 8, 26, 1, tzinfo=UTC)
    derivatives.persist_derivatives_metrics(db, [{
        "instrument_id": 1, "observed_at": stamp, "markPrice": "100", "longShortRatio": "1.0",
    }])
    derivatives.persist_derivatives_metrics(db, [{"instrument_id": 1, "observed_at": stamp.replace(hour=2), "indexPrice": "99"}])
    assert db.query(CryptoDerivativesMetric).count() == 2

    # Definitions for the same ratio cannot be silently collapsed.
    result = derivatives.persist_derivatives_metrics(db, [{
        "instrument_id": 1, "observed_at": stamp,
        "longShortRatio": "1.1",
        "metadata": {"metric_definitions": {"long_short_ratio": {"definition": "position ratio"}}},
    }])
    assert result.rejected and "incompatible metric definition" in result.rejected[0]["reason"]


def test_live_endpoint_rows_merge_sparse_definitions_and_repair_legacy_null_definition(db):
    stamp = datetime(2026, 8, 26, 1, tzinfo=UTC)
    rows = [
        {"instrument_id": 1, "observed_at": stamp, "openInterest": "2", "openInterestValue": "200"},
        {
            "instrument_id": 1, "observed_at": stamp, "longShortRatio": "1.2",
            "long_short_ratio_definition": "all trader accounts: long accounts / short accounts",
        },
        {"instrument_id": 1, "observed_at": stamp, "buyVol": "60", "sellVol": "40", "buySellRatio": "1.5"},
    ]
    result = derivatives.persist_derivatives_metrics(db, rows)
    metric = db.query(CryptoDerivativesMetric).one()
    assert result.inserted == 1
    assert metric.open_interest_base == Decimal("2") and metric.taker_buy_volume == Decimal("60")
    definitions = metric.metadata_json["metric_definitions"]
    assert definitions["long_short_ratio"]["definition"] == "all trader accounts: long accounts / short accounts"
    assert "mark_price" not in definitions

    metric.long_short_ratio = None
    metric.metadata_json = {
        "metric_definitions": {
            **definitions,
            "long_short_ratio": derivatives.METRIC_DEFINITIONS["long_short_ratio"],
        }
    }
    db.flush()
    repaired = derivatives.persist_derivatives_metrics(db, [rows[1]])
    assert repaired.updated == 1
    assert metric.metadata_json["metric_definitions"]["long_short_ratio"]["definition"] == "all trader accounts: long accounts / short accounts"


def test_history_and_status_payloads_are_json_safe(db):
    stamp = datetime(2026, 8, 26, 1, tzinfo=UTC)
    derivatives.persist_funding_rates(db, [{"instrument_id": 1, "fundingTime": stamp, "fundingRate": "0.1"}])
    derivatives.persist_derivatives_metrics(db, [{"instrument_id": 1, "observed_at": stamp, "openInterest": "2"}])
    funding = derivatives.funding_history_payload(derivatives.read_funding_history(db, instrument_id=1))
    metrics = derivatives.derivatives_history_payload(derivatives.read_derivatives_history(db, instrument_id=1))
    status = derivatives.derivatives_status_payload(db, instrument_id=1)
    assert funding["count"] == metrics["count"] == 1
    assert funding["items"][0]["funding_rate"] == "0.1"
    assert metrics["items"][0]["open_interest_base"] == "2"
    assert status["status"] == "ready" and status["coverage"]["open_interest_base"] == 1


def test_public_collector_keeps_partial_endpoint_results(db):
    stamp = 1_787_666_400_000

    class Client:
        def funding_rate_history(self, *_args, **_kwargs):
            return [SimpleNamespace(funding_time_ms=stamp, funding_rate=Decimal("0.0001"), mark_price=Decimal("100"), rate_type="Regular")]

        def open_interest_history(self, *_args, **_kwargs):
            return [SimpleNamespace(event_time_ms=stamp, sum_open_interest=Decimal("10"), sum_open_interest_value=Decimal("1000"))]

        def global_long_short_ratio(self, *_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        def taker_buy_sell_volume(self, *_args, **_kwargs):
            return [SimpleNamespace(event_time_ms=stamp, buy_sell_ratio=Decimal("1.5"), buy_volume=Decimal("60"), sell_volume=Decimal("40"))]

    result = derivatives.collect_public_derivatives(db, client=Client(), instrument=db.get(CryptoInstrument, 1))
    assert result["status"] == "partial" and "long_short" in result["errors"]
    metric = db.query(CryptoDerivativesMetric).one()
    assert metric.open_interest_base == Decimal("10")
    assert metric.taker_buy_volume == Decimal("60")
    assert db.query(CryptoFundingRate).count() == 1


def _load_migration(filename: str):
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_0071_migration_round_trip_on_sqlite():
    engine = create_engine("sqlite://")
    chain = [
        "0066_crypto_identity_assets.py", "0067_crypto_chain_token_protocol.py",
        "0068_crypto_instruments.py", "0069_crypto_collection_runs.py",
        "0070_market_candles.py", "0071_crypto_derivatives.py",
    ]
    modules = [_load_migration(name) for name in chain]
    with engine.begin() as connection:
        originals = [module.op for module in modules]
        try:
            for module in modules:
                module.op = Operations(MigrationContext.configure(connection))
                module.upgrade()
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"crypto_funding_rates", "crypto_derivatives_metrics"} <= tables
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(crypto_derivatives_metrics)"))}
            assert {"mark_price", "index_price", "basis", "open_interest_usd", "source_hash", "revision"} <= columns
            modules[-1].downgrade()
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "crypto_funding_rates" not in tables and "crypto_derivatives_metrics" not in tables
            modules[-1].upgrade()
        finally:
            for module, original in zip(modules, originals):
                module.op = original
