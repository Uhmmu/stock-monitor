"""Database boundary for normalized intraday bars and monitor events."""

from __future__ import annotations

import hashlib
import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IntradayBar as IntradayBarRow, MarketMonitorEvent
from app.services.realtime_market.contracts import IntradayBar


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def persist_intraday_bar(
    db: Session, bar: IntradayBar, *, is_backfill: bool = False, raw_payload: dict | None = None,
) -> tuple[IntradayBarRow, bool]:
    timestamp = _utc(bar.timestamp).replace(second=0, microsecond=0)
    existing = db.scalar(select(IntradayBarRow).where(
        IntradayBarRow.symbol == bar.symbol,
        IntradayBarRow.timestamp == timestamp,
        IntradayBarRow.interval == bar.interval,
        IntradayBarRow.provider == bar.provider,
        IntradayBarRow.feed == (bar.feed or "unknown"),
    ).limit(1))
    if existing is not None:
        return existing, False
    row = IntradayBarRow(
        symbol=bar.symbol,
        timestamp=timestamp,
        interval=bar.interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume) if bar.volume is not None else None,
        vwap=bar.vwap,
        trade_count=bar.trade_count,
        provider=bar.provider,
        feed=bar.feed or "unknown",
        market_session=bar.market_session,
        is_backfill=is_backfill,
        raw_payload=raw_payload,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        duplicate = db.scalar(select(IntradayBarRow).where(
            IntradayBarRow.symbol == bar.symbol,
            IntradayBarRow.timestamp == timestamp,
            IntradayBarRow.interval == bar.interval,
            IntradayBarRow.provider == bar.provider,
            IntradayBarRow.feed == (bar.feed or "unknown"),
        ).limit(1))
        if duplicate is not None:
            return duplicate, False
        raise
    return row, True


def intraday_bars(
    db: Session,
    symbol: str,
    *,
    interval: str = "1m",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 1000,
    all_sources: bool = False,
) -> list[IntradayBarRow]:
    if interval not in {"1m", "5m", "15m"}:
        raise ValueError("interval must be 1m, 5m, or 15m")
    conditions = [IntradayBarRow.symbol == symbol.strip().upper(), IntradayBarRow.interval == interval]
    if start is not None:
        conditions.append(IntradayBarRow.timestamp >= _utc(start))
    if end is not None:
        conditions.append(IntradayBarRow.timestamp <= _utc(end))
    rows = db.scalars(select(IntradayBarRow).where(*conditions).order_by(
        IntradayBarRow.timestamp.desc(), IntradayBarRow.provider,
    ).limit(max(1, min(limit if all_sources else limit * 4, 5000)))).all()
    chronological = list(reversed(rows))
    if all_sources:
        return chronological
    # Multiple providers may backfill the same minute. Public consumers get
    # one deterministic authority per timestamp; provenance remains on each
    # stored row and can be requested internally with all_sources=True.
    configured = [value.strip().lower() for value in get_settings().realtime_provider_order.split(",") if value.strip()]
    rank = {name: index for index, name in enumerate(configured)}
    selected: dict[datetime, IntradayBarRow] = {}
    def priority(row: IntradayBarRow):
        provider = row.provider.lower()
        base = provider.removesuffix("_aggregate").removesuffix("_ticks")
        aggregate_penalty = 100 if provider != base or provider == "aggregated" else 0
        return rank.get(base, 1000) + aggregate_penalty
    for row in chronological:
        key = _utc(row.timestamp)
        if key not in selected or priority(row) < priority(selected[key]):
            selected[key] = row
    return [selected[key] for key in sorted(selected)][-max(1, min(limit, 5000)):]


def bar_out(row: IntradayBarRow) -> dict[str, Any]:
    def number(value: Any) -> float | None:
        return float(value) if isinstance(value, (Decimal, int, float)) else None
    return {
        "id": row.id, "symbol": row.symbol, "timestamp": row.timestamp,
        "interval": row.interval, "open": number(row.open), "high": number(row.high),
        "low": number(row.low), "close": number(row.close), "volume": row.volume,
        "vwap": number(row.vwap), "trade_count": row.trade_count,
        "provider": row.provider, "feed": row.feed,
        "market_session": row.market_session, "is_backfill": row.is_backfill,
    }


