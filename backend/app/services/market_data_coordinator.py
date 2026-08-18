"""Global, deduplicated daily market-data scheduling and checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import random
import time
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    IndustryPulseFocusSignal,
    IndustryPulseInstrument,
    IndustryPulseNode,
    IndustryPulseSnapshot,
    MarketDataSyncState,
    PortfolioPosition,
    Security,
    WatchlistItem,
)
from app.services.industry_pulse.definitions import ETF_SYMBOLS
from app.services.industry_pulse.provider import ProviderHistory, fetch_histories
from app.services.market_calendar import expected_latest_market_session
from app.services.market_data_repository import history_counts, latest_dates, upsert_history


_RANK = {"P0": 0, "P1": 1, "P2": 2}
_REFRESH = {"P0": timedelta(hours=12), "P1": timedelta(days=3), "P2": timedelta(days=7)}
_HOT_MOODS = {"strong", "leadership", "heating", "panic", "risk-off", "overheated"}


@dataclass
class MarketDataTarget:
    symbol: str
    priority: str = "P2"
    security_id: int | None = None
    reasons: set[str] = field(default_factory=set)


def collect_market_data_universe(db: Session) -> list[MarketDataTarget]:
    targets: dict[str, MarketDataTarget] = {}

    def add(symbol: str | None, priority: str, reason: str, security_id: int | None = None) -> None:
        value = (symbol or "").strip().upper()
        if not value:
            return
        row = targets.setdefault(value, MarketDataTarget(value, security_id=security_id))
        if _RANK[priority] < _RANK[row.priority]:
            row.priority = priority
        row.security_id = row.security_id or security_id
        row.reasons.add(reason)

    securities = {row.id: row for row in db.scalars(select(Security)).all()}
    mappings = db.execute(
        select(IndustryPulseInstrument, IndustryPulseNode.taxonomy)
        .join(IndustryPulseNode, IndustryPulseNode.id == IndustryPulseInstrument.node_id)
        .where(IndustryPulseInstrument.enabled.is_(True), IndustryPulseInstrument.enabled_for_pulse.is_(True))
    ).all()
    latest_snapshot_day = db.scalar(select(func.max(IndustryPulseSnapshot.trading_date)))
    active_nodes: set[int] = set()
    hot_nodes: set[int] = set()
    if latest_snapshot_day:
        for snapshot in db.scalars(select(IndustryPulseSnapshot).where(IndustryPulseSnapshot.trading_date == latest_snapshot_day)).all():
            if snapshot.pulse is not None and float(snapshot.coverage_quality or 0) >= .6:
                active_nodes.add(snapshot.node_id)
            if snapshot.mood in _HOT_MOODS:
                hot_nodes.add(snapshot.node_id)
        hot_nodes.update(db.scalars(select(IndustryPulseFocusSignal.node_id).where(IndustryPulseFocusSignal.trading_date == latest_snapshot_day)).all())
    for mapping, taxonomy in mappings:
        security = securities.get(mapping.security_id)
        symbol = security.yahoo_symbol if security and security.yahoo_symbol else mapping.provider_symbol or mapping.ticker
        priority = "P0" if taxonomy == "ai" or mapping.node_id in hot_nodes else "P1" if mapping.node_id in active_nodes else "P2"
        add(symbol, priority, "ai_theme" if taxonomy == "ai" else "industry_seed", mapping.security_id)
        if mapping.node_id in hot_nodes:
            add(symbol, "P0", "focus_hot", mapping.security_id)
    for symbol in ETF_SYMBOLS:
        add(symbol, "P0" if symbol in {"SPY", "QQQ", "DIA"} else "P1", "benchmark" if symbol in {"SPY", "QQQ", "DIA"} else "etf_registry")
    add("^VIX", "P0", "volatility_benchmark")
    for row in db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all():
        security = securities.get(row.security_id)
        add(security.yahoo_symbol if security and security.yahoo_symbol else row.ticker, "P0", "watchlist", row.security_id)
    for row in db.scalars(select(PortfolioPosition).where(PortfolioPosition.total_quantity > 0)).all():
        security = securities.get(row.security_id)
        add(security.yahoo_symbol if security and security.yahoo_symbol else row.symbol, "P0", "portfolio", row.security_id)
    return sorted(targets.values(), key=lambda row: (_RANK[row.priority], row.symbol))


def sync_global_market_data(
    db: Session,
    *,
    full_backfill: bool = False,
    symbols: set[str] | None = None,
    now: datetime | None = None,
    fetcher: Callable[[list[str], int], dict[str, ProviderHistory]] | None = None,
) -> dict:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expected = expected_latest_market_session(current)
    targets = collect_market_data_universe(db)
    requested = {symbol.upper() for symbol in symbols} if symbols else None
    if requested is not None:
        by_symbol = {target.symbol: target for target in targets}
        targets = [by_symbol.get(symbol, MarketDataTarget(symbol, "P0", reasons={"requested"})) for symbol in sorted(requested)]
    states = {row.symbol: row for row in db.scalars(select(MarketDataSyncState).where(MarketDataSyncState.symbol.in_([target.symbol for target in targets]))).all()}
    local_latest = latest_dates(db, [target.symbol for target in targets])
    counts = history_counts(db, [target.symbol for target in targets], source="yahoo") if full_backfill else {}
    due: dict[int, list[tuple[MarketDataTarget, MarketDataSyncState]]] = {}
    skipped_fresh = skipped_priority = 0
    for target in targets:
        state = states.get(target.symbol)
        if state is None:
            state = MarketDataSyncState(symbol=target.symbol)
            db.add(state)
            states[target.symbol] = state
        metadata = dict(state.metadata_json or {})
        if "focus_hot" in target.reasons:
            metadata["promotion_until"] = (current + timedelta(days=5)).isoformat()
            metadata["cooldown_until"] = (current + timedelta(days=8)).isoformat()
        else:
            promotion_until = datetime.fromisoformat(metadata["promotion_until"]) if metadata.get("promotion_until") else None
            cooldown_until = datetime.fromisoformat(metadata["cooldown_until"]) if metadata.get("cooldown_until") else None
            if promotion_until and current < promotion_until:
                target.priority = "P0"
            elif cooldown_until and current < cooldown_until and target.priority == "P2":
                target.priority = "P1"
        state.security_id = target.security_id
        state.priority = target.priority
        state.latest_market_date = local_latest.get(target.symbol) or state.latest_market_date
        state.metadata_json = {**metadata, "reasons": sorted(target.reasons)}
        needs_backfill = full_backfill and counts.get(target.symbol, 0) < 400
        if not needs_backfill and expected and state.latest_market_date and state.latest_market_date >= expected:
            state.freshness_status = "FRESH"
            skipped_fresh += 1
            continue
        refresh_at = state.next_refresh_at
        if refresh_at and refresh_at.tzinfo is None:
            refresh_at = refresh_at.replace(tzinfo=UTC)
        if not needs_backfill and refresh_at and refresh_at > current:
            state.freshness_status = "STALE"
            skipped_priority += 1
            continue
        lookback = 500 if needs_backfill else 10 if state.latest_market_date else 60
        due.setdefault(lookback, []).append((target, state))
    db.flush()

    fetched = valid = failed = recovered = inserted = 0
    batch_size = min(60, max(40, int(get_settings().industry_pulse_yfinance_batch_size)))
    groups = [(days, rows[offset:offset + batch_size]) for days, rows in sorted(due.items(), reverse=True) for offset in range(0, len(rows), batch_size)]
    for group_index, (days, batch) in enumerate(groups):
        batch_symbols = [target.symbol for target, _state in batch]
        blocked = {state.symbol for _target, state in batch if (state.metadata_json or {}).get("finnhub_permission_denied")}
        try:
            histories = fetcher(batch_symbols, days) if fetcher else fetch_histories(batch_symbols, days=days, finnhub_blocked=blocked)
        except Exception as exc:
            histories = {symbol: ProviderHistory(symbol, error_code=type(exc).__name__) for symbol in batch_symbols}
        for target, state in batch:
            history = histories.get(target.symbol) or ProviderHistory(target.symbol, error_code="missing_result")
            state.last_fetch_at = current
            fetched += 1
            if history.bars and history.provider:
                inserted += upsert_history(db, target.symbol, history)
                latest = history.bars[-1].date
                state.latest_market_date = max(filter(None, (state.latest_market_date, latest)))
                state.last_success_at = current
                state.provider = history.provider
                state.failure_count = 0
                state.error_code = None
                state.freshness_status = "FRESH" if expected and state.latest_market_date >= expected else "STALE"
                state.next_refresh_at = current + _REFRESH[target.priority]
                valid += 1
                recovered += int(history.provider == "finnhub")
            else:
                state.failure_count += 1
                state.error_code = history.error_code or "TEMPORARY_DATA_FAILURE"
                state.freshness_status = "STALE" if state.latest_market_date else "TEMPORARY_DATA_FAILURE"
                state.next_refresh_at = current + timedelta(hours=min(24, 2 ** min(state.failure_count, 4)))
                if state.error_code == "PROVIDER_PERMISSION_DENIED":
                    state.metadata_json = {**(state.metadata_json or {}), "finnhub_permission_denied": True}
                failed += 1
        db.commit()  # each batch is a resume checkpoint
        if group_index + 1 < len(groups):
            time.sleep(random.uniform(.4, 1.2))
    return {
        "total_unique": len(targets),
        "expected_market_date": expected.isoformat() if expected else None,
        "fetched": fetched,
        "valid": valid,
        "finnhub_recovered": recovered,
        "failed": failed,
        "skipped_fresh": skipped_fresh,
        "skipped_priority": skipped_priority,
        "inserted_rows": inserted,
        "backfill": full_backfill,
    }
