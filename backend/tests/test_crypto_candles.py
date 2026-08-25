"""WP 2.3 — UTC multi-timeframe candle storage tests."""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Blockchain,
    CryptoAsset,
    CryptoInstrument,
    CryptoProtocol,
    CryptoProtocolAsset,
    CryptoProviderMapping,
    CryptoSymbolAlias,
    CryptoToken,
    MarketCandle,
)
from app.services.crypto import candles as candle_repo
from app.services.crypto.providers.binance import Kline

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "crypto"
HOUR = 3_600_000


def make_kline(open_time_ms: int, *, interval="1h", close=None, high=None, low=None, base_volume="100",
               taker_base=None, closed_offset_ms=1, market="spot", symbol="BTCUSDT") -> Kline:
    modulo = {"1h": HOUR, "4h": 4 * HOUR, "1d": 24 * HOUR}[interval]
    base_close = close if close is not None else Decimal("101")
    base_high = high if high is not None else max(Decimal("100"), base_close)
    base_low = low if low is not None else min(Decimal("100"), base_close)
    return Kline(
        market=market,
        symbol=symbol,
        interval=interval,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + modulo - closed_offset_ms,
        open=Decimal("100"),
        high=base_high,
        low=base_low,
        close=base_close,
        base_volume=Decimal(base_volume),
        quote_volume=Decimal("10000"),
        trades=50,
        taker_buy_base_volume=Decimal(taker_base) if taker_base is not None else Decimal("40"),
        taker_buy_quote_volume=Decimal("4000"),
        received_at="2000-01-01T00:00:00+00:00",  # ancient: candle counts as closed
    )


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
        CryptoProtocolAsset, CryptoInstrument, CryptoProviderMapping, MarketCandle,
    ):
        table.__table__.create(engine)
    with Session(engine) as session:
        session.add(CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin"))
        session.add(CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token"))
        session.flush()
        session.add(CryptoInstrument(
            venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
            base_asset_id=1, quote_asset_id=2, filters={},
        ))
        session.commit()
        yield session


class TestValidation:
    def test_accepts_fixture_klines(self, db):
        rows = json.loads((FIXTURE_DIR / "binance_spot_klines_1h.json").read_text())
        klines = [
            Kline(
                market="spot", symbol="BTCUSDT", interval="1h",
                open_time_ms=r[0], close_time_ms=r[6],
                open=Decimal(r[1]), high=Decimal(r[2]), low=Decimal(r[3]), close=Decimal(r[4]),
                base_volume=Decimal(r[5]), quote_volume=Decimal(r[7]), trades=r[8],
                taker_buy_base_volume=Decimal(r[9]), taker_buy_quote_volume=Decimal(r[10]),
                received_at="2100-01-01T00:00:00+00:00",
            )
            for r in rows
        ]
        for kline in klines:
            values = candle_repo.validate_kline(kline)
            assert values["open_time_ms"] == kline.open_time_ms

    def test_rejects_misaligned_open_time(self):
        with pytest.raises(candle_repo.CandleValidationError, match="boundary"):
            candle_repo.validate_kline(make_kline(HOUR + 1))

    def test_rejects_wrong_close_time(self):
        with pytest.raises(candle_repo.CandleValidationError, match="interval end"):
            candle_repo.validate_kline(make_kline(HOUR, closed_offset_ms=1000))

    def test_rejects_forming_candle(self):
        kline = make_kline(HOUR)
        object.__setattr__(kline, "received_at", "1970-01-01T00:00:00+00:00")  # close in future
        with pytest.raises(candle_repo.CandleValidationError, match="forming"):
            candle_repo.validate_kline(kline)

    def test_rejects_high_low_inconsistency(self):
        with pytest.raises(candle_repo.CandleValidationError, match="high"):
            candle_repo.validate_kline(make_kline(HOUR, close=Decimal("150"), high=Decimal("120")))

    def test_rejects_taker_volume_exceeding_total(self):
        with pytest.raises(candle_repo.CandleValidationError, match="taker"):
            candle_repo.validate_kline(make_kline(HOUR, taker_base="101"))


class TestPersistence:
    def test_roundtrip_preserves_precision(self, db):
        tiny = Decimal("0.000000000001")  # sub-picosatoshi price precision
        kline = Kline(
            market="spot", symbol="BTCUSDT", interval="1h",
            open_time_ms=HOUR, close_time_ms=2 * HOUR - 1,
            open=tiny, high=tiny * 2, low=tiny, close=tiny * 2,
            base_volume=Decimal("123456789.123456789123"), quote_volume=Decimal("1"),
            trades=1, taker_buy_base_volume=Decimal("1"), taker_buy_quote_volume=Decimal("1"),
            received_at="2000-01-01T00:00:00+00:00",
        )
        summary = candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[kline])
        assert summary.inserted == 1
        stored = candle_repo.read_candles(db, instrument_id=1, interval="1h")[0]
        assert Decimal(stored.open) == tiny
        assert Decimal(stored.base_volume) == Decimal("123456789.123456789123")

    def test_identical_replay_changes_zero_logical_rows(self, db):
        klines = [make_kline(HOUR * i) for i in range(1, 6)]
        first = candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=klines)
        second = candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=klines)
        assert first.inserted == 5
        assert second.inserted == 0 and second.updated == 0 and second.unchanged == 5
        assert db.query(MarketCandle).count() == 5

    def test_provider_revision_updates_in_place(self, db):
        original = make_kline(HOUR)
        candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[original])
        revised = make_kline(HOUR, close=Decimal("105"))
        summary = candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[revised])
        assert summary.updated == 1
        stored = candle_repo.read_candles(db, instrument_id=1, interval="1h")[0]
        assert Decimal(stored.close) == Decimal("105")
        assert db.query(MarketCandle).count() == 1

    def test_distinct_price_types_never_overwrite(self, db):
        trade = make_kline(HOUR)
        mark = make_kline(HOUR, close=Decimal("99"))
        candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[trade], price_type="trade")
        candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[mark], price_type="mark")
        assert db.query(MarketCandle).count() == 2
        assert len(candle_repo.read_candles(db, instrument_id=1, interval="1h", price_type="trade")) == 1
        assert len(candle_repo.read_candles(db, instrument_id=1, interval="1h", price_type="mark")) == 1

    def test_rejected_rows_are_reported_not_dropped_silently(self, db):
        good = make_kline(HOUR)
        bad = make_kline(HOUR + 1)  # misaligned
        summary = candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[good, bad])
        assert summary.inserted == 1 and len(summary.rejected) == 1
        assert "boundary" in summary.rejected[0]["reason"]

    def test_unique_key_enforced_at_db_level(self, db):
        kline = make_kline(HOUR)
        candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[kline])
        db.commit()
        db.add(MarketCandle(
            instrument_id=1, interval="1h", open_time_ms=HOUR, close_time_ms=2 * HOUR - 1,
            provider="binance_spot", price_type="trade", feed="rest",
            open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1),
            base_volume=Decimal(1), quote_volume=Decimal(1), source_hash="x", fetched_at=db.get(MarketCandle, 1).fetched_at,
        ))
        with pytest.raises(IntegrityError):
            db.flush()


