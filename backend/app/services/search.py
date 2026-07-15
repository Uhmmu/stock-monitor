from dataclasses import dataclass

from tavily import TavilyClient

from app.config import get_settings


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str
    source: str | None = None


def search_ticker_news(ticker: str, context: str) -> list[SearchResult]:
    settings = get_settings()
    if not settings.tavily_api_key:
        raise RuntimeError("尚未配置 TAVILY_API_KEY")
    response = TavilyClient(api_key=settings.tavily_api_key).search(
        query=f"{ticker} stock {context} latest news SEC earnings analyst regulatory",
        topic="news",
        time_range="day",
        max_results=10,
    )
    return [
        SearchResult(
            title=item.get("title", "无标题"),
            url=item["url"],
            content=item.get("content", ""),
        )
        for item in response.get("results", [])
        if item.get("url")
    ]
