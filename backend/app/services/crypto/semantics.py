"""Pure crypto identity/time/volume semantics frozen by WP 0.3.

These functions are executable examples for the identity fixture
(``backend/tests/fixtures/crypto/identity_cases.json``) and reusable pure
checks for later phases. They contain no database access and no network
calls; the real resolver in ``identity.py`` must agree with these rules but
is deliberately not implemented here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Closed-candle intervals supported by the crypto market-data store. Crypto
# trades 24/7 on UTC boundaries; XNYS session logic never applies.
INTERVAL_MODULO_MS = {
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def candle_open_time_is_aligned(interval: str, open_time_ms: int) -> bool:
    """True when ``open_time_ms`` is a valid UTC boundary for ``interval``."""
    modulo = INTERVAL_MODULO_MS.get(interval)
    if modulo is None:
        raise ValueError(f"unsupported candle interval: {interval!r}")
    return open_time_ms % modulo == 0


def taker_volume_is_subset(taker_volume: str, total_volume: str) -> bool:
    """Taker-buy volume is a subset of total volume within one candle."""
    try:
        return Decimal(taker_volume) <= Decimal(total_volume)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal volume strings: {taker_volume!r}, {total_volume!r}") from exc


def _normalize_address(chain: dict, address: str) -> str:
    rule = chain.get("address_rule", "")
    if "case-insensitive" in rule:
        return address.lower()
    return address


def resolve_identity_case(fixture: dict, query: dict) -> dict:
    """Reference resolver over the WP 0.3 fixture graph.

    Resolution order mirrors the architectural rules:

    1. provider mapping by exact ``(provider, object_type, provider_id)``;
    2. token deployment by exact ``(chain, normalized_address)``;
    3. symbol alias (e.g. XBT -> bitcoin);
    4. bare symbol lookup is only a search hint — ambiguous or unmatched
       symbols stay unresolved.

    A query for a provider namespace without its market (``binance`` instead
    of ``binance_spot``/``binance_usdm``) is rejected: the raw venue symbol
    exists on multiple markets with different semantics.
    """

    if "provider" in query:
        provider = query["provider"]
        object_type = query.get("object_type")
        provider_id = query.get("provider_id")
        matches = [
            m
            for m in fixture.get("provider_mappings", [])
            if m["provider"] == provider and m["object_type"] == object_type and m["provider_id"] == provider_id
        ]
        if len(matches) == 1:
            target = matches[0]["target"]
            return {"status": "resolved", "target": _expand_target(fixture, target)}
        if not matches:
            if provider in {p.split("_")[0] for p in fixture.get("providers", {})} and provider not in fixture.get("providers", {}):
                return {
                    "status": "unresolved",
                    "target": None,
                    "reason": "provider namespace must include the market (e.g. binance_spot vs binance_usdm); the raw venue symbol exists on multiple markets with different semantics",
                }
            return {"status": "unresolved", "target": None, "reason": "no provider mapping for the exact provider id"}
        return {"status": "unresolved", "target": None, "reason": "provider mapping is ambiguous"}

    if "chain_slug" in query and "normalized_address" in query:
        chains = {c["slug"]: c for c in fixture.get("chains", [])}
        chain = chains.get(query["chain_slug"])
        if chain is None:
            return {"status": "unresolved", "target": None, "reason": "unknown chain"}
        normalized = _normalize_address(chain, query["normalized_address"])
        matches = [
            t
            for t in fixture.get("tokens", [])
            if t["chain_slug"] == query["chain_slug"] and t["normalized_address"] == normalized
        ]
        if len(matches) == 1:
            token = matches[0]
            return {"status": "resolved", "target": dict(token, object_type="token")}
        if not matches:
            return {
                "status": "unresolved",
                "target": None,
                "reason": "no token row matches; never create an asset or token by guess from the address alone",
            }
        return {"status": "unresolved", "target": None, "reason": "address matches multiple token deployments"}

    if "symbol" in query:
        symbol = query["symbol"]
        aliases = [a for a in fixture.get("symbol_aliases", []) if a["symbol"] == symbol]
        if len(aliases) == 1:
            return {"status": "resolved_via_alias", "target": {"object_type": "asset", "slug": aliases[0]["target_asset_slug"]}}
        matches = [a for a in fixture.get("assets", []) if a["symbol"] == symbol and a["asset_kind"] != "alias_placeholder"]
        if len(matches) > 1:
            return {
                "status": "unresolved",
                "target": None,
                "reason": "two canonical assets share the symbol; symbol-only lookup must return ambiguity, never a ranked pick",
                "candidates": sorted(a["slug"] for a in matches),
            }
        return {
            "status": "search_hint_only",
            "target": None,
            "reason": "symbols are search hints; identity requires a provider mapping, chain+address, or manual verification",
        }

    return {"status": "unresolved", "target": None, "reason": "unsupported query"}


def _expand_target(fixture: dict, target: dict) -> dict:
    if target.get("object_type") == "instrument":
        for instrument in fixture.get("instruments", []):
            key = instrument["instrument_key"]
            if (
                key["venue"] == target.get("venue")
                and key["provider_symbol"] == target.get("provider_symbol")
                and key["kind"] == target.get("kind")
            ):
                return {
                    "object_type": "instrument",
                    "venue": key["venue"],
                    "provider_symbol": key["provider_symbol"],
                    "kind": key["kind"],
                    "market": instrument["market"],
                    "base_asset_slug": instrument["base_asset_slug"],
                    "quote_asset_slug": instrument["quote_asset_slug"],
                    "settlement_asset_slug": instrument.get("settlement_asset_slug"),
                }
    if target.get("object_type") == "asset":
        for asset in fixture.get("assets", []):
            if asset["slug"] == target.get("slug"):
                return dict(asset, object_type="asset")
    return dict(target)
