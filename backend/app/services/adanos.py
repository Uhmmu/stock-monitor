from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal

import httpx

from app.config import Settings, get_settings


logger = logging.getLogger(__name__)

SentimentSourceKey = Literal["reddit", "x", "news", "polymarket"]
SentimentTrend = Literal["rising", "falling", "stable"]

DEFAULT_LOOKBACK_DAYS = 7
FETCH_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 300.0

SOURCE_CONFIG: dict[SentimentSourceKey, dict[str, str]] = {
    "reddit": {
        "label": "Reddit",
        "path": "/reddit/stocks/v1/compare",
        "metric_label": "Mentions",
        "metric_field": "mentions",
    },
    "x": {
        "label": "X.com",
        "path": "/x/stocks/v1/compare",
        "metric_label": "Mentions",
        "metric_field": "mentions",
    },
    "news": {
        "label": "News",
        "path": "/news/stocks/v1/compare",
        "metric_label": "Mentions",
        "metric_field": "mentions",
    },
    "polymarket": {
        "label": "Polymarket",
        "path": "/polymarket/stocks/v1/compare",
        "metric_label": "Trades",
        "metric_field": "trade_count",
    },
}


@dataclass(frozen=True)
class SentimentSourceInsight:
    source: SentimentSourceKey
    label: str
    company_name: str | None
    buzz_score: float
    bullish_pct: float | None
    trend: SentimentTrend | None
    metric_label: str
    metric_value: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "label": self.label,
            "company_name": self.company_name,
            "buzz_score": self.buzz_score,
            "bullish_pct": self.bullish_pct,
            "trend": self.trend,
            "metric_label": self.metric_label,
            "metric_value": self.metric_value,
        }


