import asyncio
import json
from datetime import UTC, datetime, timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import get_settings
from app.services.news import NewsDTO

_REQUEST_TIMEOUT = 30


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
                image_url=row.get("image") or None,
                published_at=_parse_time(row.get("datetime")),
                raw_payload=row,
            )
        )
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


def fetch_recommendations(ticker: str) -> list[dict]:
    """分析师买/持/卖评级分布（按期倒序）。"""
    payload = _run(_call_tool("finnhub_stock_estimates",
        {"operation": "get_recommendations", "symbol": ticker}))
    return payload if isinstance(payload, list) else []
