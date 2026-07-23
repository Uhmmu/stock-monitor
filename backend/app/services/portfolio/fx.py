"""Small, honest FX conversion boundary for portfolio aggregation.

Portfolio rows retain their native trading currency. Only cross-position totals
are converted into the portfolio base currency, using Yahoo FX quotes cached in
the API process. Missing rates stay missing; callers must exclude them rather
than treating one unit of foreign currency as one base-currency unit.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import yfinance as yf


_CACHE_TTL_SECONDS = 30 * 60
_cache: dict[tuple[str, str], tuple[float, "FxQuote"]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class FxQuote:
    rate: float
    source: str
    fetched_at: datetime


def _valid_rate(value) -> float | None:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if math.isfinite(rate) and rate > 0 else None


def _fetch_yahoo_rate(source_currency: str, target_currency: str) -> FxQuote | None:
    direct_symbol = f"{source_currency}{target_currency}=X"
    inverse_symbol = f"{target_currency}{source_currency}=X"
    for symbol, inverse in ((direct_symbol, False), (inverse_symbol, True)):
        try:
            price = _valid_rate(yf.Ticker(symbol).fast_info.last_price)
        except Exception:
            price = None
        if price is None:
            continue
        rate = 1 / price if inverse else price
        return FxQuote(
            rate=rate,
            source=f"yahoo:{symbol}",
            fetched_at=datetime.now(UTC),
        )
    return None


def fx_rate(source_currency: str, target_currency: str) -> FxQuote | None:
    source = source_currency.strip().upper()
    target = target_currency.strip().upper()
    if source == target:
        return FxQuote(rate=1.0, source="identity", fetched_at=datetime.now(UTC))

    key = (source, target)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

    quote = _fetch_yahoo_rate(source, target)
    if quote is not None:
        with _cache_lock:
            _cache[key] = (now + _CACHE_TTL_SECONDS, quote)
    return quote


def fx_rate_map(base_currency: str, currencies: set[str]) -> dict[str, FxQuote]:
    base = base_currency.strip().upper()
    result: dict[str, FxQuote] = {}
    for currency in currencies:
        quote = fx_rate(currency, base)
        if quote is not None:
            result[currency] = quote
    return result


def clear_fx_cache() -> None:
    """Test/operations hook; does not touch any external cache."""
    with _cache_lock:
        _cache.clear()
