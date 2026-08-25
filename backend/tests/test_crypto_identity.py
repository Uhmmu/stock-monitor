"""WP 1.1-1.2 — canonical crypto identity repository tests.

Covers model constraints, idempotent upserts, explicit retargeting, chain/
token/protocol identities and replay of the WP 0.3 identity fixture cases
against the real service/tables.
"""

import importlib.util
import json
import pathlib

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
)
from app.services.crypto import identity

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "crypto" / "identity_cases.json"
MIGRATIONS_DIR = pathlib.Path(__file__).parents[1] / "alembic" / "versions"

IDENTITY_TABLES = (
    CryptoAsset,
    CryptoSymbolAlias,
    Blockchain,
    CryptoToken,
    CryptoProtocol,
    CryptoProtocolAsset,
    CryptoInstrument,
    CryptoProviderMapping,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in IDENTITY_TABLES:
        table.__table__.create(engine)
    with Session(engine) as session:
        yield session


def seed_core_assets(session):
    bitcoin, _ = identity.get_or_create_asset(session, slug="bitcoin", symbol="BTC", display_name="Bitcoin")
    ethereum, _ = identity.get_or_create_asset(session, slug="ethereum", symbol="ETH", display_name="Ether")
    weth, _ = identity.get_or_create_asset(
        session, slug="wrapped-ether", symbol="WETH", display_name="Wrapped Ether",
        asset_kind="token", wraps_asset_slug="ethereum",
    )
    identity.get_or_create_asset(session, slug="tether-usd", symbol="USDT", display_name="Tether USD", asset_kind="token")
    return bitcoin, ethereum, weth


def seed_chains_tokens(session):
    ethereum_chain, _ = identity.get_or_create_blockchain(
        session, slug="ethereum", name="Ethereum", namespace="eip155", reference="1", native_asset_slug="ethereum"
    )
    arbitrum, _ = identity.get_or_create_blockchain(
        session, slug="arbitrum-one", name="Arbitrum One", namespace="eip155", reference="42161"
    )
    weth_asset = identity.get_asset_by_slug(session, "wrapped-ether")
    token_l1, _ = identity.get_or_create_token(
        session, asset=weth_asset, chain=ethereum_chain,
        address="0xC02AAA39B223FE8D0A0E5C4F27EAD9083C756CC2", decimals=18,
    )
    token_l2, _ = identity.get_or_create_token(
        session, asset=weth_asset, chain=arbitrum,
        address="0x82af49447d8a07e3bd95bd0d56f35241523fbab1", decimals=18,
    )
    return ethereum_chain, arbitrum, token_l1, token_l2


def seed_instruments(session):
    """Seed BTC/ETH/USDT assets and both BTCUSDT instruments from the fixture."""
    bitcoin, _, _ = seed_core_assets(session)
    eth = identity.get_asset_by_slug(session, "ethereum")
    usdt = identity.get_asset_by_slug(session, "tether-usd")
    spot, _ = identity.upsert_instrument(
        session, venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
        base_asset=bitcoin, quote_asset=usdt,
        tick_size="0.01", step_size="0.00001", min_notional="5",
        filters={"PRICE_FILTER": {"tickSize": "0.01"}, "LOT_SIZE": {"stepSize": "0.00001"}},
    )
    perpetual, _ = identity.upsert_instrument(
        session, venue="binance", market="usdm_futures", provider_symbol="BTCUSDT", kind="perpetual",
        base_asset=bitcoin, quote_asset=usdt, settlement_asset=usdt,
        tick_size="0.10", step_size="0.001", min_notional="50", quantity_precision=3,
    )
    identity.set_provider_mapping(
        session, provider="binance_spot", provider_id="BTCUSDT", target=spot, method="provider_metadata"
    )
    identity.set_provider_mapping(
        session, provider="binance_usdm", provider_id="BTCUSDT", target=perpetual, method="provider_metadata"
    )
    return spot, perpetual


class TestInstruments:
    def test_spot_and_perpetual_same_symbol_are_distinct(self, db):
        seed_core_assets(db)
        spot, perpetual = seed_instruments(db)
        assert spot.id != perpetual.id
        assert spot.kind == "spot" and perpetual.kind == "perpetual"
        assert spot.market == "spot" and perpetual.market == "usdm_futures"
        assert perpetual.settlement_asset_id is not None and spot.settlement_asset_id is None

    def test_instrument_upsert_is_idempotent_and_updates_metadata(self, db):
        seed_core_assets(db)
        bitcoin = identity.get_asset_by_slug(db, "bitcoin")
        usdt = identity.get_asset_by_slug(db, "tether-usd")
        spot, _ = identity.upsert_instrument(
            db, venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
            base_asset=bitcoin, quote_asset=usdt, status="trading",
        )
        again, created_again = identity.upsert_instrument(
            db, venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
            base_asset=bitcoin, quote_asset=usdt, status="halted", tick_size="0.02",
        )
        assert created_again is False and spot.id == again.id
        assert again.status == "halted" and str(again.tick_size) == "0.02"

    def test_delisted_instrument_row_is_preserved(self, db):
        seed_core_assets(db)
        spot, _ = seed_instruments(db)
        bitcoin = identity.get_asset_by_slug(db, "bitcoin")
        usdt = identity.get_asset_by_slug(db, "tether-usd")
        updated, created = identity.upsert_instrument(
            db, venue="binance", market="spot", provider_symbol="BTCUSDT", kind="spot",
            base_asset=bitcoin, quote_asset=usdt, status="delisted",
        )
        assert created is False and updated.id == spot.id
        assert updated.status == "delisted"

    def test_resolve_instrument_requires_kind(self, db):
        seed_core_assets(db)
        spot, perpetual = seed_instruments(db)
        resolved = identity.resolve_instrument(db, venue="binance", provider_symbol="BTCUSDT", kind="perpetual")
        assert resolved.status == "resolved" and resolved.instrument.id == perpetual.id
        missing = identity.resolve_instrument(db, venue="binance", provider_symbol="BTCUSDT", kind="future")
        assert missing.status == "unresolved"
        assert "spot and perpetual" in missing.reason

    def test_provider_namespaces_distinguish_markets(self, db):
        seed_core_assets(db)
        spot, perpetual = seed_instruments(db)
        spot_mapping = identity.resolve_provider_id(
            db, provider="binance_spot", object_type="instrument", provider_id="BTCUSDT"
        )
        perp_mapping = identity.resolve_provider_id(
            db, provider="binance_usdm", object_type="instrument", provider_id="BTCUSDT"
        )
        assert spot_mapping.instrument.id == spot.id
        assert perp_mapping.instrument.id == perpetual.id
        assert spot_mapping.instrument.id != perp_mapping.instrument.id

    def test_display_labels_match_fixture(self, db):
        seed_core_assets(db)
        spot, perpetual = seed_instruments(db)
        bitcoin = identity.get_asset_by_slug(db, "bitcoin")
        usdt = identity.get_asset_by_slug(db, "tether-usd")
        assert identity.instrument_display_label(spot, bitcoin, usdt) == "BTC/USDT · Binance · Spot"
        assert identity.instrument_display_label(perpetual, bitcoin, usdt) == "BTC/USDT · Binance · Perpetual"
        assert identity.asset_display_label(bitcoin) == "BTC · Bitcoin"

    def test_invalid_kind_rejected(self, db):
        seed_core_assets(db)
        bitcoin = identity.get_asset_by_slug(db, "bitcoin")
        usdt = identity.get_asset_by_slug(db, "tether-usd")
        with pytest.raises(IntegrityError):
            db.add(CryptoInstrument(
                venue="binance", market="spot", provider_symbol="BTCUSDT", kind="option",
                base_asset_id=bitcoin.id, quote_asset_id=usdt.id,
            ))
            db.flush()


class TestAssetConstraints:
    def test_slug_unique_enforced(self, db):
        seed_core_assets(db)
        with pytest.raises(IntegrityError):
            db.add(CryptoAsset(slug="bitcoin", symbol="BTC2", display_name="Duplicate"))
            db.flush()

    def test_two_assets_may_share_symbol(self, db):
        identity.get_or_create_asset(db, slug="hivemapper", symbol="HONEY", display_name="Hivemapper", asset_kind="token")
        identity.get_or_create_asset(db, slug="honey-alt", symbol="HONEY", display_name="Honey alt", asset_kind="token")
        assert len(identity.find_assets_by_symbol(db, "HONEY")) == 2

    def test_invalid_kind_rejected(self, db):
        db.add(CryptoAsset(slug="bad", symbol="BAD", display_name="Bad", asset_kind="derivatives"))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_get_or_create_is_idempotent(self, db):
        one, created_one = identity.get_or_create_asset(db, slug="bitcoin", symbol="BTC", display_name="Bitcoin")
        two, created_two = identity.get_or_create_asset(db, slug="bitcoin", symbol="BTC", display_name="Bitcoin")
        assert created_one is True and created_two is False and one.id == two.id

    def test_wraps_relation_links_weth_to_eth(self, db):
        _, ethereum, weth = seed_core_assets(db)
        assert weth.wraps_asset_id == ethereum.id
        assert weth.id != ethereum.id


class TestSymbolResolution:
    def test_xbt_alias_resolves_to_bitcoin(self, db):
        bitcoin, _, _ = seed_core_assets(db)
        identity.set_symbol_alias(db, symbol="XBT", asset=bitcoin, reason="ISO ticker")
        result = identity.resolve_symbol(db, "XBT")
        assert result.status == "resolved_via_alias"
        assert result.asset.slug == "bitcoin"

    def test_unique_symbol_is_only_a_search_hint(self, db):
        seed_core_assets(db)
        result = identity.resolve_symbol(db, "BTC")
        assert result.status == "search_hint_only"
        assert result.asset.slug == "bitcoin"

    def test_same_symbol_collision_is_unresolved(self, db):
        identity.get_or_create_asset(db, slug="hivemapper", symbol="HONEY", display_name="Hivemapper", asset_kind="token")
        identity.get_or_create_asset(db, slug="honey-alt", symbol="HONEY", display_name="Honey alt", asset_kind="token")
        result = identity.resolve_symbol(db, "HONEY")
        assert result.status == "unresolved"
        assert result.candidates == ("hivemapper", "honey-alt")

    def test_unknown_symbol_unresolved(self, db):
        seed_core_assets(db)
        result = identity.resolve_symbol(db, "NOSUCH")
        assert result.status == "unresolved"
        assert result.asset is None

    def test_alias_retarget_conflict_raises(self, db):
        bitcoin, ethereum, _ = seed_core_assets(db)
        identity.set_symbol_alias(db, symbol="XBT", asset=bitcoin)
        with pytest.raises(identity.MappingConflictError):
            identity.set_symbol_alias(db, symbol="XBT", asset=ethereum)


class TestChainsAndTokens:
    def test_chain_idempotent_and_namespace_unique(self, db):
        seed_core_assets(db)
        one, created = identity.get_or_create_blockchain(
            db, slug="ethereum", name="Ethereum", namespace="eip155", reference="1", native_asset_slug="ethereum"
        )
        two, created_two = identity.get_or_create_blockchain(
            db, slug="ethereum", name="Ethereum", namespace="eip155", reference="1"
        )
        assert created and not created_two and one.id == two.id
        assert one.native_asset_id == identity.get_asset_by_slug(db, "ethereum").id
        with pytest.raises(IntegrityError):
            db.add(Blockchain(slug="eth-copy", name="Copy", namespace="eip155", reference="1"))
            db.flush()

    def test_weth_deployments_on_two_chains_share_one_asset(self, db):
        seed_core_assets(db)
        ethereum_chain, arbitrum, token_l1, token_l2 = seed_chains_tokens(db)
        assert token_l1.id != token_l2.id
        assert token_l1.asset_id == token_l2.asset_id
        assert token_l1.chain_id == ethereum_chain.id and token_l2.chain_id == arbitrum.id
        # uppercase input normalizes to the stored lowercase row on EVM chains
        assert identity.get_token_by_chain_address(
            db, ethereum_chain, "0xC02AAA39B223FE8D0A0E5C4F27EAD9083C756CC2"
        ).id == token_l1.id

    def test_same_address_different_chain_is_a_distinct_token(self, db):
        seed_core_assets(db)
        ethereum_chain, arbitrum, _, _ = seed_chains_tokens(db)
        address = "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"
        token, created = identity.get_or_create_token(
            db, asset=identity.get_asset_by_slug(db, "wrapped-ether"), chain=ethereum_chain, address=address
        )
        assert created is True  # same address on chain 1 did not collide with chain 42161

    def test_resolve_token_exact_and_unknown(self, db):
        seed_core_assets(db)
        _, _, token_l1, _ = seed_chains_tokens(db)
        result = identity.resolve_token(db, chain_slug="ethereum", address="0xC02AAA39B223FE8D0A0E5C4F27EAD9083C756CC2")
        assert result.status == "resolved" and result.token.id == token_l1.id
        assert result.asset.slug == "wrapped-ether"
        unknown = identity.resolve_token(db, chain_slug="ethereum", address="0x000000000000000000000000000000000000dEaD")
        assert unknown.status == "unresolved"
        assert "never create" in unknown.reason
        unknown_chain = identity.resolve_token(db, chain_slug="nochain", address="0x00")
        assert unknown_chain.status == "unresolved"

    def test_eth_native_coin_needs_no_token_row(self, db):
        bitcoin, ethereum, _ = seed_core_assets(db)
        chain, _ = identity.get_or_create_blockchain(
            db, slug="ethereum", name="Ethereum", namespace="eip155", reference="1", native_asset_slug="ethereum"
        )
        assert chain.native_asset_id == ethereum.id
        tokens = db.query(CryptoToken).filter_by(asset_id=ethereum.id).all()
        assert tokens == []

    def test_bridged_relation_links_token_rows(self, db):
        seed_core_assets(db)
        ethereum_chain, arbitrum, token_l1, _ = seed_chains_tokens(db)
        # a canonical bridged deployment: distinct address, origin token link
        bridged, created = identity.get_or_create_token(
            db, asset=identity.get_asset_by_slug(db, "wrapped-ether"), chain=arbitrum,
            address="0xDeadBeef00000000000000000000000000000001", bridged_from_token=token_l1,
        )
        assert created is True
        assert bridged.bridged_from_token_id == token_l1.id
        assert bridged.id != token_l1.id


class TestProtocols:
    def test_protocol_without_token_coexists(self, db):
        seed_core_assets(db)
        protocol, created = identity.get_or_create_protocol(
            db, slug="uniswap", name="Uniswap", category="dex", website="https://uniswap.org"
        )
        assert created
        again, created_again = identity.get_or_create_protocol(db, slug="uniswap", name="Uniswap")
        assert not created_again and protocol.id == again.id
        # a protocol exists with zero linked assets and zero tokens
        assert db.query(CryptoProtocolAsset).filter_by(protocol_id=protocol.id).count() == 0

    def test_protocol_asset_roles_idempotent_and_multi(self, db):
        seed_core_assets(db)
        protocol, _ = identity.get_or_create_protocol(db, slug="uniswap", name="Uniswap")
        uni, _ = identity.get_or_create_asset(db, slug="uniswap", symbol="UNI", display_name="Uniswap", asset_kind="token")
        link_one, created = identity.link_protocol_asset(db, protocol=protocol, asset=uni, role="governance")
        link_two, created_again = identity.link_protocol_asset(db, protocol=protocol, asset=uni, role="governance")
        assert created and not created_again and link_one.id == link_two.id
        identity.link_protocol_asset(db, protocol=protocol, asset=uni, role="fee")
        assert db.query(CryptoProtocolAsset).filter_by(protocol_id=protocol.id).count() == 2


class TestProviderMappings:
    def test_mapping_roundtrip_and_idempotent_upsert(self, db):
        bitcoin, _, _ = seed_core_assets(db)
        m1 = identity.set_provider_mapping(
            db, provider="coingecko", provider_id="bitcoin", target=bitcoin,
            method="verified_seed", verified=True,
        )
        m2 = identity.set_provider_mapping(
            db, provider="coingecko", provider_id="bitcoin", target=bitcoin, method="provider_metadata"
        )
        assert m1.id == m2.id
        assert m2.verified_at is not None
        db.commit()

    def test_one_provider_id_cannot_map_to_two_targets(self, db):
        bitcoin, ethereum, _ = seed_core_assets(db)
        identity.set_provider_mapping(db, provider="coingecko", provider_id="weth", target=ethereum)
        with pytest.raises(identity.MappingConflictError):
            identity.set_provider_mapping(db, provider="coingecko", provider_id="weth", target=bitcoin)

    def test_unique_constraint_enforces_single_target(self, db):
        bitcoin, ethereum, _ = seed_core_assets(db)
        identity.set_provider_mapping(db, provider="coingecko", provider_id="bitcoin", target=bitcoin)
        db.flush()
        db.add(CryptoProviderMapping(provider="coingecko", object_type="asset", provider_id="bitcoin", asset_id=ethereum.id))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_instrument_target_must_use_matching_column(self, db):
        seed_core_assets(db)
        spot, _ = seed_instruments(db)
        bitcoin = identity.get_asset_by_slug(db, "bitcoin")
        db.commit()
        # object_type must match the target column in both directions
        with pytest.raises(IntegrityError):
            db.add(CryptoProviderMapping(
                provider="binance_spot", object_type="instrument", provider_id="ETHUSDT", asset_id=bitcoin.id
            ))
            db.flush()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.add(CryptoProviderMapping(
                provider="binance_spot", object_type="asset", provider_id="BTCUSDT", instrument_id=spot.id
            ))
            db.flush()
        db.rollback()

    def test_token_target_mapping_roundtrip(self, db):
        seed_core_assets(db)
        _, _, token_l1, _ = seed_chains_tokens(db)
        mapping = identity.set_provider_mapping(
            db, provider="coingecko", provider_id="ethereum/0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            target=token_l1, method="verified_seed", verified=True,
        )
        result = identity.resolve_provider_id(
            db, provider="coingecko", object_type="token",
            provider_id="ethereum/0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        )
        assert result.status == "resolved"
        assert result.token.id == token_l1.id
        assert result.asset.slug == "wrapped-ether"
        assert mapping.object_type == "token"

    def test_token_mapping_cannot_use_asset_object_type(self, db):
        seed_core_assets(db)
        _, _, token_l1, _ = seed_chains_tokens(db)
        db.commit()
        # object_type must match the target column: a token target can never
        # be recorded through the asset column
        with pytest.raises(IntegrityError):
            db.add(CryptoProviderMapping(
                provider="coingecko", object_type="token", provider_id="bad-target", asset_id=token_l1.id
            ))
            db.flush()
        db.rollback()

    def test_explicit_retarget_allowed_and_audited(self, db):
        bitcoin, ethereum, _ = seed_core_assets(db)
        identity.set_provider_mapping(db, provider="coingecko", provider_id="weth", target=ethereum)
        mapping = identity.retarget_provider_mapping(db, provider="coingecko", provider_id="weth", target=bitcoin)
        assert mapping.asset_id == bitcoin.id
        assert mapping.token_id is None and mapping.protocol_id is None
        assert mapping.method == "manual_retarget"
        assert mapping.verified_at is not None

    def test_verify_keeps_target(self, db):
        bitcoin, _, _ = seed_core_assets(db)
        mapping = identity.set_provider_mapping(db, provider="coingecko", provider_id="bitcoin", target=bitcoin)
        identity.verify_provider_mapping(db, mapping)
        assert mapping.verified_at is not None
        assert mapping.asset_id == bitcoin.id

    def test_exact_provider_id_resolution(self, db):
        bitcoin, _, _ = seed_core_assets(db)
        identity.set_provider_mapping(db, provider="coingecko", provider_id="bitcoin", target=bitcoin)
        result = identity.resolve_provider_id(db, provider="coingecko", object_type="asset", provider_id="bitcoin")
        assert result.resolved and result.asset.slug == "bitcoin"

    def test_bare_binance_namespace_is_unresolved(self, db):
        seed_core_assets(db)
        result = identity.resolve_provider_id(db, provider="binance", object_type="instrument", provider_id="BTCUSDT")
        assert result.status == "unresolved"
        assert "market" in result.reason

    def test_unknown_provider_id_unresolved(self, db):
        seed_core_assets(db)
        result = identity.resolve_provider_id(db, provider="coingecko", object_type="asset", provider_id="no-such-coin")
        assert result.status == "unresolved"


class TestIdentityFixtureReplay:
    """Replay the WP 0.3 fixture cases against real tables."""

    @pytest.fixture()
    def seeded(self, db):
        fixture = json.loads(FIXTURE_PATH.read_text())
        for asset in fixture["assets"]:
            if asset["asset_kind"] == "alias_placeholder":
                continue
            identity.get_or_create_asset(
                db,
                slug=asset["slug"],
                symbol=asset["symbol"],
                display_name=asset["display_name"],
                asset_kind=asset["asset_kind"],
                wraps_asset_slug=asset.get("wraps_asset_slug"),
            )
        for chain in fixture["chains"]:
            identity.get_or_create_blockchain(
                db, slug=chain["slug"], name=chain["slug"].replace("-", " ").title(),
                namespace=chain["namespace"], reference=chain["reference"],
            )
        for token in fixture["tokens"]:
            identity.get_or_create_token(
                db,
                asset=identity.get_asset_by_slug(db, token["asset_slug"]),
                chain=identity.get_blockchain_by_slug(db, token["chain_slug"]),
                address=token["normalized_address"],
                decimals=token["decimals"],
            )
        for alias in fixture["symbol_aliases"]:
            asset = identity.get_asset_by_slug(db, alias["target_asset_slug"])
            identity.set_symbol_alias(db, symbol=alias["symbol"], asset=asset, reason=alias["reason"])
        for instrument in fixture["instruments"]:
            key = instrument["instrument_key"]
            identity.upsert_instrument(
                db,
                venue=key["venue"],
                market=instrument["market"],
                provider_symbol=key["provider_symbol"],
                kind=key["kind"],
                base_asset=identity.get_asset_by_slug(db, instrument["base_asset_slug"]),
                quote_asset=identity.get_asset_by_slug(db, instrument["quote_asset_slug"]),
                settlement_asset=(
                    identity.get_asset_by_slug(db, instrument["settlement_asset_slug"])
                    if instrument.get("settlement_asset_slug")
                    else None
                ),
            )
        for mapping in fixture["provider_mappings"]:
            if mapping["object_type"] == "asset":
                target = identity.get_asset_by_slug(db, mapping["target"]["slug"])
            elif mapping["object_type"] == "instrument":
                target = identity.get_instrument(
                    db,
                    venue=mapping["target"]["venue"],
                    provider_symbol=mapping["target"]["provider_symbol"],
                    kind=mapping["target"]["kind"],
                )
            else:
                continue
            identity.set_provider_mapping(
                db, provider=mapping["provider"], provider_id=mapping["provider_id"],
                target=target, method="verified_seed", verified=True,
            )
        return fixture

    def test_cases_agree_with_fixture(self, seeded, db):
        seen = set()
        for case in seeded["resolution_cases"]:
            case_id = case["case_id"]
            expected = case["expected"]
            query = case["input"]
            if "provider" in query:
                result = identity.resolve_provider_id(db, **query)
                if expected["status"] == "resolved" and result.status == "resolved":
                    target = result.instrument if expected.get("object_type") == "instrument" else result.asset
                    for field in ("venue", "provider_symbol", "kind"):
                        if field in expected:
                            assert getattr(target, field) == expected[field], case_id
                    if "base_asset_slug" in expected:
                        assert result.asset.slug == expected["base_asset_slug"], case_id
            elif "chain_slug" in query:
                result = identity.resolve_token(db, chain_slug=query["chain_slug"], address=query["normalized_address"])
            elif "symbol" in query:
                result = identity.resolve_symbol(db, query["symbol"])
            else:
                continue
            seen.add(case_id)
            assert result.status == expected["status"], case_id
            if expected["status"].startswith("resolved"):
                assert result.asset is not None, case_id
                if "slug" in expected:
                    assert result.asset.slug == expected["slug"], case_id
                if "asset_slug" in expected and expected.get("object_type") == "token":
                    assert result.asset.slug == expected["asset_slug"], case_id
                    assert result.token is not None, case_id
            if "candidates" in expected:
                assert list(result.candidates) == expected["candidates"], case_id
        assert seen == {
            "binance_spot_btcusdt",
            "binance_usdm_btcusdt_perpetual",
            "binance_symbol_without_market_namespace",
            "coingecko_bitcoin",
            "coingecko_weth_is_not_eth",
            "weth_token_on_ethereum",
            "weth_token_on_arbitrum_same_asset",
            "xbt_alias_resolves_to_bitcoin",
            "same_symbol_honey_ambiguous",
            "symbol_only_btc_not_authority",
            "unknown_token_address",
        }

    def test_weth_distinct_from_eth(self, seeded, db):
        weth = identity.resolve_provider_id(db, provider="coingecko", object_type="asset", provider_id="weth")
        eth = identity.resolve_provider_id(db, provider="coingecko", object_type="asset", provider_id="ethereum")
        assert weth.asset.id != eth.asset.id
        assert weth.asset.wraps_asset_id == eth.asset.id


def test_crypto_instruments_migration_round_trip_on_sqlite():
    migration = _load_migration("crypto_instruments_migration", "0068_crypto_instruments.py")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        prior = [
            _load_migration("prior_0066", "0066_crypto_identity_assets.py"),
            _load_migration("prior_0067", "0067_crypto_chain_token_protocol.py"),
        ]
        originals = []
        for mod in prior:
            originals.append(mod.op)
            mod.op = Operations(MigrationContext.configure(connection))
            mod.upgrade()
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "crypto_instruments" in tables
            columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(crypto_provider_mappings)"))
            }
            assert "instrument_id" in columns

            connection.execute(text("""
                INSERT INTO crypto_assets (slug, symbol, display_name, asset_kind, status)
                VALUES ('bitcoin', 'BTC', 'Bitcoin', 'coin', 'active')
            """))
            connection.execute(text("""
                INSERT INTO crypto_instruments (venue, market, provider_symbol, kind, base_asset_id, quote_asset_id, status, calendar)
                VALUES ('binance', 'spot', 'BTCUSDT', 'spot', 1, 1, 'trading', 'utc')
            """))
            connection.execute(text("""
                INSERT INTO crypto_provider_mappings (provider, object_type, provider_id, instrument_id, method)
                VALUES ('binance_spot', 'instrument', 'BTCUSDT', 1, 'provider_metadata')
            """))
            # same venue symbol with a different kind stays a second row
            connection.execute(text("""
                INSERT INTO crypto_instruments (venue, market, provider_symbol, kind, base_asset_id, quote_asset_id, status, calendar)
                VALUES ('binance', 'usdm_futures', 'BTCUSDT', 'perpetual', 1, 1, 'trading', 'utc')
            """))
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO crypto_instruments (venue, market, provider_symbol, kind, base_asset_id, quote_asset_id, status, calendar)
                    VALUES ('binance', 'spot', 'BTCUSDT', 'spot', 1, 1, 'trading', 'utc')
                """))
            migration.downgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "crypto_instruments" not in tables
            columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(crypto_provider_mappings)"))
            }
            assert "instrument_id" not in columns
            migration.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "crypto_instruments" in tables
        finally:
            migration.op = original
            for mod, orig in zip(prior, originals):
                mod.op = orig


def _load_migration(module_name: str, filename: str):
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    return migration


def test_crypto_identity_migration_round_trip_on_sqlite():
    migration = _load_migration("crypto_identity_migration", "0066_crypto_identity_assets.py")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert {"crypto_assets", "crypto_symbol_aliases", "crypto_provider_mappings"} <= tables

            connection.execute(text("""
                INSERT INTO crypto_assets (slug, symbol, display_name, asset_kind, status)
                VALUES ('bitcoin', 'BTC', 'Bitcoin', 'coin', 'active')
            """))
            connection.execute(text("""
                INSERT INTO crypto_provider_mappings (provider, object_type, provider_id, asset_id, method)
                VALUES ('coingecko', 'asset', 'bitcoin', 1, 'verified_seed')
            """))
            # duplicate slug violates the unique constraint
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO crypto_assets (slug, symbol, display_name, asset_kind, status)
                    VALUES ('bitcoin', 'XBT', 'Dup', 'coin', 'active')
                """))
            migration.downgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "crypto_assets" not in tables
            assert "crypto_provider_mappings" not in tables
            migration.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert {"crypto_assets", "crypto_symbol_aliases", "crypto_provider_mappings"} <= tables
        finally:
            migration.op = original


