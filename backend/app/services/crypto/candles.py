"""Closed-candle repository for crypto instruments (crypto/quant program WP 2.3).

All writes go through validation (UTC alignment, OHLC sanity, volume subset
semantics); identical replays change zero logical rows; provider revisions
update in place with provenance. Reads are bounded and chronological.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MarketCandle
from app.services.crypto.providers.binance import Kline
from app.services.crypto.semantics import INTERVAL_MODULO_MS, candle_open_time_is_aligned

MAX_READ_LIMIT = 5000
DEFAULT_READ_LIMIT = 1000


class CandleValidationError(ValueError):
    """Malformed candle rejected before persistence; never a guessed fixup."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def kline_source_hash(kline: Kline) -> str:
    """Deterministic provenance hash of the normalized provider row."""
    payload = json.dumps(
        [
            kline.market, kline.symbol, kline.interval, kline.open_time_ms, kline.close_time_ms,
            str(kline.open), str(kline.high), str(kline.low), str(kline.close),
            str(kline.base_volume), str(kline.quote_volume), kline.trades,
            str(kline.taker_buy_base_volume), str(kline.taker_buy_quote_volume),
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class PersistSummary:
    requested: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: list = field(default_factory=list)


def validate_kline(kline: Kline) -> dict:
    """Validate one closed candle and return normalized column values."""
    if kline.interval not in INTERVAL_MODULO_MS:
        raise CandleValidationError(f"unsupported interval {kline.interval!r}")
    if not candle_open_time_is_aligned(kline.interval, kline.open_time_ms):
        raise CandleValidationError(f"open_time {kline.open_time_ms} is not a UTC {kline.interval} boundary")
    expected_close = kline.open_time_ms + INTERVAL_MODULO_MS[kline.interval] - 1
    if kline.close_time_ms != expected_close:
        raise CandleValidationError(
            f"close_time {kline.close_time_ms} does not match interval end {expected_close}"
        )
    if not kline.closed:
        raise CandleValidationError("forming candle refused: only closed candles are persisted")
    if kline.high < kline.low:
        raise CandleValidationError("high < low")
    if kline.high < kline.open or kline.high < kline.close:
        raise CandleValidationError("high is not the bar maximum")
    if kline.low > kline.open or kline.low > kline.close:
        raise CandleValidationError("low is not the bar minimum")
    if kline.base_volume < 0 or kline.quote_volume < 0:
        raise CandleValidationError("negative volume")
    if kline.taker_buy_base_volume is not None and kline.taker_buy_base_volume > kline.base_volume:
        raise CandleValidationError("taker buy base volume exceeds base volume")
    if kline.taker_buy_quote_volume is not None and kline.taker_buy_quote_volume > kline.quote_volume:
        raise CandleValidationError("taker buy quote volume exceeds quote volume")
    return {
        "interval": kline.interval,
        "open_time_ms": kline.open_time_ms,
        "close_time_ms": kline.close_time_ms,
        "open": kline.open,
        "high": kline.high,
        "low": kline.low,
        "close": kline.close,
        "base_volume": kline.base_volume,
        "quote_volume": kline.quote_volume,
        "taker_buy_base_volume": kline.taker_buy_base_volume,
        "taker_buy_quote_volume": kline.taker_buy_quote_volume,
        "trades": kline.trades,
        "source_hash": kline_source_hash(kline),
    }


def persist_klines(
    db: Session,
    *,
    instrument_id: int,
    provider: str,
    klines: list[Kline],
    feed: str = "rest",
    price_type: str = "trade",
) -> PersistSummary:
    """Idempotent batch upsert; rejected rows are reported, never silently dropped."""
    summary = PersistSummary(requested=len(klines))
    fetched_at = _utcnow()
    for kline in klines:
        try:
            values = validate_kline(kline)
        except CandleValidationError as exc:
            summary.rejected.append({"open_time_ms": kline.open_time_ms, "reason": str(exc)})
            continue
        existing = db.scalar(
            select(MarketCandle).where(
                MarketCandle.instrument_id == instrument_id,
                MarketCandle.interval == kline.interval,
                MarketCandle.open_time_ms == kline.open_time_ms,
                MarketCandle.provider == provider,
                MarketCandle.price_type == price_type,
            )
        )
        if existing is not None:
            if existing.source_hash == values["source_hash"]:
                summary.unchanged += 1
                continue
            # same identity, revised provider content: update in place
            for column, value in values.items():
                setattr(existing, column, value)
            existing.feed = feed
            existing.fetched_at = fetched_at
            existing.final = True
            summary.updated += 1
            continue
        db.add(
            MarketCandle(
                instrument_id=instrument_id,
                provider=provider,
                feed=feed,
                price_type=price_type,
                final=True,
                fetched_at=fetched_at,
                **values,
            )
        )
        summary.inserted += 1
    db.flush()
    return summary


def read_candles(
    db: Session,
    *,
    instrument_id: int,
    interval: str,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    limit: int = DEFAULT_READ_LIMIT,
    provider: str | None = None,
    price_type: str = "trade",
) -> list[MarketCandle]:
    """Bounded chronological (ascending) read; caller pages with start_time_ms."""
    limit = max(1, min(limit, MAX_READ_LIMIT))
    query = select(MarketCandle).where(
        MarketCandle.instrument_id == instrument_id,
        MarketCandle.interval == interval,
        MarketCandle.price_type == price_type,
    )
    if provider is not None:
        query = query.where(MarketCandle.provider == provider)
    if start_time_ms is not None:
        query = query.where(MarketCandle.open_time_ms >= start_time_ms)
    if end_time_ms is not None:
        query = query.where(MarketCandle.open_time_ms <= end_time_ms)
    return list(
        db.scalars(query.order_by(MarketCandle.open_time_ms.asc()).limit(limit))
    )


@dataclass
class CandleCoverage:
    earliest_open_ms: int | None
    latest_open_ms: int | None
    candle_count: int
    expected_count: int
    missing_count: int
    missing_ranges: list


def detect_gaps(open_times: list[int], interval: str) -> list[list[int]]:
    """Missing [start_ms, end_ms] windows between sorted unique open times."""
    modulo = INTERVAL_MODULO_MS[interval]
    gaps: list[list[int]] = []
    for previous, current in zip(open_times, open_times[1:]):
        if current - previous > modulo:
            gaps.append([previous + modulo, current - modulo])
    return gaps


def candle_coverage(db: Session, *, instrument_id: int, interval: str, provider: str | None = None, price_type: str = "trade") -> CandleCoverage:
    count = db.scalar(
        select(func.count(MarketCandle.id)).where(
            MarketCandle.instrument_id == instrument_id,
            MarketCandle.interval == interval,
            MarketCandle.price_type == price_type,
            *([MarketCandle.provider == provider] if provider else []),
        )
    )
    earliest = db.scalar(
        select(func.min(MarketCandle.open_time_ms)).where(
            MarketCandle.instrument_id == instrument_id,
            MarketCandle.interval == interval,
            MarketCandle.price_type == price_type,
            *([MarketCandle.provider == provider] if provider else []),
        )
    )
    latest = db.scalar(
        select(func.max(MarketCandle.open_time_ms)).where(
            MarketCandle.instrument_id == instrument_id,
            MarketCandle.interval == interval,
            MarketCandle.price_type == price_type,
            *([MarketCandle.provider == provider] if provider else []),
        )
    )
    if count == 0 or earliest is None or latest is None:
        return CandleCoverage(None, None, 0, 0, 0, [])
    modulo = INTERVAL_MODULO_MS[interval]
    expected = (latest - earliest) // modulo + 1
    missing_count = max(0, expected - count)
    open_times = [
        row[0]
        for row in db.execute(
            select(MarketCandle.open_time_ms).where(
                MarketCandle.instrument_id == instrument_id,
                MarketCandle.interval == interval,
                MarketCandle.price_type == price_type,
                *([MarketCandle.provider == provider] if provider else []),
            ).order_by(MarketCandle.open_time_ms.asc())
        )
    ]
    return CandleCoverage(
        earliest_open_ms=earliest,
        latest_open_ms=latest,
        candle_count=count,
        expected_count=expected,
        missing_count=missing_count,
        missing_ranges=detect_gaps(open_times, interval),
    )


def latest_closed_candle(
    db: Session, *, instrument_id: int, interval: str, provider: str | None = None, price_type: str = "trade"
) -> MarketCandle | None:
    query = select(MarketCandle).where(
        MarketCandle.instrument_id == instrument_id,
        MarketCandle.interval == interval,
        MarketCandle.price_type == price_type,
        MarketCandle.final.is_(True),
    )
    if provider is not None:
        query = query.where(MarketCandle.provider == provider)
    return db.scalar(query.order_by(MarketCandle.open_time_ms.desc()).limit(1))


def candle_to_dict(candle: MarketCandle) -> dict:
    """JSON-safe API shape; decimals as strings, no information loss."""
    return {
        "instrument_id": candle.instrument_id,
        "interval": candle.interval,
        "open_time_ms": candle.open_time_ms,
        "close_time_ms": candle.close_time_ms,
        "price_type": candle.price_type,
        "provider": candle.provider,
        "feed": candle.feed,
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "base_volume": str(candle.base_volume),
        "quote_volume": str(candle.quote_volume),
        "taker_buy_base_volume": str(candle.taker_buy_base_volume) if candle.taker_buy_base_volume is not None else None,
        "taker_buy_quote_volume": str(candle.taker_buy_quote_volume) if candle.taker_buy_quote_volume is not None else None,
        "trades": candle.trades,
        "final": candle.final,
        "fetched_at": candle.fetched_at.isoformat() if candle.fetched_at else None,
        "source_hash": candle.source_hash,
    }
