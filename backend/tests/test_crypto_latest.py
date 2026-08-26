"""WP 2.5 — latest ticker cache and fallback tests."""

from __future__ import annotations

import json
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
from app.services.crypto import candles as candle_repo
from app.services.crypto import latest as latest_service
from app.services.crypto.providers.binance import (
    BinancePublicError,
    Kline,
    Ticker24h,
)

HOUR = 3_600_000


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


@pytest.fixture(autouse=True)
def isolated_redis(monkeypatch):
    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_setex(key, ttl, value):
        store[key] = value
        return True

    monkeypatch.setattr(latest_service, "_redis_get", fake_get)
    monkeypatch.setattr(latest_service, "_redis_setex", fake_setex)
    return store


def fake_ticker(symbol="BTCUSDT") -> Ticker24h:
    return Ticker24h(
        market="spot", symbol=symbol,
        last_price=Decimal("79184.01"), bid_price=Decimal("79184.00"), ask_price=Decimal("79184.02"),
        high_price=Decimal("80000"), low_price=Decimal("78000"),
        base_volume=Decimal("12345.67"), quote_volume=Decimal("987654321"),
        open_time_ms=1, close_time_ms=latest_service._now_ms() - 2000,  # 2s old event
        received_at="2026-08-26T00:00:00+00:00",
    )


class FakeTickerClient:
    def __init__(self, error=None):
        self.error = error

    def ticker_24h(self, market, symbol):
        if self.error:
            raise self.error
        return fake_ticker(symbol)


def seed_candle(db, open_time_ms):
    candle_repo.persist_klines(
        db, instrument_id=1, provider="binance_spot",
        klines=[Kline(
            market="spot", symbol="BTCUSDT", interval="1h",
            open_time_ms=open_time_ms, close_time_ms=open_time_ms + HOUR - 1,
            open=Decimal("100"), high=Decimal("110"), low=Decimal("95"), close=Decimal("105"),
            base_volume=Decimal("10"), quote_volume=Decimal("1000"), trades=5,
            taker_buy_base_volume=Decimal("4"), taker_buy_quote_volume=Decimal("400"),
            received_at="2100-01-01T00:00:00+00:00",
        )],
    )
    db.commit()


class TestRefresh:
    def test_refresh_caches_and_reports(self, db, isolated_redis):
        summary = latest_service.refresh_latest_tickers(
            db, client=FakeTickerClient(), instruments=[db.get(CryptoInstrument, 1)]
        )
        assert summary.refreshed == 1 and summary.failed == []
        assert latest_service._cache_key(1) in isolated_redis
        payload = json.loads(isolated_redis[latest_service._cache_key(1)])
        assert payload["provider"] == "binance_spot"
        assert payload["event_time_ms"] is not None
        assert latest_service._health_key("binance_spot") in isolated_redis

    def test_usdm_perpetual_uses_provider_market_name(self, db, isolated_redis):
        instrument = CryptoInstrument(
            id=2, venue="binance", market="usdm_futures", provider_symbol="BTCUSDT", kind="perpetual",
            base_asset_id=1, quote_asset_id=2, filters={},
        )
        db.add(instrument)
        db.commit()
        calls = []

        class Client:
            def ticker_24h(self, market, symbol):
                calls.append((market, symbol))
                ticker = fake_ticker(symbol)
                object.__setattr__(ticker, "bid_price", None)
                object.__setattr__(ticker, "ask_price", None)
                return ticker

        summary = latest_service.refresh_latest_tickers(db, client=Client(), instruments=[instrument])
        assert summary.refreshed == 1
        assert calls == [("usdm", "BTCUSDT")]
        payload = json.loads(isolated_redis[latest_service._cache_key(2)])
        assert payload["provider"] == "binance_usdm"
        assert payload["bid_price"] is None and payload["ask_price"] is None

    def test_provider_failure_isolated_per_instrument(self, db):
        second = CryptoInstrument(
            id=2, venue="binance", market="spot", provider_symbol="ETHUSDT", kind="spot",
            base_asset_id=1, quote_asset_id=2, filters={},
        )
        db.add(second)
        db.commit()

        class HalfFailing:
            def ticker_24h(self, market, symbol):
                if symbol == "ETHUSDT":
                    raise BinancePublicError("timeout", "down")
                return fake_ticker(symbol)

        summary = latest_service.refresh_latest_tickers(
            db, client=HalfFailing(), instruments=[db.get(CryptoInstrument, 1), db.get(CryptoInstrument, 2)]
        )
        assert summary.refreshed == 1
        assert summary.failed[0]["symbol"] == "ETHUSDT"


class TestLatestPayload:
    def test_cache_hit_reports_age_and_not_stale(self, db, isolated_redis):
        latest_service.refresh_latest_tickers(db, client=FakeTickerClient(), instruments=[db.get(CryptoInstrument, 1)])
        payload = latest_service.latest_market_payload(db, instrument=db.get(CryptoInstrument, 1))
        assert payload["source"] == "ticker_cache"
        assert payload["stale"] is False
        assert payload["age_seconds"] is not None and payload["age_seconds"] < 30
        assert payload["last_price"] == "79184.01"
        assert payload["display_label"] == "BTC/USDT · Binance · Spot"

    def test_cache_miss_falls_back_to_closed_candle_with_warning(self, db, isolated_redis):
        seed_candle(db, (latest_service._now_ms() // HOUR - 2) * HOUR)
        payload = latest_service.latest_market_payload(db, instrument=db.get(CryptoInstrument, 1))
        assert payload["source"] == "closed_candle_fallback"
        assert payload["stale"] is True
        assert "非实时" in payload["warning"]
        assert payload["last_price"] == "105"

    def test_no_data_reports_explicit_gap(self, db, isolated_redis):
        payload = latest_service.latest_market_payload(db, instrument=db.get(CryptoInstrument, 1))
        assert payload["source"] == "unavailable"
        assert payload["stale"] is True
        assert "数据不足" in payload["warning"]

    def test_stale_cache_event_marked_stale(self, db, isolated_redis):
        ticker = fake_ticker()
        object.__setattr__(ticker, "close_time_ms", latest_service._now_ms() - 10 * 60_000)
        isolated_redis[latest_service._cache_key(1)] = json.dumps({
            "instrument_id": 1, "provider": "binance_spot", "symbol": "BTCUSDT",
            "last_price": "1", "bid_price": "1", "ask_price": "1",
            "high_price_24h": "1", "low_price_24h": "1",
            "base_volume_24h": "1", "quote_volume_24h": "1",
            "event_time_ms": latest_service._now_ms() - 10 * 60_000,
            "received_at": "2026-08-26T00:00:00+00:00",
        })
        payload = latest_service.latest_market_payload(db, instrument=db.get(CryptoInstrument, 1))
        assert payload["source"] == "ticker_cache"
        assert payload["stale"] is True

    def test_cross_provider_cache_never_serves(self, db, isolated_redis):
        isolated_redis[latest_service._cache_key(1)] = json.dumps({
            "instrument_id": 1, "provider": "other_provider", "symbol": "BTCUSDT",
            "event_time_ms": latest_service._now_ms(),
        })
        payload = latest_service.latest_market_payload(db, instrument=db.get(CryptoInstrument, 1))
        assert payload["source"] != "ticker_cache"
