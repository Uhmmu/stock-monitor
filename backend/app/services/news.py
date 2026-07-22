import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "spm")

# 垃圾/低质来源黑名单统一保存规范域名；显示名由兼容别名映射。
SOURCE_BLACKLIST = {
    "zacks.com", "investorplace.com", "fool.com", "insidermonkey.com",
    "simplywall.st", "gurufocus.com", "tipranks.com", "stocktwits.com",
    "247wallst.com", "benzinga.com", "seekingalpha.com",
}
_SOURCE_DISPLAY_NAME_ALIASES = {
    "zacks": "zacks.com",
    "investorplace": "investorplace.com",
    "motley fool": "fool.com",
    "the motley fool": "fool.com",
    "insider monkey": "insidermonkey.com",
    "simply wall st": "simplywall.st",
    "simply wall st.": "simplywall.st",
    "gurufocus": "gurufocus.com",
    "tipranks": "tipranks.com",
    "stocktwits": "stocktwits.com",
    "247 wall st": "247wallst.com",
    "247 wall st.": "247wallst.com",
    "benzinga": "benzinga.com",
    "seeking alpha": "seekingalpha.com",
}
# 标题垃圾关键词（小写子串匹配）——只保留无争议的垃圾类型
TITLE_BLACKLIST = (
    "options trading", "technical analysis", "is a buy", "is it a buy",
    "should you buy", "best stocks", "stocks to buy", "moving average",
    "motley fool", "3 stocks", "5 stocks", "7 stocks",
)
_MAX_AGE = timedelta(hours=48)


def normalize_news_source(source: str | None) -> str:
    """Normalize a provider display name or URL-like source to a domain key."""
    value = (source or "").strip().lower().rstrip("/")
    if not value:
        return ""
    display_name = re.sub(r"\s+", " ", value)
    if display_name in _SOURCE_DISPLAY_NAME_ALIASES:
        return _SOURCE_DISPLAY_NAME_ALIASES[display_name]

    # Prefixing // lets urlsplit parse bare domains and subdomains as hosts.
    parsed = urlsplit(value if "://" in value else f"//{value}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    normalized = hostname or display_name
    return _SOURCE_DISPLAY_NAME_ALIASES.get(normalized, normalized)


def is_blacklisted_news_source(source: str | None) -> bool:
    normalized = normalize_news_source(source)
    if not normalized:
        return False
    return any(
        normalized == blocked_domain or normalized.endswith(f".{blocked_domain}")
        for blocked_domain in SOURCE_BLACKLIST
    )


def filter_news(dto: "NewsDTO", now: datetime | None = None) -> bool:
    """规则层：通过返回 True，丢弃返回 False。在 AI 打分前先跑，省 token。"""
    # Marketaux is quota-limited and batch-fetched, so it bypasses only this
    # source/title/age quality gate. Deduplication and relevance ranking remain.
    if dto.provider == "marketaux":
        return True
    now = now or datetime.now(UTC)
    if dto.published_at and now - dto.published_at > _MAX_AGE:
        return False
    if is_blacklisted_news_source(dto.source):
        return False
    title_lower = (dto.title or "").lower()
    if any(keyword in title_lower for keyword in TITLE_BLACKLIST):
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


_FINNHUB_CAP = 20  # finnhub 常返回上百条，取最新的即可，省 AI 打分 token


def collect_ticker_news(ticker: str, context: str = "latest company news", days: int = 7,
                        finnhub_symbol: str | None = None) -> list[NewsDTO]:
    from app.services.finnhub_mcp import fetch_company_news

    def _capped_finnhub() -> list[NewsDTO]:
        if not finnhub_symbol:
            return []
        rows = fetch_company_news(finnhub_symbol, days)
        rows.sort(key=lambda d: d.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return rows[:_FINNHUB_CAP]

    items: list[NewsDTO] = []
    for fetch in (_capped_finnhub, lambda: _yfinance_news_dtos(ticker), lambda: _tavily_dtos(ticker, context)):
        try:
            items.extend(fetch())
        except Exception:
            continue
    return deduplicate(items)


def _yfinance_news_dtos(ticker: str) -> list[NewsDTO]:
    import yfinance as yf
    from datetime import timezone

    raw = yf.Ticker(ticker).news or []
    items: list[NewsDTO] = []
    for item in raw:
        # yfinance 0.2.x 有两种结构：扁平或嵌套在 content 里
        nested = item.get("content") or {}
        title = item.get("title") or nested.get("title") or ""
        if not title:
            continue
        url = (item.get("link") or item.get("url")
               or nested.get("canonicalUrl", {}).get("url")
               or nested.get("clickThroughUrl", {}).get("url") or "")
        if not url:
            continue
        pub_ts = item.get("providerPublishTime") or nested.get("pubDate")
        published_at = None
        if pub_ts:
            try:
                published_at = (datetime.fromtimestamp(int(pub_ts), tz=UTC)
                                if isinstance(pub_ts, (int, float))
                                else datetime.fromisoformat(str(pub_ts)[:19]).replace(tzinfo=UTC))
            except Exception:
                pass
        source = (item.get("publisher") or
                  nested.get("provider", {}).get("displayName") or
                  nested.get("publisher", {}).get("name") or None)
        summary = (item.get("summary") or nested.get("summary") or
                   nested.get("description") or None)
        items.append(NewsDTO(
            provider="yfinance", ticker=ticker, title=title[:512], url=url,
            source=source, summary=summary, raw_content=summary,
            published_at=published_at,
        ))
    return items


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
    return dedupe_by_title(unique)


_TITLE_STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "is", "are",
    "as", "at", "by", "with", "from", "its", "amid", "after", "over", "into",
    "inc", "corp", "co", "ltd", "stock", "shares", "says", "will",
}
_TITLE_SIMILARITY_THRESHOLD = 0.6  # Jaccard 词集合相似度 ≥ 此值视为同一事件


def _title_tokens(title: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return frozenset(w for w in words if w not in _TITLE_STOPWORDS and len(w) > 1)


def _title_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe_by_title(items: list[NewsDTO]) -> list[NewsDTO]:
    """在精确指纹去重之后，再按标题词集合相似度合并跨来源的同一事件。
    保留先出现的一条（collect 顺序为 finnhub→yfinance→tavily，即优先高质量源）。"""
    kept: list[NewsDTO] = []
    kept_tokens: list[frozenset[str]] = []
    for item in items:
        tokens = _title_tokens(item.title)
        if any(_title_similarity(tokens, prev) >= _TITLE_SIMILARITY_THRESHOLD for prev in kept_tokens):
            continue
        kept.append(item)
        kept_tokens.append(tokens)
    return kept
