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
    CompanyProfile,
    Security,
    StockProfile,
)
from app.services.industry_pulse.calculation import calculate_composite, calculate_etf_metrics, calculate_focus, detect_regime
from app.services.industry_pulse.classification import classify_security
from app.services.industry_pulse.definitions import AI_RELATIONS, AI_TAXONOMY, BASE_TAXONOMY, ETF_REGISTRY, ETF_SYMBOLS, pulse_mappings
from app.services.industry_pulse.provider import DailyBar, ProviderHistory, fetch_histories

logger = logging.getLogger(__name__)
CALCULATION_VERSION = "industry_pulse_v1"


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
            existing.metadata_json = {**(existing.metadata_json or {}), **metadata}
            existing.enabled = bool(registry.get("enabled", True)) and bool(mapping.get("enabled", True))
    db.flush()
    return {"nodes": len(rows), "relations": len(AI_RELATIONS), "mappings": mapping_count, "etfs": len(ETF_REGISTRY)}


def sync_security_classifications(db: Session) -> dict[str, int]:
    """Persist deterministic stock classifications without mixing them into ETF Pulse weights."""
    nodes = {row.node_key: row for row in db.scalars(select(IndustryPulseNode)).all()}
    stock_profiles = {row.ticker.upper(): row for row in db.scalars(select(StockProfile)).all()}
    company_profiles = {row.symbol.upper(): row for row in db.scalars(select(CompanyProfile)).all()}
    mappings_by_security: dict[int, list[IndustryPulseInstrument]] = {}
    for row in db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.instrument_type == "stock")).all():
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
            existing.enabled = False
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
            row = next((item for item in existing_rows if item.node_id == node.id and item.role == "reference"), None)
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
            row.metadata_json = {"source": result.get("source"), "included_in_theme_pulse": row.enabled, "trusted": False}
    db.flush()
    return {"classified": classified, "unclassified": unclassified, "mappings_written": mappings_written}


def _upsert_history(db: Session, ticker: str, history: ProviderHistory, existing_cache: dict[tuple[str, str, date], HistoricalPrice] | None = None) -> int:
    inserted = 0
    if not history.bars or not history.provider:
        return inserted
    existing_by_date = {day: row for (symbol, source, day), row in (existing_cache or {}).items() if symbol == ticker and source == history.provider} if existing_cache is not None else {row.date: row for row in db.scalars(select(HistoricalPrice).where(HistoricalPrice.symbol == ticker, HistoricalPrice.source == history.provider)).all()}
    for bar in history.bars:
        row = existing_by_date.get(bar.date)
        if row is None:
            row = HistoricalPrice(symbol=ticker, date=bar.date, source=history.provider)
            db.add(row)
            if existing_cache is not None:
                existing_cache[(ticker, history.provider, bar.date)] = row
            inserted += 1
            existing_by_date[bar.date] = row
        row.open, row.high, row.low, row.close, row.volume = bar.open, bar.high, bar.low, bar.close, bar.volume
    return inserted


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
    return [{"date": row.date, "open": float(row.open), "high": float(row.high), "low": float(row.low), "close": float(row.close), "volume": row.volume} for row in (chosen[day] for day in sorted(chosen))]


def _merge_history(stored: list[dict[str, Any]], fresh: list[DailyBar]) -> list[dict[str, Any]]:
    merged = {row["date"]: row for row in stored}
    for bar in fresh:
        merged[bar.date] = bar.as_dict()
    return [merged[day] for day in sorted(merged)]


def _mapping_payload(row: IndustryPulseInstrument) -> dict[str, Any]:
    return {"ticker": row.ticker, "role": row.role, "mapping_type": row.mapping_type, "purity": row.purity, "exposure_weight": row.exposure, "confidence": row.confidence, "liquidity": row.liquidity}


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
    row.source = "deterministic_etf_composite"
    return row


