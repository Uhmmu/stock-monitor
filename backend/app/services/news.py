import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "spm")

# 垃圾/低质来源黑名单（小写匹配）
SOURCE_BLACKLIST = {
    "zacks", "investorplace", "motley fool", "the motley fool", "insider monkey",
    "simply wall st", "gurufocus", "tipranks", "stocktwits", "247wallst.com",
    "247 wall st.", "benzinga", "seeking alpha",
}
# 标题垃圾关键词（小写子串匹配）
TITLE_BLACKLIST = (
    "options trading", "technical analysis", "is a buy", "is it a buy",
    "should you buy", "best stocks", "stocks to buy", "moving average",
    "price target", "vs.", "3 stocks", "5 stocks", "7 stocks",
    "motley fool", "why is", "here's why", "here is why",
)
_MAX_AGE = timedelta(hours=24)
_MIN_SUMMARY_LEN = 30


def filter_news(dto: "NewsDTO", now: datetime | None = None) -> bool:
    """规则层：通过返回 True，丢弃返回 False。在 AI 打分前先跑，省 token。"""
    now = now or datetime.now(UTC)
    if dto.published_at and now - dto.published_at > _MAX_AGE:
        return False
    if dto.source and dto.source.strip().lower() in SOURCE_BLACKLIST:
        return False
    title_lower = (dto.title or "").lower()
    if any(keyword in title_lower for keyword in TITLE_BLACKLIST):
        return False
    body = dto.summary or dto.raw_content or ""
    if len(body.strip()) < _MIN_SUMMARY_LEN:
        return False
    return True


@dataclass(frozen=True)
class NewsDTO:
    provider: str
    ticker: str
    title: str
    url: str
    external_id: str | None = None
    source: str | None = None
    summary: str | None = None
    raw_content: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None
    raw_payload: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return news_fingerprint(self.provider, self.external_id, self.url, self.title)


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and not any(pair.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "&".join(sorted(kept)), ""))


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title or "").strip().lower()


def news_fingerprint(provider: str, external_id: str | None, url: str, title: str) -> str:
    if external_id:
        basis = f"{provider}:{external_id}"
    else:
        basis = f"{normalize_url(url)}|{_normalize_title(title)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]


def collect_ticker_news(ticker: str, context: str = "latest company news", days: int = 7) -> list[NewsDTO]:
    from app.services.finnhub_mcp import fetch_company_news

    items: list[NewsDTO] = []
    for fetch in (lambda: fetch_company_news(ticker, days), lambda: _tavily_dtos(ticker, context)):
        try:
            items.extend(fetch())
        except Exception:
            continue
    return deduplicate(items)


def _tavily_dtos(ticker: str, context: str) -> list[NewsDTO]:
    from app.services.search import search_ticker_news

    return [
        NewsDTO(
            provider="tavily",
            ticker=ticker,
            title=result.title,
            url=result.url,
            source=result.source,
            summary=result.content,
            raw_content=result.content,
        )
        for result in search_ticker_news(ticker, context)
    ]


def deduplicate(items: list[NewsDTO]) -> list[NewsDTO]:
    seen: set[str] = set()
    unique: list[NewsDTO] = []
    for item in items:
        key = item.fingerprint
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
