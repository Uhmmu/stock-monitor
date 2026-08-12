"""Seed candidate hydration, Luna classification, and membership persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.model_fallbacks import model_candidates, run_with_fallback
from app.models import (
    CompanyProfile,
    IndustryPulseClassificationCache,
    IndustryPulseInstrument,
    IndustryPulseNode,
    PeerRelation,
    Security,
    StockProfile,
    ValuationSnapshot,
)
from app.services.fmp_market import FmpError, FmpQuotaExhausted, sync_profile
from app.services.industry_pulse.candidates import candidates_by_symbol
from app.services.industry_pulse.definitions import (
    CLASSIFICATION_SOURCE_PRIORITY,
    MANUAL_CURATED_SEED,
    MANUAL_CURATED_SEED_SOURCE,
    MANUAL_SEED_MIN_CONSTITUENTS,
    MANUAL_SEED_PREFERRED_RANGE,
    MANUAL_SEED_TARGET_CONSTITUENTS,
    MANUAL_SEED_VERSION,
)

TAXONOMY_VERSION = "ai-chain-v1"


def classification_source_priority(source: str | None) -> int:
    """Return the persisted source precedence used at membership boundaries."""
    return CLASSIFICATION_SOURCE_PRIORITY.get(str(source or "").upper(), 0)


def seed_manual_curated_memberships(db: Session, *, seed: dict[str, tuple[dict, ...]] | None = None, as_of: date | None = None) -> dict[str, int]:
    """Persist the canonical 25-node basket without consulting the classifier.

    The state needed for later validation/audit/replacement is metadata only;
    a failed quote must not disable a configured manual membership here.
    """
    seed = seed or MANUAL_CURATED_SEED
    day = as_of or datetime.now(UTC).date()
    node_keys = tuple(seed)
    nodes = {row.node_key: row for row in db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "ai", IndustryPulseNode.node_key.in_(node_keys), IndustryPulseNode.level == "group")).all()}
    tickers = {str(item["ticker"]).upper() for rows in seed.values() for item in rows}
    securities = {
        (row.yahoo_symbol or row.display_symbol or "").upper(): row
        for row in db.scalars(select(Security).where(or_(Security.yahoo_symbol.in_(tickers), Security.display_symbol.in_(tickers)))).all()
        if (row.yahoo_symbol or row.display_symbol)
    }
    existing = db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.instrument_type == "stock", IndustryPulseInstrument.ticker.in_(tickers))).all()
    by_key: dict[tuple[int, str], list[IndustryPulseInstrument]] = {}
    for row in existing:
        by_key.setdefault((row.node_id, row.ticker.upper()), []).append(row)
    created = updated = missing_nodes = 0
    for node_key, members in seed.items():
        node = nodes.get(node_key)
        if node is None:
            missing_nodes += 1
            continue
        node.metadata_json = {
            **(node.metadata_json or {}),
            "synthetic_etf": {
                "target_constituents": MANUAL_SEED_TARGET_CONSTITUENTS,
                "preferred_range": list(MANUAL_SEED_PREFERRED_RANGE),
                "minimum_constituents": MANUAL_SEED_MIN_CONSTITUENTS,
                "seed_source": MANUAL_CURATED_SEED_SOURCE,
            },
        }
        for member in members:
            ticker = str(member["ticker"]).upper()
            candidates = by_key.get((node.id, ticker), [])
            item = next((row for row in candidates if row.classification_source == MANUAL_CURATED_SEED_SOURCE), None)
            item = item or next((row for row in sorted(candidates, key=lambda row: classification_source_priority(row.classification_source), reverse=True)), None)
            if item is None:
                item = IndustryPulseInstrument(node_id=node.id, ticker=ticker, instrument_type="stock", role="reference")
                db.add(item)
                by_key.setdefault((node.id, ticker), []).append(item)
                created += 1
            else:
                updated += 1
            security = securities.get(ticker)
            metadata = dict(item.metadata_json or {})
            metadata.update({
                "manual_seed": True,
                "seed_node": node_key,
                "seed_version": MANUAL_SEED_VERSION,
                "seed_notes": member.get("notes"),
                "sub_role": member.get("sub_role"),
                "role_factor": member.get("role_factor"),
                "seed_weight": member.get("weight"),
                "weight": member.get("weight"),
                "exposure_weight": member.get("exposure_weight"),
                "historical_membership_mode": "MONTHLY_ROLE_WEIGHT_RECONSTRUCTION",
                "seed_validation_status": metadata.get("seed_validation_status", "PENDING"),
                "validation_status": metadata.get("validation_status", "PENDING"),
                "audit_status": metadata.get("audit_status", "PENDING"),
                "replacement_state": metadata.get("replacement_state", "NONE"),
                "replacement_status": metadata.get("replacement_status", "NONE"),
            })
            item.security_id = security.id if security else item.security_id
            item.mapping_type = "theme_exposure"
            item.role = "reference"
            item.constituent_role = str(member["role"]).upper()
            item.purity = float(member.get("purity", 0) or 0)
            item.exposure = float(member.get("exposure_weight", 0) or 0)
            item.confidence = 1.0
            item.liquidity = float(member.get("liquidity", 1) or 1)
            item.classification_source = MANUAL_CURATED_SEED_SOURCE
            item.enabled = True
            item.enabled_for_pulse = True
            # Manual seeds define the canonical basket for reconstructed
            # history; a today's start date would erase the backfill window.
            item.valid_from = None
            item.valid_to = None
            item.metadata_json = metadata
    db.flush()
    return {"nodes": len(nodes), "configured_nodes": len(seed), "missing_nodes": missing_nodes, "memberships": sum(len(rows) for rows in seed.values()), "created": created, "updated": updated, "unique_tickers": len(tickers)}


class MembershipSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node: str
    role: Literal["CORE", "SECONDARY", "ENABLER"]
    exposure_weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    short_reason: str = Field(min_length=1, max_length=300)


class SymbolClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    memberships: list[MembershipSuggestion] = Field(default_factory=list, max_length=12)


class ClassificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[SymbolClassification]


_SYSTEM_PROMPT = """You classify public companies into an existing canonical AI industry-chain taxonomy.
Use only the supplied node IDs. Never create a node. A candidate list is discovery evidence, not automatic membership.
Return an empty memberships array when evidence is insufficient. Multiple memberships are allowed. Use CORE only for direct material business exposure, SECONDARY for meaningful adjacent exposure, and ENABLER for enabling technology. Lower exposure and confidence when uncertain. Do not classify generic fintech, cloud, semiconductor, defense, or healthcare exposure as AI exposure without specific business evidence. Output only the required JSON schema."""


def _market_cap(payload: object) -> float | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).casefold() in {"market_cap", "marketcap", "marketcapitalization"}:
                try:
                    return float(value) if value is not None else None
                except (TypeError, ValueError):
                    pass
            found = _market_cap(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _market_cap(value)
            if found is not None:
                return found
    return None


def _metadata_rows(db: Session) -> dict[str, dict]:
    candidates = candidates_by_symbol()
    symbols = set(candidates)
    securities: dict[str, Security] = {}
    for row in db.scalars(select(Security).where(or_(Security.yahoo_symbol.in_(symbols), Security.display_symbol.in_(symbols)))).all():
        securities[(row.yahoo_symbol or row.display_symbol).upper()] = row
    stocks = {row.ticker.upper(): row for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all()}
    companies = {row.symbol.upper(): row for row in db.scalars(select(CompanyProfile).where(CompanyProfile.symbol.in_(symbols))).all()}
    peers: dict[str, list[str]] = {}
    for row in db.scalars(select(PeerRelation).where(PeerRelation.base_ticker.in_(symbols), PeerRelation.enabled.is_(True))).all():
        peers.setdefault(row.base_ticker.upper(), []).append(row.peer_ticker.upper())
    valuations: dict[str, ValuationSnapshot] = {}
    for row in db.scalars(select(ValuationSnapshot).where(ValuationSnapshot.ticker.in_(symbols)).order_by(ValuationSnapshot.snapshot_date.desc())).all():
        valuations.setdefault(row.ticker.upper(), row)
    result: dict[str, dict] = {}
    for symbol, candidate_nodes in candidates.items():
        security, stock, company, valuation = securities.get(symbol), stocks.get(symbol), companies.get(symbol), valuations.get(symbol)
        result[symbol] = {
            "symbol": symbol,
            "company_name": (company.company_name if company else None) or (stock.company_name if stock else None) or (security.display_name if security else None),
            "business_description": company.description_en if company else None,
            "provider_sector": (company.sector if company else None) or (stock.official_sector if stock else None),
            "provider_industry": (company.industry if company else None) or (stock.official_industry if stock else None),
            "market_cap": _market_cap(valuation.payload) if valuation else None,
            "exchange": (company.exchange if company else None) or (security.exchange_code if security else None),
            "country": (company.country if company else None) or (security.country_code if security else None),
            "peers": peers.get(symbol, [])[:10],
            "existing_project_classification": {"sector": stock.official_sector if stock else None, "industry": stock.official_industry if stock else None},
            "candidate_nodes": list(candidate_nodes),
        }
    return result


def _digest(row: dict, model: str) -> str:
    return hashlib.sha256(json.dumps({"metadata": row, "taxonomy": TAXONOMY_VERSION, "model": model}, sort_keys=True, default=str).encode()).hexdigest()


def hydrate_candidate_metadata(db: Session, *, limit: int | None = None) -> dict[str, int]:
    settings = get_settings()
    if not settings.fmp_sync_enabled or not settings.fmp_profile_sync_enabled:
        return {"attempted": 0, "completed": 0, "failed": 0}
    candidates = candidates_by_symbol()
    existing = set(db.scalars(select(CompanyProfile.symbol).where(CompanyProfile.symbol.in_(candidates))).all())
    missing = [symbol for symbol in candidates if symbol not in existing]
    attempted = completed = failed = 0
    for symbol in missing[: max(0, limit if limit is not None else settings.industry_pulse_metadata_hydrate_limit)]:
        attempted += 1
        try:
            if sync_profile(db, symbol).get("status") == "completed":
                completed += 1
        except FmpQuotaExhausted:
            failed += 1
            break
        except FmpError:
            failed += 1
    return {"attempted": attempted, "completed": completed, "failed": failed}


def _classify_batch(rows: list[dict]) -> tuple[ClassificationBatch, str]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is unavailable")
    nodes = [{"id": node_id, "name": node_id.rsplit(".", 1)[-1].replace("_", " ")} for node_id in sorted({node for row in rows for node in row["candidate_nodes"]})]
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url, timeout=120, max_retries=1)
    def classify(selected_client, selected_model):
        response = selected_client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": json.dumps({"canonical_ai_nodes": nodes, "companies": rows}, ensure_ascii=False, default=str)}],
            temperature=0,
            response_format={"type": "json_schema", "json_schema": {"name": "ai_node_memberships_v1", "strict": True, "schema": ClassificationBatch.model_json_schema()}},
        )
        payload = json.loads(response.choices[0].message.content or "")
        if not isinstance(payload, dict):
            raise ValueError("classification response must be an object")
        return _normalize_classification_payload(payload)

    return run_with_fallback(settings.model_medium, client, classify)


def _normalize_classification_payload(payload: dict) -> ClassificationBatch:
    grouped: dict[str, list[dict]] = {}
    memberships = list(payload.get("memberships", []))
    for result in payload.get("results", []):
        memberships.extend({**membership, "symbol": result.get("symbol")} for membership in result.get("memberships", []))
    for membership in memberships:
        row = dict(membership)
        symbol = str(row.pop("symbol", None) or row.pop("company_symbol", None) or "").upper()
        row.pop("company_symbol", None)
        if symbol:
            row["node"] = row.pop("node", None) or row.pop("node_id", None)
            row.pop("node_id", None)
            raw_exposure = row.pop("exposure", None)
            row["role"] = str(row.pop("role", None) or row.pop("tier", None) or (raw_exposure if isinstance(raw_exposure, str) else None) or "SECONDARY").upper()
            row.pop("tier", None)
            exposure = row.pop("exposure_weight", None)
            row["exposure_weight"] = exposure if exposure is not None else raw_exposure if isinstance(raw_exposure, (int, float)) else {"CORE": .9, "SECONDARY": .6, "ENABLER": .45}.get(row["role"], .3)
            row["short_reason"] = row.pop("short_reason", None) or f"Luna classified {row['role'].lower()} exposure from supplied company metadata."
            grouped.setdefault(symbol, []).append(row)
    return ClassificationBatch.model_validate({"results": [{"symbol": symbol, "memberships": memberships} for symbol, memberships in grouped.items()]})


def _persist_result(db: Session, row: dict, result: SymbolClassification, *, metadata_hash: str, model: str, now: datetime) -> tuple[int, int]:
    settings = get_settings()
    symbol = row["symbol"]
    allowed = set(row["candidate_nodes"])
    nodes = {node.node_key: node for node in db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.node_key.in_(allowed), IndustryPulseNode.taxonomy == "ai", IndustryPulseNode.level == "group")).all()}
    security = db.scalar(select(Security).where(or_(Security.yahoo_symbol == symbol, Security.display_symbol == symbol)).limit(1))
    existing = db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.ticker == symbol, IndustryPulseInstrument.instrument_type == "stock")).all()
    by_node = {item.node_id: item for item in existing}
    accepted_node_ids: set[int] = set()
    accepted = low = 0
    for membership in result.memberships:
        node = nodes.get(membership.node)
        if node is None:
            continue
        accepted_node_ids.add(node.id)
        manual = db.scalar(select(IndustryPulseInstrument).where(IndustryPulseInstrument.node_id == node.id, IndustryPulseInstrument.ticker == symbol, IndustryPulseInstrument.classification_source.in_(("MANUAL_CURATED_SEED", "MANUAL"))).limit(1))
        if manual:
            continue
        item = by_node.get(node.id)
        if item is None:
            item = IndustryPulseInstrument(node_id=node.id, security_id=security.id if security else None, ticker=symbol, instrument_type="stock", mapping_type="theme_exposure", role="reference", classification_source="AI_CLASSIFIED")
            db.add(item)
        item.mapping_type = "theme_exposure"
        item.role = "reference"
        item.classification_source = "AI_CLASSIFIED"
        item.security_id = security.id if security else item.security_id
        item.exposure = membership.exposure_weight
        item.purity = membership.exposure_weight
        item.confidence = membership.confidence
        item.constituent_role = membership.role
        item.enabled = True
        item.enabled_for_pulse = membership.exposure_weight >= settings.industry_pulse_exposure_threshold and membership.confidence >= settings.industry_pulse_constituent_confidence_threshold
        item.valid_from = item.valid_from or now.date()
        item.valid_to = None
        item.metadata_json = {**(item.metadata_json or {}), "short_reason": membership.short_reason, "classification_model": model, "taxonomy_version": TAXONOMY_VERSION, "classification_timestamp": now.isoformat(), "metadata_hash": metadata_hash, "candidate_origin": "seed"}
        accepted += int(item.enabled_for_pulse)
        low += int(not item.enabled_for_pulse)
    for item in existing:
        if item.classification_source == "AI_CLASSIFIED" and item.node_id not in accepted_node_ids:
            item.enabled_for_pulse = False
            item.enabled = False
            item.valid_to = now.date()
    return accepted, low


def bootstrap_ai_constituents(db: Session, *, force: bool = False, classifier=None, hydrate: bool = True) -> dict[str, int | str]:
    settings = get_settings()
    hydration = hydrate_candidate_metadata(db) if hydrate else {"attempted": 0, "completed": 0, "failed": 0}
    metadata = _metadata_rows(db)
    cache = {row.symbol: row for row in db.scalars(select(IndustryPulseClassificationCache).where(IndustryPulseClassificationCache.symbol.in_(metadata))).all()}
    accepted_models = model_candidates(settings.model_medium)
    due = [row for symbol, row in metadata.items() if force or symbol not in cache or cache[symbol].status == "failed" or cache[symbol].metadata_hash not in {_digest(row, model) for model in accepted_models} or cache[symbol].taxonomy_version != TAXONOMY_VERSION or cache[symbol].model not in accepted_models]
    classified = rejected = enabled = low = calls = 0
    batch_size = max(1, min(40, settings.industry_pulse_classification_batch_size))
    now = datetime.now(UTC)
    classify = classifier or _classify_batch
    for offset in range(0, len(due), batch_size):
        batch = due[offset : offset + batch_size]
        calls += 1
        try:
            response, model = classify(batch)
            results = {item.symbol.upper(): item for item in response.results}
            for row in batch:
                symbol = row["symbol"]
                digest = _digest(row, model)
                result = results.get(symbol)
                item = cache.get(symbol) or IndustryPulseClassificationCache(symbol=symbol, metadata_hash=digest, taxonomy_version=TAXONOMY_VERSION, model=model)
                if symbol not in cache:
                    db.add(item)
                    cache[symbol] = item
                item.metadata_hash, item.taxonomy_version, item.model, item.classified_at = digest, TAXONOMY_VERSION, model, now
                if result is None:
                    item.status, item.result_json, item.error = "rejected", {}, "model omitted symbol"
                    rejected += 1
                    continue
                accepted_count, low_count = _persist_result(db, row, result, metadata_hash=digest, model=model, now=now)
                item.status = "completed" if result.memberships else "rejected"
                item.result_json = result.model_dump(mode="json")
                item.error = None
                classified += 1
                rejected += int(not result.memberships)
                enabled += accepted_count
                low += low_count
            db.flush()
            db.commit()
        except Exception as exc:
            db.rollback()
            for row in batch:
                symbol = row["symbol"]
                digest = _digest(row, settings.model_medium)
                item = db.get(IndustryPulseClassificationCache, symbol) or IndustryPulseClassificationCache(symbol=symbol, metadata_hash=digest, taxonomy_version=TAXONOMY_VERSION, model=settings.model_medium)
                if item.symbol not in cache:
                    db.add(item)
                    cache[symbol] = item
                item.metadata_hash, item.taxonomy_version, item.model = digest, TAXONOMY_VERSION, settings.model_medium
                item.status, item.error, item.classified_at = "failed", f"{type(exc).__name__}: {str(exc)[:300]}", now
            rejected += len(batch)
            db.commit()
    db.commit()
    return {"seed_candidates": len(metadata), "due": len(due), "classified": classified, "rejected": rejected, "enabled_memberships": enabled, "low_confidence_memberships": low, "luna_calls": calls, "model": settings.model_medium, "metadata_attempted": hydration["attempted"], "metadata_completed": hydration["completed"], "metadata_failed": hydration["failed"]}


bootstrap_manual_curated_seed = seed_manual_curated_memberships


__all__ = [
    "ClassificationBatch",
    "MembershipSuggestion",
    "SymbolClassification",
    "bootstrap_ai_constituents",
    "bootstrap_manual_curated_seed",
    "classification_source_priority",
    "hydrate_candidate_metadata",
    "seed_manual_curated_memberships",
]