def aggregate_from_one_minute(
    db: Session, symbol: str, interval: str, start: datetime, end: datetime,
) -> list[IntradayBar]:
    if interval not in {"5m", "15m"}:
        raise ValueError("aggregate interval must be 5m or 15m")
    minutes = int(interval[:-1])
    source = intraday_bars(db, symbol, interval="1m", start=start, end=end, limit=5000)
    buckets: dict[datetime, list[IntradayBarRow]] = {}
    for row in source:
        stamp = _utc(row.timestamp)
        bucket = stamp.replace(minute=(stamp.minute // minutes) * minutes, second=0, microsecond=0)
        buckets.setdefault(bucket, []).append(row)
    output: list[IntradayBar] = []
    for timestamp, rows in sorted(buckets.items()):
        rows.sort(key=lambda row: _utc(row.timestamp))
        volume_values = [row.volume for row in rows if row.volume is not None]
        total_volume = sum(volume_values) if volume_values else None
        weighted = sum(float(row.vwap) * row.volume for row in rows if row.vwap is not None and row.volume) if total_volume else None
        output.append(IntradayBar(
            symbol=symbol, timestamp=timestamp, interval=interval,
            open=float(rows[0].open), high=max(float(row.high) for row in rows),
            low=min(float(row.low) for row in rows), close=float(rows[-1].close),
            volume=total_volume, vwap=(weighted / total_volume if weighted is not None and total_volume else None),
            trade_count=sum(row.trade_count for row in rows if row.trade_count is not None) or None,
            provider="aggregated", feed="1m", market_session=rows[-1].market_session,
            is_partial=len(rows) < minutes,
        ))
    return output


def _event_key(symbol: str, event_type: str, timestamp: datetime) -> str:
    cooldown = max(60, get_settings().realtime_event_cooldown_seconds)
    bucket = int(_utc(timestamp).timestamp()) // cooldown
    return hashlib.sha256(f"{symbol}:{event_type}:{bucket}".encode()).hexdigest()[:64]


def persist_monitor_event(
    db: Session,
    *,
    symbol: str,
    event_type: str,
    timestamp: datetime,
    severity: str = "info",
    value: float | None = None,
    threshold: float | None = None,
    provider: str | None = None,
    feed: str | None = None,
    market_session: str = "unknown",
    metadata: dict[str, Any] | None = None,
) -> tuple[MarketMonitorEvent, bool]:
    value_symbol = symbol.strip().upper()
    key = _event_key(value_symbol, event_type, timestamp)
    existing = db.scalar(select(MarketMonitorEvent).where(MarketMonitorEvent.event_key == key).limit(1))
    if existing is not None:
        return existing, False
    row = MarketMonitorEvent(
        event_key=key, symbol=value_symbol, event_type=event_type,
        severity=severity, value=value, threshold=threshold, timestamp=_utc(timestamp),
        provider=provider, feed=feed, market_session=market_session,
        metadata_json=metadata or {},
    )
    try:
        with db.begin_nested():
            db.add(row); db.flush()
    except IntegrityError:
        duplicate = db.scalar(select(MarketMonitorEvent).where(MarketMonitorEvent.event_key == key).limit(1))
        if duplicate is not None:
            return duplicate, False
        raise
    return row, True


def evaluate_bar_events(db: Session, row: IntradayBarRow) -> list[MarketMonitorEvent]:
    """Generate only events supported by persisted evidence; missing baselines stay absent."""
    previous = db.scalar(select(IntradayBarRow).where(
        IntradayBarRow.symbol == row.symbol,
        IntradayBarRow.interval == row.interval,
        IntradayBarRow.timestamp < row.timestamp,
    ).order_by(IntradayBarRow.timestamp.desc()).limit(1))
    if previous is None:
        return []
    market_zone = ZoneInfo(get_settings().market_timezone)
    local_day = _utc(row.timestamp).astimezone(market_zone).date()
    day_start = datetime.combine(local_day, datetime.min.time(), tzinfo=market_zone).astimezone(UTC)
    prior_day_high = db.scalar(select(func.max(IntradayBarRow.high)).where(
        IntradayBarRow.symbol == row.symbol,
        IntradayBarRow.interval == row.interval,
        IntradayBarRow.timestamp >= day_start,
        IntradayBarRow.timestamp < row.timestamp,
    ))
    prior_day_low = db.scalar(select(func.min(IntradayBarRow.low)).where(
        IntradayBarRow.symbol == row.symbol,
        IntradayBarRow.interval == row.interval,
        IntradayBarRow.timestamp >= day_start,
        IntradayBarRow.timestamp < row.timestamp,
    ))
    candidates: list[tuple[str, str, float, float, dict[str, Any]]] = []
    close, old_close = float(row.close), float(previous.close)
    if prior_day_high is not None and old_close <= float(prior_day_high) < close:
        candidates.append(("day_high_breakout", "notice", close, float(prior_day_high), {}))
    if prior_day_low is not None and old_close >= float(prior_day_low) > close:
        candidates.append(("day_low_breakdown", "notice", close, float(prior_day_low), {}))
    move_pct = (close - old_close) / old_close * 100 if old_close else 0
    if abs(move_pct) >= 1.0:
        candidates.append(("rapid_move", "warning", move_pct, 1.0, {"window": row.interval}))
    if row.vwap is not None and previous.vwap is not None:
        current_vwap, prior_vwap = float(row.vwap), float(previous.vwap)
        if (old_close - prior_vwap) * (close - current_vwap) < 0:
            candidates.append(("price_crosses_vwap", "info", close, current_vwap, {"direction": "above" if close > current_vwap else "below"}))
    history = list(db.scalars(select(IntradayBarRow).where(
        IntradayBarRow.symbol == row.symbol,
        IntradayBarRow.interval == row.interval,
        IntradayBarRow.timestamp <= row.timestamp,
    ).order_by(IntradayBarRow.timestamp.desc()).limit(80)).all())
    history.reverse()
    closes = [float(item.close) for item in history]
    if len(history) >= 2:
        day_open = float(history[0].open)
        day_move = (close - day_open) / day_open * 100 if day_open else 0
        if abs(day_move) >= 3.0:
            candidates.append(("percentage_move", "notice", day_move, 3.0, {"basis": "session_open"}))
    if len(closes) >= 21:
        previous_ma = statistics.fmean(closes[-21:-1])
        current_ma = statistics.fmean(closes[-20:])
        if (closes[-2] - previous_ma) * (closes[-1] - current_ma) < 0:
            candidates.append(("price_crosses_ma20", "info", close, current_ma, {"direction": "above" if close > current_ma else "below"}))
        old_window, new_window = closes[-21:-1], closes[-20:]
        old_mid, new_mid = statistics.fmean(old_window), statistics.fmean(new_window)
        old_std, new_std = statistics.pstdev(old_window), statistics.pstdev(new_window)
        old_upper, old_lower = old_mid + 2 * old_std, old_mid - 2 * old_std
        new_upper, new_lower = new_mid + 2 * new_std, new_mid - 2 * new_std
        if closes[-2] <= old_upper < closes[-1]:
            candidates.append(("bollinger_upper_breakout", "notice", close, new_upper, {}))
        elif closes[-2] >= old_lower > closes[-1]:
            candidates.append(("bollinger_lower_breakdown", "notice", close, new_lower, {}))
    if len(closes) >= 16:
        previous_rsi = _rsi(closes[:-1], 14)
        current_rsi = _rsi(closes, 14)
        for threshold in (30.0, 70.0):
            if previous_rsi is not None and current_rsi is not None and (previous_rsi - threshold) * (current_rsi - threshold) < 0:
                candidates.append(("rsi_cross", "info", current_rsi, threshold, {"direction": "above" if current_rsi > threshold else "below"}))
    if len(closes) >= 36:
        macd_values = _macd_series(closes)
        if len(macd_values) >= 10:
            signal_values = _ema_series(macd_values, 9)
            if len(signal_values) >= 2:
                previous_macd, current_macd = macd_values[-2], macd_values[-1]
                previous_signal, current_signal = signal_values[-2], signal_values[-1]
                if (previous_macd - previous_signal) * (current_macd - current_signal) < 0:
                    candidates.append(("macd_crossover", "info", current_macd, current_signal, {"direction": "bullish" if current_macd > current_signal else "bearish"}))
    for window in (5, 15):
        volumes = [item.volume for item in history if item.volume is not None]
        # Require at least three preceding, non-overlapping windows. This is a
        # real same-session baseline, not a fabricated historical RVOL.
        if len(volumes) < window * 4:
            continue
        current_volume = sum(volumes[-window:])
        previous_windows = [
            sum(volumes[index:index + window])
            for index in range(max(0, len(volumes) - window * 4), len(volumes) - window, window)
        ]
        baseline = statistics.fmean(previous_windows) if previous_windows else 0
        if baseline > 0 and current_volume / baseline >= 1.8:
            candidates.append((f"{window}m_volume_spike", "notice", current_volume / baseline, 1.8, {"basis": "prior_same_session_windows", "baseline_volume": baseline}))
    output: list[MarketMonitorEvent] = []
    for event_type, severity, value, threshold, metadata in candidates:
        event, created = persist_monitor_event(
            db, symbol=row.symbol, event_type=event_type, timestamp=row.timestamp,
            severity=severity, value=value, threshold=threshold, provider=row.provider,
            feed=row.feed, market_session=row.market_session, metadata=metadata,
        )
        if created:
            output.append(event)
    return output


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1 - alpha) * output[-1])
    return output


