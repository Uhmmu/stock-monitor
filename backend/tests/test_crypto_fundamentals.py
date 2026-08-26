"""WP 5.1/5.2 CoinGecko identity enrichment and market fundamentals."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.models import (
    Blockchain,
    CryptoAsset,
    CryptoAssetFundamentalSnapshot,
    CryptoAssetReference,
    CryptoInstrument,
    CryptoProtocol,
    CryptoProviderMapping,
    CryptoToken,
)
from app.services.crypto import fundamentals
from app.services.crypto.fundamentals import FundamentalPayloadError
from app.services.crypto.providers.coingecko import CoinGeckoClient, CoinGeckoError


FIXTURE = Path(__file__).parent / "fixtures" / "crypto" / "coingecko_markets.json"
ROOT = Path(__file__).parents[1]


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in (
        CryptoAsset,
        CryptoAssetReference,
        CryptoAssetFundamentalSnapshot,
        CryptoInstrument,
        CryptoProtocol,
        CryptoProviderMapping,
        Blockchain,
        CryptoToken,
    ):
        table.__table__.create(engine)
    with Session(engine) as session:
        btc = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin")
        eth = CryptoAsset(slug="ethereum", symbol="ETH", display_name="Ether")
        honey_one = CryptoAsset(slug="hivemapper", symbol="HONEY", display_name="Hivemapper", asset_kind="token")
        honey_two = CryptoAsset(slug="honey-alt", symbol="HONEY", display_name="Honey alt", asset_kind="token")
        session.add_all([btc, eth, honey_one, honey_two])
        session.commit()
        yield session


def _markets() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def test_coingecko_client_parses_market_fixture_without_credentials():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_markets())

    client = CoinGeckoClient(base_url="https://example.test/api/v3", transport=httpx.MockTransport(handler), max_retries=0)
    rows = client.markets(["bitcoin", "ethereum"])
    assert [row.provider_id for row in rows] == ["bitcoin", "ethereum"]
    assert calls[0].url.path == "/api/v3/coins/markets"
    assert "x-cg-demo-api-key" not in calls[0].headers


def test_coingecko_client_normalizes_provider_errors():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = CoinGeckoClient(transport=httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(CoinGeckoError) as exc:
        client.markets(["bitcoin"])
    assert exc.value.kind == "rate_limited" and exc.value.status_code == 429


def test_btc_eth_mapping_and_null_max_supply_are_persisted(db):
    rows = _markets()
    btc, eth = db.query(CryptoAsset).filter(CryptoAsset.slug.in_(["bitcoin", "ethereum"])).order_by(CryptoAsset.id).all()
    fetched_at = datetime(2026, 8, 26, 1, tzinfo=UTC)
    for asset, row in zip((btc, eth), rows):
        result = fundamentals.sync_asset_reference(db, row, asset=asset, fetched_at=fetched_at)
        assert result.status == "created"
        snapshot = fundamentals.persist_fundamental_snapshot(db, asset=asset, payload=row, fetched_at=fetched_at)
        assert snapshot.status == "created"
    db.commit()

    btc_mapping = db.query(CryptoProviderMapping).filter_by(provider="coingecko", provider_id="bitcoin", object_type="asset").one()
    eth_mapping = db.query(CryptoProviderMapping).filter_by(provider="coingecko", provider_id="ethereum", object_type="asset").one()
    assert {btc_mapping.asset_id, eth_mapping.asset_id} == {btc.id, eth.id}
    btc_snapshot = fundamentals.latest_fundamental_snapshot(db, btc.id)
    eth_snapshot = fundamentals.latest_fundamental_snapshot(db, eth.id)
    assert btc_snapshot.market_cap == Decimal("1590728580245")
    assert btc_snapshot.fully_diluted_valuation == Decimal("1590728580245")
    assert eth_snapshot.max_supply is None
    assert eth_snapshot.total_supply == Decimal("120681302.5213096")
    assert eth_snapshot.provider_timestamp is not None
    assert eth_snapshot.freshness_status == "fresh"


def test_symbol_collision_is_not_authoritative(db):
    result = fundamentals.sync_asset_reference(
        db,
        {"id": "honey-provider", "symbol": "honey", "name": "Honey"},
        fetched_at=datetime(2026, 8, 26, tzinfo=UTC),
    )
    assert result.status == "unresolved"
    assert "symbol-only" in (result.reason or "")
    assert db.query(CryptoProviderMapping).count() == 0


def test_chain_contract_evidence_precedes_canonical_mapping(db):
    eth = db.query(CryptoAsset).filter_by(slug="ethereum").one()
    chain = Blockchain(slug="ethereum", name="Ethereum", namespace="eip155", reference="1")
    db.add(chain)
    db.flush()
    token = CryptoToken(
        asset_id=eth.id,
        chain_id=chain.id,
        normalized_address="0xabc",
        decimals=18,
    )
    db.add(token)
    db.flush()
    payload = {"id": "wrapped-ether", "symbol": "WETH", "platforms": {"ethereum": "0xABC"}}
    result = fundamentals.sync_asset_reference(
        db,
        payload,
        known_mappings={"wrapped-ether": "hivemapper"},
    )
    assert result.status == "created" and result.asset_id == eth.id and result.method == "chain_contract"


def test_idempotent_snapshot_and_revision_on_source_change(db):
    btc = db.query(CryptoAsset).filter_by(slug="bitcoin").one()
    payload = _markets()[0]
    fetched_at = datetime(2026, 8, 26, 1, tzinfo=UTC)
    first = fundamentals.persist_fundamental_snapshot(db, asset=btc, payload=payload, fetched_at=fetched_at)
    second = fundamentals.persist_fundamental_snapshot(db, asset=btc, payload=payload, fetched_at=fetched_at)
    assert (first.status, second.status, db.query(CryptoAssetFundamentalSnapshot).count()) == ("created", "unchanged", 1)
    revised = {**payload, "market_cap": payload["market_cap"] + 1}
    updated = fundamentals.persist_fundamental_snapshot(db, asset=btc, payload=revised, fetched_at=fetched_at)
    snapshot = fundamentals.latest_fundamental_snapshot(db, btc.id)
    assert updated.status == "updated" and snapshot.revision == 1
    assert snapshot.market_cap == Decimal("1590728580246")


def test_batch_sync_uses_asset_detail_for_reference_metadata(db):
    btc = db.query(CryptoAsset).filter_by(slug="bitcoin").one()

    class DetailClient:
        def markets(self, _ids):
            row = _markets()[0]
            return [type("Row", (), {"provider_id": "bitcoin", "payload": row})()]

        def asset_detail(self, provider_id):
            assert provider_id == "bitcoin"
            return {
                **_markets()[0],
                "categories": ["Layer 1"],
                "links": {"homepage": ["https://bitcoin.org"], "blockchain_site": []},
                "platforms": {},
            }

    summary = fundamentals.sync_coingecko_assets(db, client=DetailClient(), assets=[btc])
    reference = db.query(CryptoAssetReference).filter_by(asset_id=btc.id, provider="coingecko").one()
    assert summary.status == "success"
    assert reference.categories == ["Layer 1"]
    assert reference.website_urls == ["https://bitcoin.org"]


def test_negative_provider_value_is_rejected_without_fabrication(db):
    btc = db.query(CryptoAsset).filter_by(slug="bitcoin").one()
    with pytest.raises(FundamentalPayloadError):
        fundamentals.persist_fundamental_snapshot(
            db,
            asset=btc,
            payload={"id": "bitcoin", "market_cap": -1, "last_updated": "2026-08-26T00:00:00Z"},
        )
    assert db.query(CryptoAssetFundamentalSnapshot).count() == 0


def test_batch_failure_keeps_last_good_and_other_rows_are_isolated(db):
    btc, eth = db.query(CryptoAsset).filter(CryptoAsset.slug.in_(["bitcoin", "ethereum"])).order_by(CryptoAsset.id).all()
    fetched_at = datetime(2026, 8, 26, 1, tzinfo=UTC)
    fundamentals.persist_fundamental_snapshot(db, asset=btc, payload=_markets()[0], fetched_at=fetched_at)
    db.commit()

    class FailingClient:
        def markets(self, _ids):
            raise CoinGeckoError("timeout", "provider unavailable")

    summary = fundamentals.sync_coingecko_assets(db, client=FailingClient(), assets=[btc, eth], fetched_at=fetched_at)
    assert summary.status == "failed" and summary.errors[0]["kind"] == "timeout"
    assert fundamentals.latest_fundamental_snapshot(db, btc.id).market_cap == Decimal("1590728580245")

    class MixedClient:
        def markets(self, _ids):
            return [
                type("Row", (), {"provider_id": "bitcoin", "payload": _markets()[0]})(),
                type("Row", (), {"provider_id": "ethereum", "payload": {"id": "ethereum", "market_cap": -1}})(),
            ]

    summary = fundamentals.sync_coingecko_assets(db, client=MixedClient(), assets=[btc, eth], fetched_at=fetched_at)
    assert summary.status == "partial" and summary.mapped == 1 and summary.errors
    assert fundamentals.latest_fundamental_snapshot(db, btc.id) is not None
    assert fundamentals.latest_fundamental_snapshot(db, eth.id) is None


def _load_migration(filename: str):
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_0072_migration_round_trip_on_sqlite():
    engine = create_engine("sqlite://")
    chain = [
        "0066_crypto_identity_assets.py", "0067_crypto_chain_token_protocol.py",
        "0068_crypto_instruments.py", "0069_crypto_collection_runs.py",
        "0070_market_candles.py", "0071_crypto_derivatives.py",
        "0072_crypto_asset_fundamentals.py",
    ]
    modules = [_load_migration(name) for name in chain]
    with engine.begin() as connection:
        originals = [module.op for module in modules]
        try:
            for module in modules:
                module.op = Operations(MigrationContext.configure(connection))
                module.upgrade()
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"crypto_asset_references", "crypto_asset_fundamental_snapshots"} <= tables
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(crypto_asset_fundamental_snapshots)"))}
            assert {"market_cap", "fully_diluted_valuation", "circulating_supply", "total_supply", "max_supply", "market_cap_rank", "fetched_at"} <= columns
            modules[-1].downgrade()
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "crypto_asset_references" not in tables and "crypto_asset_fundamental_snapshots" not in tables
            modules[-1].upgrade()
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert {"crypto_asset_references", "crypto_asset_fundamental_snapshots"} <= tables
        finally:
            for module, original in zip(modules, originals):
                module.op = original
