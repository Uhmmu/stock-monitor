from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit

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
    pooled = [
        item.strip()
        for item in settings.adanos_api_keys.replace("\n", ",").replace(";", ",").split(",")
        if item.strip()
    ]
    api_keys = list(dict.fromkeys(item for item in (pooled or [settings.adanos_api_key.strip()]) if item))
    if len(api_keys) > 2:
        logger.error("Adanos disabled: ADANOS_API_KEYS must contain at most two distinct keys")
        return []
    return api_keys


def _valid_proxy_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "socks5h" and bool(parsed.hostname and parsed.port)
    except ValueError:
        return False


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
    primary_client: httpx.AsyncClient,
    secondary_client: httpx.AsyncClient | None,
    source: SentimentSourceKey,
    symbol: str,
    days: int,
    *,
    base_url: str,
    primary_key: str,
    secondary_key: str | None,
) -> SentimentSourceInsight | None:
    url = f"{base_url.rstrip('/')}{SOURCE_CONFIG[source]['path']}"
    params = {"tickers": symbol, "days": days}
    try:
        response = await primary_client.get(url, params=params, headers={"X-API-Key": primary_key})
        if response.status_code == 429 and secondary_key and secondary_client:
            logger.warning("Adanos %s primary quota exhausted for %s; trying proxied secondary", source, symbol)
            response = await secondary_client.get(
                url, params=params, headers={"X-API-Key": secondary_key},
            )
        if response.status_code == 404:
            return None
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


async def get_stock_sentiment_insights(
    symbol: str,
    days: int = DEFAULT_LOOKBACK_DAYS,
    *,
    config: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    secondary_client: httpx.AsyncClient | None = None,
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

    owns_primary = client is None
    primary_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.adanos_request_timeout_seconds),
        follow_redirects=True,
        trust_env=False,
    )
    secondary_key = api_keys[1] if len(api_keys) == 2 else None
    proxy_url = getattr(settings, "adanos_proxy_url", "").strip()
    owns_secondary = False
    active_secondary = secondary_client
    if secondary_key and not _valid_proxy_url(proxy_url):
        logger.error("Adanos secondary disabled: ADANOS_PROXY_URL must be a valid socks5h URL")
        secondary_key = None
        active_secondary = None
    elif secondary_key and active_secondary is None:
        active_secondary = httpx.AsyncClient(
            proxy=proxy_url,
            timeout=httpx.Timeout(settings.adanos_request_timeout_seconds),
            follow_redirects=True,
            trust_env=False,
        )
        owns_secondary = True
    try:
        source_keys = list(SOURCE_CONFIG)
        sources = await asyncio.gather(*(
            _fetch_compare_source(
                primary_client,
                active_secondary,
                source,
                normalized_symbol,
                lookback_days,
                base_url=settings.adanos_api_base_url,
                primary_key=api_keys[0],
                secondary_key=secondary_key,
            )
            for source in source_keys
        ))
    finally:
        if owns_primary:
            await primary_client.aclose()
        if owns_secondary and active_secondary:
            await active_secondary.aclose()

    result = build_stock_sentiment_insights(
        normalized_symbol,
        sources,
        period_days=lookback_days,
    )
    if result is not None and use_cache:
        async with _cache_lock:
            _cache[cache_key] = (monotonic() + CACHE_TTL_SECONDS, result)
    return result
