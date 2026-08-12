"""Persistence and read-side orchestration for Industry/Sector Pulse."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import logging
from time import perf_counter
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    HistoricalPrice,
    IndustryPulseFocusSignal,
    IndustryPulseInstrument,
    IndustryPulseNode,
    IndustryPulseNarrative,
    IndustryPulseRelation,
    IndustryPulseSnapshot,
    IndustryPulseSyncRun,
    IndustrySeedReplacementReview,
    MarketDataSyncState,
    CompanyProfile,
    Security,
    StockProfile,
)
from app.services.industry_pulse.calculation import calculate_basket_signal, calculate_composite, calculate_etf_metrics, calculate_focus, calculate_hybrid_composite, classify_mood, detect_regime
from app.services.industry_pulse.classification import classify_security
from app.services.industry_pulse.constituents import bootstrap_ai_constituents, seed_manual_curated_memberships
from app.services.industry_pulse.definitions import AI_RELATIONS, AI_TAXONOMY, BASE_TAXONOMY, ETF_REGISTRY, ETF_SYMBOLS, pulse_mappings
from app.services.industry_pulse.provider import DailyBar, ProviderHistory
from app.services.industry_pulse.seed_registry import seed_base_industry_registry
from app.services.industry_pulse.synthetic import persist_leaf_indexes
from app.services.market_data_coordinator import sync_global_market_data
from app.services.market_calendar import expected_latest_market_session
from app.services.market_data_repository import upsert_history

logger = logging.getLogger(__name__)
CALCULATION_VERSION = "industry_pulse_v3"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        return float(value) if value.__class__.__name__ == "Decimal" else value
    except (TypeError, ValueError):
        return str(value)


def _taxonomy_for(node_id: str) -> str:
    return "ai" if str(node_id).startswith("ai.") else "base"


def _level(value: Any) -> str:
    return {1: "sector", 2: "group", 3: "leaf", "1": "sector", "2": "group", "3": "leaf"}.get(value, "leaf")


def ensure_seed_data(db: Session) -> dict[str, int]:
    """Idempotently materialise definitions into normalized tables."""
    existing_nodes = db.scalars(select(IndustryPulseNode)).all()
    by_key: dict[tuple[str, str], IndustryPulseNode] = {(node.taxonomy, node.node_key): node for node in existing_nodes}
    rows = list(BASE_TAXONOMY) + list(AI_TAXONOMY)
    rows.sort(key=lambda row: (str(row.get("id", "")).count("."), str(row.get("id", ""))))
    for row in rows:
        node_id = str(row["id"])
        taxonomy = _taxonomy_for(node_id)
        node = by_key.get((taxonomy, node_id))
        if node is None:
            node = IndustryPulseNode(taxonomy=taxonomy, node_key=node_id)
            db.add(node)
        node.name = str(row.get("name") or node_id)
        node.name_zh = str(row.get("name_zh") or node.name)
        node.slug = node_id.rsplit(".", 1)[-1]
        node.level = _level(row.get("level"))
        node.enabled = bool(row.get("enabled", True))
        node.metadata_json = {**(node.metadata_json or {}), "code": row.get("code"), "kind": row.get("kind")}
        by_key[(taxonomy, node_id)] = node
    db.flush()
    for row in rows:
        node = by_key[(_taxonomy_for(str(row["id"])), str(row["id"]))]
        parent_id = row.get("parent_id")
        if parent_id:
            parent = by_key.get((_taxonomy_for(str(parent_id)), str(parent_id)))
            node.parent_id = parent.id if parent else None
    existing_relations = {(edge.source_node_id, edge.target_node_id, edge.relation_type) for edge in db.scalars(select(IndustryPulseRelation)).all()}
    for relation in AI_RELATIONS:
        source_key = str(relation.get("source_id") or "")
        target_key = str(relation.get("target_id") or "")
        source = by_key.get((_taxonomy_for(source_key), source_key))
        target = by_key.get((_taxonomy_for(target_key), target_key))
        if not source or not target:
            continue
        relation_type = str(relation.get("relation") or "downstream")
        if (source.id, target.id, relation_type) not in existing_relations:
            db.add(IndustryPulseRelation(source_node_id=source.id, target_node_id=target.id, relation_type=relation_type, weight=1.0, confidence=1.0))
            existing_relations.add((source.id, target.id, relation_type))
    mapping_count = 0
    existing_mappings = {(row.node_id, row.ticker, row.role): row for row in db.scalars(select(IndustryPulseInstrument)).all()}
    for ticker, registry in ETF_REGISTRY.items():
        for mapping in registry.get("mappings", ()):
            node_key = str(mapping.get("node_id") or "")
            node = by_key.get((_taxonomy_for(node_key), node_key))
            if not node:
                continue
            role = str(mapping.get("role") or "secondary")
            existing = existing_mappings.get((node.id, ticker, role))
            # ETF registry rows are proxies for either base or AI nodes.  The
            # stock classification mapping types remain a separate boundary;
            # ETF role (primary/secondary/reference/benchmark) is orthogonal.
            mapping_type = "etf_proxy"
            metadata = {"name": registry.get("name"), "notes": mapping.get("notes"), "coverage_quality": mapping.get("coverage_quality"), "seed": True}
            if existing is None:
                existing = IndustryPulseInstrument(node_id=node.id, ticker=ticker, instrument_type=str(registry.get("instrument_class") or "etf"), role=role)
                db.add(existing)
                existing_mappings[(node.id, ticker, role)] = existing
                mapping_count += 1
            # Preserve trusted/manual mappings. Seed metadata can be refreshed,
            # but never changes a manually selected node or role.
            trusted = bool((existing.metadata_json or {}).get("trusted"))
            if not trusted:
                existing.mapping_type = mapping_type
                existing.purity = float(mapping.get("purity", 1.0) or 0)
                existing.exposure = float(mapping.get("exposure_weight", 1.0) or 0)
                existing.confidence = float(mapping.get("confidence", 0.0) or 0)
                existing.provider_symbol = ticker
                existing.classification_source = "MANUAL"
                existing.constituent_role = "PROXY"
                existing.enabled_for_pulse = role in {"primary", "secondary"}
            existing.metadata_json = {**(existing.metadata_json or {}), **metadata}
            existing.enabled = bool(registry.get("enabled", True)) and bool(mapping.get("enabled", True))
    db.flush()
    manual = seed_manual_curated_memberships(db)
    base_seed = seed_base_industry_registry(db)
    return {"nodes": len(rows), "relations": len(AI_RELATIONS), "mappings": mapping_count, "etfs": len(ETF_REGISTRY), **{f"manual_{key}": value for key, value in manual.items()}, **{f"base_seed_{key}": value for key, value in base_seed.items()}}


def sync_security_classifications(db: Session) -> dict[str, int]:
    """Persist deterministic stock classifications without mixing them into ETF Pulse weights."""
    nodes = {row.node_key: row for row in db.scalars(select(IndustryPulseNode)).all()}
    stock_profiles = {row.ticker.upper(): row for row in db.scalars(select(StockProfile)).all()}
    company_profiles = {row.symbol.upper(): row for row in db.scalars(select(CompanyProfile)).all()}
    mappings_by_security: dict[int, list[IndustryPulseInstrument]] = {}
    stock_mappings = db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.instrument_type == "stock")).all()
    mappings_by_node_ticker = {(row.node_id, row.ticker.upper()): row for row in stock_mappings}
    for row in stock_mappings:
        if row.security_id is not None:
            mappings_by_security.setdefault(row.security_id, []).append(row)
    classified = unclassified = mappings_written = 0
    for security in db.scalars(select(Security)).all():
        ticker = (security.yahoo_symbol or security.display_symbol or "").upper()
        if not ticker:
            continue
        stock = stock_profiles.get(ticker)
        company = company_profiles.get(ticker)
        result = classify_security(
            ticker,
            profile={"official_sector": stock.official_sector, "official_industry": stock.official_industry} if stock else None,
            company_profile={"sector": company.sector, "industry": company.industry} if company else None,
        )
        existing_rows = mappings_by_security.setdefault(security.id, [])
        if any((row.metadata_json or {}).get("trusted") for row in existing_rows):
            classified += 1
            continue
        for existing in existing_rows:
            if existing.classification_source in {"PROVIDER", "INHERITED"}:
                existing.enabled = False
                existing.enabled_for_pulse = False
        if not result.get("primary_industry"):
            unclassified += 1
            continue
        classified += 1
        assignments = [(result["primary_industry"], "primary_industry", 1.0)]
        assignments += [(node_key, "secondary_industry", .5) for node_key in result.get("secondary_industries", ())]
        assignments += [(node_key, "theme_exposure", exposure) for node_key, exposure in result.get("theme_exposures", {}).items()]
        for node_key, mapping_type, exposure in assignments:
            node = nodes.get(node_key)
            if not node:
                continue
            global_mapping = mappings_by_node_ticker.get((node.id, ticker))
            authoritative = next((item for item in existing_rows if item.node_id == node.id and item.classification_source in {"MANUAL_CURATED_SEED", "MANUAL", "AI_CLASSIFIED"}), None)
            if global_mapping and global_mapping.classification_source in {"MANUAL_CURATED_SEED", "MANUAL", "AI_CLASSIFIED"}:
                authoritative = authoritative or global_mapping
            if authoritative:
                if authoritative.classification_source == "MANUAL_CURATED_SEED" and authoritative.security_id is None:
                    authoritative.security_id = security.id
                continue
            row = next((item for item in existing_rows if item.node_id == node.id and item.role == "reference" and item.classification_source in {"PROVIDER", "INHERITED"}), None)
            if row is None:
                row = IndustryPulseInstrument(node_id=node.id, security_id=security.id, ticker=ticker, instrument_type="stock", role="reference")
                db.add(row)
                existing_rows.append(row)
                mappings_written += 1
            if (row.metadata_json or {}).get("trusted"):
                continue
            row.mapping_type, row.purity, row.exposure = mapping_type, float(exposure), float(exposure)
            row.confidence = float(result.get("confidence") or 0)
            row.enabled = mapping_type != "theme_exposure" or float(exposure) >= get_settings().industry_pulse_exposure_threshold
            row.classification_source = "MANUAL" if result.get("trusted") else "PROVIDER"
            row.constituent_role = "CORE" if mapping_type == "theme_exposure" and float(exposure) >= .8 else "SECONDARY"
            row.enabled_for_pulse = bool(mapping_type == "theme_exposure" and row.enabled and row.confidence >= get_settings().industry_pulse_constituent_confidence_threshold)
            row.valid_from = row.valid_from or datetime.now(UTC).date()
            row.metadata_json = {"source": result.get("source"), "included_in_theme_pulse": row.enabled_for_pulse, "trusted": bool(result.get("trusted"))}
    db.flush()
    return {"classified": classified, "unclassified": unclassified, "mappings_written": mappings_written}


def _upsert_history(db: Session, ticker: str, history: ProviderHistory, existing_cache: dict[tuple[str, str, date], HistoricalPrice] | None = None) -> int:
    return upsert_history(db, ticker, history, existing_cache)


def _history_rows(db: Session, ticker: str, source: str | None = None) -> list[dict[str, Any]]:
    query = select(HistoricalPrice).where(HistoricalPrice.symbol == ticker)
    if source:
        query = query.where(HistoricalPrice.source == source)
    rows = db.scalars(query.order_by(HistoricalPrice.date.asc())).all()
    return _stored_history_payload(rows)


def _stored_history_payload(rows: list[HistoricalPrice]) -> list[dict[str, Any]]:
    priority = {"yfinance": 0, "yahoo": 0, "finnhub": 1, "fmp": 2}
    chosen: dict[date, HistoricalPrice] = {}
    for row in rows:
        current = chosen.get(row.date)
        if current is None or priority.get(row.source, 99) < priority.get(current.source, 99):
            chosen[row.date] = row
    return [{"date": row.date, "open": float(row.open), "high": float(row.high), "low": float(row.low), "close": float(row.close), "adjusted_close": float(row.adjusted_close) if row.adjusted_close is not None else None, "volume": row.volume} for row in (chosen[day] for day in sorted(chosen))]


def _merge_history(stored: list[dict[str, Any]], fresh: list[DailyBar]) -> list[dict[str, Any]]:
    merged = {row["date"]: row for row in stored}
    for bar in fresh:
        merged[bar.date] = bar.as_dict()
    return [merged[day] for day in sorted(merged)]


def _mapping_payload(row: IndustryPulseInstrument) -> dict[str, Any]:
    return {"ticker": row.ticker, "role": row.role, "mapping_type": row.mapping_type, "instrument_type": row.instrument_type, "purity": row.purity, "exposure_weight": row.exposure, "confidence": row.confidence, "liquidity": row.liquidity, "classification_source": row.classification_source, "source_etf": row.source_etf, "constituent_role": row.constituent_role, "enabled_for_pulse": row.enabled_for_pulse, "valid_from": row.valid_from, "valid_to": row.valid_to, "short_reason": (row.metadata_json or {}).get("short_reason")}


def _stock_mapping_active(mapping: IndustryPulseInstrument, day: date) -> bool:
    settings = get_settings()
    return bool(
        mapping.enabled and mapping.enabled_for_pulse and mapping.instrument_type == "stock"
        and (mapping.mapping_type == "theme_exposure" or mapping.classification_source == "MANUAL_CURATED_SEED" and mapping.mapping_type == "primary_industry")
        and mapping.exposure >= settings.industry_pulse_exposure_threshold
        and mapping.confidence >= settings.industry_pulse_constituent_confidence_threshold
        and (mapping.valid_from is None or mapping.valid_from <= day)
        and (mapping.valid_to is None or mapping.valid_to >= day)
    )


def _constituent_health(history: ProviderHistory, failures: int, *, no_history: bool, manual_seed: bool) -> str:
    if history.status in {"success", "degraded", "fallback"}:
        return {"success": "ACTIVE", "degraded": "DEGRADED", "fallback": "FALLBACK"}[history.status]
    return "STALE" if failures >= 3 else "TEMPORARY_DATA_FAILURE"


def _pulse_stock_mappings(mappings: list[IndustryPulseInstrument], day: date) -> list[IndustryPulseInstrument]:
    stocks = [mapping for mapping in mappings if _stock_mapping_active(mapping, day)]
    manual = [mapping for mapping in stocks if mapping.classification_source == "MANUAL_CURATED_SEED"]
    return manual or stocks


def _fetch_lookback_days(cached_dates: dict[str, set[date]], symbols: set[str]) -> int:
    covered = sum(len(cached_dates.get(ticker, set())) >= 252 for ticker in symbols)
    return 10 if symbols and covered / len(symbols) >= .9 else get_settings().industry_pulse_history_days


def _history_backfill_complete(manual_node_ids: set[int], versioned_node_ids: set[int]) -> bool:
    return bool(manual_node_ids and manual_node_ids <= versioned_node_ids)


def _snapshot_history_start(trading_days: list[date], all_trading_days: list[date]) -> date:
    return min(trading_days[0], all_trading_days[max(0, len(all_trading_days) - 21)])


def _prune_snapshot_history(
    snapshots: dict[tuple[int, date], IndustryPulseSnapshot],
    history: dict[int, list[IndustryPulseSnapshot]],
    day: date,
) -> None:
    """Keep only the 20 prior rows needed by change calculations."""
    for key in [key for key in snapshots if key[1] < day]:
        snapshots.pop(key)
    for node_id, rows in history.items():
        past = [row for row in rows if row.trading_date <= day]
        future = [row for row in rows if row.trading_date > day]
        history[node_id] = past[-20:] + future


def _calculate_node(
    mappings: list[IndustryPulseInstrument], metrics: dict[str, dict[str, Any]], histories: dict[str, list[dict[str, Any]]],
    benchmark_rows: dict[str, list[dict[str, Any]]], day: date,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    etfs = [mapping for mapping in mappings if mapping.enabled and mapping.mapping_type == "etf_proxy"]
    stocks = _pulse_stock_mappings(mappings, day)
    etf_signal = calculate_composite(metrics, [_mapping_payload(mapping) for mapping in etfs], benchmark_metrics={name: metrics.get(name, {}) for name in ("SPY", "QQQ")}, weights=_score_weights(), exposure_threshold=settings.industry_pulse_exposure_threshold)
    basket_signal = calculate_basket_signal(
        {mapping.ticker: histories.get(mapping.ticker, []) for mapping in stocks},
        [_mapping_payload(mapping) for mapping in stocks], benchmark_rows=benchmark_rows.get("SPY"), qqq_rows=benchmark_rows.get("QQQ"), as_of=day,
        minimum_constituents=4 if any(mapping.classification_source == "MANUAL_CURATED_SEED" for mapping in stocks) else settings.industry_pulse_min_constituents,
        minimum_coverage=settings.industry_pulse_min_effective_coverage,
        single_stock_max_weight=settings.industry_pulse_single_stock_max_weight,
        top_three_max_weight=settings.industry_pulse_top_three_max_weight,
        weights=_score_weights(),
    )
    composite = calculate_hybrid_composite(etf_signal, basket_signal)
    disagreement = composite.get("etf_basket_disagreement")
    breadth = ((composite.get("basket") or {}).get("breadth") or {})
    positive_20d = (breadth.get("positive_20d_count") or 0) / max(1, breadth.get("positive_20d_eligible") or 0)
    divergence = "NARROW_LEADERSHIP" if disagreement is not None and etf_signal.get("pulse", 0) >= 60 and positive_20d < .4 else "EARLY_BROADENING" if disagreement is not None and basket_signal.get("pulse", 0) >= 60 and etf_signal.get("pulse", 100) < 55 and positive_20d >= .6 else None
    representative = next((metrics.get(mapping.ticker, {}) for mapping in etfs if mapping.ticker in metrics), {})
    node_metrics = {
        **representative,
        "proxy_mode": composite.get("proxy_mode"),
        "basket": composite.get("basket") or {},
        "etf_signal": {key: etf_signal.get(key) for key in ("pulse", "status", "coverage_quality", "confidence", "members")},
        "basket_signal": {key: basket_signal.get(key) for key in ("pulse", "status", "coverage_quality", "confidence", "members")},
        "etf_basket_disagreement": composite.get("etf_basket_disagreement"),
        "proxy_divergence": divergence,
    }
    return composite, node_metrics


def _upsert_snapshot(
    db: Session,
    node_id: int,
    day: date,
    composite: dict[str, Any],
    *,
    metrics: dict[str, Any],
    benchmark: dict[str, Any],
    previous: IndustryPulseSnapshot | None,
    prior_rows: list[IndustryPulseSnapshot] | None = None,
    snapshot_cache: dict[tuple[int, date], IndustryPulseSnapshot] | None = None,
) -> IndustryPulseSnapshot:
    # The sync job preloads this map once for the whole date window.  Keeping
    # the standalone DB fallback makes the helper safe for focused callers,
    # while the backfill/current inner loops remain query-free.
    if snapshot_cache is None:
        row = db.scalar(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id == node_id, IndustryPulseSnapshot.trading_date == day))
    else:
        row = snapshot_cache.get((node_id, day))
    if row is None:
        row = IndustryPulseSnapshot(node_id=node_id, trading_date=day)
        db.add(row)
    components = composite.get("components") or {}
    row.pulse = composite.get("pulse")
    row.trend_score = components.get("trend")
    row.relative_strength_score = components.get("relative_strength")
    row.volume_score = components.get("volume")
    row.momentum_score = components.get("momentum")
    row.breadth_score = components.get("breadth")
    row.consensus_score = components.get("consensus")
    row.heat, row.risk = composite.get("heat"), composite.get("risk")
    row.change_1d = row.pulse - previous.pulse if row.pulse is not None and previous and previous.pulse is not None else None
    history_rows = prior_rows
    if history_rows is None:
        history_rows = db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id == node_id, IndustryPulseSnapshot.trading_date < day, IndustryPulseSnapshot.pulse.is_not(None)).order_by(IndustryPulseSnapshot.trading_date.desc()).limit(20)).all()
        history_rows = list(reversed(history_rows))
    valid_prior = [item.pulse for item in history_rows if item.pulse is not None]
    row.change_5d = row.pulse - valid_prior[-5] if row.pulse is not None and len(valid_prior) >= 5 else None
    row.change_20d = row.pulse - valid_prior[-20] if row.pulse is not None and len(valid_prior) >= 20 else None
    row.direction = "up" if (row.change_1d or 0) > .5 else "down" if (row.change_1d or 0) < -.5 else "flat"
    row.mood = composite.get("mood")
    row.regime = detect_regime({"pulse": row.pulse, "heat": row.heat, "risk": row.risk, "mood": row.mood}, {"pulse": previous.pulse} if previous else None)
    row.confidence = composite.get("confidence", composite.get("coverage_quality"))
    row.data_quality = "high" if (row.confidence or 0) >= .8 else "medium" if (row.confidence or 0) >= .5 else "low"
    row.coverage_quality = composite.get("coverage_quality")
    row.metrics_json = _json_safe(metrics)
    row.benchmark_json = _json_safe(benchmark)
    row.calculation_version = CALCULATION_VERSION
    row.source = f"deterministic_{str(composite.get('proxy_mode') or 'etf').casefold()}"
    return row


def _rollup_base_hierarchy(
    db: Session,
    nodes: list[IndustryPulseNode],
    day: date,
    snapshots: dict[tuple[int, date], IndustryPulseSnapshot],
    history: dict[int, list[IndustryPulseSnapshot]],
) -> list[dict[str, Any]]:
    """Aggregate 229 leaves into 50 groups and then 11 sectors."""
    output: list[dict[str, Any]] = []
    for level in ("group", "sector"):
        for node in (row for row in nodes if row.taxonomy == "base" and row.level == level):
            children = [row for row in nodes if row.parent_id == node.id]
            child_snapshots = [snapshots.get((child.id, day)) for child in children]
            valid = [row for row in child_snapshots if row and row.pulse is not None]
            if not valid:
                continue
            def average(field: str) -> float | None:
                values = [(float(value), float(row.coverage_quality or 0)) for row in valid if (value := getattr(row, field)) is not None]
                total = sum(weight for _value, weight in values)
                return sum(value * weight for value, weight in values) / total if total else None
            coverage = sum(float(row.coverage_quality or 0) for row in valid) / max(1, len(children))
            composite = {
                "pulse": average("pulse"), "heat": average("heat"), "risk": average("risk"),
                "coverage_quality": coverage, "confidence": average("confidence"), "proxy_mode": "CHILD_AGGREGATE",
                "components": {name: average(f"{name}_score") for name in ("trend", "relative_strength", "volume", "momentum", "breadth", "consensus")},
            }
            composite["mood"] = classify_mood(composite["pulse"], composite["heat"], composite["risk"], composite["components"]["breadth"], composite["components"]["consensus"])
            prior = [item for item in history.get(node.id, []) if item.trading_date < day]
            snapshot = _upsert_snapshot(db, node.id, day, composite, metrics={"proxy_mode": "CHILD_AGGREGATE", "child_nodes": [child.node_key for child in children], "available_children": len(valid)}, benchmark={}, previous=prior[-1] if prior else None, prior_rows=prior, snapshot_cache=snapshots)
            snapshots[(node.id, day)] = snapshot
            output.append({"node_id": node.id, "node_key": node.node_key, "pulse": snapshot.pulse, "change_5d": snapshot.change_5d, "relative_strength": snapshot.relative_strength_score, "volume_score": snapshot.volume_score, "volume_z": None, "heat": snapshot.heat, "risk": snapshot.risk, "direction": snapshot.direction, "mood": snapshot.mood, "coverage_quality": snapshot.coverage_quality, "confidence": snapshot.confidence, "metrics_json": snapshot.metrics_json})
    return output


def sync_pulse(db: Session, *, as_of: date | None = None, trigger_type: str = "scheduled") -> dict[str, Any]:
    """Fetch, calculate and commit numeric snapshots before optional AI work."""
    started = perf_counter()
    requested_day = as_of or datetime.now(UTC).date()
    ensure_seed_data(db)
    db.commit()
    bootstrap = bootstrap_ai_constituents(db, hydrate=True)
    if db.get_bind().dialect.name == "postgresql" and not db.scalar(select(func.pg_try_advisory_xact_lock(81730121))):
        return {"status": "running", "bootstrap": bootstrap}
    sync_security_classifications(db)
    active = db.scalar(select(IndustryPulseSyncRun).where(IndustryPulseSyncRun.status == "running", IndustryPulseSyncRun.started_at >= datetime.now(UTC) - timedelta(seconds=get_settings().industry_pulse_sync_lock_seconds)).order_by(IndustryPulseSyncRun.started_at.desc()).limit(1))
    if active:
        db.rollback()
        return {"status": "running", "run_id": active.id}
    run = IndustryPulseSyncRun(trigger_type=trigger_type)
    db.add(run)
    db.commit()
    all_mappings = db.scalars(select(IndustryPulseInstrument)).all()
    mappings_by_ticker: dict[str, list[IndustryPulseInstrument]] = {}
    for mapping in all_mappings:
        mappings_by_ticker.setdefault(mapping.ticker, []).append(mapping)
    pulse_symbols = set(ETF_SYMBOLS)
    pulse_symbols.update(mapping.ticker for mapping in all_mappings if mapping.enabled and mapping.enabled_for_pulse and mapping.instrument_type == "stock")
    market_sync = sync_global_market_data(db, symbols=pulse_symbols)
    states = {row.symbol: row for row in db.scalars(select(MarketDataSyncState).where(MarketDataSyncState.symbol.in_(pulse_symbols))).all()}
    priority = {"yfinance": 0, "yahoo": 0, "finnhub": 1, "fmp": 2}
    stored: dict[str, dict[date, tuple[int, dict[str, Any]]]] = {}
    price_rows = db.execute(select(
        HistoricalPrice.symbol, HistoricalPrice.date, HistoricalPrice.open,
        HistoricalPrice.high, HistoricalPrice.low, HistoricalPrice.close,
        HistoricalPrice.adjusted_close, HistoricalPrice.volume, HistoricalPrice.source,
    ).where(HistoricalPrice.symbol.in_(list(pulse_symbols)))).yield_per(5000)
    for row in price_rows:
        rank = priority.get(row.source, 99)
        chosen = stored.setdefault(row.symbol, {})
        if row.date not in chosen or rank < chosen[row.date][0]:
            chosen[row.date] = (rank, {
                "date": row.date, "open": float(row.open), "high": float(row.high),
                "low": float(row.low), "close": float(row.close),
                "adjusted_close": float(row.adjusted_close) if row.adjusted_close is not None else None,
                "volume": row.volume,
            })
    stored_history_by_ticker = {
        ticker: [item[1] for _day, item in sorted(stored.pop(ticker, {}).items())]
        for ticker in pulse_symbols
    }
    histories: dict[str, ProviderHistory] = {}
    for ticker in pulse_symbols:
        state = states.get(ticker)
        rows = stored_history_by_ticker.get(ticker, [])
        histories[ticker] = ProviderHistory(
            ticker=ticker,
            bars=[DailyBar(date=row["date"], open=row["open"], high=row["high"], low=row["low"], close=row["close"], volume=row["volume"], adjusted_close=row.get("adjusted_close")) for row in rows],
            provider=state.provider if state and rows else None,
            status="success" if state and state.freshness_status == "FRESH" else "degraded" if rows else "unavailable",
            error_code=state.error_code if state else None,
            volume_available=any(row.get("volume") is not None for row in rows),
            total_rows=len(rows),
        )
    run.etf_total = len(ETF_SYMBOLS)
    for ticker, history in histories.items():
        for mapping in mappings_by_ticker.get(ticker, []):
            metadata = dict(mapping.metadata_json or {})
            failures = 0 if history.bars else int(metadata.get("consecutive_data_failures") or 0) + 1
            metadata["consecutive_data_failures"] = failures
            no_history = not history.bars
            mapping.health_status = _constituent_health(history, failures, no_history=no_history, manual_seed=mapping.classification_source == "MANUAL_CURATED_SEED")
            if mapping.classification_source == "MANUAL_CURATED_SEED":
                metadata["seed_validation_status"] = "VALID" if history.bars else mapping.health_status
                metadata["market_data_failure"] = None if history.bars else history.error_code or "unknown"
                metadata["failure_semantic"] = None if history.bars else "STALE" if mapping.health_status == "STALE" else "TEMPORARY"
            mapping.metadata_json = metadata
            mapping.last_checked_at = datetime.now(UTC)
            mapping.last_trading_date = history.bars[-1].date if history.bars else None
            mapping.data_quality = history.data_quality
            mapping.error_code = history.error_code
    run.yfinance_success = int(market_sync["valid"]) - int(market_sync["finnhub_recovered"])
    run.finnhub_fallback = int(market_sync["finnhub_recovered"])
    run.failed = int(market_sync["failed"])
    db.flush()
    history_rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for ticker, history in histories.items():
        history_rows_by_ticker[ticker] = _merge_history(stored_history_by_ticker.get(ticker, []), history.bars)
    synthetic_indexes = persist_leaf_indexes(db, history_rows_by_ticker, as_of=requested_day)
    benchmark_rows = {ticker: history_rows_by_ticker.get(ticker, []) for ticker in ("SPY", "QQQ")}
    benchmark_days = [row["date"] for row in benchmark_rows.get("SPY", []) if row.get("date") and row["date"] <= requested_day]
    if not benchmark_days:
        raise RuntimeError("SPY benchmark has no trading session on or before the requested date")
    day = max(benchmark_days)
    metrics_by_ticker: dict[str, dict[str, Any]] = {}
    for ticker, history in histories.items():
        rows = history_rows_by_ticker.get(ticker, [])
        if not rows:
            continue
        metrics = calculate_etf_metrics(rows, benchmark_rows=benchmark_rows.get("SPY"), benchmark_name="SPY", as_of=day)
        qqq = calculate_etf_metrics(rows, benchmark_rows=benchmark_rows.get("QQQ"), benchmark_name="QQQ", as_of=day)
        metrics["relative_strength_benchmarks"] = {"SPY": {key: value for key, value in metrics.items() if key.startswith("rs_")}, "QQQ": {key: value for key, value in qqq.items() if key.startswith("rs_")}}
        metrics["rs_breakout"] = bool(any(metrics["relative_strength_benchmarks"][name].get("rs_breakout_20d") for name in ("SPY", "QQQ")))
        metrics_by_ticker[ticker] = metrics
    _apply_liquidity_floor(metrics_by_ticker)
    nodes = db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.enabled.is_(True))).all()
    enabled_mappings = [mapping for mapping in all_mappings if mapping.enabled]
    mappings_by_node: dict[int, list[IndustryPulseInstrument]] = {}
    for mapping in enabled_mappings:
        metric = metrics_by_ticker.get(mapping.ticker)
        if mapping.mapping_type == "etf_proxy" and metric:
            mapping.data_quality = metric.get("data_quality")
            mapping.last_trading_date = metric.get("as_of")
        if mapping.mapping_type == "etf_proxy" and metric and metric.get("error_code") == "stale_history":
            mapping.health_status, mapping.error_code, mapping.data_quality = "UNAVAILABLE", "stale_history", 0.0
        mappings_by_node.setdefault(mapping.node_id, []).append(mapping)
    nodes_by_id = {node.id: node for node in nodes}
    for group in (node for node in nodes if node.taxonomy == "ai" and node.level == "group"):
        inherited = [
            mapping
            for child in nodes
            if child.parent_id == group.id
            for mapping in mappings_by_node.get(child.id, [])
            if mapping.mapping_type == "etf_proxy"
        ]
        known = {(mapping.ticker, mapping.role) for mapping in mappings_by_node.get(group.id, [])}
        mappings_by_node.setdefault(group.id, []).extend(mapping for mapping in inherited if (mapping.ticker, mapping.role) not in known)
    sector_benchmark_by_node: dict[int, str] = {}
    for node in nodes:
        ancestor = node
        while ancestor.parent_id and ancestor.level != "sector":
            parent = nodes_by_id.get(ancestor.parent_id)
            if parent is None:
                break
            ancestor = parent
        benchmark_mapping = next((mapping for mapping in mappings_by_node.get(ancestor.id, []) if mapping.mapping_type == "etf_proxy" and mapping.role == "benchmark"), None)
        if benchmark_mapping:
            sector_benchmark_by_node[node.id] = benchmark_mapping.ticker
    mapped_nodes = [(node, mappings) for node in nodes if (mappings := [mapping for mapping in mappings_by_node.get(node.id, []) if mapping.mapping_type == "etf_proxy" or mapping.enabled_for_pulse])]
    # Causal backfill: only dates present in the benchmark history are used,
    # and every indicator is sliced at that date before being persisted.
    backfill_limit = max(0, int(get_settings().industry_pulse_backfill_days))
    all_trading_days = sorted({row["date"] for row in benchmark_rows.get("SPY", []) if row.get("date") and row["date"] <= day})
    trading_days = all_trading_days[-backfill_limit:] if backfill_limit else []
    manual_node_ids = {mapping.node_id for mapping in all_mappings if mapping.classification_source == "MANUAL_CURATED_SEED"}
    versioned_node_ids = set(db.scalars(select(IndustryPulseSnapshot.node_id).where(IndustryPulseSnapshot.node_id.in_(manual_node_ids), IndustryPulseSnapshot.calculation_version == CALCULATION_VERSION).distinct()).all()) if manual_node_ids else set()
    if _history_backfill_complete(manual_node_ids, versioned_node_ids):
        trading_days = [day]
    snapshot_history: dict[int, list[IndustryPulseSnapshot]] = {node.id: [] for node, _ in mapped_nodes}
    existing_snapshot_by_key: dict[tuple[int, date], IndustryPulseSnapshot] = {}
    if nodes:
        min_day = _snapshot_history_start(trading_days, all_trading_days)
        existing_snapshots = db.scalars(
            select(IndustryPulseSnapshot).where(
                IndustryPulseSnapshot.node_id.in_([node.id for node in nodes]),
                IndustryPulseSnapshot.trading_date <= day,
                IndustryPulseSnapshot.trading_date >= min_day,
            ).order_by(IndustryPulseSnapshot.trading_date.asc())
        ).all()
        for existing_snapshot in existing_snapshots:
            existing_snapshot_by_key[(existing_snapshot.node_id, existing_snapshot.trading_date)] = existing_snapshot
            snapshot_history.setdefault(existing_snapshot.node_id, []).append(existing_snapshot)
        del existing_snapshots
    for calc_day in trading_days[:-1]:
        metrics_at_day: dict[str, dict[str, Any]] = {}
        for ticker, history in histories.items():
            rows = history_rows_by_ticker.get(ticker, [])
            if not rows:
                continue
            first = calculate_etf_metrics(rows, benchmark_rows=benchmark_rows.get("SPY"), benchmark_name="SPY", as_of=calc_day)
            second = calculate_etf_metrics(rows, benchmark_rows=benchmark_rows.get("QQQ"), benchmark_name="QQQ", as_of=calc_day)
            first["relative_strength_benchmarks"] = {"SPY": {key: value for key, value in first.items() if key.startswith("rs_")}, "QQQ": {key: value for key, value in second.items() if key.startswith("rs_")}}
            first["rs_breakout"] = bool(any(first["relative_strength_benchmarks"][name].get("rs_breakout_20d") for name in ("SPY", "QQQ")))
            metrics_at_day[ticker] = first
        _apply_liquidity_floor(metrics_at_day)
        for node, orm_mappings in mapped_nodes:
            composite, representative = _calculate_node(orm_mappings, metrics_at_day, history_rows_by_ticker, benchmark_rows, calc_day)
            prior = [item for item in snapshot_history.get(node.id, []) if item.trading_date < calc_day]
            previous = prior[-1] if prior else None
            cached_snapshot = existing_snapshot_by_key.get((node.id, calc_day))
            if composite.get("pulse") is None and not (cached_snapshot and cached_snapshot.pulse is not None):
                continue
            snapshot = cached_snapshot if composite.get("pulse") is None else _upsert_snapshot(db, node.id, calc_day, composite, metrics=representative, benchmark={name: metrics_at_day.get(name, {}) for name in ("SPY", "QQQ")}, previous=previous, prior_rows=prior, snapshot_cache=existing_snapshot_by_key)
            existing_snapshot_by_key[(node.id, calc_day)] = snapshot
            if snapshot not in snapshot_history.setdefault(node.id, []):
                snapshot_history[node.id].append(snapshot)
        for rolled in _rollup_base_hierarchy(db, nodes, calc_day, existing_snapshot_by_key, snapshot_history):
            rolled_snapshot = existing_snapshot_by_key[(rolled["node_id"], calc_day)]
            if rolled_snapshot not in snapshot_history.setdefault(rolled["node_id"], []):
                snapshot_history[rolled["node_id"]].append(rolled_snapshot)
        db.flush()
        _prune_snapshot_history(existing_snapshot_by_key, snapshot_history, calc_day)
    db.flush()
    current_rows: list[dict[str, Any]] = []
    previous_by_node: dict[int, dict[str, Any]] = {}
    for node in nodes:
        orm_mappings = mappings_by_node.get(node.id, [])
        composite, node_metrics = _calculate_node(orm_mappings, metrics_by_ticker, history_rows_by_ticker, benchmark_rows, day)
        representative_mapping = None
        if composite.get("pulse") is None:
            run.sector_unavailable += 1
            metrics = {}
        else:
            run.sector_calculated += 1
            representative_mapping = next((mapping for mapping in orm_mappings if mapping.mapping_type == "etf_proxy" and mapping.role == "primary" and mapping.ticker in metrics_by_ticker), None)
            representative_mapping = representative_mapping or next((mapping for mapping in orm_mappings if mapping.mapping_type == "etf_proxy" and mapping.role == "secondary" and mapping.ticker in metrics_by_ticker), None)
            metrics = dict(node_metrics)
            sector_benchmark = sector_benchmark_by_node.get(node.id)
            if representative_mapping and sector_benchmark and sector_benchmark != representative_mapping.ticker and history_rows_by_ticker.get(sector_benchmark):
                sector_relative = calculate_etf_metrics(history_rows_by_ticker[representative_mapping.ticker], benchmark_rows=history_rows_by_ticker[sector_benchmark], benchmark_name=sector_benchmark, as_of=day)
                metrics["relative_strength_benchmarks"] = {**(metrics.get("relative_strength_benchmarks") or {}), sector_benchmark: {key: value for key, value in sector_relative.items() if key.startswith("rs_")}}
        prior = [item for item in snapshot_history.get(node.id, []) if item.trading_date < day]
        previous = prior[-1] if prior else None
        if previous:
            previous_by_node[node.id] = {"pulse": previous.pulse, "change_5d": previous.change_5d, "breadth": previous.breadth_score, "relative_strength": previous.relative_strength_score}
        cached_snapshot = existing_snapshot_by_key.get((node.id, day))
        if composite.get("pulse") is None and not (cached_snapshot and cached_snapshot.pulse is not None):
            continue
        benchmark_payload = {name: metrics_by_ticker.get(name, {}) for name in ("SPY", "QQQ")}
        if sector_benchmark_by_node.get(node.id) and (not representative_mapping or sector_benchmark_by_node[node.id] != representative_mapping.ticker):
            benchmark_payload[sector_benchmark_by_node[node.id]] = metrics_by_ticker.get(sector_benchmark_by_node[node.id], {})
        snapshot = cached_snapshot if composite.get("pulse") is None else _upsert_snapshot(db, node.id, day, composite, metrics=metrics, benchmark=benchmark_payload, previous=previous, prior_rows=prior, snapshot_cache=existing_snapshot_by_key)
        existing_snapshot_by_key[(node.id, day)] = snapshot
        if snapshot not in snapshot_history.setdefault(node.id, []):
            snapshot_history[node.id].append(snapshot)
        current_rows.append({"node_id": node.id, "node_key": node.node_key, "pulse": snapshot.pulse, "change_5d": snapshot.change_5d, "relative_strength": snapshot.relative_strength_score, "volume_score": snapshot.volume_score, "volume_z": metrics.get("volume_z"), "heat": snapshot.heat, "risk": snapshot.risk, "direction": snapshot.direction, "mood": snapshot.mood, "coverage_quality": snapshot.coverage_quality, "confidence": snapshot.confidence, "metrics_json": metrics})
    rolled_up = _rollup_base_hierarchy(db, nodes, day, existing_snapshot_by_key, snapshot_history)
    rolled_ids = {row["node_id"] for row in rolled_up}
    current_rows = [row for row in current_rows if row["node_id"] not in rolled_ids] + rolled_up
    db.flush()
    focus_signals = calculate_focus(current_rows, previous_by_node)
    db.execute(delete(IndustryPulseFocusSignal).where(IndustryPulseFocusSignal.trading_date == day))
    for signal in focus_signals:
        existing = IndustryPulseFocusSignal(node_id=signal.get("node_id"), trading_date=day, signal_type=signal.get("signal_type"))
        db.add(existing)
        existing.score, existing.rank, existing.payload = signal.get("score"), signal.get("rank"), _json_safe(signal.get("payload") or {})
        existing.confidence = float((signal.get("payload") or {}).get("confidence") or 0.5)
    run.focus_signal_count = len(focus_signals)
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    run.duration_ms = int((perf_counter() - started) * 1000)
    db.commit()
    health_counts: dict[str, int] = {}
    manual_rows = [mapping for mapping in all_mappings if mapping.classification_source == "MANUAL_CURATED_SEED"]
    manual_symbols = {mapping.ticker for mapping in manual_rows}
    valid_symbols = {ticker for ticker in manual_symbols if histories.get(ticker) and histories[ticker].bars}
    temporary_symbols = {mapping.ticker for mapping in manual_rows if mapping.health_status == "TEMPORARY_DATA_FAILURE"}
    invalid_symbols = {mapping.ticker for mapping in manual_rows if mapping.health_status in {"SEED_INVALID", "PERMANENT_SYMBOL_INVALID"}}
    for mapping in all_mappings:
        if mapping.classification_source == "MANUAL_CURATED_SEED":
            health_counts[mapping.health_status] = health_counts.get(mapping.health_status, 0) + 1
    return {"status": run.status, "run_id": run.id, "trading_date": day.isoformat(), "etf_total": run.etf_total, "constituent_total": len(pulse_symbols - set(ETF_SYMBOLS)), "manual_seed_memberships": len(manual_rows), "unique_ticker_count": len(manual_symbols), "valid_ticker_count": len(valid_symbols), "invalid_ticker_count": len(invalid_symbols), "temporary_data_failures": len(temporary_symbols), "yfinance_success": run.yfinance_success, "finnhub_fallback": run.finnhub_fallback, "failed": run.failed, "health_counts": health_counts, "sector_calculated": run.sector_calculated, "sector_unavailable": run.sector_unavailable, "focus_signal_count": run.focus_signal_count, "synthetic_indexes": synthetic_indexes, "duration_ms": run.duration_ms, "bootstrap": bootstrap}


def _score_weights() -> dict[str, float]:
    raw = get_settings().industry_pulse_score_weights
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return {str(key): float(value) for key, value in payload.items() if float(value) >= 0}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"trend": .25, "relative_strength": .25, "volume": .15, "momentum": .10, "breadth": .15, "consensus": .10}


def _apply_liquidity_floor(metrics: dict[str, dict[str, Any]]) -> None:
    floor = max(0.0, min(1.0, get_settings().industry_pulse_liquidity_floor))
    for row in metrics.values():
        row["liquidity_quality"] = max(floor, float(row.get("liquidity_quality") or 0))


def _latest_day(db: Session, taxonomy: str | None = None, level: str | None = None) -> date | None:
    query = select(func.max(IndustryPulseSnapshot.trading_date))
    if taxonomy or level:
        query = query.join(IndustryPulseNode, IndustryPulseNode.id == IndustryPulseSnapshot.node_id)
    if taxonomy:
        query = query.where(IndustryPulseNode.taxonomy == taxonomy)
    if level:
        query = query.where(IndustryPulseNode.level == level)
    return db.scalar(query)


def _snapshot_payload(db: Session, snapshot: IndustryPulseSnapshot, node: IndustryPulseNode | None = None) -> dict[str, Any]:
    node = node or db.get(IndustryPulseNode, snapshot.node_id)
    metrics = snapshot.metrics_json or {}
    basket = metrics.get("basket") or {}
    expected = expected_latest_market_session()
    freshness = "FRESH" if expected and snapshot.trading_date >= expected else "STALE"
    return {"node_id": snapshot.node_id, "node_key": node.node_key if node else None, "name": node.name if node else None, "name_zh": node.name_zh if node else None, "taxonomy": node.taxonomy if node else None, "trading_date": snapshot.trading_date.isoformat(), "pulse": snapshot.pulse, "mood": snapshot.mood, "regime": snapshot.regime, "heat": snapshot.heat, "risk": snapshot.risk, "change": {"1d": snapshot.change_1d, "5d": snapshot.change_5d, "20d": snapshot.change_20d}, "change_1d": snapshot.change_1d, "change_5d": snapshot.change_5d, "change_20d": snapshot.change_20d, "rank": None, "confidence": snapshot.confidence, "coverage_quality": snapshot.coverage_quality, "data_quality": snapshot.data_quality, "freshness": freshness, "direction": snapshot.direction, "trend_score": snapshot.trend_score, "relative_strength_score": snapshot.relative_strength_score, "volume_score": snapshot.volume_score, "momentum_score": snapshot.momentum_score, "breadth_score": snapshot.breadth_score, "consensus_score": snapshot.consensus_score, "proxy_mode": metrics.get("proxy_mode") or "DIRECT_ETF", "constituent_count": basket.get("valid_constituents", 0), "breadth": basket.get("breadth") or {}, "calculation_status": "READY" if snapshot.pulse is not None else "INSUFFICIENT_COVERAGE", "components": {"trend": snapshot.trend_score, "relative_strength": snapshot.relative_strength_score, "volume": snapshot.volume_score, "momentum": snapshot.momentum_score, "breadth": snapshot.breadth_score, "consensus": snapshot.consensus_score}}


def overview_payload(db: Session, range_days: int = 30) -> dict[str, Any]:
    day = _latest_day(db, "base", "sector")
    if day is None:
        return {"as_of": None, "range_days": range_days, "sectors": [], "rows": [], "status": "unavailable"}
    rows = db.scalars(select(IndustryPulseSnapshot).join(IndustryPulseNode, IndustryPulseNode.id == IndustryPulseSnapshot.node_id).where(IndustryPulseSnapshot.trading_date == day, IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "sector")).all()
    payload = [_snapshot_payload(db, row) for row in rows]
    sector_ids = [row.node_id for row in rows]
    proxies: dict[int, list[str]] = {}
    if sector_ids:
        for mapping in db.scalars(select(IndustryPulseInstrument).where(
            IndustryPulseInstrument.node_id.in_(sector_ids),
            IndustryPulseInstrument.enabled.is_(True),
            IndustryPulseInstrument.mapping_type == "etf_proxy",
        )).all():
            if mapping.ticker not in proxies.setdefault(mapping.node_id, []):
                proxies[mapping.node_id].append(mapping.ticker)
    history_by_node: dict[int, list[dict[str, Any]]] = {}
    if sector_ids:
        history_rows = db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id.in_(sector_ids), IndustryPulseSnapshot.trading_date >= day - timedelta(days=range_days)).order_by(IndustryPulseSnapshot.trading_date)).all()
        for row in history_rows:
            history_by_node.setdefault(row.node_id, []).append({"trading_date": row.trading_date.isoformat(), "pulse": row.pulse})
    for item in payload:
        item["history"] = history_by_node.get(item["node_id"], [])
        item["proxy_etfs"] = proxies.get(item["node_id"], [])
    payload.sort(key=lambda item: (item["pulse"] is None, -(item["pulse"] or 0)))
    for rank, item in enumerate(payload, 1): item["rank"] = rank
    return {"as_of": day.isoformat(), "range_days": range_days, "sectors": payload, "rows": payload, "status": "ready"}


def focus_payload(db: Session, range_days: int = 30) -> dict[str, Any]:
    day = db.scalar(select(func.max(IndustryPulseFocusSignal.trading_date)))
    if day is None: return {"as_of": None, "signals": [], "buckets": {}}
    signals = db.scalars(select(IndustryPulseFocusSignal).where(IndustryPulseFocusSignal.trading_date == day).order_by(IndustryPulseFocusSignal.signal_type, IndustryPulseFocusSignal.rank)).all()
    buckets: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        node = db.get(IndustryPulseNode, signal.node_id)
        snapshot = db.scalar(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id == signal.node_id, IndustryPulseSnapshot.trading_date == day))
        row = {"signal_type": signal.signal_type, "node_id": signal.node_id, "node_key": node.node_key if node else None, "name": node.name if node else None, "name_zh": node.name_zh if node else None, "score": signal.score, "rank": signal.rank, "confidence": snapshot.confidence if snapshot else signal.confidence, "coverage_quality": snapshot.coverage_quality if snapshot else None, "pulse": snapshot.pulse if snapshot else None, "change_5d": snapshot.change_5d if snapshot else None, "breadth_score": snapshot.breadth_score if snapshot else None, "relative_strength_score": snapshot.relative_strength_score if snapshot else None, "direction": snapshot.direction if snapshot else None, "heat": snapshot.heat if snapshot else None, "risk": snapshot.risk if snapshot else None, "mood": snapshot.mood if snapshot else None, "payload": signal.payload}
        buckets.setdefault(signal.signal_type, []).append(row)
    return {"as_of": day.isoformat(), "range_days": range_days, "signals": [item for values in buckets.values() for item in values], "buckets": buckets}


def taxonomy_payload(db: Session) -> dict[str, Any]:
    rows = db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.enabled.is_(True), IndustryPulseNode.taxonomy == "base").order_by(IndustryPulseNode.node_key)).all()
    node_ids = [row.id for row in rows]
    latest_dates = select(IndustryPulseSnapshot.node_id, func.max(IndustryPulseSnapshot.trading_date).label("trading_date")).where(IndustryPulseSnapshot.node_id.in_(node_ids)).group_by(IndustryPulseSnapshot.node_id).subquery()
    snapshots = {snapshot.node_id: snapshot for snapshot in db.scalars(select(IndustryPulseSnapshot).join(latest_dates, and_(IndustryPulseSnapshot.node_id == latest_dates.c.node_id, IndustryPulseSnapshot.trading_date == latest_dates.c.trading_date))).all()} if node_ids else {}
    return {"nodes": [{"id": row.id, "node_key": row.node_key, "name": row.name, "name_zh": row.name_zh, "taxonomy": row.taxonomy, "level": row.level, "parent_id": row.parent_id, "metadata": row.metadata_json or {}, **(_snapshot_payload(db, snapshots[row.id], row) if row.id in snapshots else {})} for row in rows]}


def system_status_payload(db: Session) -> dict[str, Any]:
    states = db.scalars(select(MarketDataSyncState)).all()
    freshness: dict[str, int] = {}
    priorities: dict[str, int] = {}
    for row in states:
        freshness[row.freshness_status] = freshness.get(row.freshness_status, 0) + 1
        priorities[row.priority] = priorities.get(row.priority, 0) + 1
    latest = db.scalar(select(IndustryPulseSyncRun).order_by(IndustryPulseSyncRun.started_at.desc()).limit(1))
    pending = db.scalar(select(func.count()).select_from(IndustrySeedReplacementReview).where(IndustrySeedReplacementReview.status == "PENDING_REVIEW")) or 0
    return {"market_data": {"total": len(states), "freshness": freshness, "priorities": priorities}, "replacement_pending": pending, "latest_run": {"status": latest.status, "started_at": latest.started_at, "finished_at": latest.finished_at, "failed": latest.failed} if latest else None}


def replacement_reviews_payload(db: Session) -> dict[str, Any]:
    rows = db.scalars(select(IndustrySeedReplacementReview).order_by(IndustrySeedReplacementReview.leaf_code, IndustrySeedReplacementReview.old_symbol)).all()
    return {"items": [{"leaf_code": row.leaf_code, "leaf_name": row.leaf_name, "old_symbol": row.old_symbol, "reason": row.reason, "last_valid_date": row.last_valid_date, "remaining_constituents": row.remaining_constituents, "suggested_candidates": row.suggested_candidates, "suggestion_reason": row.suggestion_reason, "confidence": row.confidence, "status": row.status} for row in rows], "count": len(rows)}


def ai_chain_payload(db: Session, range_days: int = 30) -> dict[str, Any]:
    day = _latest_day(db, "ai")
    all_nodes = db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.enabled.is_(True)).order_by(IndustryPulseNode.node_key)).all()
    nodes = [node for node in all_nodes if node.taxonomy == "ai"]
    nodes_by_id = {node.id: node for node in all_nodes}
    snapshots = {row.node_id: row for row in db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.trading_date == day)).all()} if day else {}
    history_by_node: dict[int, list[IndustryPulseSnapshot]] = {}
    if day:
        for row in db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.trading_date <= day, IndustryPulseSnapshot.trading_date >= day - timedelta(days=400)).order_by(IndustryPulseSnapshot.trading_date)).all():
            history_by_node.setdefault(row.node_id, []).append(row)
    children: dict[int | None, list[IndustryPulseNode]] = {}
    for row in nodes: children.setdefault(row.parent_id, []).append(row)
    proxies: dict[int, list[str]] = {}
    for mapping in db.scalars(select(IndustryPulseInstrument).where(
        IndustryPulseInstrument.node_id.in_([node.id for node in nodes]),
        IndustryPulseInstrument.enabled.is_(True),
        IndustryPulseInstrument.mapping_type == "etf_proxy",
    )).all():
        if mapping.ticker not in proxies.setdefault(mapping.node_id, []):
            proxies[mapping.node_id].append(mapping.ticker)
    def aggregate(node: IndustryPulseNode, snapshot: IndustryPulseSnapshot | None, descendants: list[IndustryPulseSnapshot], total_nodes: int) -> dict[str, Any]:
        evidence = [snapshot] if snapshot else descendants

        def mean(field: str) -> float | None:
            values = [float(value) for item in evidence if (value := getattr(item, field)) is not None]
            return sum(values) / len(values) if values else None

        direct_metrics = snapshot.metrics_json or {} if snapshot else {}
        basket = direct_metrics.get("basket") or {}
        return {
            "id": node.id, "node_key": node.node_key, "name": node.name, "name_zh": node.name_zh,
            "pulse": mean("pulse"), "change_5d": mean("change_5d"), "breadth": mean("breadth_score"),
            "relative_strength_score": mean("relative_strength_score"), "confidence": mean("confidence"),
            "coverage_quality": mean("coverage_quality"), "heat": mean("heat"), "risk": mean("risk"),
            "mood": snapshot.mood if snapshot else "derived" if evidence else "unavailable",
            "covered_nodes": len(descendants), "total_nodes": total_nodes,
            "derived_from_children": snapshot is None and bool(descendants),
            "proxy_mode": direct_metrics.get("proxy_mode") if snapshot else "DERIVED" if descendants else None,
            "proxy_etfs": proxies.get(node.id, []),
            "constituent_count": basket.get("valid_constituents", 0),
            "synthetic_available": int(basket.get("valid_constituents", 0) or 0) >= get_settings().industry_pulse_min_constituents,
            "synthetic_confidence": basket.get("coverage_confidence", "UNAVAILABLE"),
            "synthetic_coverage_quality": basket.get("effective_weight_coverage"),
            "breadth_detail": basket.get("breadth") or {},
            "calculation_status": "READY" if evidence and mean("pulse") is not None else "INSUFFICIENT_COVERAGE",
        }

    groups: list[dict[str, Any]] = []
    for category in children.get(None, []):
        category_groups = []
        category_rows: list[dict[str, Any]] = []
        category_descendants: list[IndustryPulseSnapshot] = []
        for group in children.get(category.id, []):
            group_nodes: list[dict[str, Any]] = []
            group_snapshots: list[IndustryPulseSnapshot] = []
            for leaf in children.get(group.id, []):
                snapshot = snapshots.get(leaf.id)
                payload = aggregate(leaf, snapshot, [], 1)
                group_nodes.append(payload)
                if snapshot and snapshot.pulse is not None:
                    group_snapshots.append(snapshot)
            group_payload = aggregate(group, snapshots.get(group.id), group_snapshots, len(group_nodes))
            group_payload["proxy_etfs"] = list(dict.fromkeys(group_payload["proxy_etfs"] + [ticker for leaf in group_nodes for ticker in leaf["proxy_etfs"]]))
            group_payload["nodes"] = group_nodes
            group_payload["rows"] = [row for row in group_nodes if row.get("pulse") is not None]
            category_groups.append(group_payload)
            category_rows.append(group_payload)
            category_descendants.extend(group_snapshots)
        category_payload = aggregate(category, snapshots.get(category.id), category_descendants, len(category_groups))
        groups.append({**category_payload, "groups": category_groups, "industry_groups": category_groups, "rows": category_rows, "nodes": category_rows})
    relation_rows = db.scalars(select(IndustryPulseRelation).order_by(IndustryPulseRelation.id)).all()
    relations = [{"source_id": edge.source_node_id, "target_id": edge.target_node_id, "relation": edge.relation_type, "weight": edge.weight} for edge in relation_rows]
    group_rows = [node for group in groups for node in group["rows"]]
    calculable_rows = [node for node in group_rows if node.get("pulse") is not None]
    eligible_rows = [node for node in calculable_rows if float(node.get("confidence") or 0) >= get_settings().industry_pulse_constituent_confidence_threshold and float(node.get("coverage_quality") or 0) >= get_settings().industry_pulse_min_effective_coverage]
    strong_rows = [node for node in eligible_rows if node["pulse"] >= 60]
    breadth = len(strong_rows) / len(eligible_rows) if eligible_rows else 0.0
    breadth_summary = {"score": breadth, "strong_nodes": len(strong_rows), "eligible_nodes": len(eligible_rows), "total_nodes": len(group_rows), "status": "READY" if eligible_rows else "INSUFFICIENT_COVERAGE"}
    propagation_edges = []
    for edge in relation_rows:
        if edge.relation_type != "downstream":
            continue
        source_snapshot, target_snapshot = snapshots.get(edge.source_node_id), snapshots.get(edge.target_node_id)
        source_pulse = source_snapshot.pulse if source_snapshot else None
        target_pulse = target_snapshot.pulse if target_snapshot else None
        target_change = target_snapshot.change_5d if target_snapshot else None
        def eligibility(snapshot: IndustryPulseSnapshot | None) -> str | None:
            if snapshot is None or snapshot.pulse is None:
                return "INSUFFICIENT_COVERAGE"
            if len([row for row in history_by_node.get(snapshot.node_id, []) if row.pulse is not None]) < get_settings().industry_pulse_propagation_history_days:
                return "INSUFFICIENT_HISTORY"
            if float(snapshot.confidence or 0) < get_settings().industry_pulse_constituent_confidence_threshold:
                return "LOW_CONFIDENCE"
            if float(snapshot.coverage_quality or 0) < get_settings().industry_pulse_min_effective_coverage:
                return "INSUFFICIENT_COVERAGE"
            return None
        issue = eligibility(source_snapshot) or eligibility(target_snapshot)
        if issue:
            status, phase = issue, None
        else:
            target_history = history_by_node.get(edge.target_node_id, [])
            prior20 = target_history[-21] if len(target_history) >= 21 else None
            pulse_change20 = target_pulse - prior20.pulse if target_pulse is not None and prior20 and prior20.pulse is not None else None
            heating = (target_change or 0) > 0 or (pulse_change20 or 0) >= 5
            status = "ACTIVE" if source_pulse is not None and source_pulse >= 60 and target_pulse is not None and target_pulse >= 50 and heating else "LAGGING" if source_pulse is not None and source_pulse >= 60 else "DORMANT"
            phase = "DOWNSTREAM_HEATING" if status == "ACTIVE" and target_pulse is not None and target_pulse < 60 and heating else None
        propagation_edges.append({"source_id": edge.source_node_id, "source": nodes_by_id.get(edge.source_node_id).name if nodes_by_id.get(edge.source_node_id) else None, "source_zh": nodes_by_id.get(edge.source_node_id).name_zh if nodes_by_id.get(edge.source_node_id) else None, "target_id": edge.target_node_id, "target": nodes_by_id.get(edge.target_node_id).name if nodes_by_id.get(edge.target_node_id) else None, "target_zh": nodes_by_id.get(edge.target_node_id).name_zh if nodes_by_id.get(edge.target_node_id) else None, "source_pulse": source_pulse, "target_pulse": target_pulse, "target_change_5d": target_change, "status": status, "phase": phase})
    active_edges = [edge for edge in propagation_edges if edge["status"] == "ACTIVE"]
    propagation_status = "BROADENING" if len(active_edges) >= 3 else "STABLE" if active_edges else "CONCENTRATING"
    propagation_frontier = (active_edges[-1].get("target_zh") or active_edges[-1]["target"]) if active_edges else None
    if not strong_rows:
        concentration = {"status": "NO_STRONG_NODES", "score": None, "label_zh": "暂无强势链条", "strong_node_count": 0, "top_node_share": None, "top_three_share": None}
    else:
        strengths = sorted(((max(0.0, float(node["pulse"]) - 50), node) for node in strong_rows), key=lambda item: item[0])
        total_strength = sum(value for value, _ in strengths) or 1.0
        shares = sorted((value / total_strength for value, _ in strengths), reverse=True)
        top_share, top_three = shares[0], sum(shares[:3])
        strong_categories = sum(any(node in strong_rows for node in group["rows"]) for group in groups)
        state = "HIGHLY_CONCENTRATED" if len(strong_rows) <= 2 or top_share >= .5 else "CONCENTRATED" if top_three >= .75 or strong_categories <= 2 else "BROAD" if breadth >= .6 and strong_categories >= 4 else "BALANCED"
        concentration = {"status": state, "score": top_three, "label_zh": {"HIGHLY_CONCENTRATED": "高度集中", "CONCENTRATED": "相对集中", "BALANCED": "结构均衡", "BROAD": "广泛扩散"}[state], "strong_node_count": len(strong_rows), "top_node_share": top_share, "top_three_share": top_three, "strong_subchains": strong_categories}
    available_groups = calculable_rows
    total_groups = sum(len(group["industry_groups"]) for group in groups)
    confidence_counts = {"high": 0, "medium": 0, "low": 0, "unavailable": 0}
    proxy_counts = {"DIRECT_ETF": 0, "EQUITY_BASKET": 0, "HYBRID": 0}
    for row in group_rows:
        if row.get("pulse") is None:
            confidence_counts["unavailable"] += 1
            continue
        confidence = float(row.get("confidence") or 0)
        confidence_counts["high" if confidence >= .75 else "medium" if confidence >= .55 else "low"] += 1
        if row.get("proxy_mode") in proxy_counts:
            proxy_counts[row["proxy_mode"]] += 1
    coverage = {"total_nodes": total_groups, "direct_etf_nodes": proxy_counts["DIRECT_ETF"], "equity_basket_nodes": proxy_counts["EQUITY_BASKET"], "hybrid_nodes": proxy_counts["HYBRID"], "calculable_nodes": len(calculable_rows), "eligible_nodes": len(eligible_rows), "insufficient_nodes": total_groups - len(calculable_rows), "confidence": confidence_counts}
    synthetic_confidence = {key: sum(str(row.get("synthetic_confidence") or "UNAVAILABLE").upper() == key.upper() for row in group_rows) for key in ("high", "medium", "low", "unavailable")}
    synthetic_quality = [float(row["synthetic_coverage_quality"]) for row in group_rows if row.get("synthetic_coverage_quality") is not None]
    synthetic_coverage = {"total_nodes": len(group_rows), "available_nodes": sum(bool(row.get("synthetic_available")) for row in group_rows), "effective_data_coverage": sum(synthetic_quality) / len(synthetic_quality) if synthetic_quality else None, "confidence": synthetic_confidence}
    def historical_breadth(period: int) -> float | None:
        rows: list[IndustryPulseSnapshot] = []
        for group in [node for node in nodes if node.level == "group"]:
            history = [item for item in history_by_node.get(group.id, []) if item.pulse is not None]
            if len(history) > period:
                candidate = history[-1 - period]
                if float(candidate.confidence or 0) >= get_settings().industry_pulse_constituent_confidence_threshold and float(candidate.coverage_quality or 0) >= get_settings().industry_pulse_min_effective_coverage:
                    rows.append(candidate)
        return sum(float(row.pulse or 0) >= 60 for row in rows) / len(rows) if rows else None
    breadth_5d, breadth_20d = historical_breadth(5), historical_breadth(20)
    breadth_change_5d = breadth - breadth_5d if breadth_5d is not None else None
    breadth_change_20d = breadth - breadth_20d if breadth_20d is not None else None
    broadening_state = "RAPIDLY_BROADENING" if (breadth_change_5d or 0) >= .15 else "BROADENING" if (breadth_change_5d or 0) >= .05 or (breadth_change_20d or 0) >= .10 else "CONCENTRATING" if (breadth_change_5d or 0) <= -.05 else "STABLE"
    leaf_nodes = [leaf for category in groups for group in category["industry_groups"] for leaf in group["nodes"]]
    return {"as_of": day.isoformat() if day else None, "groups": groups, "nodes": leaf_nodes, "relations": relations, "hierarchy": relations, "breadth": breadth, "breadth_summary": breadth_summary, "chain_breadth_score": breadth, "chain_breadth_change_5d": breadth_change_5d, "chain_breadth_change_20d": breadth_change_20d, "chain_broadening_status": broadening_state, "concentration": concentration, "propagation_status": propagation_status, "propagation_frontier": propagation_frontier, "propagation_edges": propagation_edges, "coverage": coverage, "synthetic_coverage": synthetic_coverage, "available_groups": len(available_groups), "total_groups": total_groups}


def node_detail_payload(db: Session, node_id: int, range_days: int = 30) -> dict[str, Any] | None:
    node = db.get(IndustryPulseNode, node_id)
    if not node: return None
    latest_day = db.scalar(select(func.max(IndustryPulseSnapshot.trading_date)).where(IndustryPulseSnapshot.node_id == node_id))
    since = (latest_day or date.today()) - timedelta(days=range_days)
    snapshots = db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id == node_id, IndustryPulseSnapshot.trading_date >= since).order_by(IndustryPulseSnapshot.trading_date.asc())).all()
    mappings = db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.node_id == node_id)).all()
    latest = snapshots[-1] if snapshots else None
    composite = _snapshot_payload(db, latest) if latest else None
    node_payload = {"id": node.id, "node_key": node.node_key, "name": node.name, "name_zh": node.name_zh, "taxonomy": node.taxonomy, "level": node.level, "parent_id": node.parent_id, **(composite or {})}
    narrative = db.scalar(select(IndustryPulseNarrative).where(IndustryPulseNarrative.node_id == node_id).order_by(IndustryPulseNarrative.trading_date.desc()).limit(1))
    latest_metrics = latest.metrics_json or {} if latest else {}
    relative = latest_metrics.get("relative_strength_benchmarks") or (latest_metrics.get("basket") or {}).get("relative_strength_benchmarks") or {}
    node_payload["relative_strength"] = relative
    metrics = latest.metrics_json if latest else {}
    basket = metrics.get("basket") or {}
    basket_members = {row.get("ticker"): row for row in basket.get("members", [])}
    breadth_members = {row.get("ticker"): row for row in (basket.get("breadth") or {}).get("constituents", [])}
    market_states = {row.symbol: row for row in db.scalars(select(MarketDataSyncState).where(MarketDataSyncState.symbol.in_([mapping.ticker for mapping in mappings]))).all()}
    constituents = []
    for row in mappings:
        if row.instrument_type != "stock" or row.mapping_type not in {"theme_exposure", "primary_industry"}:
            continue
        state = market_states.get(row.ticker)
        stats = breadth_members.get(row.ticker) or {}
        weight = (basket_members.get(row.ticker) or {}).get("weight", .2 if row.classification_source == "MANUAL_CURATED_SEED" else None)
        constituents.append({"ticker": row.ticker, "slot": row.slot, "role": row.constituent_role, "sub_role": (row.metadata_json or {}).get("sub_role"), "purity": row.purity, "exposure": row.exposure, "confidence": row.confidence, "weight": weight, "classification_source": row.classification_source, "audit_status": (row.metadata_json or {}).get("audit_status"), "validation_status": (row.metadata_json or {}).get("seed_validation_status"), "health_status": "PENDING_REPLACEMENT" if not row.enabled else row.health_status, "freshness": state.freshness_status if state else "MISSING", "latest_date": state.latest_market_date.isoformat() if state and state.latest_market_date else None, "short_reason": (row.metadata_json or {}).get("short_reason"), "enabled_for_pulse": row.enabled_for_pulse, "valid_from": row.valid_from.isoformat() if row.valid_from else None, "valid_to": row.valid_to.isoformat() if row.valid_to else None, **stats, "contribution_5d": float(stats.get("return_5d") or 0) * float(weight or 0)})
    etfs = [{"ticker": row.ticker, "role": row.role, "mapping_type": row.mapping_type, "purity": row.purity, "exposure": row.exposure, "confidence": row.confidence, "health_status": row.health_status, "data_quality": row.data_quality} for row in mappings if row.mapping_type == "etf_proxy" and row.enabled]
    return {"node": node_payload, "proxy_mode": metrics.get("proxy_mode") or "DIRECT_ETF", "etfs": etfs, "constituents": constituents, "breadth": basket.get("breadth") or {}, "metrics": metrics, "composite": composite, "history": [_snapshot_payload(db, row) for row in snapshots], "mood": latest.mood if latest else "unavailable", "benchmark": latest.benchmark_json if latest else {}, "relative_strength": relative, "ai_summary": narrative.summary if narrative else None, "ai_summary_meta": {"model": narrative.model, "status": narrative.status} if narrative else None}


__all__ = ["ai_chain_payload", "ensure_seed_data", "focus_payload", "node_detail_payload", "overview_payload", "replacement_reviews_payload", "sync_pulse", "system_status_payload", "taxonomy_payload"]
