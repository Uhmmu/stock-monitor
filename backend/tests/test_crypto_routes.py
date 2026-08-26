"""WP 1.3 — crypto identity API contract tests.

Standalone app with just the crypto router; real bearer tokens against an
in-memory SQLite database seeded with the WP 0.3 fixture identities.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.crypto_routes import router
from app.auth import create_token
from app.database import Base, get_db
from app.models import User
from app.services.crypto import identity

IDENTITY_TABLES = [
    "crypto_assets",
    "crypto_symbol_aliases",
    "blockchains",
    "crypto_tokens",
    "crypto_protocols",
    "crypto_protocol_assets",
    "crypto_instruments",
    "crypto_provider_mappings",
    "crypto_funding_rates",
    "crypto_derivatives_metrics",
]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [Base.metadata.tables[name] for name in IDENTITY_TABLES] + [User.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed(db: Session) -> None:
    bitcoin, _ = identity.get_or_create_asset(db, slug="bitcoin", symbol="BTC", display_name="Bitcoin")
    identity.get_or_create_asset(db, slug="ethereum", symbol="ETH", display_name="Ether")
    usdt, _ = identity.get_or_create_asset(db, slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token")
    identity.get_or_create_asset(db, slug="hivemapper", symbol="HONEY", display_name="Hivemapper", asset_kind="token")
    identity.get_or_create_asset(db, slug="honey-alt", symbol="HONEY", display_name="Honey alt", asset_kind="token")
    spot, _ = identity.upsert_instrument(
        db, venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
        base_asset=bitcoin, quote_asset=usdt, tick_size="0.01",
    )
    perp, _ = identity.upsert_instrument(
        db, venue="binance", market="usdm_futures", provider_symbol="BTCUSDT", kind="perpetual",
        base_asset=bitcoin, quote_asset=usdt, settlement_asset=usdt,
    )
    eth, _ = identity.get_or_create_asset(db, slug="ethereum", symbol="ETH", display_name="Ether")
    eth_spot, _ = identity.upsert_instrument(
        db, venue="binance", market="spot", provider_symbol="ETHUSDT", kind="spot",
        base_asset=eth, quote_asset=usdt,
    )
    identity.set_provider_mapping(db, provider="binance_spot", provider_id="BTCUSDT", target=spot, method="provider_metadata", verified=True)
    identity.set_provider_mapping(db, provider="binance_usdm", provider_id="BTCUSDT", target=perp, method="provider_metadata")
    identity.set_provider_mapping(db, provider="binance_spot", provider_id="ETHUSDT", target=eth_spot, method="provider_metadata")
    db.commit()
    return None


@pytest.fixture()
def client(db):
    _seed(db)
    user = User(username="crypto-user", password_hash="x", role="user", status="active")
    db.add(user)
    db.commit()
    db.refresh(user)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {create_token(user.id)}"})
        yield test_client


def test_crypto_routes_require_authentication(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: (yield db)
    assert TestClient(app).get("/api/crypto/instruments").status_code == 401
    assert TestClient(app).get("/api/crypto/search", params={"q": "BTC"}).status_code == 401


def test_list_instruments_distinguishes_spot_and_perpetual(client):
    response = client.get("/api/crypto/instruments", params={"venue": "binance"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    btcusdt = [item for item in payload["items"] if item["provider_symbol"] == "BTCUSDT"]
    assert len(btcusdt) == 2
    assert {item["kind"] for item in btcusdt} == {"spot", "perpetual"}
    labels = {item["display_label"] for item in btcusdt}
    assert labels == {"BTC/USDT · Binance · Spot", "BTC/USDT · Binance · Perpetual"}


def test_list_instruments_filters_and_pagination_bounds(client):
    response = client.get("/api/crypto/instruments", params={"kind": "perpetual"})
    assert response.json()["total"] == 1
    response = client.get("/api/crypto/instruments", params={"limit": 2, "offset": 0})
    assert len(response.json()["items"]) == 2
    assert response.json()["limit"] == 2
    invalid = client.get("/api/crypto/instruments", params={"limit": 500})
    assert invalid.status_code == 422
    invalid = client.get("/api/crypto/instruments", params={"offset": -1})
    assert invalid.status_code == 422


def test_instrument_detail_returns_assets_and_mapping_evidence(client):
    listing = client.get("/api/crypto/instruments", params={"kind": "perpetual"}).json()
    instrument_id = listing["items"][0]["id"]
    detail = client.get(f"/api/crypto/instruments/{instrument_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["base_asset"]["slug"] == "bitcoin"
    assert payload["quote_asset"]["slug"] == "tether-usd"
    assert payload["settlement_asset"]["slug"] == "tether-usd"
    assert payload["calendar"] == "utc"
    assert payload["provider_mappings"][0]["provider"] == "binance_usdm"
    assert payload["provider_mappings"][0]["verified_at"] is None or payload["provider_mappings"][0]["verified_at"]


def test_instrument_detail_404(client):
    assert client.get("/api/crypto/instruments/99999").status_code == 404


def test_spot_candles_reject_derivative_price_authority(client):
    spot_id = client.get("/api/crypto/instruments", params={"kind": "spot"}).json()["items"][0]["id"]
    response = client.get(
        "/api/crypto/market/candles",
        params={"instrument_id": spot_id, "interval": "1h", "price_type": "mark"},
    )
    assert response.status_code == 422


def test_derivatives_routes_are_perpetual_only_and_truthful_when_empty(client):
    listing = client.get("/api/crypto/instruments").json()["items"]
    spot_id = next(item["id"] for item in listing if item["kind"] == "spot")
    perpetual_id = next(item["id"] for item in listing if item["kind"] == "perpetual")
    assert client.get("/api/crypto/derivatives", params={"instrument_id": spot_id}).status_code == 422

    history = client.get("/api/crypto/derivatives", params={"instrument_id": perpetual_id})
    assert history.status_code == 200
    assert history.json()["metrics"] == []
    regime = client.get("/api/crypto/derivatives/regime", params={"instrument_id": perpetual_id})
    assert regime.status_code == 200
    assert regime.json()["state"] == "INSUFFICIENT_DATA"


def test_search_returns_typed_stable_ids(client):
    payload = client.get("/api/crypto/search", params={"q": "BTCUSDT"}).json()
    assert payload["instruments"], "BTCUSDT prefix must match instruments"
    kinds = {item["kind"] for item in payload["instruments"]}
    assert kinds == {"spot", "perpetual"}
    for item in payload["instruments"]:
        assert item["object_type"] == "instrument" and isinstance(item["id"], int)

    assets = client.get("/api/crypto/search", params={"q": "HONEY"}).json()["assets"]
    assert {item["slug"] for item in assets} == {"hivemapper", "honey-alt"}, \
        "same-symbol collision surfaces both candidates as hints"

    empty = client.get("/api/crypto/search", params={"q": ""})
    assert empty.status_code == 422


def test_search_never_resolves_identity(client):
    payload = client.get("/api/crypto/search", params={"q": "BTC"}).json()
    assert "never identity authority" in payload["note"]
    assert payload["assets"], "asset hints are returned separately from instruments"