class TestReadsAndGaps:
    @pytest.fixture()
    def seeded(self, db):
        open_times = [HOUR * i for i in (1, 2, 3, 5, 6, 9)]  # gaps at 4,7,8
        candle_repo.persist_klines(db, instrument_id=1, provider="binance_spot", klines=[make_kline(t) for t in open_times])
        db.commit()
        return db

    def test_chronological_pagination(self, seeded):
        page_one = candle_repo.read_candles(seeded, instrument_id=1, interval="1h", limit=4)
        page_two = candle_repo.read_candles(
            seeded, instrument_id=1, interval="1h", limit=4, start_time_ms=page_one[-1].open_time_ms + HOUR
        )
        times = [c.open_time_ms for c in page_one + page_two]
        assert times == sorted(times)
        assert page_one[0].open_time_ms == HOUR
        assert len(page_two) == 2

    def test_gap_detection_reports_missing_ranges(self, seeded):
        coverage = candle_repo.candle_coverage(seeded, instrument_id=1, interval="1h")
        assert coverage.candle_count == 6
        assert coverage.expected_count == 9
        assert coverage.missing_count == 3
        assert coverage.missing_ranges == [[4 * HOUR, 4 * HOUR], [7 * HOUR, 8 * HOUR]]

    def test_latest_closed_candle(self, seeded):
        latest = candle_repo.latest_closed_candle(seeded, instrument_id=1, interval="1h")
        assert latest.open_time_ms == 9 * HOUR

    def test_empty_coverage_is_explicit(self, db):
        coverage = candle_repo.candle_coverage(db, instrument_id=1, interval="4h")
        assert coverage.candle_count == 0 and coverage.missing_count == 0

    def test_candle_to_dict_json_safe(self, seeded):
        stored = candle_repo.read_candles(seeded, instrument_id=1, interval="1h", limit=1)[0]
        payload = candle_repo.candle_to_dict(stored)
        json.dumps(payload)  # must serialize
        assert payload["open"].startswith("100")


def test_market_candles_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions" / "0070_market_candles.py"
    spec = importlib.util.spec_from_file_location("market_candles_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
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
                INSERT INTO market_candles (instrument_id, interval, open_time_ms, close_time_ms, price_type, provider, feed,
                    open, high, low, close, base_volume, quote_volume, source_hash, final, fetched_at)
                VALUES (1, '1h', 3600000, 7199999, 'trade', 'binance_spot', 'rest',
                    100, 110, 95, 105, 12.5, 1300, 'abc', 1, '2026-08-25T00:00:00+00:00')
            """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO market_candles (instrument_id, interval, open_time_ms, close_time_ms, price_type, provider, feed,
                        open, high, low, close, base_volume, quote_volume, source_hash, final, fetched_at)
                    VALUES (1, '1h', 3600000, 7199999, 'trade', 'binance_spot', 'rest',
                        100, 110, 95, 105, 12.5, 1300, 'def', 1, '2026-08-25T00:00:00+00:00')
                """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO market_candles (instrument_id, interval, open_time_ms, close_time_ms, price_type, provider, feed,
                        open, high, low, close, base_volume, quote_volume, source_hash, final, fetched_at)
                    VALUES (1, '15m', 3600000, 7199999, 'trade', 'binance_spot', 'rest',
                        100, 110, 95, 105, 12.5, 1300, 'abc', 1, '2026-08-25T00:00:00+00:00')
                """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO market_candles (instrument_id, interval, open_time_ms, close_time_ms, price_type, provider, feed,
                        open, high, low, close, base_volume, quote_volume, source_hash, final, fetched_at)
                    VALUES (1, '1h', 3600000, 7199999, 'trade', 'binance_spot', 'rest',
                        100, 90, 95, 105, 12.5, 1300, 'abc', 1, '2026-08-25T00:00:00+00:00')
                """))
            migration.downgrade()
            tables = {
                row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "market_candles" not in tables
            migration.upgrade()
        finally:
            migration.op = original