def sync_pulse(db: Session, *, as_of: date | None = None, trigger_type: str = "scheduled") -> dict[str, Any]:
    """Fetch, calculate and commit numeric snapshots before optional AI work."""
    started = perf_counter()
    requested_day = as_of or datetime.now(UTC).date()
    if db.get_bind().dialect.name == "postgresql" and not db.scalar(select(func.pg_try_advisory_xact_lock(81730121))):
        return {"status": "running"}
    ensure_seed_data(db)
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
    stored_prices = db.scalars(select(HistoricalPrice).where(HistoricalPrice.symbol.in_(list(ETF_SYMBOLS)))).all()
    stored_price_cache = {(row.symbol, row.source, row.date): row for row in stored_prices}
    cached_dates: dict[str, set[date]] = {}
    for row in stored_prices:
        cached_dates.setdefault(row.symbol, set()).add(row.date)
    fetch_days = 45 if all(len(cached_dates.get(ticker, set())) >= 252 for ticker in ETF_SYMBOLS) else get_settings().industry_pulse_history_days
    histories = fetch_histories(list(ETF_SYMBOLS), days=fetch_days)
    run.etf_total = len(histories)
    for ticker, history in histories.items():
        if history.provider:
            _upsert_history(db, ticker, history, stored_price_cache)
        for mapping in mappings_by_ticker.get(ticker, []):
            mapping.health_status = "ACTIVE" if history.status == "success" else "DEGRADED" if history.status == "degraded" else "FALLBACK" if history.status == "fallback" else "UNAVAILABLE"
            mapping.last_checked_at = datetime.now(UTC)
            mapping.last_trading_date = history.bars[-1].date if history.bars else None
            mapping.data_quality = history.data_quality
            mapping.error_code = history.error_code
        if history.status == "success": run.yfinance_success += 1
        elif history.status == "fallback": run.finnhub_fallback += 1
        elif not history.bars: run.failed += 1
    db.flush()
    stored_by_ticker: dict[str, list[HistoricalPrice]] = {}
    for row in stored_price_cache.values():
        stored_by_ticker.setdefault(row.symbol, []).append(row)
    stored_history_by_ticker = {ticker: _stored_history_payload(stored_by_ticker.get(ticker, [])) for ticker in ETF_SYMBOLS}
    history_rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for ticker, history in histories.items():
        history_rows_by_ticker[ticker] = _merge_history(stored_history_by_ticker.get(ticker, []), history.bars)
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
    mapped_nodes = [(node, etfs) for node in nodes if (etfs := [mapping for mapping in mappings_by_node.get(node.id, []) if mapping.mapping_type == "etf_proxy"])]
    # Causal backfill: only dates present in the benchmark history are used,
    # and every indicator is sliced at that date before being persisted.
    backfill_limit = max(0, int(get_settings().industry_pulse_backfill_days))
    all_trading_days = sorted({row["date"] for row in benchmark_rows.get("SPY", []) if row.get("date") and row["date"] <= day})
    trading_days = all_trading_days[-backfill_limit:] if backfill_limit else []
    snapshot_history: dict[int, list[IndustryPulseSnapshot]] = {node.id: [] for node, _ in mapped_nodes}
    existing_snapshot_by_key: dict[tuple[int, date], IndustryPulseSnapshot] = {}
    if nodes:
        min_day = trading_days[0] if trading_days else day - timedelta(days=max(5, int(get_settings().industry_pulse_backfill_days) * 2))
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
            composite = calculate_composite(metrics_at_day, [{**_mapping_payload(mapping), "ticker": mapping.ticker} for mapping in orm_mappings], benchmark_metrics={name: metrics_at_day.get(name, {}) for name in ("SPY", "QQQ")}, weights=_score_weights(), exposure_threshold=get_settings().industry_pulse_exposure_threshold)
            representative = next((metrics_at_day.get(mapping.ticker, {}) for mapping in orm_mappings if mapping.ticker in metrics_at_day), {})
            prior = [item for item in snapshot_history.get(node.id, []) if item.trading_date < calc_day]
            previous = prior[-1] if prior else None
            cached_snapshot = existing_snapshot_by_key.get((node.id, calc_day))
            if composite.get("pulse") is None and not (cached_snapshot and cached_snapshot.pulse is not None):
                continue
            snapshot = cached_snapshot if composite.get("pulse") is None else _upsert_snapshot(db, node.id, calc_day, composite, metrics=representative, benchmark={name: metrics_at_day.get(name, {}) for name in ("SPY", "QQQ")}, previous=previous, prior_rows=prior, snapshot_cache=existing_snapshot_by_key)
            existing_snapshot_by_key[(node.id, calc_day)] = snapshot
            if snapshot not in snapshot_history.setdefault(node.id, []):
                snapshot_history[node.id].append(snapshot)
    db.flush()
    current_rows: list[dict[str, Any]] = []
    previous_by_node: dict[int, dict[str, Any]] = {}
    for node in nodes:
        orm_mappings = mappings_by_node.get(node.id, [])
        mapping_dicts = [{**_mapping_payload(mapping), "ticker": mapping.ticker} for mapping in orm_mappings]
        composite = calculate_composite(metrics_by_ticker, mapping_dicts, benchmark_metrics={name: metrics_by_ticker.get(name, {}) for name in ("SPY", "QQQ")}, weights=_score_weights(), exposure_threshold=get_settings().industry_pulse_exposure_threshold)
        representative_mapping = None
        if composite.get("pulse") is None:
            run.sector_unavailable += 1
            metrics = {}
        else:
            run.sector_calculated += 1
            representative_mapping = next((mapping for mapping in orm_mappings if mapping.mapping_type == "etf_proxy" and mapping.role == "primary" and mapping.ticker in metrics_by_ticker), None)
            representative_mapping = representative_mapping or next((mapping for mapping in orm_mappings if mapping.mapping_type == "etf_proxy" and mapping.role == "secondary" and mapping.ticker in metrics_by_ticker), None)
            metrics = dict(metrics_by_ticker.get(representative_mapping.ticker, {})) if representative_mapping else {}
            sector_benchmark = sector_benchmark_by_node.get(node.id)
            if representative_mapping and sector_benchmark and sector_benchmark != representative_mapping.ticker and history_rows_by_ticker.get(sector_benchmark):
                sector_relative = calculate_etf_metrics(history_rows_by_ticker[representative_mapping.ticker], benchmark_rows=history_rows_by_ticker[sector_benchmark], benchmark_name=sector_benchmark, as_of=day)
                metrics["relative_strength_benchmarks"] = {**(metrics.get("relative_strength_benchmarks") or {}), sector_benchmark: {key: value for key, value in sector_relative.items() if key.startswith("rs_")}}
        prior = [item for item in snapshot_history.get(node.id, []) if item.trading_date < day]
        previous = prior[-1] if prior else None
        if previous:
            previous_by_node[node.id] = {"pulse": previous.pulse, "change_5d": previous.change_5d}
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
    return {"status": run.status, "run_id": run.id, "trading_date": day.isoformat(), "etf_total": run.etf_total, "yfinance_success": run.yfinance_success, "finnhub_fallback": run.finnhub_fallback, "failed": run.failed, "sector_calculated": run.sector_calculated, "sector_unavailable": run.sector_unavailable, "focus_signal_count": run.focus_signal_count, "duration_ms": run.duration_ms}


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
    return {"node_id": snapshot.node_id, "node_key": node.node_key if node else None, "name": node.name if node else None, "name_zh": node.name_zh if node else None, "taxonomy": node.taxonomy if node else None, "trading_date": snapshot.trading_date.isoformat(), "pulse": snapshot.pulse, "mood": snapshot.mood, "regime": snapshot.regime, "heat": snapshot.heat, "risk": snapshot.risk, "change": {"1d": snapshot.change_1d, "5d": snapshot.change_5d, "20d": snapshot.change_20d}, "change_1d": snapshot.change_1d, "change_5d": snapshot.change_5d, "change_20d": snapshot.change_20d, "rank": None, "confidence": snapshot.confidence, "coverage_quality": snapshot.coverage_quality, "data_quality": snapshot.data_quality, "direction": snapshot.direction, "trend_score": snapshot.trend_score, "relative_strength_score": snapshot.relative_strength_score, "volume_score": snapshot.volume_score, "momentum_score": snapshot.momentum_score, "breadth_score": snapshot.breadth_score, "consensus_score": snapshot.consensus_score, "components": {"trend": snapshot.trend_score, "relative_strength": snapshot.relative_strength_score, "volume": snapshot.volume_score, "momentum": snapshot.momentum_score, "breadth": snapshot.breadth_score, "consensus": snapshot.consensus_score}}


