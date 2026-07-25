"""Normalized ownership/share-statistics adapters and cache access."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EquityShareStatistic, Security

SHARE_STATISTICS_TTL = timedelta(hours=24)
ANALYZER_VERSION = "v0.4"
SEC_TRANSACTION_LABELS = {
    "P": "公开市场买入",
    "S": "公开市场卖出",
    "A": "授予或奖励",
    "M": "期权行权",
    "F": "税款代扣",
    "G": "赠与",
    "D": "处置",
    "J": "其他交易",
}

_FIELDS = {
    "shares_outstanding": "sharesOutstanding",
    "float_shares": "floatShares",
    "implied_shares_outstanding": "impliedSharesOutstanding",
    "shares_short": "sharesShort",
    "shares_short_prior_month": "sharesShortPriorMonth",
    "short_percent_of_float": "shortPercentOfFloat",
    "short_percent_of_outstanding": "sharesPercentSharesOut",
    "short_ratio": "shortRatio",
    "held_percent_insiders": "heldPercentInsiders",
    "held_percent_institutions": "heldPercentInstitutions",
    "average_volume": "averageVolume",
    "average_volume_10d": "averageVolume10days",
}
_PERCENT_FIELDS = {
    "short_percent_of_float",
    "short_percent_of_outstanding",
    "held_percent_insiders",
    "held_percent_institutions",
}


def classify_sec_transaction_code(code: str | None) -> str:
    """SEC Form 4 transaction codes describe mechanics, not bullish direction."""
    return SEC_TRANSACTION_LABELS.get((code or "").strip().upper(), "其他交易")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def normalize_yahoo_share_statistics(symbol: str, info: dict[str, Any], *, fetched_at: datetime | None = None) -> dict:
    """Map Yahoo names to stable domain names; unsupported values remain null."""
    values: dict[str, float | None] = {}
    for field, source_field in _FIELDS.items():
        value = _number(info.get(source_field))
        if value is not None and field in _PERCENT_FIELDS:
            value = round(value * 100, 8)
        values[field] = value
    outstanding, float_shares = values["shares_outstanding"], values["float_shares"]
    free_float = round(float_shares / outstanding * 100, 8) if outstanding and float_shares is not None else None
    as_of = _date(info.get("dateShortInterest")) or _date(info.get("lastFiscalYearEnd"))
    raw_payload = {}
    for key in set(_FIELDS.values()) | {
        "symbol", "market", "exchange", "currency", "dateShortInterest", "lastFiscalYearEnd"
    }:
        raw = info.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            raw = _number(raw)
        if raw is not None:
            raw_payload[key] = raw
    return {
        "symbol": symbol.upper(),
        "market": info.get("market") or info.get("exchange"),
        "currency": info.get("currency"),
        **values,
        "free_float_percent": free_float,
        "as_of_date": as_of,
        "source": "yahoo",
        "source_url": f"https://finance.yahoo.com/quote/{symbol.upper()}/key-statistics/",
        "confidence": "medium",
        "is_estimated": False,
        "fetched_at": fetched_at or datetime.now(UTC),
        "raw_payload": raw_payload,
    }


def fetch_yahoo_share_statistics(symbol: str) -> dict:
    info = yf.Ticker(symbol).get_info() or {}
    normalized = normalize_yahoo_share_statistics(symbol, info)
    if not any(normalized.get(field) is not None for field in (
        "shares_outstanding", "float_shares", "shares_short",
        "held_percent_insiders", "held_percent_institutions",
    )):
        raise LookupError(f"{symbol} 没有可用的股本数据")
    return normalized


class ShareStatisticsProviderAdapter(Protocol):
    name: str

    def fetch(self, symbol: str) -> dict: ...


class YahooShareStatisticsAdapter:
    name = "yahoo"

    def fetch(self, symbol: str) -> dict:
        return fetch_yahoo_share_statistics(symbol)


SHARE_STATISTICS_PROVIDERS: tuple[ShareStatisticsProviderAdapter, ...] = (
    YahooShareStatisticsAdapter(),
)


def _security(db: Session, symbol: str) -> Security | None:
    value = symbol.upper()
    return db.scalar(select(Security).where(
        (Security.yahoo_symbol == value) | (Security.display_symbol == value)
    ).limit(1))


def refresh_share_statistics(db: Session, symbol: str) -> EquityShareStatistic:
    value = symbol.strip().upper()
    payload = None
    errors = []
    for provider in SHARE_STATISTICS_PROVIDERS:
        try:
            payload = provider.fetch(value)
            break
        except Exception as exc:
            errors.append(f"{provider.name}:{type(exc).__name__}")
    if payload is None:
        raise LookupError(";".join(errors) or f"{value} 没有可用的股本数据")
    row = db.scalar(select(EquityShareStatistic).where(EquityShareStatistic.symbol == value))
    if row is None:
        row = EquityShareStatistic(symbol=value)
        db.add(row)
    security = _security(db, value)
    row.security_id = security.id if security else None
    for field in (
        "market", "currency", "shares_outstanding", "float_shares", "free_float_percent",
        "implied_shares_outstanding", "shares_short", "shares_short_prior_month",
        "short_percent_of_float", "short_percent_of_outstanding", "short_ratio",
        "held_percent_insiders", "held_percent_institutions", "average_volume",
        "average_volume_10d", "as_of_date", "source", "source_url", "confidence",
        "is_estimated", "raw_payload", "fetched_at",
    ):
        setattr(row, field, payload[field])
    row.updated_at = datetime.now(UTC)
    db.flush()
    return row


def get_share_statistics(db: Session, symbol: str, *, refresh_if_stale: bool = True) -> tuple[EquityShareStatistic | None, bool, str | None]:
    """Return cache and whether it is stale; provider failure never deletes it."""
    value = symbol.strip().upper()
    row = db.scalar(select(EquityShareStatistic).where(EquityShareStatistic.symbol == value))
    now = datetime.now(UTC)
    fetched_at = row.fetched_at if row else None
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    stale = row is None or fetched_at is None or now - fetched_at > SHARE_STATISTICS_TTL
    warning = None
    if stale and refresh_if_stale:
        try:
            row = refresh_share_statistics(db, value)
            db.commit()
            stale = False
        except Exception:
            db.rollback()
            warning = "上游暂不可用，当前展示最近一次有效缓存。" if row else "当前数据源暂不可用。"
    return row, stale, warning


def serialize_share_statistics(row: EquityShareStatistic, *, stale: bool, warning: str | None) -> dict:
    return {
        "symbol": row.symbol,
        "market": row.market,
        "currency": row.currency,
        "shares_outstanding": row.shares_outstanding,
        "float_shares": row.float_shares,
        "free_float_percent": row.free_float_percent,
        "implied_shares_outstanding": row.implied_shares_outstanding,
        "shares_short": row.shares_short,
        "shares_short_prior_month": row.shares_short_prior_month,
        "short_percent_of_float": row.short_percent_of_float,
        "short_percent_of_outstanding": row.short_percent_of_outstanding,
        "short_ratio": row.short_ratio,
        "held_percent_insiders": row.held_percent_insiders,
        "held_percent_institutions": row.held_percent_institutions,
        "average_volume": row.average_volume,
        "average_volume_10d": row.average_volume_10d,
        "as_of_date": row.as_of_date,
        "source": row.source,
        "source_url": row.source_url,
        "fetched_at": row.fetched_at,
        "is_estimated": row.is_estimated,
        "confidence": row.confidence,
        "stale": stale,
        "warning": warning,
        "analyzer_version": ANALYZER_VERSION,
        "parameter_set_version": ANALYZER_VERSION,
    }


def ownership_capabilities(*, is_us_market: bool) -> dict[str, bool]:
    return {
        "share_statistics": True,
        "major_holders": False,
        "institutional_holders": False,
        "insider_transactions": is_us_market,
        "form_13f": is_us_market,
        "government_trades": False,
    }
