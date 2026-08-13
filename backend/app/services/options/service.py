"""Persisted Options read model shared by API, AI tools, and reports."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

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


RANK_FIELDS = {
    "activity": "activity_score",
    "iv": "atm_iv",
    "iv_change": "iv_change",
    "put_call_volume": "put_call_volume_ratio",
    "put_call_oi": "put_call_oi_ratio",
    "downside_skew": "downside_skew",
    "call_activity": "call_volume",
    "put_activity": "put_volume",
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


def snapshot_payload(db: Session, row: OptionsSnapshot, *, watchlist: WatchlistItem | None = None) -> dict[str, Any]:
    metrics = row.metrics_json or {}
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
        "iv_change": row.iv_change,
        "call_volume": row.call_volume,
        "put_volume": row.put_volume,
        "total_volume": (row.call_volume + row.put_volume) if row.call_volume is not None and row.put_volume is not None else None,
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
        "activity_level": row.activity_status,
        "activity_score": row.activity_score,
        "activity_components": metrics.get("activity_components", {}),
        "options_bias": metrics.get("options_bias", "neutral"),
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


def overview_payload(db: Session, ranking: str = "activity") -> dict[str, Any]:
    rows = _latest_rows(db)
    by_symbol = {row.symbol: row for row in rows}
    watched = {row.ticker: row for row in db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()}
    market = [snapshot_payload(db, by_symbol[symbol]) for symbol in ("SPY", "QQQ", "IWM") if symbol in by_symbol]
    sectors = []
    for node in db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "sector", IndustryPulseNode.enabled.is_(True)).order_by(IndustryPulseNode.node_key)).all():
        mappings = list(db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.node_id == node.id, IndustryPulseInstrument.instrument_type == "etf", IndustryPulseInstrument.enabled.is_(True)).order_by(IndustryPulseInstrument.role, IndustryPulseInstrument.ticker)).all())
        primary_symbols = list(dict.fromkeys(item.ticker for item in mappings if item.role == "primary"))
        secondary_symbols = list(dict.fromkeys(item.ticker for item in mappings if item.role == "secondary"))
        primary = next((snapshot_payload(db, by_symbol[symbol]) for symbol in primary_symbols if symbol in by_symbol), None)
        secondary = [snapshot_payload(db, by_symbol[symbol]) for symbol in secondary_symbols if symbol in by_symbol]
        sectors.append({"sector": node.name, "sector_id": node.node_key, "name_zh": node.name_zh, "primary": primary, "secondary": secondary})
    watchlist = [snapshot_payload(db, row, watchlist=watched[row.symbol]) for row in rows if row.symbol in watched]
    field = RANK_FIELDS.get(ranking, RANK_FIELDS["activity"])
    ranked = sorted((item for item in watchlist if item.get(field) is not None), key=lambda item: item[field], reverse=True)
    sector_ranked = sorted((item["primary"] for item in sectors if item["primary"] and item["primary"].get(field) is not None), key=lambda item: item[field], reverse=True)
    latest_run = db.scalar(select(OptionsSyncRun).order_by(OptionsSyncRun.started_at.desc()).limit(1))
    return {
        "as_of": max((row.fetched_at for row in rows), default=None),
        "status": "ready" if rows else "insufficient_history",
        "market": market,
        "sectors": sectors,
        "watchlist": watchlist,
        "rankings": {ranking: ranked[:20], "watchlist": ranked[:20], "sectors": sector_ranked},
        "sync": sync_run_payload(latest_run) if latest_run else None,
        "limitations": ["Secondary ETF signals remain distinct and are never averaged into the primary sector proxy.", "Historical anomaly labels remain unavailable until enough daily snapshots accumulate."],
    }


def symbol_payload(db: Session, symbol: str, expiration: date | None = None) -> dict[str, Any] | None:
    symbol = symbol.strip().upper()
    row = db.scalar(select(OptionsSnapshot).where(OptionsSnapshot.symbol == symbol).order_by(OptionsSnapshot.trading_date.desc()).limit(1))
    if not row:
        return None
    summary = snapshot_payload(db, row)
    chains = list(db.scalars(select(OptionsChainCache).where(OptionsChainCache.symbol == symbol, OptionsChainCache.expires_at > datetime.now(UTC)).order_by(OptionsChainCache.expiration)).all())
    selected = next((item for item in chains if item.expiration == expiration), chains[0] if chains else None)
    history = list(db.scalars(select(OptionsSnapshot).where(OptionsSnapshot.symbol == symbol).order_by(OptionsSnapshot.trading_date.desc()).limit(365)).all())
    chain = ([{**item, "option_type": "call"} for item in selected.calls_json] + [{**item, "option_type": "put"} for item in selected.puts_json]) if selected else []
    return {
        **summary,
        "expirations": [item.expiration for item in chains],
        "selected_expiration": selected.expiration if selected else None,
        "chain": chain,
        "history": [history_point(item) for item in reversed(history)],
    }


def history_point(row: OptionsSnapshot) -> dict[str, Any]:
    return {"date": row.trading_date, "x": row.trading_date, "y": row.atm_iv, "atm_iv": row.atm_iv, "iv_change": row.iv_change, "put_call_volume_ratio": row.put_call_volume_ratio, "put_call_oi_ratio": row.put_call_oi_ratio, "downside_skew": row.downside_skew, "activity_score": row.activity_score, "quality_score": row.quality_score, "status": row.status}


def history_payload(db: Session, symbol: str, days: int = 365) -> dict[str, Any]:
    start = date.today() - timedelta(days=days)
    rows = db.scalars(select(OptionsSnapshot).where(OptionsSnapshot.symbol == symbol.upper(), OptionsSnapshot.trading_date >= start).order_by(OptionsSnapshot.trading_date)).all()
    return {"symbol": symbol.upper(), "history": [history_point(row) for row in rows], "count": len(rows)}


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


__all__ = ["RANK_FIELDS", "history_payload", "overview_payload", "semantic_options_context", "snapshot_payload", "symbol_payload", "prune_chain_cache"]
