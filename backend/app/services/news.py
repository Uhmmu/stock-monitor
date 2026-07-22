"""Deterministic news normalisation, filtering, scoring and clustering.

This module deliberately runs before optional AI summaries: ingesting a feed must
never require an LLM call or allow a noisy provider to consume that budget.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MARKET_TICKER = "__MARKET__"  # storage sentinel; never exposed as a security/ticker.
_TRACKING_KEYS = {"fbclid", "gclid", "guccounter", "ref", "spm"}
_TRACKING_PREFIXES = ("utm_", "mc_")
MARKET_MAX_AGE = timedelta(hours=72)
COMPANY_MAX_AGE = timedelta(days=14)

# Only clearly non-editorial sources are blocked. The rest is a ranking penalty.
SOURCE_BLACKLIST = {"stocktwits.com"}
SOURCE_WEIGHTS = {
    "reuters.com": 1.0, "bloomberg.com": .95, "wsj.com": .95, "ft.com": .95,
    "apnews.com": .9, "cnbc.com": .8, "marketwatch.com": .75,
    "seekingalpha.com": .35, "fool.com": .25, "investorplace.com": .2,
    "zacks.com": .3, "benzinga.com": .45, "tipranks.com": .35,
}
_SOURCE_ALIASES = {
    "reuters": "reuters.com", "bloomberg": "bloomberg.com", "the wall street journal": "wsj.com",
    "wall street journal": "wsj.com", "financial times": "ft.com", "associated press": "apnews.com",
    "cnbc": "cnbc.com", "marketwatch": "marketwatch.com", "seeking alpha": "seekingalpha.com",
    "the motley fool": "fool.com", "motley fool": "fool.com", "investorplace": "investorplace.com",
    "zacks": "zacks.com", "benzinga": "benzinga.com", "tipranks": "tipranks.com",
    "stocktwits": "stocktwits.com",
}
HARD_NOISE = ("coupon", "giveaway", "buy now", "subscribe now")
LOW_QUALITY = ("stocks to buy", "best stocks", "millionaire maker", "could soar", "should you buy", "is this stock a buy", "price prediction")
MARKET_TOPICS = {
    "宏观经济": ("cpi", "ppi", "pce", "inflation", "gdp", "pmi", "retail sales", "unemployment", "jobless claims", "payroll", "recession"),
    "央行与利率": ("federal reserve", "fomc", "interest rate", "rate cut", "rate hike", "ecb", "bank of japan", "treasury yield", "bond yield"),
    "美股市场": ("s&p 500", "nasdaq", "dow jones", "russell 2000", "market selloff", "market rally", "vix", "stock futures", "bear market", "bull market"),
    "监管与政策": ("tariff", "sanction", "export control", "government shutdown", "debt ceiling", "antitrust", "regulation", "tax policy"),
    "地缘政治": ("war", "ceasefire", "invasion", "geopolit"),
    "能源与大宗商品": ("oil", "opec", "natural gas", "commodity", "gold price"),
    "科技与 AI": ("artificial intelligence", " ai ", "semiconductor", "chip"),
    "债券与信用": ("credit crisis", "liquidity", "default", "banking crisis"),
    "外汇": ("dollar", "currency", "forex", "yen", "euro"),
    "加密资产": ("bitcoin", "crypto", "ethereum"),
}
COMPANY_IMPORTANT = ("earnings", "revenue", "eps", "guidance", "acquire", "merger", "fda", "lawsuit", "investigation", "ceo", "cfo", "dividend", "buyback", "debt", "downgrade", "upgrade", "bankruptcy", "delist", "data breach", "contract", "recall")
_STOPWORDS = {"the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "is", "are", "as", "at", "by", "with", "from", "its", "after", "over", "into", "inc", "corp", "co", "ltd", "stock", "shares", "says", "will"}


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
    symbols: list[str] = field(default_factory=list)
    news_type: str = "article"
    raw_payload: dict = field(default_factory=dict)
    scope: str = "company"
    topic: str = "其他"
    importance_score: float = 0.0
    quality_score: float = 0.0
    cluster_key: str | None = None

    @property
    def fingerprint(self) -> str:
        return news_fingerprint(self.provider, self.external_id, self.url, self.title)


def normalize_news_source(source: str | None) -> str:
    value = (source or "").strip().lower().rstrip("/")
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    if value in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[value]
    parsed = urlsplit(value if "://" in value else f"//{value}")
    host = (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")
    return _SOURCE_ALIASES.get(host or value, host or value)


def is_blacklisted_news_source(source: str | None) -> bool:
    normalized = normalize_news_source(source)
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in SOURCE_BLACKLIST)


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in _TRACKING_KEYS and not key.lower().startswith(_TRACKING_PREFIXES)]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def normalize_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", title or "").lower().replace("’", "'").replace("–", "-")
    value = re.sub(r"^(?:breaking|update)\s*:\s*", "", value)
    value = re.sub(r"\s+-\s+(?:reuters|bloomberg|cnbc)$", "", value)
    return re.sub(r"[^\w\s.-]+|\s+", " ", value).strip()


def news_fingerprint(provider: str, external_id: str | None, url: str, title: str) -> str:
    basis = f"{provider}:{external_id}" if external_id else f"{normalize_url(url)}|{normalize_title(title)}"
    return hashlib.sha256(basis.encode()).hexdigest()[:64]


def _text(dto: NewsDTO) -> str:
    return f" {normalize_title(dto.title)} {(dto.summary or '').lower()} "


def classify_topic(dto: NewsDTO) -> str:
    text = _text(dto)
    for topic, keywords in MARKET_TOPICS.items():
        if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) for word in keywords):
            return topic
    return "公司与财报" if dto.scope == "company" else "其他"


def filter_news(dto: NewsDTO, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    title, url = (dto.title or "").strip(), (dto.url or "").strip()
    if not title or not url or not urlsplit(url).scheme:
        return False
    if dto.published_at:
        published = dto.published_at if dto.published_at.tzinfo else dto.published_at.replace(tzinfo=UTC)
        max_age = MARKET_MAX_AGE if dto.scope == "market" else COMPANY_MAX_AGE
        if now - published > max_age or published > now + timedelta(hours=2):
            return False
    text = _text(dto)
    if is_blacklisted_news_source(dto.source) or any(term in text for term in HARD_NOISE):
        return False
    return not (len(normalize_title(title)) < 12 and len((dto.summary or "").strip()) < 30)


def _tokens(title: str) -> frozenset[str]:
    value = normalize_title(title)
    # Small, explicit event-language canonicalisation improves common wire-copy
    # variants without broad stemming that would merge unrelated articles.
    value = re.sub(r"\bfederal reserve\b", "fed", value)
    value = re.sub(r"\binterest rates?\b", "rates", value)
    return frozenset(word for word in re.findall(r"[a-z0-9]+", value) if len(word) > 1 and word not in _STOPWORDS)


def title_similarity(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def score_news_item(dto: NewsDTO, now: datetime | None = None) -> NewsDTO:
    now = now or datetime.now(UTC)
    text = _text(dto)
    topic = classify_topic(dto)
    important_terms = COMPANY_IMPORTANT if dto.scope == "company" else tuple(term for terms in MARKET_TOPICS.values() for term in terms)
    importance = min(1.0, .18 + .16 * sum(1 for term in important_terms if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text)))
    if topic != "其他": importance = min(1.0, importance + .18)
    quality = SOURCE_WEIGHTS.get(normalize_news_source(dto.source), .55) * .55
    quality += .18 if dto.summary and len(dto.summary.strip()) >= 60 else 0
    quality += .12 if dto.published_at else 0
    quality -= .28 if any(term in text for term in LOW_QUALITY) else 0
    if dto.published_at:
        age = max(0, (now - dto.published_at).total_seconds() / 3600)
        half_life = 36 if topic in {"宏观经济", "央行与利率", "监管与政策", "公司与财报"} else 18
        freshness = math.exp(-age / half_life) * .35
    else: freshness = .05
    cluster = hashlib.sha256("|".join(sorted(_tokens(dto.title))).encode()).hexdigest()[:32]
    return replace(dto, topic=topic, importance_score=round(importance, 3), quality_score=round(max(0, min(1, quality + freshness)), 3), cluster_key=cluster)


def deduplicate(items: list[NewsDTO]) -> list[NewsDTO]:
    seen: set[tuple[str, str]] = set(); result: list[NewsDTO] = []
    for item in items:
        key = (item.provider, item.external_id) if item.external_id else ("url", normalize_url(item.url))
        if key not in seen:
            seen.add(key); result.append(item)
    return result


def cluster_news(items: list[NewsDTO]) -> tuple[list[NewsDTO], int]:
    """Select a representative inside a 48h event window, retaining no data deletion."""
    selected: list[NewsDTO] = []; clustered = 0
    for item in sorted(items, key=lambda row: row.importance_score + row.quality_score, reverse=True):
        match = next((old for old in selected if title_similarity(item.title, old.title) >= .5 and
                      (not item.published_at or not old.published_at or abs((item.published_at - old.published_at).total_seconds()) <= 48 * 3600)), None)
        if match: clustered += 1; continue
        selected.append(item)
    return selected, clustered


def diversify(items: list[NewsDTO], limit: int) -> list[NewsDTO]:
    topic_count: dict[str, int] = {}; source_count: dict[str, int] = {}; ticker_count: dict[str, int] = {}; result: list[NewsDTO] = []
    ranked = sorted(items, key=lambda row: row.importance_score + row.quality_score, reverse=True)
    for item in ranked:
        source = normalize_news_source(item.source)
        ticker = (item.symbols or [item.ticker])[0]
        if topic_count.get(item.topic, 0) >= 5 or source_count.get(source, 0) >= 4 or ticker_count.get(ticker, 0) >= 3:
            continue
        result.append(item); topic_count[item.topic] = topic_count.get(item.topic, 0) + 1; source_count[source] = source_count.get(source, 0) + 1; ticker_count[ticker] = ticker_count.get(ticker, 0) + 1
        if len(result) >= limit: break
    return result or ranked[:limit]


def prepare_news(items: list[NewsDTO], *, scope: str, now: datetime | None = None, limit: int = 20) -> tuple[list[NewsDTO], dict[str, int]]:
    scoped = [replace(item, scope=scope) for item in items]
    accepted = [score_news_item(item, now) for item in deduplicate(scoped) if filter_news(item, now)]
    clustered, clustered_count = cluster_news(accepted)
    return diversify(clustered, limit), {"fetched": len(items), "accepted": len(accepted), "filtered": len(scoped) - len(accepted), "clustered": clustered_count}


def collect_ticker_news(ticker: str, context: str = "latest company news", days: int = 7, finnhub_symbol: str | None = None) -> list[NewsDTO]:
    from app.services.finnhub_mcp import fetch_company_news
    items: list[NewsDTO] = []
    for fetch in (lambda: fetch_company_news(finnhub_symbol, days) if finnhub_symbol else [], lambda: _yfinance_news_dtos(ticker), lambda: _tavily_dtos(ticker, context)):
        try: items.extend(fetch())
        except Exception: continue
    return deduplicate(items)


def _yfinance_news_dtos(ticker: str) -> list[NewsDTO]:
    import yfinance as yf
    rows = yf.Ticker(ticker).news or []; result = []
    for item in rows:
        nested = item.get("content") or {}; title = item.get("title") or nested.get("title") or ""; url = item.get("link") or item.get("url") or nested.get("canonicalUrl", {}).get("url") or ""
        if not title or not url: continue
        value = item.get("providerPublishTime") or nested.get("pubDate"); published = None
        try: published = datetime.fromtimestamp(value, UTC) if isinstance(value, (int, float)) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError): pass
        result.append(NewsDTO(provider="yfinance", ticker=ticker, title=title[:512], url=url, source=item.get("publisher") or nested.get("provider", {}).get("displayName"), summary=item.get("summary") or nested.get("summary") or nested.get("description"), published_at=published))
    return result


def _tavily_dtos(ticker: str, context: str) -> list[NewsDTO]:
    from app.services.search import search_ticker_news
    return [NewsDTO(provider="tavily", ticker=ticker, title=row.title, url=row.url, source=row.source, summary=row.content, raw_content=row.content) for row in search_ticker_news(ticker, context)]
