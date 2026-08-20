import asyncio
import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import UTC, datetime, timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import get_settings
from app.services.news import NewsDTO

_REQUEST_TIMEOUT = 30
logger = logging.getLogger(__name__)


async def _call_tool(name: str, arguments: dict) -> dict | list:
    settings = get_settings()
    async with streamablehttp_client(
        settings.finnhub_mcp_url,
        headers={"Host": "localhost:8125"},
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await asyncio.wait_for(session.call_tool(name, arguments), _REQUEST_TIMEOUT)
    if result.isError:
        raise RuntimeError(f"Finnhub MCP 调用失败：{name}")
    text = "".join(block.text for block in result.content if getattr(block, "type", None) == "text")
    return json.loads(text) if text else []


def _run(coro):
    return asyncio.run(coro)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (ValueError, TypeError, OSError):
        return None


def fetch_company_news(ticker: str, days: int = 7) -> list[NewsDTO]:
    to_date = datetime.now(UTC).date()
    from_date = to_date - timedelta(days=days)
    payload = _run(
        _call_tool(
            "finnhub_news_sentiment",
            {
                "operation": "get_company_news",
                "symbol": ticker,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
            },
        )
    )
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    items: list[NewsDTO] = []
    for row in rows:
        url = row.get("url")
        if not url:
            continue
        items.append(
            NewsDTO(
                provider="finnhub",
                ticker=ticker,
                external_id=str(row.get("id")) if row.get("id") is not None else None,
                title=row.get("headline") or "无标题",
                url=url,
                source=row.get("source"),
                summary=row.get("summary"),
                raw_content=row.get("summary"),
                image_url=None,
                published_at=_parse_time(row.get("datetime")),
                raw_payload=row,
            )
        )
    return items


def fetch_market_news() -> list[NewsDTO]:
    """Finnhub's general market news via the MCP sidecar, bounded and defensive."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        logger.info("Finnhub market news skipped: API key unavailable")
        return []
    try:
        payload = _run(_call_tool(
            "finnhub_news_sentiment",
            {"operation": "get_market_news", "category": "general"},
        ))
    except Exception as exc:
        logger.warning("Finnhub market news request failed: %s", type(exc).__name__)
        return []
    rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list): return []
    items: list[NewsDTO] = []
    for row in rows[:100]:
        if not isinstance(row, dict) or not row.get("headline") or not row.get("url"): continue
        symbols = [str(value).upper() for value in row.get("related", "").split(",") if value.strip()]
        items.append(NewsDTO(provider="finnhub", ticker="__MARKET__", external_id=str(row.get("id")) if row.get("id") is not None else None, title=str(row["headline"])[:512], url=str(row["url"]), source=row.get("source"), summary=row.get("summary"), published_at=_parse_time(row.get("datetime")), symbols=symbols, raw_payload=row, scope="market"))
    return items


def fetch_quarterly_financials(ticker: str) -> dict:
    payload = _run(
        _call_tool(
            "finnhub_stock_fundamentals",
            {
                "operation": "get_basic_financials",
                "symbol": ticker,
                "metric": "all",
                "include_series": True,
                "series_limit": 4,
            },
        )
    )
    return payload if isinstance(payload, dict) else {}


def fetch_reported_financials(ticker: str) -> list[dict]:
    """SEC 原始财报（含绝对值营收/净利润/现金流）。"""
    payload = _run(_call_tool("finnhub_stock_fundamentals",
        {"operation": "get_reported_financials", "symbol": ticker, "freq": "quarterly"}))
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        return data if isinstance(data, list) else []
    return payload if isinstance(payload, list) else []


def fetch_basic_metrics(ticker: str) -> dict:
    """基本面指标（P/E、利润率、增速、beta 等）。"""
    payload = _run(_call_tool("finnhub_stock_fundamentals",
        {"operation": "get_basic_financials", "symbol": ticker, "metric": "all"}))
    if isinstance(payload, dict):
        metric = payload.get("metric")
        return metric if isinstance(metric, dict) else {}
    return {}


def fetch_quote(ticker: str) -> dict:
    """Finnhub /quote fallback used by the unified persisted price pipeline."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise RuntimeError("Finnhub API key is unavailable")
    query = urlencode({"symbol": ticker.upper()})
    request = Request(
        f"https://finnhub.io/api/v1/quote?{query}",
        headers={
            "X-Finnhub-Token": settings.finnhub_api_key,
            "User-Agent": "stock-monitor/2.0",
        },
    )
    with urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Finnhub quote response was invalid")
    return payload


def fetch_historical_candles(ticker: str, days: int = 500, timeout: int | None = None) -> list[dict]:
    """Fetch bounded daily OHLCV candles for low-frequency fallback consumers.

    Finnhub's quote endpoint has no volume; the candle endpoint is therefore
    kept separate so callers can mark missing/partial history explicitly.
    """
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise RuntimeError("Finnhub API key is unavailable")
    end = datetime.now(UTC)
    start = end - timedelta(days=max(30, int(days * 1.8)))
    query = urlencode({
        "symbol": ticker.upper(),
        "resolution": "D",
        "from": int(start.timestamp()),
        "to": int(end.timestamp()),
    })
    request = Request(
        f"https://finnhub.io/api/v1/stock/candle?{query}",
        headers={"X-Finnhub-Token": settings.finnhub_api_key, "User-Agent": "stock-monitor/2.0"},
    )
    with urlopen(request, timeout=timeout or _REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("s") not in {"ok", "no_data"}:
        raise RuntimeError("Finnhub candle response was invalid")
    if payload.get("s") != "ok":
        return []
    timestamps = payload.get("t") or []
    opens = payload.get("o") or []
    highs = payload.get("h") or []
    lows = payload.get("l") or []
    closes = payload.get("c") or []
    volumes = payload.get("v") or []
    rows: list[dict] = []
    for index, timestamp in enumerate(timestamps):
        if index >= len(opens) or index >= len(highs) or index >= len(lows) or index >= len(closes):
            continue
        rows.append({
            "date": datetime.fromtimestamp(int(timestamp), tz=UTC).date().isoformat(),
            "open": opens[index], "high": highs[index], "low": lows[index], "close": closes[index],
            "volume": volumes[index] if index < len(volumes) else None,
        })
    return rows[-max(30, int(days)):]


def fetch_recommendations(ticker: str) -> list[dict]:
    """分析师买/持/卖评级分布（按期倒序）。"""
    payload = _run(_call_tool("finnhub_stock_estimates",
        {"operation": "get_recommendations", "symbol": ticker}))
    return payload if isinstance(payload, list) else []


def fetch_company_peers(ticker: str) -> list[str]:
    """Finnhub 官方 /stock/peers。同行关系由 Finnhub 提供，不自行猜测。"""
    settings = get_settings()
    if not settings.finnhub_api_key:
        return []
    query = urlencode({"symbol": ticker.upper(), "grouping": "subIndustry"})
    request = Request(
        f"https://finnhub.io/api/v1/stock/peers?{query}",
        headers={"X-Finnhub-Token": settings.finnhub_api_key, "User-Agent": "stock-monitor/2.0"},
    )
    with urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        return []
    seen: set[str] = set()
    peers: list[str] = []
    for item in payload:
        symbol = str(item or "").strip().upper()
        if not symbol or symbol == ticker.upper() or symbol in seen:
            continue
        seen.add(symbol)
        peers.append(symbol)
    return peers[:10]