def test_chain_token_protocol_migration_round_trip_on_sqlite():
    migration = _load_migration("chain_token_protocol_migration", "0067_crypto_chain_token_protocol.py")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        first = _load_migration("crypto_identity_migration_first", "0066_crypto_identity_assets.py")
        original_first, first.op = first.op, Operations(MigrationContext.configure(connection))
        first.upgrade()
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert {"blockchains", "crypto_tokens", "crypto_protocols", "crypto_protocol_assets"} <= tables
            columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(crypto_provider_mappings)"))
            }
            assert {"token_id", "protocol_id"} <= columns

            connection.execute(text("""
                INSERT INTO crypto_assets (slug, symbol, display_name, asset_kind, status)
                VALUES ('wrapped-ether', 'WETH', 'Wrapped Ether', 'token', 'active')
            """))
            connection.execute(text("""
                INSERT INTO blockchains (slug, name, namespace, reference, status)
                VALUES ('ethereum', 'Ethereum', 'eip155', '1', 'active')
            """))
            connection.execute(text("""
                INSERT INTO crypto_tokens (asset_id, chain_id, normalized_address, decimals, verification_status)
                VALUES (1, 1, '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', 18, 'unverified')
            """))
            # token mapping now valid under the replaced checks
            connection.execute(text("""
                INSERT INTO crypto_provider_mappings (provider, object_type, provider_id, token_id, method)
                VALUES ('coingecko', 'token', 'ethereum/0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', 1, 'verified_seed')
            """))
            # instrument object type still rejected (its target column does not exist yet)
            with pytest.raises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO crypto_provider_mappings (provider, object_type, provider_id, token_id, method)
                    VALUES ('binance_spot', 'instrument', 'BTCUSDT', 1, 'manual')
                """))
            migration.downgrade()
            columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(crypto_provider_mappings)"))
            }
            assert "token_id" not in columns and "protocol_id" not in columns
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert "crypto_tokens" not in tables and "blockchains" not in tables
            migration.upgrade()
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
            assert {"blockchains", "crypto_tokens", "crypto_protocols", "crypto_protocol_assets"} <= tables
        finally:
            migration.op = original
            first.op = original_first
