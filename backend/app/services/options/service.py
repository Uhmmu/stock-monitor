"""Persisted Options read model shared by API, AI tools, and reports."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    IndustryPulseInstrument,
    IndustryPulseNode,
    OptionsChainCache,
    OptionsSnapshot,
    OptionsSyncRun,
    Security,
    StockGroup,
    StockProfile,
    WatchlistItem,
)
from app.services.industry_pulse.definitions import BASE_TAXONOMY_BY_ID, ETF_REGISTRY
from app.services.options.analytics import classify_options_bias, enrich_options_history


RANK_FIELDS = {
    "activity": "activity_score",
    "iv": "atm_iv",
    "iv_change": "iv_change",
    "put_call_volume": "put_call_volume_ratio",
    "put_call_oi": "put_call_oi_ratio",
    "downside_skew": "downside_skew",
    "call_activity": "call_volume",
    "put_activity": "put_volume",
    "most_active": "activity_percentile",
    "activity_surge": "activity_change_1",
    "highest_iv": "atm_iv",
    "largest_iv_increase": "iv_change_1",
    "lowest_put_call": "put_call_volume_ratio",
    "highest_put_call": "put_call_volume_ratio",
    "largest_skew": "downside_skew",
    "largest_skew_change": "skew_change_1",
    "largest_oi_change": "oi_change_1",
}


def _latest_rows(db: Session) -> list[OptionsSnapshot]:
    latest = select(OptionsSnapshot.symbol, func.max(OptionsSnapshot.trading_date).label("day")).group_by(OptionsSnapshot.symbol).subquery()
    return list(db.scalars(select(OptionsSnapshot).join(latest, (OptionsSnapshot.symbol == latest.c.symbol) & (OptionsSnapshot.trading_date == latest.c.day))).all())


def _sector_ancestor(db: Session, node_id: int | None) -> IndustryPulseNode | None:
    node = db.get(IndustryPulseNode, node_id) if node_id else None
    seen: set[int] = set()
    while node and node.level != "sector" and node.parent_id and node.id not in seen:
        seen.add(node.id)
        node = db.get(IndustryPulseNode, node.parent_id)
    return node if node and node.level == "sector" else None


def _quality(row: OptionsSnapshot) -> dict[str, Any]:
    level = "HIGH" if row.quality_score >= .75 else "MEDIUM" if row.quality_score >= .45 else "LOW"
    return {"level": level, "score": row.quality_score, "coverage": row.coverage, "warnings": row.warnings or []}


def _term(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**item, "x": item.get("expiration"), "y": item.get("atm_iv")} for item in metrics.get("expiration_structure", [])]


def _distribution(metrics: dict[str, Any], key: str) -> list[dict[str, Any]]:
    result = []
    value_key = "open_interest" if key == "strike_oi_distribution" else "volume"
    for side, rows in (metrics.get(key) or {}).items():
        result.extend({**item, "side": side, "x": item.get("strike"), "y": item.get(value_key)} for item in rows)
    return result


def _stored_history(db: Session, symbol: str, *, limit: int = 365) -> list[OptionsSnapshot]:
    return list(reversed(list(
        db.scalars(
            select(OptionsSnapshot)
            .where(OptionsSnapshot.symbol == symbol.upper())
            .order_by(OptionsSnapshot.trading_date.desc())
            .limit(limit)
        ).all()
    )))


def _state_from_metrics(metrics: dict[str, Any], history: dict[str, Any] | None = None) -> dict[str, Any]:
    state = metrics.get("options_state") if isinstance(metrics.get("options_state"), dict) else {}
    if history and history.get("historical_comparison"):
        comparison = history["historical_comparison"]
        state = {**state}
        activity = {**(state.get("activity") or {})}
        activity["historical_comparison"] = comparison
        activity.setdefault("status", comparison.get("activity_level", comparison.get("status")))
        activity.setdefault("raw_metrics", {})
        activity["raw_metrics"] = {
            **activity["raw_metrics"],
            "percentile": comparison.get("activity_percentile"),
            "zscore": comparison.get("activity_zscore"),
        }
        state["activity"] = activity
        historical = {**(state.get("historical_regime") or {})}
        historical.update({"status": comparison.get("status"), "historical_comparison": comparison, "raw_metrics": {"anomaly": comparison.get("anomaly_status"), "direction": comparison.get("anomaly_direction")}})
        state["historical_regime"] = historical
    state.setdefault("activity", {"status": "INSUFFICIENT_HISTORY", "raw_metrics": {}, "historical_comparison": (history or {}).get("historical_comparison"), "quality": metrics.get("quality_score", 0.0), "confidence": "low"})
    state.setdefault("bias", {"status": metrics.get("options_bias", "INSUFFICIENT_DATA") if metrics.get("bias_status") == "READY" else "INSUFFICIENT_DATA", "raw_metrics": metrics.get("bias_components", {}), "historical_comparison": (history or {}).get("historical_comparison"), "quality": metrics.get("quality_score", 0.0), "confidence": "low"})
    iv_percentile = ((history or {}).get("historical_comparison") or {}).get("iv_percentile_20")
    risk_status = "INSUFFICIENT_DATA" if metrics.get("atm_iv") is None else "INSUFFICIENT_HISTORY" if iv_percentile is None else "IV_HIGH" if iv_percentile >= 80 else "IV_LOW" if iv_percentile <= 20 else "IV_NORMAL"
    state.setdefault("risk_pricing", {"status": risk_status, "raw_metrics": {key: metrics.get(key) for key in ("atm_iv", "near_term_iv", "next_term_iv", "downside_skew", "upside_skew", "term_structure_status")}, "historical_comparison": (history or {}).get("historical_comparison"), "quality": metrics.get("iv_quality", {}), "confidence": "medium" if metrics.get("atm_iv") is not None else "low"})
    positioning = metrics.get("positioning", {})
    state.setdefault("positioning", positioning if isinstance(positioning, dict) and positioning.get("status") else {"status": "INSUFFICIENT_DATA", "raw_metrics": {}, "historical_comparison": (history or {}).get("historical_comparison"), "quality": 0.0, "confidence": "low"})
    state.setdefault("historical_regime", {"status": (history or {}).get("status", "INSUFFICIENT_HISTORY"), "raw_metrics": {}, "historical_comparison": (history or {}).get("historical_comparison"), "quality": metrics.get("quality_score", 0.0), "confidence": "low"})
    return state


def snapshot_payload(
    db: Session,
    row: OptionsSnapshot,
    *,
    watchlist: WatchlistItem | None = None,
    history_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = {
        **(row.metrics_json or {}),
        "atm_iv": row.atm_iv,
        "near_term_iv": row.near_term_iv,
        "next_term_iv": row.next_term_iv,
        "downside_skew": row.downside_skew,
        "upside_skew": row.upside_skew,
        "quality_score": row.quality_score,
    }
    if metrics.get("total_oi") is None and row.call_open_interest is not None and row.put_open_interest is not None:
        metrics["total_oi"] = row.call_open_interest + row.put_open_interest
    total_volume = (row.call_volume + row.put_volume) if row.call_volume is not None and row.put_volume is not None else None
    total_oi = metrics.get("total_oi")
    if not metrics.get("bias_components"):
        metrics["bias_components"] = {
            "volume": ((row.call_volume - row.put_volume) / total_volume) if total_volume else None,
            "open_interest": ((row.call_open_interest - row.put_open_interest) / total_oi) if total_oi else None,
            "downside_skew": row.downside_skew,
        }
    if not metrics.get("options_bias"):
        metrics["options_bias"] = classify_options_bias(metrics["bias_components"]["volume"], metrics["bias_components"]["open_interest"])
    if metrics.get("options_bias") and not metrics.get("bias_status"):
        metrics["bias_status"] = "READY"
    if not metrics.get("positioning"):
        oi_distribution = metrics.get("oi_distribution") or []
        concentration = max((float(item.get("value") or 0) for item in oi_distribution), default=0) / total_oi if total_oi else None
        status = "HIGH_CONCENTRATION" if concentration is not None and concentration >= .35 else "CONCENTRATED" if concentration is not None and concentration >= .20 else "DISTRIBUTED" if concentration is not None else "INSUFFICIENT_DATA"
        metrics["positioning"] = {
            "status": status,
            "raw_metrics": {
                "total_oi": total_oi,
                "call_oi": row.call_open_interest,
                "put_oi": row.put_open_interest,
                "put_call_oi": row.put_call_oi_ratio,
                "oi_concentration": round(concentration, 6) if concentration is not None else None,
                "largest_call_strikes": metrics.get("major_call_oi_levels", []),
                "largest_put_strikes": metrics.get("major_put_oi_levels", []),
            },
            "quality": row.quality_score,
            "confidence": "medium" if concentration is not None else "low",
        }
    history_enrichment = history_enrichment or enrich_options_history(_stored_history(db, row.symbol))
    comparison = history_enrichment.get("historical_comparison") or {}
    current_comparison = comparison if history_enrichment.get("current") else metrics.get("historical_comparison") or {}
    state = _state_from_metrics(metrics, history_enrichment)
    activity_percentile = metrics.get("activity_percentile", current_comparison.get("activity_percentile"))
    activity_ready = current_comparison.get("status") == "READY"
    activity_status = state.get("activity", {}).get("status") or (metrics.get("activity_status") if activity_ready else "INSUFFICIENT_HISTORY")
    activity_score = activity_percentile if activity_ready and activity_percentile is not None else None
    sector = _sector_ancestor(db, row.sector_node_id)
    profile = db.get(StockProfile, row.symbol)
    security = db.get(Security, row.security_id) if row.security_id else None
    group = db.get(StockGroup, watchlist.user_group_id) if watchlist and watchlist.user_group_id else None
    return {
        "symbol": row.symbol,
        "name": (security.display_name if security else None) or (profile.company_name if profile else None) or row.symbol,
        "asset_type": row.asset_type,
        "sector": sector.name if sector else None,
        "sector_id": sector.node_key if sector else None,
        "industry": profile.official_industry if profile else None,
        "user_group": group.name if group else None,
        "status": row.status,
        "provider": row.provider,
        "underlying_price": row.underlying_price,
        "nearest_expiration": row.nearest_expiration,
        "next_expiration": row.next_expiration,
        "dte": row.days_to_expiration,
        "active_contracts": row.active_contracts,
        "atm_iv": row.atm_iv,
        "near_term_iv": row.near_term_iv,
        "next_term_iv": row.next_term_iv,
        "iv_change": row.iv_change if row.iv_change is not None else current_comparison.get("iv_change_1"),
        "call_volume": row.call_volume,
        "put_volume": row.put_volume,
        "total_volume": metrics.get("total_volume") if metrics.get("total_volume") is not None else ((row.call_volume + row.put_volume) if row.call_volume is not None and row.put_volume is not None else None),
        "total_oi": metrics.get("total_oi", metrics.get("total_open_interest")),
        "total_open_interest": metrics.get("total_open_interest", metrics.get("total_oi")),
        "volume_oi_ratio": metrics.get("volume_oi_ratio"),
        "put_call_volume_ratio": row.put_call_volume_ratio,
        "call_put_volume_ratio": (1 / row.put_call_volume_ratio) if row.put_call_volume_ratio else None,
        "call_oi": row.call_open_interest,
        "put_oi": row.put_open_interest,
        "total_oi": (row.call_open_interest + row.put_open_interest) if row.call_open_interest is not None and row.put_open_interest is not None else None,
        "put_call_oi_ratio": row.put_call_oi_ratio,
        "call_put_oi_ratio": (1 / row.put_call_oi_ratio) if row.put_call_oi_ratio else None,
        "downside_skew": row.downside_skew,
        "upside_skew": row.upside_skew,
        "skew_method": metrics.get("skew_method", "moneyness_proxy"),
        "activity_level": activity_status,
        "activity_status": activity_status,
        "activity_score": activity_score,
        "activity_components": metrics.get("activity_components", {}),
        "options_bias": metrics.get("options_bias", "MIXED"),
        "bias_status": metrics.get("bias_status", "INSUFFICIENT_DATA"),
        "bias_components": metrics.get("bias_components", {}),
        "activity_percentile": activity_percentile,
        "activity_zscore": metrics.get("activity_zscore", current_comparison.get("activity_zscore")),
        "activity_anomaly": metrics.get("activity_anomaly", current_comparison.get("anomaly_status", "INSUFFICIENT_HISTORY")),
        "activity_anomaly_direction": metrics.get("activity_anomaly_direction", current_comparison.get("anomaly_direction", "NONE")),
        "activity_trend": metrics.get("activity_trend", (current_comparison.get("trend") or {}).get("activity")),
        "activity_change_1": current_comparison.get("activity_change_1"),
        "activity_change_5": current_comparison.get("activity_change_5"),
        "activity_change_20": current_comparison.get("activity_change_20"),
        "iv_change_1": current_comparison.get("iv_change_1"),
        "iv_change_5": current_comparison.get("iv_change_5"),
        "iv_change_20": current_comparison.get("iv_change_20"),
        "skew_change_1": current_comparison.get("skew_change_1"),
        "skew_change_5": current_comparison.get("skew_change_5"),
        "skew_change_20": current_comparison.get("skew_change_20"),
        "oi_change_1": current_comparison.get("total_oi_change_1"),
        "oi_change_5": current_comparison.get("total_oi_change_5"),
        "oi_change_20": current_comparison.get("total_oi_change_20"),
        "term_structure_status": metrics.get("term_structure_status", "INSUFFICIENT_DATA"),
        "iv_quality": metrics.get("iv_quality", {"status": "INSUFFICIENT_DATA", "sample_size": 0, "warnings": []}),
        "skew_quality": metrics.get("skew_quality", {"status": "INSUFFICIENT_DATA", "sample_size": 0, "warnings": []}),
        "positioning": metrics.get("positioning", {}),
        "historical_comparison": current_comparison,
        "historical_regime": metrics.get("historical_regime", current_comparison),
        "options_state": state,
        "quality": _quality(row),
        "sample_size": row.sample_size,
        "updated_at": row.fetched_at,
        "expiration_structure": metrics.get("expiration_structure", []),
        "term_structure": _term(metrics),
        "oi_distribution": metrics.get("oi_distribution") or _distribution(metrics, "strike_oi_distribution"),
        "volume_distribution": metrics.get("volume_distribution") or _distribution(metrics, "strike_volume_distribution"),
        "major_call_oi_levels": metrics.get("major_call_oi_levels", []),
        "major_put_oi_levels": metrics.get("major_put_oi_levels", []),
    }


def _ranked(items: list[dict[str, Any]], field: str, *, reverse: bool = True, require_history: bool = False) -> list[dict[str, Any]]:
    eligible = []
    for item in items:
        value = item.get(field)
        if value is None:
            continue
        eligible.append(item)
    return sorted(eligible, key=lambda item: item[field], reverse=reverse)[:20]


def _enrich_items(db: Session, rows: list[OptionsSnapshot]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[OptionsSnapshot]] = {}
    for row in rows:
        by_symbol.setdefault(row.symbol, []).append(row)
    return [
        snapshot_payload(db, row, history_enrichment=enrich_options_history(by_symbol[row.symbol]))
        for row in rows
    ]


def overview_payload(db: Session, ranking: str = "activity") -> dict[str, Any]:
    rows = _latest_rows(db)
    by_symbol = {row.symbol: row for row in rows}
    histories = {symbol: enrich_options_history(_stored_history(db, symbol)) for symbol in by_symbol}
    watched = {row.ticker: row for row in db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()}
    market = [snapshot_payload(db, by_symbol[symbol], history_enrichment=histories[symbol]) for symbol in ("SPY", "QQQ", "IWM") if symbol in by_symbol]
    sectors = []
    for node in db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "sector", IndustryPulseNode.enabled.is_(True)).order_by(IndustryPulseNode.node_key)).all():
        mappings = list(db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.node_id == node.id, IndustryPulseInstrument.mapping_type == "etf_proxy", IndustryPulseInstrument.enabled.is_(True)).order_by(IndustryPulseInstrument.role, IndustryPulseInstrument.ticker)).all())
        primary_symbols = list(dict.fromkeys(item.ticker for item in mappings if item.role == "primary"))
        secondary_symbols = list(dict.fromkeys(item.ticker for item in mappings if item.role == "secondary"))
        primary = next((snapshot_payload(db, by_symbol[symbol], history_enrichment=histories[symbol]) for symbol in primary_symbols if symbol in by_symbol), None)
        secondary = [snapshot_payload(db, by_symbol[symbol], history_enrichment=histories[symbol]) for symbol in secondary_symbols if symbol in by_symbol]
        sectors.append({"sector": node.name, "sector_id": node.node_key, "name_zh": node.name_zh, "primary": primary, "secondary": secondary})
    watchlist = [snapshot_payload(db, row, watchlist=watched[row.symbol], history_enrichment=histories[row.symbol]) for row in rows if row.symbol in watched]
    field = RANK_FIELDS.get(ranking, RANK_FIELDS["activity"])
    ranked = _ranked(watchlist, field, require_history=ranking in {"most_active", "activity_surge", "largest_iv_increase", "largest_skew_change", "largest_oi_change"})
    sector_items = [item["primary"] for item in sectors if item["primary"]]
    sector_ranked = _ranked(sector_items, field, require_history=ranking in {"most_active", "activity_surge", "largest_iv_increase", "largest_skew_change", "largest_oi_change"})
    all_items = market + sector_items + watchlist
    rankings = {
        ranking: ranked[:20],
        "watchlist": ranked[:20],
        "sectors": sector_ranked,
        "most_active": _ranked(all_items, "activity_percentile", require_history=True),
        "activity_surge": _ranked(all_items, "activity_change_1", require_history=True),
        "highest_iv": _ranked(all_items, "atm_iv"),
        "largest_iv_increase": _ranked(all_items, "iv_change_1", require_history=True),
        "lowest_put_call": _ranked(all_items, "put_call_volume_ratio", reverse=False),
        "highest_put_call": _ranked(all_items, "put_call_volume_ratio"),
        "largest_skew": _ranked(all_items, "downside_skew"),
        "largest_skew_change": _ranked(all_items, "skew_change_1", require_history=True),
        "largest_oi_change": _ranked(all_items, "oi_change_1", require_history=True),
    }
    latest_run = db.scalar(select(OptionsSyncRun).order_by(OptionsSyncRun.started_at.desc()).limit(1))
    return {
        "as_of": max((row.fetched_at for row in rows), default=None),
        "status": "ready" if rows else "insufficient_history",
        "market": market,
        "sectors": sectors,
        "watchlist": watchlist,
        "rankings": rankings,
        "sync": sync_run_payload(latest_run) if latest_run else None,
        "limitations": ["Secondary ETF signals remain distinct and are never averaged into the primary sector proxy.", "Historical anomaly labels remain unavailable until enough daily snapshots accumulate."],
    }


def symbol_payload(db: Session, symbol: str, expiration: date | None = None) -> dict[str, Any] | None:
    symbol = symbol.strip().upper()
    row = db.scalar(select(OptionsSnapshot).where(OptionsSnapshot.symbol == symbol).order_by(OptionsSnapshot.trading_date.desc()).limit(1))
    if not row:
        return None
    history_rows = _stored_history(db, symbol)
    enriched = enrich_options_history(history_rows)
    summary = snapshot_payload(db, row, history_enrichment=enriched)
    chains = list(db.scalars(select(OptionsChainCache).where(OptionsChainCache.symbol == symbol, OptionsChainCache.expires_at > datetime.now(UTC)).order_by(OptionsChainCache.expiration)).all())
    selected = next((item for item in chains if item.expiration == expiration), chains[0] if chains else None)
    chain = ([{**item, "option_type": "call"} for item in selected.calls_json] + [{**item, "option_type": "put"} for item in selected.puts_json]) if selected else []
    return {
        **summary,
        "expirations": [item.expiration for item in chains],
        "selected_expiration": selected.expiration if selected else None,
        "chain": chain,
        "history": [history_point(item) for item in enriched["points"]],
    }


def history_point(row: OptionsSnapshot | Mapping[str, Any]) -> dict[str, Any]:
    value = row if isinstance(row, Mapping) else {key: getattr(row, key, None) for key in ("trading_date", "atm_iv", "near_term_iv", "next_term_iv", "iv_change", "call_volume", "put_volume", "put_call_volume_ratio", "put_call_oi_ratio", "downside_skew", "upside_skew", "activity_score", "quality_score", "status", "metrics_json")}
    metrics = value.get("metrics_json") or {}
    comparison = value.get("historical_comparison") or metrics.get("historical_comparison") or {}
    return {
        "date": value.get("trading_date") or value.get("date"),
        "x": value.get("trading_date") or value.get("date"),
        "y": value.get("atm_iv"),
        "atm_iv": value.get("atm_iv"),
        "near_term_iv": value.get("near_term_iv", metrics.get("near_term_iv")),
        "next_term_iv": value.get("next_term_iv", metrics.get("next_term_iv")),
        "iv_change": value.get("iv_change"),
        "call_volume": value.get("call_volume"),
        "put_volume": value.get("put_volume"),
        "put_call_volume_ratio": value.get("put_call_volume_ratio"),
        "put_call_oi_ratio": value.get("put_call_oi_ratio"),
        "downside_skew": value.get("downside_skew"),
        "upside_skew": value.get("upside_skew"),
        "activity_score": value.get("activity_score"),
        "quality_score": value.get("quality_score"),
        "status": value.get("status"),
        "total_volume": value.get("total_volume", metrics.get("total_volume")),
        "total_oi": value.get("total_oi", metrics.get("total_oi", metrics.get("total_open_interest"))),
        "volume_oi_ratio": value.get("volume_oi_ratio", metrics.get("volume_oi_ratio")),
        "activity_percentile": value.get("activity_percentile", metrics.get("activity_percentile", comparison.get("activity_percentile"))),
        "activity_zscore": value.get("activity_zscore", metrics.get("activity_zscore", comparison.get("activity_zscore"))),
        "activity_anomaly": value.get("activity_anomaly", metrics.get("activity_anomaly", comparison.get("anomaly_status", "INSUFFICIENT_HISTORY"))),
        "activity_anomaly_direction": value.get("activity_anomaly_direction", metrics.get("activity_anomaly_direction", comparison.get("anomaly_direction", "NONE"))),
        "historical_comparison": comparison,
        "historical_regime": value.get("historical_regime", metrics.get("historical_regime", comparison)),
        "metric_anomalies": comparison.get("metric_anomalies", {}),
        "changes": comparison.get("changes", {}),
        "averages": comparison.get("averages", {}),
    }


def history_payload(db: Session, symbol: str, days: int = 365) -> dict[str, Any]:
    start = date.today() - timedelta(days=days)
    rows = db.scalars(select(OptionsSnapshot).where(OptionsSnapshot.symbol == symbol.upper(), OptionsSnapshot.trading_date >= start).order_by(OptionsSnapshot.trading_date)).all()
    enriched = enrich_options_history(rows)
    return {"symbol": symbol.upper(), "history": [history_point(row) for row in enriched["points"]], "count": len(rows), "status": enriched["status"], "historical_comparison": enriched.get("historical_comparison")}


def semantic_options_context(db: Session, scope: str = "market", symbol: str | None = None, ranking: str = "activity") -> dict[str, Any]:
    """Bounded aggregate-only contract for AI and reports; never returns raw chains."""
    if symbol:
        value = symbol_payload(db, symbol)
        if value:
            value.pop("chain", None)
            value["history"] = value.get("history", [])[-30:]
        return value or {"symbol": symbol.upper(), "status": "NO_DATA"}
    overview = overview_payload(db, ranking)
    if scope == "market":
        return {"as_of": overview["as_of"], "market": overview["market"], "status": overview["status"]}
    if scope == "sector":
        return {"as_of": overview["as_of"], "sectors": overview["sectors"], "status": overview["status"]}
    return {"as_of": overview["as_of"], "watchlist": overview["watchlist"], "rankings": overview["rankings"], "status": overview["status"]}


def sync_run_payload(run: OptionsSyncRun) -> dict[str, Any]:
    return {key: getattr(run, key) for key in ("id", "started_at", "finished_at", "status", "trigger_type", "symbols_requested", "symbols_success", "symbols_failed", "contracts_received", "contracts_filtered", "low_quality_symbols", "duration_ms")}


def prune_chain_cache(db: Session) -> int:
    result = db.execute(delete(OptionsChainCache).where(OptionsChainCache.expires_at <= datetime.now(UTC)))
    return int(result.rowcount or 0)


__all__ = ["RANK_FIELDS", "enrich_options_history", "history_payload", "overview_payload", "semantic_options_context", "snapshot_payload", "symbol_payload", "prune_chain_cache"]
