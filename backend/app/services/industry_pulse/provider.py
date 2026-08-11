"""Bounded daily candle providers for Industry Pulse.

The live quote router has a different authority/provider order.  This module
keeps the pulse-specific yfinance-first policy isolated and returns explicit
quality/status metadata instead of inventing missing observations.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
import logging
import math
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class ProviderHistory:
    ticker: str
    bars: list[DailyBar] = field(default_factory=list)
    provider: str | None = None
    status: str = "unavailable"
    error_code: str | None = None
    volume_available: bool = False
    malformed_rows: int = 0
    total_rows: int = 0

    @property
    def data_quality(self) -> float:
        if not self.bars:
            return 0.0
        recency = min(1.0, len(self.bars) / 252.0)
        completeness = min(1.0, len(self.bars) / self.total_rows) if self.total_rows else 1.0
        return round(recency * completeness * (1.0 if self.volume_available else 0.75), 4)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _normalise_rows(rows: Any) -> list[DailyBar]:
    """Convert common yfinance/Finnhub candle shapes into validated bars."""
    if rows is None:
        return []
    if isinstance(rows, pd.DataFrame):
        iterator = rows.reset_index().to_dict("records")
    elif isinstance(rows, dict):
        iterator = rows.get("data", rows.get("bars", []))
        if isinstance(iterator, dict):
            iterator = [iterator]
    else:
        iterator = rows
    result: list[DailyBar] = []
    for row in iterator or []:
        if not isinstance(row, dict):
            continue
        lowered = {str(key).casefold().replace(" ", "_"): value for key, value in row.items()}
        day = _to_date(lowered.get("date") or lowered.get("datetime") or lowered.get("timestamp") or lowered.get("index"))
        open_ = _finite(lowered.get("open"))
        high = _finite(lowered.get("high"))
        low = _finite(lowered.get("low"))
        close = _finite(lowered.get("close"))
        if day is None or None in (open_, high, low, close) or min(open_, high, low, close) <= 0:
            continue
        if high < low or open_ < low or open_ > high or close < low or close > high:
            continue
        volume_value = lowered.get("volume")
        try:
            volume = int(float(volume_value)) if volume_value is not None and math.isfinite(float(volume_value)) else None
        except (TypeError, ValueError, OverflowError):
            volume = None
        result.append(DailyBar(day, open_, high, low, close, volume))
    result.sort(key=lambda item: item.date)
    deduped: dict[date, DailyBar] = {item.date: item for item in result}
    return [deduped[day] for day in sorted(deduped)]


def _frame_for_ticker(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame
    columns = frame.columns
    if isinstance(columns, pd.MultiIndex):
        # yfinance may use either (field, ticker) or (ticker, field).
        level0 = {str(value).upper() for value in columns.get_level_values(0)}
        level1 = {str(value).upper() for value in columns.get_level_values(1)}
        symbol = ticker.upper()
        if symbol in level0:
            return frame[symbol]
        if symbol in level1:
            return frame.xs(symbol, axis=1, level=1)
        return pd.DataFrame()
    return frame


def fetch_yfinance_batch(tickers: list[str] | tuple[str, ...], days: int = 500) -> dict[str, ProviderHistory]:
    symbols = tuple(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()))
    if not symbols:
        return {}
    result = {ticker: ProviderHistory(ticker=ticker) for ticker in symbols}
    try:
        kwargs = {
            "tickers": list(symbols),
            "period": "3mo" if days <= 60 else "2y",
            "interval": "1d",
            "group_by": "ticker",
            "auto_adjust": False,
            "progress": False,
            "threads": True,
            "timeout": get_settings().industry_pulse_provider_timeout_seconds,
        }
        try:
            frame = yf.download(**kwargs)
        except TypeError:
            kwargs.pop("threads", None)
            frame = yf.download(**kwargs)
        for ticker in symbols:
            raw = _frame_for_ticker(frame, ticker)
            total_rows = int(len(raw.index)) if isinstance(raw, pd.DataFrame) else 0
            rows = _normalise_rows(raw)
            if rows:
                malformed = max(0, total_rows - len(rows))
                volume_available = any(bar.volume is not None for bar in rows)
                result[ticker] = ProviderHistory(
                    ticker=ticker,
                    bars=rows[-days:],
                    provider="yfinance",
                    status="degraded" if malformed >= max(3, math.ceil(total_rows * .01)) or not volume_available else "success",
                    volume_available=volume_available,
                    malformed_rows=malformed,
                    total_rows=total_rows,
                )
    except Exception as exc:
        logger.info("Industry Pulse yfinance batch failed: %s", type(exc).__name__)
    return result


def fetch_finnhub_history(ticker: str, days: int = 500) -> ProviderHistory:
    """Fetch daily candles through the shared Finnhub candle helper."""
    try:
        from app.services.finnhub_mcp import fetch_historical_candles

        rows = fetch_historical_candles(ticker, days=days, timeout=get_settings().industry_pulse_provider_timeout_seconds)
        bars = _normalise_rows(rows)[-days:]
        if bars:
            return ProviderHistory(
                ticker=ticker,
                bars=bars,
                provider="finnhub",
                status="fallback",
                volume_available=any(bar.volume is not None for bar in bars),
                total_rows=len(bars),
            )
        return ProviderHistory(ticker=ticker, status="unavailable", error_code="empty_response")
    except Exception as exc:
        return ProviderHistory(ticker=ticker, status="unavailable", error_code=type(exc).__name__)


def fetch_histories(
    tickers: list[str] | tuple[str, ...],
    *,
    days: int | None = None,
    yfinance_fetcher: Callable[[list[str] | tuple[str, ...], int], dict[str, ProviderHistory]] | None = None,
    finnhub_fetcher: Callable[[str, int], ProviderHistory] | None = None,
) -> dict[str, ProviderHistory]:
    """Fetch all symbols with per-symbol fallback and no fake partial rows."""
    settings = get_settings()
    lookback = max(30, int(days or settings.industry_pulse_history_days))
    symbols = tuple(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()))
    fetch_primary = yfinance_fetcher or fetch_yfinance_batch
    batch_size = max(1, int(settings.industry_pulse_yfinance_batch_size))
    primary: dict[str, ProviderHistory] = {}
    for offset in range(0, len(symbols), batch_size):
        primary.update(fetch_primary(symbols[offset : offset + batch_size], lookback))
    fallback = finnhub_fetcher or fetch_finnhub_history
    fallback_symbols: list[str] = []
    for ticker in symbols:
        current = primary.get(ticker) or ProviderHistory(ticker=ticker)
        needs_fallback = not current.bars or len(current.bars) < min(252, lookback) or not current.volume_available
        if needs_fallback:
            fallback_symbols.append(ticker)
    with ThreadPoolExecutor(max_workers=min(4, len(fallback_symbols) or 1)) as pool:
        alternates = dict(zip(fallback_symbols, pool.map(lambda ticker: fallback(ticker, lookback), fallback_symbols)))
    for ticker, alternate in alternates.items():
        current = primary.get(ticker) or ProviderHistory(ticker=ticker)
        if alternate.bars:
            primary[ticker] = alternate
        elif current.bars:
            current.status = "degraded"
            current.error_code = "history_insufficient" if len(current.bars) < min(252, lookback) else "volume_missing"
    return {ticker: primary.get(ticker, ProviderHistory(ticker=ticker)) for ticker in symbols}


__all__ = ["DailyBar", "ProviderHistory", "fetch_finnhub_history", "fetch_histories", "fetch_yfinance_batch"]
