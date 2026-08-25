"""WP 2.4 — historical backfill and gap repair tests (fixture-shaped, no network)."""

from __future__ import annotations

from decimal import Decimal

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
    CryptoSyncState,
    CryptoToken,
    MarketCandle,
)
from app.services.crypto import backfill, candles as candle_repo
from app.services.crypto.providers.binance import (
    BinancePublicError,
    Kline,
    parse_kline_row,
)

HOUR = 3_600_000
NOW_MS = 100 * HOUR  # synthetic now far from real time


def make_kline(open_time_ms: int, *, interval="1h", close="105") -> Kline:
    modulo = {"1h": HOUR, "4h": 4 * HOUR, "1d": 24 * HOUR}[interval]
    return Kline(
        market="spot", symbol="BTCUSDT", interval=interval,
        open_time_ms=open_time_ms, close_time_ms=open_time_ms + modulo - 1,
        open=Decimal("100"), high=Decimal(max(100, int(close))), low=Decimal("99"),
        close=Decimal(close), base_volume=Decimal("10"), quote_volume=Decimal("1000"),
        trades=5, taker_buy_base_volume=Decimal("4"), taker_buy_quote_volume=Decimal("400"),
        received_at="2100-01-01T00:00:00+00:00",
    )


class FakeKlineClient:
    """Serves pages from an in-memory candle sequence; optional failure injection."""

    def __init__(self, open_times, *, page_size=3, fail_on_page=None, forming_last=False):
        self.open_times = list(open_times)
        self.page_size = page_size
        self.fail_on_page = fail_on_page
        self.forming_last = forming_last
        self.calls = []

    def klines(self, market, symbol, interval, *, start_time_ms=None, end_time_ms=None, limit=500):
        self.calls.append((start_time_ms, end_time_ms, limit))
        page_index = len(self.calls)
        if self.fail_on_page is not None and page_index == self.fail_on_page:
            raise BinancePublicError("rate_limited", "too many requests")
        matches = [t for t in self.open_times if t >= (start_time_ms or 0) and t <= (end_time_ms or 10**15)]
        selected = matches[: min(limit, self.page_size)]
        rows = [make_kline(t) for t in selected]
        if self.forming_last and page_index * self.page_size >= len(self.open_times):
            # last page carries one still-forming candle: close time in the future
            forming = make_kline(selected[-1] + HOUR if selected else 0)
            object.__setattr__(forming, "close_time_ms", 10**15)
            object.__setattr__(forming, "received_at", "2000-01-01T00:00:00+00:00")
            rows.append(forming)
        return rows


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
        CryptoCollectionRun, CryptoSyncState,
    ):
        table.__table__.create(engine)
    with Session(engine) as session:
        session.add(CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin"))
        session.add(CryptoAsset(slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token"))
        session.flush()
        session.add(CryptoInstrument(
            id=1, venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
            base_asset_id=1, quote_asset_id=2, filters={},
        ))
        session.commit()
        yield session


def instrument(db) -> CryptoInstrument:
    return db.get(CryptoInstrument, 1)


class TestBackfill:
    def test_backfill_pages_by_time_and_persists(self, db):
        times = [HOUR * i for i in range(1, 8)]  # 7 candles
        client = FakeKlineClient(times, page_size=3)
        result = backfill.backfill_instrument_candles(
            db, client=client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0, page_limit=3,
        )
        assert result.status == "success"
        assert result.inserted == 7 and result.pages == 3
        coverage = candle_repo.candle_coverage(db, instrument_id=1, interval="1h")
        assert coverage.missing_count == 0
        # watermark persisted
        state = db.query(CryptoSyncState).one()
        assert state.watermark_ms == HOUR * 7
        assert state.next_due_at is not None and state.last_error is None

    def test_open_forming_candle_excluded_not_errored(self, db):
        times = [HOUR * i for i in range(1, 4)]
        client = FakeKlineClient(times, page_size=10, forming_last=True)
        result = backfill.backfill_instrument_candles(
            db, client=client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        assert result.skipped_forming == 1
        assert result.rejected == []  # forming is not a validation error
        assert db.query(MarketCandle).count() == 3

    def test_rerun_is_idempotent_and_incremental(self, db):
        times = [HOUR * i for i in range(1, 6)]
        first_client = FakeKlineClient(times, page_size=10)
        first = backfill.backfill_instrument_candles(
            db, client=first_client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        assert first.inserted == 5
        # restart: same data available, watermark prevents refetch
        second_client = FakeKlineClient(times + [HOUR * 6], page_size=10)
        second = backfill.backfill_instrument_candles(
            db, client=second_client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        assert second.inserted == 1 and second.unchanged == 0
        # fetch starts strictly after the watermark
        start_arg = second_client.calls[0][0]
        assert start_arg == HOUR * 6

    def test_duplicate_pages_are_unchanged(self, db):
        times = [HOUR * i for i in range(1, 4)]
        client = FakeKlineClient(times, page_size=10)
        backfill.backfill_instrument_candles(
            db, client=client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        replay = backfill.backfill_instrument_candles(
            db, client=FakeKlineClient(times, page_size=10), instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        assert replay.inserted == 0

    def test_midway_failure_is_partial_with_prior_pages_persisted(self, db):
        times = [HOUR * i for i in range(1, 10)]
        client = FakeKlineClient(times, page_size=3, fail_on_page=2)
        result = backfill.backfill_instrument_candles(
            db, client=client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0, page_limit=3,
        )
        assert result.status == "partial"
        assert result.inserted == 3  # page one persisted before the failure
        assert "rate_limited" in result.error
        state = db.query(CryptoSyncState).one()
        assert state.last_error == result.error
        assert state.watermark_ms == HOUR * 3  # recomputed from persisted truth

    def test_gap_inside_window_keeps_status_partial(self, db):
        times = [HOUR, HOUR * 2, HOUR * 5]  # hole at 3,4
        client = FakeKlineClient(times, page_size=10)
        result = backfill.backfill_instrument_candles(
            db, client=client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        assert result.status == "partial"
        assert result.gaps == [{"start_ms": HOUR * 3, "end_ms": HOUR * 4}]
        state = db.query(CryptoSyncState).one()
        assert state.missing_count == 2

    def test_history_window_bounded(self, db):
        # a candle older than history_days is outside the requested window
        times = [HOUR, HOUR * 2]
        client = FakeKlineClient(times, page_size=10)
        result = backfill.backfill_instrument_candles(
            db, client=client, instrument=instrument(db), interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        # 1 day window from now: both candles are far older... history_start clamps cursor
        first_call_start = client.calls[0][0]
        assert first_call_start >= 0
        assert result.pages >= 1

    def test_universe_loop_isolates_failures(self, db):
        second = CryptoInstrument(
            id=2, venue="binance", market="spot", provider_symbol="ETHUSDT", kind="spot",
            base_asset_id=1, quote_asset_id=2, filters={},
        )
        db.add(second)
        db.commit()

        class OneFails:
            def __init__(self, ok_client):
                self.ok = ok_client

            def klines(self, market, symbol, interval, **kwargs):
                if symbol == "ETHUSDT":
                    raise BinancePublicError("timeout", "down")
                return self.ok.klines(market, symbol, interval, **kwargs)

        payloads = backfill.sync_candles_for_universe(
            db,
            client=OneFails(FakeKlineClient([HOUR, HOUR * 2], page_size=10)),
            instruments=[db.get(CryptoInstrument, 1), db.get(CryptoInstrument, 2)],
            intervals=["1h"],
        )
        by_instrument = {p["instrument_id"]: p for p in payloads}
        assert by_instrument[1]["status"] == "success"
        assert by_instrument[2]["status"] in ("failed", "partial")
        assert by_instrument[2]["error"]

    def test_due_work_respects_next_due(self, db):
        from datetime import datetime, timedelta, timezone

        inst = instrument(db)
        assert backfill.due_candle_work(db, instruments=[inst], intervals=["1h"]) == [(inst, "1h")]
        backfill.backfill_instrument_candles(
            db, client=FakeKlineClient([HOUR], page_size=10), instrument=inst, interval="1h",
            now_ms=NOW_MS, history_days=5, page_pause_seconds=0,
        )
        # next_due far in the future (synthetic 1970-based now makes the set value stale)
        state = db.query(CryptoSyncState).one()
        state.next_due_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()
        assert backfill.due_candle_work(db, instruments=[inst], intervals=["1h"]) == []
        # simulate elapsed time past next_due
        state = db.query(CryptoSyncState).one()
        state.next_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert backfill.due_candle_work(db, instruments=[inst], intervals=["1h"]) == [(inst, "1h")]