def _macd_series(values: list[float]) -> list[float]:
    fast, slow = _ema_series(values, 12), _ema_series(values, 26)
    return [left - right for left, right in zip(fast, slow)]


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    changes = [right - left for left, right in zip(values[-period - 1:-1], values[-period:])]
    gains = sum(max(value, 0) for value in changes) / period
    losses = sum(max(-value, 0) for value in changes) / period
    if losses == 0:
        return 100.0
    ratio = gains / losses
    return 100 - 100 / (1 + ratio)


def monitor_events(
    db: Session, *, symbols: Iterable[str] | None = None, since: datetime | None = None, limit: int = 200,
) -> list[MarketMonitorEvent]:
    conditions = []
    values = {value.strip().upper() for value in symbols or [] if value.strip()}
    if values:
        conditions.append(MarketMonitorEvent.symbol.in_(values))
    if since is not None:
        conditions.append(MarketMonitorEvent.timestamp >= _utc(since))
    return list(db.scalars(select(MarketMonitorEvent).where(*conditions).order_by(
        MarketMonitorEvent.timestamp.desc(), MarketMonitorEvent.id.desc(),
    ).limit(max(1, min(limit, 1000)))).all())


def event_out(row: MarketMonitorEvent) -> dict[str, Any]:
    return {
        "id": row.id, "symbol": row.symbol, "event_type": row.event_type,
        "severity": row.severity, "value": row.value, "threshold": row.threshold,
        "timestamp": row.timestamp, "provider": row.provider, "feed": row.feed,
        "market_session": row.market_session, "metadata": row.metadata_json or {},
    }


def intraday_summary(db: Session, symbol: str, *, now: datetime | None = None) -> dict[str, Any]:
    current = _utc(now or datetime.now(UTC))
    start = current - timedelta(days=1)
    rows = intraday_bars(db, symbol, interval="1m", start=start, end=current, limit=2000)
    if not rows:
        return {"symbol": symbol.strip().upper(), "available": False, "reason": "data_unavailable"}
    volumes = [row.volume for row in rows if row.volume is not None]
    total_volume = sum(volumes) if volumes else None
    weighted = sum(float(row.vwap) * row.volume for row in rows if row.vwap is not None and row.volume) if total_volume else None
    return {
        "symbol": rows[-1].symbol, "available": True, "from": rows[0].timestamp,
        "through": rows[-1].timestamp, "open": float(rows[0].open),
        "high": max(float(row.high) for row in rows), "low": min(float(row.low) for row in rows),
        "close": float(rows[-1].close), "volume": total_volume,
        "vwap": weighted / total_volume if weighted is not None and total_volume else None,
        "bar_count": len(rows), "market_session": rows[-1].market_session,
        "providers": sorted({row.provider for row in rows}),
    }
