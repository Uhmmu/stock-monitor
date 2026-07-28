from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class SearchError(RuntimeError):
    code = "search_failed"
    retryable = False


class SearchConfigurationError(SearchError):
    code = "missing_api_key"


class SearchTransientError(SearchError):
    code = "search_temporarily_unavailable"
    retryable = True


@dataclass(frozen=True)
class SearchResult:
    queries: list[str]
    results: list[dict[str, Any]]
    raw_response: dict[str, Any]
    request_count: int = 1
    cost_usd: float = 0.005


def build_search_queries(context: dict) -> list[str]:
    """Search only for time-sensitive narrative evidence, never local fundamentals."""
    sectors = [
        str(item.get("name"))
        for item in context.get("portfolio_summary", {}).get("sector_weights", [])[:4]
        if isinstance(item, dict) and item.get("name")
    ]
    watchlist = [str(item) for item in context.get("current_watchlist", [])[:12]]
    universe = ", ".join(watchlist)
    sector_hint = ", ".join(sectors)
    return [
        "US listed companies recent corporate events guidance changes product launches regulatory decisions "
        "and investor attention in the last 30 days",
        "US stock market emerging industry trends demand inflections supply chain changes and analyst sentiment "
        "in the last 30 days",
        "US equities recent earnings narrative changes management commentary estimate revisions and upcoming "
        "catalysts; narrative developments only because quantitative fundamentals are provided locally",
        f"Recent company news and why-now developments for this research universe: {universe or 'US large and mid cap stocks'}",
        f"Recent macro and policy changes affecting US equity sectors {sector_hint or 'technology healthcare industrials financials'}",
    ]


def run_search(queries: list[str]) -> SearchResult:
    settings = get_settings()
    key = settings.perplexity_api_key.strip()
    if not key:
        raise SearchConfigurationError("尚未配置 Perplexity API Key")
    request = {
        "query": queries,
        "max_results": 20,
        "search_context_size": "high",
        "country": "US",
        "search_language_filter": ["en"],
    }
    try:
        response = httpx.post(
            settings.perplexity_search_url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=request,
            timeout=settings.perplexity_request_timeout_seconds,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise SearchTransientError("Perplexity Search 暂时不可用") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise SearchTransientError("Perplexity Search 暂时受限")
    if response.status_code >= 400:
        raise SearchError(f"Perplexity Search 请求失败（HTTP {response.status_code}）")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SearchError("Perplexity Search 返回了无效 JSON") from exc
    results = payload.get("results")
    if not isinstance(results, list):
        raise SearchError("Perplexity Search 响应不含 results")
    cleaned = [
        {
            "title": str(row.get("title") or ""),
            "url": str(row.get("url") or ""),
            "snippet": str(row.get("snippet") or "")[:3000],
            "date": row.get("date"),
            "last_updated": row.get("last_updated"),
        }
        for row in results
        if isinstance(row, dict) and row.get("url")
    ]
    return SearchResult(queries=queries, results=cleaned, raw_response=payload)
