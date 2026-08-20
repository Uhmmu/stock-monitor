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
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MARKET_TICKER = "__MARKET__"  # storage sentinel; never exposed as a security/ticker.
# Yahoo has no market-wide news endpoint; index tickers are the closest proxy
# and pull the same wire stories (Reuters/CNBC/AP) that feed the general feeds.
MARKET_INDEX_TICKERS = ("^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX")
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
# Promotional noise is hard-filtered; investment-listicle language remains
# visible but is down-ranked by LOW_QUALITY so useful context is not discarded.
HARD_NOISE = ("coupon", "giveaway", "subscribe now")
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
    # Provider-specific metadata is kept on the DTO even though the current
    # NewsItem schema has no dedicated columns for it.  Tiingo, in particular,
    # exposes both the publisher time and the time it discovered the article;
    # callers must never silently substitute one for the other.
    crawl_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    provider_sources: list[str] = field(default_factory=list)
    canonical_story_id: str | None = None

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
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return ""
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in _TRACKING_KEYS and not key.lower().startswith(_TRACKING_PREFIXES)]
    # URL identity is intentionally provider-agnostic.  The hostname and
    # default ports are normalised so a Reuters link copied through two feeds
    # does not become two stories merely because one includes ``www``.
    hostname = (parts.hostname or "").lower().removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        # Keep malformed provider URLs filterable instead of allowing one row
        # to abort a combined provider batch.
        port = None
    netloc = hostname
    if port is not None and not ((parts.scheme or "").lower() == "http" and port == 80) and not ((parts.scheme or "").lower() == "https" and port == 443):
        netloc = f"{hostname}:{port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def normalize_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", title or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    value = re.sub(r"^(?:breaking|update)\s*:\s*", "", value)
    value = re.sub(r"\s+-\s+(?:reuters|bloomberg|cnbc)$", "", value)
    return re.sub(r"[^\w\s.-]+|\s+", " ", value).strip()


def news_fingerprint(provider: str, external_id: str | None, url: str, title: str) -> str:
    basis = f"{provider}:{external_id}" if external_id else f"{normalize_url(url)}|{normalize_title(title)}"
    return hashlib.sha256(basis.encode()).hexdigest()[:64]


def canonical_story_id(dto: NewsDTO) -> str:
    """Return a stable, provider-independent identity for a news story.

    URLs are preferred because they survive small title edits made by feed
    providers.  A title fallback still gives title-only feeds a useful
    identity; the time-window check in :func:`deduplicate` prevents unrelated
    same-title articles from being merged.
    """
    normalized_url = normalize_url(dto.url)
    basis = f"url:{normalized_url}" if normalized_url else f"title:{normalize_title(dto.title)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _story_time(dto: NewsDTO) -> datetime | None:
    # crawl_at is deliberately only a fallback for feeds that omit publication
    # time; it is not used to overwrite published_at or to claim publication.
    return _as_utc(dto.published_at) or _as_utc(dto.crawl_at)


def _within_story_window(left: NewsDTO, right: NewsDTO) -> bool:
    left_time, right_time = _story_time(left), _story_time(right)
    if left_time is None or right_time is None:
        return False
    return abs((left_time - right_time).total_seconds()) <= 48 * 3600


