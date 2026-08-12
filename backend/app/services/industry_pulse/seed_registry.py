"""Versioned, runtime JSON-backed base-industry seed registry."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import IndustryPulseInstrument, IndustryPulseNode, IndustrySeedReplacementReview, Security, SecuritySymbolAlias


SEED_VERSION = 1
DATA_DIR = Path(__file__).with_name("data")


def load_seed_registry() -> dict:
    return json.loads((DATA_DIR / "leaf_industry_seed_registry.v1.json").read_text())


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def seed_base_industry_registry(db: Session) -> dict[str, int]:
    registry = load_seed_registry()
    nodes = {row.node_key: row for row in db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "leaf")).all()}
    expected_nodes = {row["taxonomy_node_id"] for row in registry["leaves"]}
    if set(nodes) != expected_nodes:
        raise ValueError(f"Canonical leaf mismatch: expected {len(expected_nodes)}, found {len(nodes)}")
    symbols = {row["ticker"].upper() for row in registry["unique_universe"]}
    lifecycle = registry.get("symbol_lifecycle", [])
    lookup_symbols = symbols | {row["previous_symbol"].upper() for row in lifecycle}
    securities_by_symbol = {
        (row.yahoo_symbol or row.display_symbol).upper(): row
        for row in db.scalars(select(Security).where(or_(Security.yahoo_symbol.in_(lookup_symbols), Security.display_symbol.in_(lookup_symbols)))).all()
        if row.yahoo_symbol or row.display_symbol
    }
    for change in lifecycle:
        current, previous = change["current_symbol"].upper(), change["previous_symbol"].upper()
        security = securities_by_symbol.get(current)
        if security is None and (security := securities_by_symbol.get(previous)) is not None:
            security.yahoo_symbol = current
            if security.display_symbol.upper() == previous:
                security.display_symbol = current
            if (security.local_symbol or "").upper() == previous:
                security.local_symbol = current
            if (security.finnhub_symbol or "").upper() == previous:
                security.finnhub_symbol = current
            security.mapping_method = "symbol_lifecycle"
            securities_by_symbol[current] = security
    securities = {symbol: securities_by_symbol[symbol] for symbol in symbols if symbol in securities_by_symbol}
    created_securities = 0
    universe_by_symbol = {row["ticker"].upper(): row for row in registry["unique_universe"]}
    for symbol, source in universe_by_symbol.items():
        security = securities.get(symbol)
        if security is None:
            security = Security(
                display_symbol=symbol,
                local_symbol=symbol,
                yahoo_symbol=symbol,
                yahoo_status="available" if source["market_data_status"] in {"VALID", "FOREIGN_MARKET"} else "unavailable",
                finnhub_status="unknown",
                mapping_method="manual_seed_registry",
            )
            db.add(security)
            securities[symbol] = security
            created_securities += 1
    db.flush()

    existing_aliases = {(row.provider, row.symbol): row for row in db.scalars(select(SecuritySymbolAlias)).all()}
    created_aliases = 0
    for change in lifecycle:
        current, previous = change["current_symbol"].upper(), change["previous_symbol"].upper()
        alias = existing_aliases.get(("yahoo", previous))
        if alias is None:
            alias = SecuritySymbolAlias(
                security_id=securities[current].id,
                provider="yahoo",
                symbol=previous,
                valid_to=_day(change["symbol_change_date"]),
                change_reason=change["lifecycle_status"],
            )
            db.add(alias)
            existing_aliases[("yahoo", previous)] = alias
            created_aliases += 1
        else:
            alias.security_id = securities[current].id
            alias.valid_to = _day(change["symbol_change_date"])
            alias.change_reason = change["lifecycle_status"]

    existing = {
        (row.node_id, row.ticker.upper()): row
        for row in db.scalars(select(IndustryPulseInstrument).where(
            IndustryPulseInstrument.node_id.in_([node.id for node in nodes.values()]),
            IndustryPulseInstrument.role == "reference",
        )).all()
    }
    created_memberships = updated_memberships = 0
    for leaf in registry["leaves"]:
        node = nodes.get(leaf["taxonomy_node_id"])
        if node is None:
            raise ValueError(f"Missing canonical leaf node: {leaf['taxonomy_node_id']}")
        for member in leaf["memberships"]:
            symbol = member["ticker"].upper()
            item = existing.get((node.id, symbol))
            if item is None:
                item = IndustryPulseInstrument(node_id=node.id, ticker=symbol, instrument_type="stock", role="reference")
                db.add(item)
                existing[(node.id, symbol)] = item
                created_memberships += 1
            else:
                updated_memberships += 1
            enabled = bool(member.get("enabled", True))
            item.security_id = securities[symbol].id
            item.provider_symbol = symbol
            item.mapping_type = "primary_industry"
            item.constituent_role = str(member["role"]).upper()
            item.purity = item.exposure = item.confidence = item.liquidity = 1.0
            item.classification_source = "MANUAL_CURATED_SEED"
            item.seed_version = SEED_VERSION
            item.slot = int(member["slot"])
            item.basket_quality = leaf.get("basket_quality")
            item.enabled = item.enabled_for_pulse = enabled
            item.valid_from = _day(member.get("valid_from"))
            item.valid_to = _day(member.get("valid_to"))
            item.health_status = "PENDING_REPLACEMENT" if not enabled else "UNAVAILABLE"
            item.metadata_json = {
                **(item.metadata_json or {}),
                **{key: value for key, value in member.items() if key not in {"slot", "ticker", "role", "source", "enabled", "valid_from", "valid_to"}},
                "leaf_code": leaf["leaf_code"],
                "seed_version": SEED_VERSION,
                "manual_seed": True,
                "replacement_status": member.get("replacement_state", "NONE"),
            }
    db.flush()

    replacement_payload = json.loads((DATA_DIR / "replacement_required.v1.json").read_text())
    reviews = {(row.seed_version, row.leaf_code, row.old_symbol): row for row in db.scalars(select(IndustrySeedReplacementReview)).all()}
    created_reviews = updated_reviews = 0
    for source in replacement_payload["items"]:
        key = (SEED_VERSION, source["leaf_code"], source["old_ticker"].upper())
        review = reviews.get(key)
        if review is None:
            review = IndustrySeedReplacementReview(seed_version=SEED_VERSION, leaf_code=key[1], old_symbol=key[2], leaf_name=source["leaf_name"], reason=source["reason"])
            db.add(review)
            reviews[key] = review
            created_reviews += 1
        else:
            updated_reviews += 1
        review.leaf_name = source["leaf_name"]
        review.reason = source["reason"]
        review.last_valid_date = _day(source.get("last_valid_date"))
        review.remaining_constituents = source["current_other_4_constituents"]
        review.suggested_candidates = review.suggested_candidates or []
        review.status = "PENDING_REVIEW"
        review.metadata_json = {"lifecycle_status": source["lifecycle_status"], "evidence": source.get("evidence")}
    db.flush()
    return {
        "seed_version": SEED_VERSION,
        "leaf_count": len(registry["leaves"]),
        "membership_count": sum(len(leaf["memberships"]) for leaf in registry["leaves"]),
        "unique_security_count": len(symbols),
        "created_securities": created_securities,
        "created_aliases": created_aliases,
        "created_memberships": created_memberships,
        "updated_memberships": updated_memberships,
        "created_reviews": created_reviews,
        "updated_reviews": updated_reviews,
    }