_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()
_key_cursor = 0
_key_lock = asyncio.Lock()
_KEY_FAILOVER_STATUSES = {401, 403, 429, 500, 502, 503, 504}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = float(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if math.isfinite(parsed) else None


def _round_to(value: float, digits: int = 1) -> float:
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor


def _round_integer(value: float) -> int:
    return math.floor(value + 0.5)


def _trend(value: Any) -> SentimentTrend | None:
    return value if value in {"rising", "falling", "stable"} else None


def configured_api_keys(settings: Settings) -> list[str]:
    raw_values = [
        item.strip()
        for item in settings.adanos_api_keys.replace("\n", ",").replace(";", ",").split(",")
    ]
    raw_values.append(settings.adanos_api_key.strip())
    return list(dict.fromkeys(item for item in raw_values if item))


async def _source_key_orders(api_keys: list[str], count: int) -> list[list[str]]:
    global _key_cursor
    async with _key_lock:
        start = _key_cursor % len(api_keys)
        _key_cursor = (_key_cursor + 1) % len(api_keys)
    return [
        [api_keys[(start + source_index + offset) % len(api_keys)] for offset in range(len(api_keys))]
        for source_index in range(count)
    ]


def source_alignment(bullish_values: list[float]) -> str:
    if not bullish_values:
        return "No sentiment mix"
    if len(bullish_values) == 1:
        return "Single-source view"
    spread = max(bullish_values) - min(bullish_values)
    average = sum(bullish_values) / len(bullish_values)
    if spread <= 12 and average >= 60:
        return "Bullish alignment"
    if spread <= 12 and average <= 40:
        return "Bearish alignment"
    if spread <= 12:
        return "Tight alignment"
    if spread >= 25:
        return "Wide divergence"
    return "Mixed"


def normalize_source_insight(
    source: SentimentSourceKey,
    row: dict[str, Any] | None,
) -> SentimentSourceInsight | None:
    if not isinstance(row, dict):
        return None
    config = SOURCE_CONFIG[source]
    buzz_score = _number(row.get("buzz_score"))
    metric_value = _number(row.get(config["metric_field"]))
    if buzz_score is None or metric_value is None:
        return None
    bullish_pct = _number(row.get("bullish_pct"))
    company_name = row.get("company_name")
    return SentimentSourceInsight(
        source=source,
        label=config["label"],
        company_name=company_name if isinstance(company_name, str) else None,
        buzz_score=_round_to(buzz_score),
        bullish_pct=bullish_pct,
        trend=_trend(row.get("trend")),
        metric_label=config["metric_label"],
        metric_value=_round_integer(metric_value),
    )


def build_stock_sentiment_insights(
    symbol: str,
    sources: list[SentimentSourceInsight | None],
    *,
    period_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any] | None:
    available = [source for source in sources if source is not None]
    if not available:
        return None
    buzz_values = [source.buzz_score for source in available]
    bullish_values = [source.bullish_pct for source in available if source.bullish_pct is not None]
    company_name = next((source.company_name for source in available if source.company_name), None)
    return {
        "symbol": symbol.upper(),
        "company_name": company_name,
        "period_days": period_days,
        "average_buzz": _round_to(sum(buzz_values) / len(buzz_values)),
        "bullish_average": _round_to(sum(bullish_values) / len(bullish_values)) if bullish_values else None,
        "source_alignment": source_alignment(bullish_values),
        "available_sources": len(available),
        "sources": [source.as_dict() for source in available],
    }


async def _fetch_compare_source(
    client: httpx.AsyncClient,
    source: SentimentSourceKey,
    symbol: str,
    days: int,
    *,
    base_url: str,
    api_keys: list[str],
) -> SentimentSourceInsight | None:
    for position, api_key in enumerate(api_keys):
        try:
            response = await client.get(
                f"{base_url.rstrip('/')}{SOURCE_CONFIG[source]['path']}",
                params={"tickers": symbol, "days": days},
                headers={"X-API-Key": api_key},
            )
            if response.status_code == 404:
                return None
            if response.status_code in _KEY_FAILOVER_STATUSES and position + 1 < len(api_keys):
                logger.warning(
                    "Adanos %s compare returned %s for %s; trying alternate key",
                    source,
                    response.status_code,
                    symbol,
                )
                continue
            response.raise_for_status()
            payload = response.json()
            stocks = payload.get("stocks") if isinstance(payload, dict) else None
            row = next(
                (
                    item for item in stocks or []
                    if isinstance(item, dict) and str(item.get("ticker") or "").upper() == symbol
                ),
                None,
            )
            return normalize_source_insight(source, row)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Adanos %s compare request failed for %s: %s", source, symbol, type(exc).__name__)
            return None
    return None


async def get_stock_sentiment_insights(
    symbol: str,
    days: int = DEFAULT_LOOKBACK_DAYS,
    *,
    config: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    settings = config or get_settings()
    api_keys = configured_api_keys(settings)
    normalized_symbol = (symbol or "").strip().upper()
    if not api_keys or not normalized_symbol:
        return None
    lookback_days = max(1, min(int(days), 30))
    cache_key = (normalized_symbol, lookback_days)
    now = monotonic()
    if use_cache:
        async with _cache_lock:
            cached = _cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]
            if cached:
                _cache.pop(cache_key, None)

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.adanos_request_timeout_seconds),
        follow_redirects=True,
        trust_env=False,
    )
    try:
        source_keys = list(SOURCE_CONFIG)
        key_orders = await _source_key_orders(api_keys, len(source_keys))
        sources = await asyncio.gather(*(
            _fetch_compare_source(
                active_client,
                source,
                normalized_symbol,
                lookback_days,
                base_url=settings.adanos_api_base_url,
                api_keys=key_orders[index],
            )
            for index, source in enumerate(source_keys)
        ))
    finally:
        if owns_client:
            await active_client.aclose()

    result = build_stock_sentiment_insights(
        normalized_symbol,
        sources,
        period_days=lookback_days,
    )
    if result is not None and use_cache:
        async with _cache_lock:
            _cache[cache_key] = (monotonic() + CACHE_TTL_SECONDS, result)
    return result
