from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PriceSnapshot, Security
from app.services.finnhub_mcp import fetch_quote as fetch_finnhub_quote
from app.services.market_calendar import market_data_collection_status, market_status
from app.services.market_data import LiveQuote, fetch_live_quote

SOURCE_TYPE = "price_snapshot"
PROVIDER_ROLE = "market_data_aggregator"
VALID_SESSIONS = {"pre_market", "regular", "after_hours", "closed", "unknown"}
VALID_TIMESTAMP_SOURCES = {"provider", "derived", "fetched_at_fallback"}


@dataclass(frozen=True)
class PriceSnapshotInput:
    symbol: str
    provider: str
    provider_symbol: str
    last_price: float
    fetched_at: datetime
    market_timestamp: datetime | None = None
    trading_date: date | None = None
    market_session: str = "unknown"
    timestamp_source: str = "provider"
    exchange: str | None = None
    currency: str | None = None
    open_price: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    previous_close: float | None = None
    day_volume: int | None = None
    average_volume_10d: float | None = None
    average_volume_20d: float | None = None
    relative_volume_basis: str | None = "full_day_average"
    is_delayed: bool | None = None
    delay_seconds: int | None = None
    raw_payload: dict[str, Any] | None = None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _positive(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _epoch(value: Any) -> datetime | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def validate_snapshot_input(value: PriceSnapshotInput) -> PriceSnapshotInput:
    if not value.symbol or not value.provider or not value.provider_symbol:
        raise ValueError("symbol, provider, and provider_symbol are required")
    if value.last_price <= 0:
        raise ValueError("last_price must be positive")
    if value.day_high is not None and value.day_high <= 0:
        raise ValueError("day_high must be positive when present")
    if value.day_low is not None and value.day_low <= 0:
        raise ValueError("day_low must be positive when present")
    if value.day_high is not None and value.day_low is not None and value.day_high < value.day_low:
        raise ValueError("day_high must not be below day_low")
    if value.market_session not in VALID_SESSIONS:
        raise ValueError("invalid market_session")
    if value.timestamp_source not in VALID_TIMESTAMP_SOURCES:
        raise ValueError("invalid timestamp_source")
    return value


def normalize_yfinance_quote(
    symbol: str,
    provider_symbol: str,
    quote: LiveQuote,
) -> PriceSnapshotInput:
    return validate_snapshot_input(PriceSnapshotInput(
        symbol=symbol.upper(),
        provider="yfinance",
        provider_symbol=provider_symbol.upper(),
        last_price=quote.price,
        fetched_at=_utc(quote.retrieved_at) or datetime.now(UTC),
        market_timestamp=_utc(quote.quote_time),
        trading_date=quote.trading_date,
        # Store the session of the provider quote itself. Retrieval may happen
        # after the extended session has ended and must not rewrite a valid
        # after-hours quote as merely "closed".
        market_session=(
            quote.quote_session
            if quote.quote_session in VALID_SESSIONS
            else "unknown"
        ),
        timestamp_source=quote.timestamp_source,
        exchange=quote.exchange,
        currency=quote.currency,
        open_price=quote.open,
        day_high=quote.day_high,
        day_low=quote.day_low,
        previous_close=quote.previous_close,
        day_volume=quote.volume,
        average_volume_10d=quote.average_volume_10d,
        average_volume_20d=quote.average_volume_20d,
        relative_volume_basis="full_day_average",
        is_delayed=quote.is_delayed,
        delay_seconds=quote.delay_seconds,
        raw_payload=quote.raw_payload,
    ))


def normalize_finnhub_quote(
    symbol: str,
    provider_symbol: str,
    payload: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
    exchange: str | None = None,
    currency: str | None = None,
) -> PriceSnapshotInput:
    fetched = _utc(fetched_at) or datetime.now(UTC)
    market_timestamp = _epoch(payload.get("t"))
    quote_status = market_data_collection_status(market_timestamp or fetched)
    market_timezone = ZoneInfo(get_settings().market_timezone)
    return validate_snapshot_input(PriceSnapshotInput(
        symbol=symbol.upper(),
        provider="finnhub",
        provider_symbol=provider_symbol.upper(),
        last_price=_positive(payload.get("c")) or 0,
        fetched_at=fetched,
        market_timestamp=market_timestamp,
        trading_date=(market_timestamp or fetched).astimezone(market_timezone).date(),
        market_session=quote_status["market_session"],
        timestamp_source="provider" if market_timestamp else "fetched_at_fallback",
        exchange=exchange,
        currency=currency,
        open_price=_positive(payload.get("o")),
        day_high=_positive(payload.get("h")),
        day_low=_positive(payload.get("l")),
        previous_close=_positive(payload.get("pc")),
        # Finnhub /quote does not supply volume. Missing values stay NULL.
        day_volume=None,
        average_volume_10d=None,
        average_volume_20d=None,
        relative_volume_basis="unknown",
        is_delayed=None,
        delay_seconds=None,
        raw_payload={
            key: payload.get(key)
            for key in ("c", "d", "dp", "h", "l", "o", "pc", "t")
            if payload.get(key) is not None
        },
    ))


def _provider_order() -> list[str]:
    configured = [
        value.strip().lower()
        for value in get_settings().price_snapshot_provider_order.split(",")
        if value.strip()
    ]
    supported = [value for value in configured if value in {"yfinance", "finnhub"}]
    return list(dict.fromkeys(supported)) or ["yfinance", "finnhub"]


def fetch_standardized_price_snapshot(
    symbol: str,
    *,
    yahoo_symbol: str | None,
    finnhub_symbol: str | None,
    provider_order: list[str] | None = None,
    yahoo_fetcher: Callable[[str], LiveQuote] = fetch_live_quote,
    finnhub_fetcher: Callable[[str], dict[str, Any]] = fetch_finnhub_quote,
    exchange: str | None = None,
    currency: str | None = None,
) -> PriceSnapshotInput:
    errors: list[str] = []
    for provider in provider_order or _provider_order():
        try:
            if provider == "yfinance" and yahoo_symbol:
                return normalize_yfinance_quote(symbol, yahoo_symbol, yahoo_fetcher(yahoo_symbol))
            if provider == "finnhub" and finnhub_symbol:
                return normalize_finnhub_quote(
                    symbol,
                    finnhub_symbol,
                    finnhub_fetcher(finnhub_symbol),
                    exchange=exchange,
                    currency=currency,
                )
        except Exception as exc:
            errors.append(f"{provider}:{type(exc).__name__}")
    detail = ", ".join(errors) if errors else "no configured provider symbol"
    raise RuntimeError(f"no valid price snapshot for {symbol}: {detail}")


def collect_price_snapshot(db: Session, symbol: str) -> PriceSnapshotInput:
    value = symbol.strip().upper()
    security = db.scalar(
        select(Security).where(or_(
            Security.yahoo_symbol == value,
            Security.display_symbol == value,
        )).limit(1)
    )
    return fetch_standardized_price_snapshot(
        value,
        yahoo_symbol=(security.yahoo_symbol if security else value),
        finnhub_symbol=(security.finnhub_symbol if security else None),
        exchange=(security.exchange_name if security else None),
        currency=(security.currency if security else None),
    )


def _snapshot_key(value: PriceSnapshotInput) -> str:
    timestamp = value.market_timestamp or value.fetched_at
    payload = {
        "symbol": value.symbol,
        "provider": value.provider,
        "provider_symbol": value.provider_symbol,
        "timestamp": _utc(timestamp).isoformat() if timestamp else None,
        "last_price": round(value.last_price, 10),
        "day_volume": value.day_volume,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def persist_price_snapshot(
    db: Session,
    value: PriceSnapshotInput,
) -> tuple[PriceSnapshot, bool]:
    value = validate_snapshot_input(value)
    key = _snapshot_key(value)
    existing = db.scalar(
        select(PriceSnapshot).where(PriceSnapshot.snapshot_key == key).limit(1)
    )
    if existing is None and value.market_timestamp is not None:
        existing = db.scalar(
            select(PriceSnapshot).where(
                PriceSnapshot.symbol == value.symbol,
                PriceSnapshot.provider == value.provider,
                PriceSnapshot.market_timestamp == _utc(value.market_timestamp),
            ).limit(1)
        )
    if existing:
        return existing, False

    change = (
        value.last_price - value.previous_close
        if value.previous_close is not None and value.previous_close > 0
        else None
    )
    change_percent = (
        change / value.previous_close * 100
        if change is not None and value.previous_close
        else None
    )
    relative_volume = (
        value.day_volume / value.average_volume_20d
        if value.day_volume is not None
        and value.average_volume_20d is not None
        and value.average_volume_20d > 0
        else None
    )
    now = datetime.now(UTC)
    row = PriceSnapshot(
        symbol=value.symbol,
        exchange=value.exchange,
        currency=value.currency,
        source_type=SOURCE_TYPE,
        provider=value.provider,
        provider_symbol=value.provider_symbol,
        provider_role=PROVIDER_ROLE,
        last_price=value.last_price,
        open_price=value.open_price,
        day_high=value.day_high,
        day_low=value.day_low,
        previous_close=value.previous_close,
        price_change=change,
        price_change_percent=change_percent,
        day_volume=value.day_volume,
        average_volume_10d=value.average_volume_10d,
        average_volume_20d=value.average_volume_20d,
        relative_volume_20d=relative_volume,
        relative_volume_basis=value.relative_volume_basis,
        market_timestamp=_utc(value.market_timestamp),
        trading_date=value.trading_date,
        market_session=value.market_session,
        timestamp_source=value.timestamp_source,
        fetched_at=_utc(value.fetched_at),
        persisted_at=now,
        is_delayed=value.is_delayed,
        delay_seconds=value.delay_seconds,
        raw_payload=value.raw_payload,
        snapshot_key=key,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        duplicate = db.scalar(
            select(PriceSnapshot).where(PriceSnapshot.snapshot_key == key).limit(1)
        )
        if duplicate is None and value.market_timestamp is not None:
            duplicate = db.scalar(
                select(PriceSnapshot).where(
                    PriceSnapshot.symbol == value.symbol,
                    PriceSnapshot.market_timestamp == _utc(value.market_timestamp),
                ).limit(1)
            )
        if duplicate:
            return duplicate, False
        raise
    return row, True


def get_latest_persisted_price_snapshot(
    db: Session,
    symbol: str,
) -> PriceSnapshot | None:
    value = symbol.strip().upper()
    return db.scalar(
        select(PriceSnapshot)
        .where(
            PriceSnapshot.symbol == value,
            PriceSnapshot.source_type == SOURCE_TYPE,
            PriceSnapshot.last_price > 0,
        )
        .order_by(
            PriceSnapshot.market_timestamp.desc().nullslast(),
            PriceSnapshot.fetched_at.desc().nullslast(),
            PriceSnapshot.persisted_at.desc().nullslast(),
        )
        .limit(1)
    )


def snapshot_freshness(
    row: PriceSnapshot,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc(now) or datetime.now(UTC)
    basis = _utc(row.market_timestamp) or _utc(row.fetched_at)
    age_seconds = max(0, int((current - basis).total_seconds())) if basis else None
    threshold = max(60, get_settings().price_snapshot_stale_seconds)
    return {
        "age_seconds": age_seconds,
        "is_stale": age_seconds is None or age_seconds > threshold,
        "stale_after_seconds": threshold,
        "age_basis": "market_timestamp" if row.market_timestamp else "fetched_at",
    }


def effective_market_session(
    row: PriceSnapshot,
    *,
    now: datetime | None = None,
) -> str:
    current = _utc(now) or datetime.now(UTC)
    market_date = current.astimezone(
        ZoneInfo(get_settings().market_timezone)
    ).date()
    if row.trading_date is not None and row.trading_date < market_date:
        return "closed"
    current_status = market_status(current)
    if not current_status["is_open"] and row.market_session == "regular":
        return "closed"
    return row.market_session if row.market_session in VALID_SESSIONS else "unknown"


def price_snapshot_out(
    row: PriceSnapshot,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    freshness = snapshot_freshness(row, now=now)
    return {
        "id": row.id,
        "symbol": row.symbol,
        "exchange": row.exchange,
        "currency": row.currency,
        "source_type": row.source_type,
        "provider": row.provider,
        "provider_symbol": row.provider_symbol,
        "provider_role": row.provider_role,
        "last_price": row.last_price,
        "open_price": row.open_price,
        "day_high": row.day_high,
        "day_low": row.day_low,
        "previous_close": row.previous_close,
        "price_change": row.price_change,
        "price_change_percent": row.price_change_percent,
        "day_volume": row.day_volume,
        "average_volume_10d": row.average_volume_10d,
        "average_volume_20d": row.average_volume_20d,
        "relative_volume_20d": row.relative_volume_20d,
        "relative_volume_basis": row.relative_volume_basis,
        "market_timestamp": row.market_timestamp,
        "trading_date": row.trading_date,
        "market_session": effective_market_session(row, now=now),
        "snapshot_market_session": row.market_session,
        "timestamp_source": row.timestamp_source,
        "fetched_at": row.fetched_at,
        "persisted_at": row.persisted_at,
        "is_delayed": row.is_delayed,
        "delay_seconds": row.delay_seconds,
        **freshness,
    }


def build_ai_price_snapshot_context(row: PriceSnapshot | None) -> dict[str, Any]:
    return {
        "latest_price_snapshot": price_snapshot_out(row) if row is not None else None
    }
