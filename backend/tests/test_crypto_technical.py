"""WP 3.3 — crypto technical analysis tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.crypto_routes import router
from app.auth import create_token
from app.database import Base, get_db
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
    User,
)
from app.services.crypto import candles as candle_repo
from app.services.crypto import technical as crypto_technical
from app.services.crypto.providers.binance import Kline

HOUR = 3_600_000


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [
        "crypto_assets", "crypto_symbol_aliases", "blockchains", "crypto_tokens",
        "crypto_protocols", "crypto_protocol_assets", "crypto_instruments",
        "crypto_provider_mappings", "market_candles", "crypto_collection_runs",
        "crypto_sync_states", "users",
    ]
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in tables])
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
    engine.dispose()


def seed_candles(session, count: int, interval: str = "1h", start: int = HOUR) -> None:
    modulo = {"1h": HOUR, "4h": 4 * HOUR, "1d": 24 * HOUR}[interval]
    price = Decimal("100")
    klines = []
    for index in range(count):
        open_time = start + index * modulo
        close_price = price + Decimal(index + 1)
        klines.append(Kline(
            market="spot", symbol="BTCUSDT", interval=interval,
            open_time_ms=open_time, close_time_ms=open_time + modulo - 1,
            open=price, high=close_price + Decimal(2), low=price - Decimal(2), close=close_price,
            base_volume=Decimal("10"), quote_volume=Decimal("1000"), trades=10,
            taker_buy_base_volume=Decimal("4"), taker_buy_quote_volume=Decimal("400"),
            received_at="2100-01-01T00:00:00+00:00",
        ))
        price = close_price
    candle_repo.persist_klines(session, instrument_id=1, provider="binance_spot", klines=klines)
    session.commit()


class TestTechnicalPayload:
    def test_insufficient_history_returns_explicit_gap(self, db):
        seed_candles(db, 10)
        payload = crypto_technical.crypto_technical_payload(db, instrument_id=1, interval="1h")
        assert payload["status"] == "insufficient"
        assert "数据不足" in payload["reason"]
        assert payload["candle_count"] == 10 and payload["minimum_required"] == 30
        assert set(payload["omissions"]) >= {"rsi", "macd"}

    def test_ready_payload_has_versioned_indicators_and_hash(self, db):
        seed_candles(db, 60)
        payload = crypto_technical.crypto_technical_payload(db, instrument_id=1, interval="1h")
        assert payload["status"] == "ready"
        assert payload["version"] == "crypto-v1"
        assert payload["parameter_set_version"] == "crypto-indicators-v1"
        last = payload["last"]
        assert last["rsi"] is not None and 0 <= last["rsi"] <= 100
        assert last["atr"] is not None and last["atr"] > 0
        assert last["bollinger_upper"] >= last["bollinger_middle"] >= last["bollinger_lower"]
        assert payload["input_hash"] and len(payload["input_hash"]) == 64
        assert payload["data_through_ms"] > 0
        assert payload["omissions"] == []

    def test_deterministic_same_input_same_hash(self, db):
        seed_candles(db, 50)
        one = crypto_technical.crypto_technical_payload(db, instrument_id=1, interval="1h")
        two = crypto_technical.crypto_technical_payload(db, instrument_id=1, interval="1h")
        assert one["input_hash"] == two["input_hash"]
        assert one["last"] == two["last"]

    def test_invalid_interval_rejected(self, db):
        payload = crypto_technical.crypto_technical_payload(db, instrument_id=1, interval="5m")
        assert payload["status"] == "invalid"

    def test_uses_only_persisted_candles_no_252_assumption(self, db):
        seed_candles(db, 35)
        payload = crypto_technical.crypto_technical_payload(db, instrument_id=1, interval="1h")
        assert payload["status"] == "ready"
        assert payload["candle_count"] == 35  # works below any 252-day equity minimum


def _client(db):
    user = User(username="tech-user", password_hash="x", role="user", status="active")
    db.add(user)
    db.commit()
    db.refresh(user)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {create_token(user.id)}"})
    return client


class TestTechnicalApi:
    def test_requires_auth(self, db):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: (yield db)
        response = TestClient(app).get("/api/crypto/market/technical", params={"instrument_id": 1})
        assert response.status_code == 401

    def test_insufficient_renders_gap_not_error(self, db):
        seed_candles(db, 5)
        response = _client(db).get("/api/crypto/market/technical", params={"instrument_id": 1, "interval": "1h"})
        assert response.status_code == 200
        assert response.json()["status"] == "insufficient"

    def test_ready_payload(self, db):
        seed_candles(db, 60)
        response = _client(db).get("/api/crypto/market/technical", params={"instrument_id": 1, "interval": "1h"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["last"]["rsi"] is not None

    def test_invalid_interval_422(self, db):
        response = _client(db).get("/api/crypto/market/technical", params={"instrument_id": 1, "interval": "5m"})
        assert response.status_code == 422

    def test_unknown_instrument_404(self, db):
        response = _client(db).get("/api/crypto/market/technical", params={"instrument_id": 999})
        assert response.status_code == 404
