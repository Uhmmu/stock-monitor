"""Financial Modeling Prep news provider.

The public functions return the same ``NewsDTO`` objects as the other news
sources.  ``fetch_fmp_news`` is the scheduler-facing adapter which adds the
shared persistent quota/batch state used by quota-limited providers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
import time
from typing import Any, Callable

import httpx
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models import NewsProviderState
from app.services.news import NewsDTO


logger = logging.getLogger(__name__)
_PROVIDER = "fmp"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (0.25, 0.5)


@dataclass(frozen=True)
class FmpFetchResult:
    items_by_ticker: dict[str, list[NewsDTO]] = field(default_factory=dict)
    batch: tuple[str, ...] = ()
    articles: int = 0
    press_releases: int = 0
    usage: int = 0
    remaining: int = 0
    skipped: str | None = None


def _symbols(symbols: list[str]) -> list[str]:
    return sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})


def _batches(symbols: list[str], size: int) -> list[tuple[str, ...]]:
    normalized = _symbols(symbols)
    size = max(int(size), 1)
    return [tuple(normalized[i:i + size]) for i in range(0, len(normalized), size)]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern).replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _row_symbols(row: dict[str, Any], requested: set[str]) -> list[str]:
    values = row.get("symbols") or row.get("symbol") or row.get("ticker") or ""
    if isinstance(values, str):
        candidates = values.replace(";", ",").split(",")
    elif isinstance(values, list):
        candidates = values
    else:
        candidates = []
    return sorted({str(value).strip().upper() for value in candidates if str(value).strip().upper() in requested})


def _parse(rows: list[Any], requested: list[str] | None, news_type: str) -> list[NewsDTO]:
    requested_set = set(requested or [])
    result: list[NewsDTO] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("headline") or "").strip()
        url = str(raw.get("url") or raw.get("link") or "").strip()
        if requested is None:
            raw_symbols = raw.get("symbols") or raw.get("symbol") or raw.get("ticker") or "MARKET"
            symbols = [str(raw_symbols).split(",")[0].strip().upper() or "MARKET"]
        else:
            symbols = _row_symbols(raw, requested_set)
        if not title or not url or not symbols:
            continue
        external_id = raw.get("id") or raw.get("articleId") or raw.get("uuid")
        summary = str(raw.get("text") or raw.get("summary") or raw.get("description") or "").strip() or None
        for symbol in symbols:
            result.append(NewsDTO(
                provider=_PROVIDER,
                ticker=symbol,
                external_id=str(external_id) if external_id is not None else None,
                title=title[:512], url=url,
                source=str(raw.get("site") or raw.get("publisher") or raw.get("source") or "").strip() or None,
                summary=summary, raw_content=summary,
                image_url=str(raw.get("image") or raw.get("image_url") or "").strip() or None,
                published_at=_parse_datetime(raw.get("publishedDate") or raw.get("published_at") or raw.get("date")),
                symbols=symbols, news_type=news_type, raw_payload=raw,
            ))
    return result


def _response_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    raise ValueError("invalid FMP response shape")


def _request(
    endpoint: str, symbols: list[str], *, config: Settings, http_get: Callable[..., Any], reserve_call: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Any]:
    base_url = config.fmp_base_url.rstrip("/")
    for attempt in range(len(_RETRY_DELAYS) + 1):
        if reserve_call is not None and not reserve_call():
            raise RuntimeError("daily_limit_reached")
        try:
            response = http_get(
                f"{base_url}{endpoint}", params={"symbols": ",".join(symbols)} if symbols else {},
                headers={"apikey": config.fmp_api_key}, timeout=config.fmp_request_timeout_seconds,
            )
            status = getattr(response, "status_code", None)
            if status in {402, 403}:
                logger.warning("[FMP] HTTP %s; FMP unavailable", status)
                return []
            if status in {400, 422} and len(symbols) > 1:
                # The stable endpoint accepts a symbols list today, but keep the
                # provider contract stable if a plan/endpoint only accepts one.
                logger.info("[FMP] multi-symbol request unsupported; falling back to single symbols")
                return [
                    row
                    for symbol in symbols
                    for row in _request(endpoint, [symbol], config=config, http_get=http_get, reserve_call=reserve_call, sleep=sleep)
                ]
            if status in _RETRYABLE_STATUSES:
                logger.warning("[FMP] HTTP %s", status)
                if attempt < len(_RETRY_DELAYS):
                    sleep(_RETRY_DELAYS[attempt])
                    continue
            response.raise_for_status()
            return _response_rows(response.json())
        except httpx.TimeoutException:
            logger.warning("[FMP] timeout")
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {402, 403}:
                logger.warning("[FMP] HTTP %s; FMP unavailable", status)
                return []
            logger.warning("[FMP] request failed: %s", status and f"HTTP {status}" or type(exc).__name__)
        if attempt < len(_RETRY_DELAYS):
            sleep(_RETRY_DELAYS[attempt])
    return []


def fetch_stock_news(symbols: list[str], *, config: Settings | None = None, http_get: Callable[..., Any] = httpx.get) -> list[NewsDTO]:
    config = config or get_settings()
    if not config.fmp_enabled or not config.fmp_api_key.strip():
        return []
    requested = _symbols(symbols)
    if not requested:
        return []
    return _parse(_request("/news/stock", requested, config=config, http_get=http_get), requested, "article")


def fetch_press_releases(symbols: list[str], *, config: Settings | None = None, http_get: Callable[..., Any] = httpx.get) -> list[NewsDTO]:
    config = config or get_settings()
    if not config.fmp_enabled or not config.fmp_api_key.strip():
        return []
    requested = _symbols(symbols)
    if not requested:
        return []
    return _parse(_request("/news/press-releases", requested, config=config, http_get=http_get), requested, "press_release")


def fetch_market_news(*, config: Settings | None = None, http_get: Callable[..., Any] = httpx.get) -> list[NewsDTO]:
    """Future-only global feed.  It is deliberately not scheduled or persisted."""
    config = config or get_settings()
    if not config.fmp_enabled or not config.fmp_api_key.strip():
        return []
    rows = _request("/news/stock-latest", [], config=config, http_get=http_get)
    # Market news has no watchlist ticker; retain it as an unassigned DTO for a future consumer.
    return _parse(rows, None, "article")


def _state(db, now: datetime) -> NewsProviderState:
    state = db.scalar(select(NewsProviderState).where(NewsProviderState.provider == _PROVIDER).with_for_update())
    if state is None:
        state = NewsProviderState(provider=_PROVIDER, quota_utc_date=now.date(), request_count=0, next_batch_index=0)
        db.add(state)
        db.flush()
    if state.quota_utc_date != now.date():
        state.quota_utc_date, state.request_count = now.date(), 0
    return state


def fetch_fmp_news(db, symbols: list[str], *, config: Settings | None = None, now: datetime | None = None, http_get: Callable[..., Any] = httpx.get, sleep: Callable[[float], None] = time.sleep) -> FmpFetchResult:
    config = config or get_settings()
    if not config.fmp_enabled or not config.fmp_api_key.strip():
        return FmpFetchResult(skipped="disabled")
    batches = _batches(symbols, config.fmp_news_batch_size)
    if not batches:
        return FmpFetchResult(skipped="no_symbols")
    now = _utc(now or datetime.now(UTC))
    state = _state(db, now)
    if state.request_count >= config.fmp_daily_call_limit:
        db.commit()
        logger.warning("[FMP] Daily limit reached")
        return FmpFetchResult(usage=state.request_count, remaining=0, skipped="daily_limit_reached")
    batch = batches[state.next_batch_index % len(batches)]
    state.next_batch_index = (state.next_batch_index + 1) % len(batches)
    db.commit()

    def reserve_call() -> bool:
        state = _state(db, now)
        if state.request_count >= config.fmp_daily_call_limit:
            db.commit()
            logger.warning("[FMP] Daily limit reached")
            return False
        state.request_count += 1
        db.commit()
        return True

    logger.info("[FMP] Fetching batch: %s", " ".join(batch))
    try:
        article_rows = _request("/news/stock", list(batch), config=config, http_get=http_get, reserve_call=reserve_call, sleep=sleep)
    except RuntimeError as exc:
        if str(exc) != "daily_limit_reached":
            raise
        article_rows = []
    try:
        release_rows = _request("/news/press-releases", list(batch), config=config, http_get=http_get, reserve_call=reserve_call, sleep=sleep)
    except RuntimeError as exc:
        if str(exc) != "daily_limit_reached":
            raise
        release_rows = []
    articles, releases = _parse(article_rows, list(batch), "article"), _parse(release_rows, list(batch), "press_release")
    grouped: dict[str, list[NewsDTO]] = defaultdict(list)
    for item in articles + releases:
        grouped[item.ticker].append(item)
    state = _state(db, now)
    db.commit()
    logger.info("[FMP] Fetched %d articles", len(articles))
    logger.info("[FMP] Fetched %d press releases", len(releases))
    logger.info("[FMP] Completed")
    return FmpFetchResult(dict(grouped), batch, len(articles), len(releases), state.request_count, max(config.fmp_daily_call_limit - state.request_count, 0))