def overview_payload(db: Session, range_days: int = 30) -> dict[str, Any]:
    day = _latest_day(db, "base", "sector")
    if day is None:
        return {"as_of": None, "range_days": range_days, "sectors": [], "rows": [], "status": "unavailable"}
    rows = db.scalars(select(IndustryPulseSnapshot).join(IndustryPulseNode, IndustryPulseNode.id == IndustryPulseSnapshot.node_id).where(IndustryPulseSnapshot.trading_date == day, IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "sector")).all()
    payload = [_snapshot_payload(db, row) for row in rows]
    sector_ids = [row.node_id for row in rows]
    history_by_node: dict[int, list[dict[str, Any]]] = {}
    if sector_ids:
        history_rows = db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id.in_(sector_ids), IndustryPulseSnapshot.trading_date >= day - timedelta(days=range_days)).order_by(IndustryPulseSnapshot.trading_date)).all()
        for row in history_rows:
            history_by_node.setdefault(row.node_id, []).append({"trading_date": row.trading_date.isoformat(), "pulse": row.pulse})
    for item in payload:
        item["history"] = history_by_node.get(item["node_id"], [])
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


def ai_chain_payload(db: Session, range_days: int = 30) -> dict[str, Any]:
    day = _latest_day(db, "ai")
    all_nodes = db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.enabled.is_(True)).order_by(IndustryPulseNode.node_key)).all()
    nodes = [node for node in all_nodes if node.taxonomy == "ai"]
    nodes_by_id = {node.id: node for node in all_nodes}
    snapshots = {row.node_id: row for row in db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.trading_date == day)).all()} if day else {}
    children: dict[int | None, list[IndustryPulseNode]] = {}
    for row in nodes: children.setdefault(row.parent_id, []).append(row)
    def aggregate(node: IndustryPulseNode, snapshot: IndustryPulseSnapshot | None, descendants: list[IndustryPulseSnapshot], total_nodes: int) -> dict[str, Any]:
        evidence = [snapshot] if snapshot else descendants

        def mean(field: str) -> float | None:
            values = [float(value) for item in evidence if (value := getattr(item, field)) is not None]
            return sum(values) / len(values) if values else None

        return {
            "id": node.id, "node_key": node.node_key, "name": node.name, "name_zh": node.name_zh,
            "pulse": mean("pulse"), "change_5d": mean("change_5d"), "breadth": mean("breadth_score"),
            "relative_strength_score": mean("relative_strength_score"), "confidence": mean("confidence"),
            "coverage_quality": mean("coverage_quality"), "heat": mean("heat"), "risk": mean("risk"),
            "mood": snapshot.mood if snapshot else "derived" if evidence else "unavailable",
            "covered_nodes": len(descendants), "total_nodes": total_nodes,
            "derived_from_children": snapshot is None and bool(descendants),
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
            group_payload["nodes"] = group_nodes
            group_payload["rows"] = [row for row in group_nodes if row.get("pulse") is not None]
            category_groups.append(group_payload)
            if group_payload["pulse"] is not None:
                category_rows.append(group_payload)
            category_descendants.extend(group_snapshots)
        category_payload = aggregate(category, snapshots.get(category.id), category_descendants, len(category_groups))
        groups.append({**category_payload, "groups": category_groups, "industry_groups": category_groups, "rows": category_rows, "nodes": category_rows})
    relation_rows = db.scalars(select(IndustryPulseRelation).order_by(IndustryPulseRelation.id)).all()
    relations = [{"source_id": edge.source_node_id, "target_id": edge.target_node_id, "relation": edge.relation_type, "weight": edge.weight} for edge in relation_rows]
    scored = [node["pulse"] for group in groups for node in group["rows"] if node.get("pulse") is not None]
    breadth = sum(value >= 60 for value in scored) / len(scored) if scored else 0.0
    propagation_edges = []
    for edge in relation_rows:
        if edge.relation_type != "downstream":
            continue
        source_snapshot, target_snapshot = snapshots.get(edge.source_node_id), snapshots.get(edge.target_node_id)
        source_pulse = source_snapshot.pulse if source_snapshot else None
        target_pulse = target_snapshot.pulse if target_snapshot else None
        target_change = target_snapshot.change_5d if target_snapshot else None
        status = "active" if source_pulse is not None and source_pulse >= 60 and target_pulse is not None and target_pulse >= 50 and target_change is not None and target_change > 0 else "lagging" if source_pulse is not None and source_pulse >= 60 else "dormant"
        propagation_edges.append({"source_id": edge.source_node_id, "source": nodes_by_id.get(edge.source_node_id).name if nodes_by_id.get(edge.source_node_id) else None, "source_zh": nodes_by_id.get(edge.source_node_id).name_zh if nodes_by_id.get(edge.source_node_id) else None, "target_id": edge.target_node_id, "target": nodes_by_id.get(edge.target_node_id).name if nodes_by_id.get(edge.target_node_id) else None, "target_zh": nodes_by_id.get(edge.target_node_id).name_zh if nodes_by_id.get(edge.target_node_id) else None, "source_pulse": source_pulse, "target_pulse": target_pulse, "target_change_5d": target_change, "status": status})
    active_edges = [edge for edge in propagation_edges if edge["status"] == "active"]
    propagation_status = "broadening" if len(active_edges) >= 3 else "mixed" if active_edges else "narrowing"
    propagation_frontier = (active_edges[-1].get("target_zh") or active_edges[-1]["target"]) if active_edges else None
    strong_by_category = [sum(node.get("pulse") is not None and node["pulse"] >= 60 for node in group["rows"]) for group in groups]
    concentration = max(strong_by_category) / sum(strong_by_category) if sum(strong_by_category) else None
    available_groups = [node for group in groups for node in group["rows"]]
    total_groups = sum(len(group["industry_groups"]) for group in groups)
    leaf_nodes = [leaf for category in groups for group in category["industry_groups"] for leaf in group["nodes"]]
    return {"as_of": day.isoformat() if day else None, "groups": groups, "nodes": leaf_nodes, "relations": relations, "hierarchy": relations, "breadth": breadth, "concentration": concentration, "propagation_status": propagation_status, "propagation_frontier": propagation_frontier, "propagation_edges": propagation_edges, "available_groups": len(available_groups), "total_groups": total_groups}


def node_detail_payload(db: Session, node_id: int, range_days: int = 30) -> dict[str, Any] | None:
    node = db.get(IndustryPulseNode, node_id)
    if not node: return None
    latest_day = db.scalar(select(func.max(IndustryPulseSnapshot.trading_date)).where(IndustryPulseSnapshot.node_id == node_id))
    since = (latest_day or date.today()) - timedelta(days=range_days)
    snapshots = db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.node_id == node_id, IndustryPulseSnapshot.trading_date >= since).order_by(IndustryPulseSnapshot.trading_date.asc())).all()
    mappings = db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.node_id == node_id, IndustryPulseInstrument.enabled.is_(True), IndustryPulseInstrument.mapping_type == "etf_proxy")).all()
    latest = snapshots[-1] if snapshots else None
    composite = _snapshot_payload(db, latest) if latest else None
    node_payload = {"id": node.id, "node_key": node.node_key, "name": node.name, "name_zh": node.name_zh, "taxonomy": node.taxonomy, "level": node.level, "parent_id": node.parent_id, **(composite or {})}
    narrative = db.scalar(select(IndustryPulseNarrative).where(IndustryPulseNarrative.node_id == node_id).order_by(IndustryPulseNarrative.trading_date.desc()).limit(1))
    relative = (latest.metrics_json or {}).get("relative_strength_benchmarks", {}) if latest else {}
    node_payload["relative_strength"] = relative
    return {"node": node_payload, "etfs": [{"ticker": row.ticker, "role": row.role, "mapping_type": row.mapping_type, "purity": row.purity, "exposure": row.exposure, "confidence": row.confidence, "health_status": row.health_status, "data_quality": row.data_quality} for row in mappings], "metrics": (latest.metrics_json if latest else {}), "composite": composite, "history": [_snapshot_payload(db, row) for row in snapshots], "mood": latest.mood if latest else "unavailable", "benchmark": latest.benchmark_json if latest else {}, "relative_strength": relative, "ai_summary": narrative.summary if narrative else None, "ai_summary_meta": {"model": narrative.model, "status": narrative.status} if narrative else None}


__all__ = ["ai_chain_payload", "ensure_seed_data", "focus_payload", "node_detail_payload", "overview_payload", "sync_pulse", "taxonomy_payload"]
