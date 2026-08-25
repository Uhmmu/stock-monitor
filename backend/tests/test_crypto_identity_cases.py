"""WP 0.3 — identity, UTC time and volume semantic fixtures.

``identity_cases.json`` freezes the highest-integrity join decisions before
any crypto schema exists: canonical identities, provider namespaces, symbol
aliases, uniqueness keys, UTC candle boundaries and volume semantics. Phase 1
migrations and resolvers are judged against these executable examples.
"""

import json
from pathlib import Path

import pytest

from app.services.crypto.semantics import (
    candle_open_time_is_aligned,
    resolve_identity_case,
    taker_volume_is_subset,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "crypto" / "identity_cases.json"


@pytest.fixture(scope="module")
def cases() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


class TestFixtureSchema:
    def test_core_sections_exist(self, cases):
        for section in (
            "providers",
            "assets",
            "chains",
            "tokens",
            "instruments",
            "provider_mappings",
            "symbol_aliases",
            "resolution_cases",
            "utc_candle_rules",
            "volume_rules",
            "display_labels",
        ):
            assert section in cases, f"missing fixture section {section}"

    def test_assets_have_canonical_fields(self, cases):
        for asset in cases["assets"]:
            assert asset["slug"] and asset["symbol"] and asset["display_name"]
            assert asset["asset_kind"] in ("coin", "token", "alias_placeholder")

    def test_tokens_are_chain_scoped(self, cases):
        chain_slugs = {c["slug"] for c in cases["chains"]}
        for token in cases["tokens"]:
            assert token["chain_slug"] in chain_slugs
            assert token["normalized_address"].startswith("0x")
            assert token["normalized_address"] == token["normalized_address"].lower()
            assert isinstance(token["decimals"], int)


class TestUniquenessCollisionTable:
    def test_asset_slugs_unique_but_symbols_may_collide(self, cases):
        slugs = [a["slug"] for a in cases["assets"]]
        assert len(slugs) == len(set(slugs))
        honey = [a for a in cases["assets"] if a["symbol"] == "HONEY"]
        assert len(honey) == 2, "same-symbol collision case must stay two distinct assets"
        assert {a["slug"] for a in honey} == {"hivemapper", "honey-alt"}

    def test_token_uniqueness_is_chain_plus_address(self, cases):
        keys = [(t["chain_slug"], t["normalized_address"]) for t in cases["tokens"]]
        assert len(keys) == len(set(keys))
        # the same asset deployed on two chains yields two distinct token rows
        assets = [t["asset_slug"] for t in cases["tokens"] if t["asset_slug"] == "wrapped-ether"]
        assert len(assets) == 2

    def test_instrument_uniqueness_requires_kind(self, cases):
        keys_without_kind = [(i["instrument_key"]["venue"], i["instrument_key"]["provider_symbol"]) for i in cases["instruments"]]
        # the fixture intentionally contains the spot/perpetual collision:
        # (binance, BTCUSDT) alone is NOT a valid unique key
        assert len(keys_without_kind) != len(set(keys_without_kind))
        keys_with_kind = [
            (i["instrument_key"]["venue"], i["instrument_key"]["provider_symbol"], i["instrument_key"]["kind"])
            for i in cases["instruments"]
        ]
        assert len(keys_with_kind) == len(set(keys_with_kind))

    def test_provider_mapping_keys_unique(self, cases):
        keys = [(m["provider"], m["object_type"], m["provider_id"]) for m in cases["provider_mappings"]]
        assert len(keys) == len(set(keys))
        # binance_spot:BTCUSDT and binance_usdm:BTCUSDT differ by provider namespace
        assert ("binance_spot", "instrument", "BTCUSDT") in keys
        assert ("binance_usdm", "instrument", "BTCUSDT") in keys

    def test_binance_provider_namespaces_carry_market(self, cases):
        assert cases["providers"]["binance_spot"]["market"] == "spot"
        assert cases["providers"]["binance_usdm"]["market"] == "usdm_futures"


class TestResolutionCases:
    def test_every_case_has_terminal_expectation(self, cases):
        for case in cases["resolution_cases"]:
            assert case["case_id"]
            status = case["expected"]["status"]
            assert status in ("resolved", "resolved_via_alias", "unresolved", "search_hint_only")
            if status == "unresolved":
                assert case["expected"].get("reason"), f"{case['case_id']} must document why"

    def test_resolver_agrees_with_every_case(self, cases):
        for case in cases["resolution_cases"]:
            result = resolve_identity_case(cases, case["input"])
            assert result["status"] == case["expected"]["status"], case["case_id"]
            if result["status"].startswith("resolved"):
                assert result["target"] is not None, case["case_id"]
            if case["expected"]["status"] == "resolved":
                expected = case["expected"]
                for field in ("object_type", "slug", "venue", "provider_symbol", "kind"):
                    if field in expected:
                        assert result["target"].get(field) == expected[field], case["case_id"]

    def test_xbt_is_alias_never_new_asset(self, cases):
        result = resolve_identity_case(cases, {"symbol": "XBT"})
        assert result["status"] == "resolved_via_alias"
        assert result["target"]["slug"] == "bitcoin"
        # the placeholder asset row exists in the fixture only to prove the
        # resolver refuses to treat it as canonical identity
        placeholder = next(a for a in cases["assets"] if a["slug"] == "xbt")
        assert placeholder["asset_kind"] == "alias_placeholder"

    def test_honey_collision_is_unresolved(self, cases):
        result = resolve_identity_case(cases, {"symbol": "HONEY"})
        assert result["status"] == "unresolved"
        assert sorted(result.get("candidates", [])) == ["hivemapper", "honey-alt"]

    def test_symbol_without_market_namespace_is_unresolved(self, cases):
        result = resolve_identity_case(cases, {"provider": "binance", "object_type": "instrument", "provider_id": "BTCUSDT"})
        assert result["status"] == "unresolved"
        assert "market" in result["reason"]

    def test_weth_deployments_share_one_asset(self, cases):
        one = resolve_identity_case(cases, {"chain_slug": "ethereum", "normalized_address": "0xC02AAA39B223FE8D0A0E5C4F27EAD9083C756CC2"})
        two = resolve_identity_case(cases, {"chain_slug": "arbitrum-one", "normalized_address": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"})
        assert one["target"]["asset_slug"] == two["target"]["asset_slug"] == "wrapped-ether"
        assert one["target"]["chain_slug"] != two["target"]["chain_slug"]


class TestUtcAndVolumeRules:
    def test_interval_modulo_rules(self, cases):
        rules = cases["utc_candle_rules"]["interval_open_time_modulo_ms"]
        assert rules == {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

    def test_candle_alignment_math(self):
        # open times taken verbatim from the WP 0.2 Binance captures
        assert candle_open_time_is_aligned("1h", 1_787_662_800_000)
        assert candle_open_time_is_aligned("4h", 1_787_630_400_000)
        assert candle_open_time_is_aligned("1d", 1_787_443_200_000)
        assert not candle_open_time_is_aligned("1h", 1_787_662_800_001)
        assert not candle_open_time_is_aligned("4h", 1_787_662_800_000)

    def test_taker_volume_is_subset(self):
        assert taker_volume_is_subset("616.24854100", "795.15037700")
        assert taker_volume_is_subset("795.15037700", "795.15037700")
        assert not taker_volume_is_subset("796.00000000", "795.15037700")

    def test_kline_fixtures_obey_volume_rules(self, cases):
        for interval in ("1h", "4h", "1d"):
            rows = json.loads((FIXTURE_PATH.parent / f"binance_spot_klines_{interval}.json").read_text())
            for row in rows:
                assert taker_volume_is_subset(row[9], row[5]), f"{interval} taker base <= base"
                assert taker_volume_is_subset(row[10], row[7]), f"{interval} taker quote <= quote"

    def test_no_exchange_calendar_rule(self, cases):
        assert "XNYS" in cases["utc_candle_rules"]["no_exchange_calendar"]


class TestDisplayLabels:
    def test_stable_label_strings(self, cases):
        labels = cases["display_labels"]
        assert labels["binance_btcusdt_spot"] == "BTC/USDT · Binance · Spot"
        assert labels["binance_btcusdt_perpetual"] == "BTC/USDT · Binance · Perpetual"
        assert labels["asset_bitcoin"] == "BTC · Bitcoin"