def _normalise_values(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    result: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text:
            result.add(text)
    return sorted(result, key=str.casefold)


def _provider_record(dto: NewsDTO) -> dict[str, Any]:
    """Build a JSON-safe provenance record for a merged story."""
    payload = dict(dto.raw_payload or {}) if isinstance(dto.raw_payload, dict) else {}
    payload.setdefault("provider", dto.provider)
    if dto.external_id and not payload.get("id") and not payload.get("uuid"):
        payload["id"] = dto.external_id
    if dto.crawl_at and not payload.get("crawlDate"):
        payload["crawlDate"] = _as_utc(dto.crawl_at).isoformat()
    if dto.published_at and not payload.get("publishedDate"):
        payload["publishedDate"] = _as_utc(dto.published_at).isoformat()
    if dto.tags and not payload.get("tags"):
        payload["tags"] = list(dto.tags)
    if dto.symbols and not payload.get("tickers"):
        payload["tickers"] = list(dto.symbols)
    return payload


def _merge_payload(left: NewsDTO, right: NewsDTO, *, story_id: str) -> dict[str, Any]:
    """Keep each provider's original payload while exposing merged metadata."""
    left_payload = dict(left.raw_payload or {}) if isinstance(left.raw_payload, dict) else {}
    records: list[dict[str, Any]] = []
    existing_records = left_payload.pop("_provider_records", None)
    if isinstance(existing_records, list):
        records.extend(row for row in existing_records if isinstance(row, dict))
    else:
        records.append(_provider_record(left))
    right_payload = dict(right.raw_payload or {}) if isinstance(right.raw_payload, dict) else {}
    right_records = right_payload.pop("_provider_records", None)
    if isinstance(right_records, list):
        records.extend(row for row in right_records if isinstance(row, dict))
    else:
        records.append(_provider_record(right))

    providers = _normalise_values([left.provider, right.provider, *left.provider_sources, *right.provider_sources])
    tags = _normalise_values([*left.tags, *right.tags])
    merged = left_payload
    if len(records) > 1:
        merged["_provider_records"] = records
    if providers:
        merged["_provider_sources"] = providers
    if tags:
        merged["_news_tags"] = tags
    merged["_canonical_story_id"] = story_id
    return merged


def _merge_news_dto(left: NewsDTO, right: NewsDTO) -> NewsDTO:
    """Merge provider metadata instead of discarding it during dedupe."""
    story_id = left.canonical_story_id or canonical_story_id(left)
    published_candidates = [value for value in (_as_utc(left.published_at), _as_utc(right.published_at)) if value]
    crawl_candidates = [value for value in (_as_utc(left.crawl_at), _as_utc(right.crawl_at)) if value]
    summary = left.summary if len((left.summary or "").strip()) >= len((right.summary or "").strip()) else right.summary
    source = left.source or right.source
    symbols = _normalise_values([*left.symbols, *right.symbols])
    tags = _normalise_values([*left.tags, *right.tags])
    providers = _normalise_values([left.provider, right.provider, *left.provider_sources, *right.provider_sources])
    topic = left.topic if left.topic != "其他" else right.topic
    return replace(
        left,
        external_id=left.external_id or right.external_id,
        source=source,
        summary=summary,
        raw_content=left.raw_content or right.raw_content,
        image_url=left.image_url or right.image_url,
        published_at=min(published_candidates) if published_candidates else None,
        crawl_at=min(crawl_candidates) if crawl_candidates else None,
        symbols=symbols,
        tags=tags,
        provider_sources=providers,
        topic=topic,
        importance_score=max(left.importance_score, right.importance_score),
        quality_score=max(left.quality_score, right.quality_score),
        raw_payload=_merge_payload(left, right, story_id=story_id),
        canonical_story_id=story_id,
    )


def _same_story(left: NewsDTO, right: NewsDTO) -> bool:
    if left.scope != right.scope:
        return False
    if left.provider == right.provider and left.external_id and right.external_id and left.external_id == right.external_id:
        return True
    left_url, right_url = normalize_url(left.url), normalize_url(right.url)
    if left_url and right_url and left_url == right_url:
        return True
    left_title, right_title = normalize_title(left.title), normalize_title(right.title)
    if not left_title or not right_title or not _within_story_window(left, right):
        return False
    if left_title == right_title:
        return True
    return title_similarity(left.title, right.title) >= 0.86


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
    try:
        parsed_url = urlsplit(url)
    except ValueError:
        return False
    if not title or not url or not parsed_url.scheme:
        return False
    # The market page curates market-level themes. Unclassified items from
    # broad feeds are almost always single-company PR or off-market noise.
    # dto.topic is authoritative when scored (cluster merges can inherit a
    # topic from a partner whose headline carried the keywords); reclassify
    # only for unscored DTOs.
    if dto.scope == "market" and dto.topic == "其他" and classify_topic(dto) == "其他":
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
    """Deduplicate within and across providers while retaining provenance.

    A provider article id is only authoritative inside that provider.  URL
    identity is global, and title similarity is considered only inside a
    bounded publication/discovery window to avoid collapsing recurring stories.
    """
    result: list[NewsDTO] = []
    for item in items:
        match_index = next((index for index, old in enumerate(result) if _same_story(old, item)), None)
        if match_index is None:
            result.append(replace(item, canonical_story_id=item.canonical_story_id or canonical_story_id(item)))
        else:
            result[match_index] = _merge_news_dto(result[match_index], item)
    return result


def cluster_news(items: list[NewsDTO]) -> tuple[list[NewsDTO], int]:
    """Select a representative inside a 48h event window, retaining no data deletion."""
    selected: list[NewsDTO] = []; clustered = 0
    for item in sorted(items, key=lambda row: row.importance_score + row.quality_score, reverse=True):
        match_index = next((index for index, old in enumerate(selected) if title_similarity(item.title, old.title) >= .8 and
                            (not _story_time(item) or not _story_time(old) or _within_story_window(item, old))), None)
        if match_index is not None:
            selected[match_index] = _merge_news_dto(selected[match_index], item)
            clustered += 1
            continue
        selected.append(item)
    return selected, clustered


def diversify(items: list[NewsDTO], limit: int) -> list[NewsDTO]:
    topic_count: dict[str, int] = {}; source_count: dict[str, int] = {}; ticker_count: dict[str, int] = {}; result: list[NewsDTO] = []
    ranked = sorted(items, key=lambda row: row.importance_score + row.quality_score, reverse=True)
    deferred: list[NewsDTO] = []
    for item in ranked:
        source = normalize_news_source(item.source)
        ticker = (item.symbols or [item.ticker])[0]
        # A market article without an identified company must not be treated as
        # one synthetic company merely because it uses the storage sentinel.
        ticker_limited = not (item.scope == "market" and not item.symbols)
        if topic_count.get(item.topic, 0) >= 5 or source_count.get(source, 0) >= 4 or (ticker_limited and ticker_count.get(ticker, 0) >= 3):
            deferred.append(item)
            continue
        result.append(item); topic_count[item.topic] = topic_count.get(item.topic, 0) + 1; source_count[source] = source_count.get(source, 0) + 1; ticker_count[ticker] = ticker_count.get(ticker, 0) + 1
        if len(result) >= limit: break
    # These are soft limits: do not leave a thin market-news page just because
    # one wire service or topic dominates an otherwise useful feed.
    if len(result) < limit:
        result.extend(deferred[:limit - len(result)])
    return result or ranked[:limit]


def prepare_news(items: list[NewsDTO], *, scope: str, now: datetime | None = None, limit: int = 20) -> tuple[list[NewsDTO], dict[str, int]]:
    scoped = [replace(item, scope=scope) for item in items]
    scored = [score_news_item(item, now) for item in scoped]
    canonical = deduplicate(scored)
    # Cross-provider canonical merges are part of clustering from the caller's
    # perspective even when they occur before scoring.  Counting them keeps
    # ingestion metrics stable while still retaining the merged provenance.
    canonical_merges = sum(max(len(item.provider_sources) - 1, 0) for item in canonical)
    accepted = [item for item in canonical if filter_news(item, now)]
    clustered, clustered_count = cluster_news(accepted)
    return diversify(clustered, limit), {"fetched": len(items), "accepted": len(accepted), "filtered": len(scoped) - len(accepted), "clustered": clustered_count + canonical_merges}


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
