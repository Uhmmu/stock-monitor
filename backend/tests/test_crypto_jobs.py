"""WP 2.2 — Binance exchange-metadata sync tests (fixture-driven, no network)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import (
    Blockchain,
    CryptoAsset,
    CryptoCollectionRun,
    CryptoInstrument,
    CryptoProtocol,
    CryptoProtocolAsset,
    CryptoProviderMapping,
    CryptoSymbolAlias,
    CryptoToken,
)
from app.services.crypto import identity, jobs
from app.services.crypto.providers.binance import parse_exchange_info

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "crypto"


class FakeClient:
    """Deterministic stand-in returning fixture-shaped exchange info."""

    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def exchange_info(self, market="spot", symbol=None):
        if self._error is not None:
            raise self._error
        return parse_exchange_info(market, self._payload)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in (
        CryptoAsset, CryptoSymbolAlias, Blockchain, CryptoToken, CryptoProtocol,
        CryptoProtocolAsset, CryptoInstrument, CryptoProviderMapping,
        CryptoCollectionRun,
    ):
        table.__table__.create(engine)
    with Session(engine) as session:
        yield session


def fixture_client(name="binance_spot_exchange_info.json") -> FakeClient:
    payload = json.loads((FIXTURE_DIR / name).read_text())
    # extend with ETHUSDT from its dedicated fixture so the universe covers both
    eth = json.loads((FIXTURE_DIR / "binance_spot_exchange_info.json").read_text())
    return FakeClient(payload)


class TestParseSpotUniverse:
    def test_parse_dedupe_uppercase_bounded(self):
        assert jobs.parse_spot_universe("btcusdt, BTCUSDT,ethusdt,, ") == ["BTCUSDT", "ETHUSDT"]

    def test_parse_caps_length(self):
        universe = jobs.parse_spot_universe(",".join(f"S{i}USDT" for i in range(80)))
        assert len(universe) == 50


class TestCoreIdentitySeed:
    def test_seed_idempotent(self, db):
        first = jobs.ensure_core_identity_seed(db)
        second = jobs.ensure_core_identity_seed(db)
        assert first["assets_created"] == 3 and first["mappings_created"] == 3
        assert second["assets_created"] == 0 and second["mappings_created"] == 0
        # XBT alias seeded to bitcoin
        result = identity.resolve_symbol(db, "XBT")
        assert result.status == "resolved_via_alias" and result.asset.slug == "bitcoin"

    def test_seed_mappings_resolve_binance_assets(self, db):
        jobs.ensure_core_identity_seed(db)
        for provider_id, slug in (("BTC", "bitcoin"), ("ETH", "ethereum"), ("USDT", "tether-usd")):
            resolved = identity.resolve_provider_id(
                db, provider="binance_spot", object_type="asset", provider_id=provider_id
            )
            assert resolved.resolved and resolved.asset.slug == slug


class TestSpotExchangeInfoSync:
    def test_sync_creates_instruments_with_exact_filters(self, db):
        result = jobs.sync_spot_exchange_info(db, client=fixture_client(), universe=["BTCUSDT", "ETHUSDT"], bucket="2026082516")
        assert result.status == "success"
        assert result.items_seen == 2 and result.items_created == 2 and result.items_updated == 0
        instrument = identity.get_instrument(db, venue="binance", provider_symbol="BTCUSDT", kind="spot")
        assert instrument is not None
        assert Decimal(instrument.tick_size) == Decimal("0.01")
        assert instrument.filters["LOT_SIZE"]["stepSize"] == "0.00001000"
        assert instrument.status == "trading"
        mapping = identity.resolve_provider_id(
            db, provider="binance_spot", object_type="instrument", provider_id="BTCUSDT"
        )
        assert mapping.resolved and mapping.instrument.id == instrument.id

    def test_repeat_run_is_idempotent(self, db):
        client = fixture_client()
        first = jobs.sync_spot_exchange_info(db, client=client, universe=["BTCUSDT"], bucket="2026082516")
        second = jobs.sync_spot_exchange_info(db, client=FakeClient(json.loads((FIXTURE_DIR / "binance_spot_exchange_info.json").read_text())), universe=["BTCUSDT"], bucket="2026082517")
        assert first.items_created == 1
        assert second.items_created == 0 and second.items_updated == 1
        assert db.query(CryptoInstrument).count() == 1
        assert db.query(CryptoProviderMapping).filter_by(object_type="instrument").count() == 1

    def test_same_bucket_claim_returns_none(self, db):
        client = fixture_client()
        first = jobs.sync_spot_exchange_info(db, client=client, universe=["BTCUSDT"], bucket="2026082516")
        again = jobs.sync_spot_exchange_info(db, client=client, universe=["BTCUSDT"], bucket="2026082516")
        assert first is not None and again is None

    def test_symbol_status_change_updates_row(self, db):
        payload = json.loads((FIXTURE_DIR / "binance_spot_exchange_info.json").read_text())
        jobs.sync_spot_exchange_info(db, client=FakeClient(payload), universe=["BTCUSDT"], bucket="b1")
        delisted = json.loads(json.dumps(payload))
        delisted["symbols"][0]["status"] = "BREAK"
        result = jobs.sync_spot_exchange_info(db, client=FakeClient(delisted), universe=["BTCUSDT"], bucket="b2")
        instrument = identity.get_instrument(db, venue="binance", provider_symbol="BTCUSDT", kind="spot")
        assert instrument.status == "halted"
        assert result.items_updated == 1 and db.query(CryptoInstrument).count() == 1

    def test_unresolved_assets_skip_instrument_and_are_reported(self, db):
        payload = json.loads((FIXTURE_DIR / "binance_spot_exchange_info.json").read_text())
        payload["symbols"].append({
            "symbol": "SOLUSDT", "status": "TRADING", "baseAsset": "SOL", "quoteAsset": "USDT",
            "baseAssetPrecision": 8, "quotePrecision": 8, "quoteAssetPrecision": 8,
            "orderTypes": ["MARKET"], "filters": [], "permissionSets": [],
        })
        result = jobs.sync_spot_exchange_info(db, client=FakeClient(payload), universe=["BTCUSDT", "SOLUSDT"], bucket="b1")
        assert result.status == "partial"
        assert result.unresolved_count == 1
        assert result.unresolved[0]["symbol"] == "SOLUSDT"
        assert identity.get_instrument(db, venue="binance", provider_symbol="SOLUSDT", kind="spot") is None
        assert identity.get_instrument(db, venue="binance", provider_symbol="BTCUSDT", kind="spot") is not None

    def test_universe_symbol_absent_is_excluded_with_reason(self, db):
        result = jobs.sync_spot_exchange_info(
            db, client=fixture_client(), universe=["BTCUSDT", "NOSUCHUSDT"], bucket="b1"
        )
        assert result.status == "partial"
        assert result.excluded == [{"symbol": "NOSUCHUSDT", "reason": "not_present_in_exchange_info"}]

    def test_provider_failure_marks_run_failed_and_keeps_last_good(self, db):
        good = jobs.sync_spot_exchange_info(db, client=fixture_client(), universe=["BTCUSDT"], bucket="b1")
        assert good.status == "success"
        from app.services.crypto.providers.binance import BinancePublicError

        failed = jobs.sync_spot_exchange_info(
            db,
            client=FakeClient(None, error=BinancePublicError("retryable", "upstream down")),
            universe=["BTCUSDT"],
            bucket="b2",
        )
        assert failed.status == "failed" and "retryable" in failed.error
        # last-good instruments survive; a failed run never clears data
        assert identity.get_instrument(db, venue="binance", provider_symbol="BTCUSDT", kind="spot") is not None
        runs = db.query(CryptoCollectionRun).order_by(CryptoCollectionRun.id).all()
        assert [r.status for r in runs] == ["success", "failed"]
        assert jobs.latest_successful_run(db, provider="binance", domain="spot_exchange_info").bucket == "b1"

    def test_due_check_requires_refresh_interval(self, db):
        assert jobs.spot_exchange_info_due(db) is True
        jobs.sync_spot_exchange_info(db, client=fixture_client(), universe=["BTCUSDT"], bucket="b1")
        assert jobs.spot_exchange_info_due(db) is False


def test_collection_runs_migration_round_trip_on_sqlite():
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    path = Path(__file__).parents[1] / "alembic/versions/0069_crypto_collection_runs.py"
    spec = importlib.util.spec_from_file_location("crypto_collection_runs_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        # prerequisite tables for the sync-state FK come straight from models
        CryptoAsset.__table__.create(connection)
        CryptoInstrument.__table__.create(connection)

        original, migration.op = migration.op, Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            connection.execute(text("""
                INSERT INTO crypto_assets (slug, symbol, display_name, asset_kind, status)
                VALUES ('bitcoin', 'BTC', 'Bitcoin', 'coin', 'active')
            """))
            connection.execute(text("""
                INSERT INTO crypto_instruments (venue, market, provider_symbol, kind, base_asset_id, quote_asset_id, status, calendar, filters)
                VALUES ('binance', 'spot', 'BTCUSDT', 'spot', 1, 1, 'trading', 'utc', '{}')
            """))
            connection.execute(text("""
                INSERT INTO crypto_collection_runs (provider, domain, bucket, status)
                VALUES ('binance', 'spot_exchange_info', 'b1', 'success')
            """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO crypto_collection_runs (provider, domain, bucket, status)
                    VALUES ('binance', 'spot_exchange_info', 'b1', 'success')
                """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO crypto_collection_runs (provider, domain, bucket, status)
                    VALUES ('binance', 'spot_exchange_info', 'b2', 'bogus_status')
                """))
            connection.execute(text("""
                INSERT INTO crypto_sync_states (instrument_id, provider, data_kind, interval, watermark_ms)
                VALUES (1, 'binance', 'candles', '1h', 1500000000000)
            """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO crypto_sync_states (instrument_id, provider, data_kind, interval)
                    VALUES (1, 'binance', 'candles', '1h')
                """))
            migration.downgrade()
            tables = {
                row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "crypto_collection_runs" not in tables and "crypto_sync_states" not in tables
            migration.upgrade()
        finally:
            migration.op = original
