"""Tiingo News provider adapter.

The adapter deliberately returns :class:`~app.services.news.NewsDTO` objects
instead of exposing Tiingo's response shape to the scheduler or UI.  It is
safe to call with a tracked-symbol list: symbols are normalised and split into
bounded requests, and one failed batch never discards successful batches.

Credentials are read from the application settings object at call time.  No
token is included in logs, exception labels, or returned results.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Callable

import httpx

from app.config import Settings, get_settings
from app.services.news import NewsDTO, deduplicate, normalize_url


logger = logging.getLogger(__name__)

PROVIDER = "tiingo"
ENDPOINT = "https://api.tiingo.com/tiingo/news"
DEFAULT_BATCH_SIZE = 50
DEFAULT_LIMIT = 100
DEFAULT_LOOKBACK_HOURS = 48
DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class TiingoFetchResult:
    """Result of one bounded Tiingo News execution."""

    items_by_ticker: dict[str, list[NewsDTO]] = field(default_factory=dict)
    batches: tuple[tuple[str, ...], ...] = ()
    returned: int = 0
    failed_batches: tuple[tuple[str, ...], ...] = ()
    errors: tuple[str, ...] = ()
    skipped: str | None = None

    @property
    def partial_failure(self) -> bool:
        return bool(self.failed_batches) and any(bool(items) for items in self.items_by_ticker.values())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _batches(symbols: list[str], batch_size: int) -> list[tuple[str, ...]]:
    size = max(int(batch_size), 1)
    normalised = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol or "").strip()})
    return [tuple(normalised[index:index + size]) for index in range(0, len(normalised), size)]


def _setting(config: Settings, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(config, name, None)
        if value is not None:
            return value
    return default


def _token(config: Settings) -> str:
    value = _setting(config, "tiingo_api_token", "tiingo_news_api_token", "tiingo_token", default="")
    return str(value or "").strip()


def _enabled(config: Settings) -> bool:
    return bool(_setting(config, "tiingo_news_enabled", "tiingo_enabled", default=True))


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _values(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return sorted({str(item).strip() for item in value if str(item or "").strip()}, key=str.casefold)


def _source(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("title") or value.get("domain"))
    return _text(value)


def _error_label(response: Any = None, exc: Exception | None = None) -> str:
    status_code = getattr(response, "status_code", None)
    if status_code is None and exc is not None:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 401:
        return "HTTP 401"
    if status_code == 403:
        return "HTTP 403"
    if status_code == 429:
        return "HTTP 429"
    return f"HTTP {status_code}" if status_code is not None else type(exc).__name__ if exc else "request_failed"


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "news", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_articles(rows: list[Any], batch: tuple[str, ...]) -> dict[str, list[NewsDTO]]:
    requested = set(batch)
    result: dict[str, list[NewsDTO]] = {symbol: [] for symbol in batch}
    records: list[NewsDTO] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        external_id = _text(raw.get("id") or raw.get("uuid"))
        title = _text(raw.get("title"))
        url = _text(raw.get("url") or raw.get("link"))
        if not external_id or not title or not url:
            continue
        # Tiingo normally returns all matching tickers.  Restrict symbols to
        # the requested batch so a provider response can never fan out to an
        # untracked universe.
        tickers = [symbol.upper() for symbol in _values(raw.get("tickers"))]
        symbols = sorted({symbol for symbol in tickers if symbol in requested})
        if not symbols:
            continue
        published_at = _parse_datetime(raw.get("publishedDate") or raw.get("published_date"))
        crawl_at = _parse_datetime(raw.get("crawlDate") or raw.get("crawl_date"))
        description = _text(raw.get("description"))
        tags = _values(raw.get("tags"))
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(records)
                if (existing.external_id and existing.external_id == external_id)
                or (normalize_url(existing.url) and normalize_url(existing.url) == normalize_url(url))
            ),
            None,
        )
        if duplicate_index is not None:
            existing = records[duplicate_index]
            payload = dict(existing.raw_payload or {})
            duplicates = payload.setdefault("_tiingo_duplicate_payloads", [])
            if isinstance(duplicates, list):
                duplicates.append(dict(raw))
            records[duplicate_index] = replace(
                existing,
                symbols=sorted({*existing.symbols, *symbols}),
                tags=sorted({*existing.tags, *tags}, key=str.casefold),
                raw_payload=payload,
            )
            continue
        records.append(
            NewsDTO(
                provider=PROVIDER,
                ticker=symbols[0],
                external_id=external_id,
                title=title[:512],
                url=url,
                source=_source(raw.get("source")),
                summary=description,
                raw_content=description,
                image_url=_text(raw.get("imageUrl") or raw.get("image_url")),
                published_at=published_at,
                crawl_at=crawl_at,
                symbols=symbols,
                tags=tags,
                raw_payload=dict(raw),
            )
        )
    for article in records:
        for symbol in article.symbols:
            result[symbol].append(replace(article, ticker=symbol))
    return result


def _request_params(batch: tuple[str, ...], now: datetime, config: Settings) -> dict[str, str | int]:
    lookback = _setting(config, "tiingo_news_lookback_hours", default=None)
    if lookback is None:
        lookback = float(_setting(config, "tiingo_news_lookback_days", default=DEFAULT_LOOKBACK_HOURS / 24)) * 24
    lookback = max(float(lookback), 0)
    start = now - timedelta(hours=lookback)
    limit = max(int(_setting(config, "tiingo_news_limit", default=DEFAULT_LIMIT)), 1)
    # Tiingo's news endpoint accepts date boundaries; using UTC dates keeps the
    # request portable while the DTO retains the precise ISO timestamps.
    return {
        "tickers": ",".join(batch),
        "startDate": start.date().isoformat(),
        "endDate": now.date().isoformat(),
        "sortBy": str(_setting(config, "tiingo_news_sort_by", default="crawlDate")),
        "limit": limit,
    }


def fetch_tiingo_news(
    symbols: list[str],
    *,
    config: Settings | None = None,
    now: datetime | None = None,
    http_get: Callable[..., Any] = httpx.get,
) -> TiingoFetchResult:
    """Fetch recent news for tracked symbols in bounded Tiingo batches.

    The function intentionally has no database or Celery dependency; the
    existing scheduler owns cadence and can combine this result with
    Marketaux, Finnhub, Yahoo and other providers.  A failed batch is returned
    as structured status while successful batches remain usable.
    """
    config = config or get_settings()
    if not _enabled(config) or not _token(config):
        return TiingoFetchResult(skipped="disabled")
    batch_size = max(int(_setting(config, "tiingo_news_batch_size", default=DEFAULT_BATCH_SIZE)), 1)
    batches = _batches(symbols, batch_size)
    if not batches:
        return TiingoFetchResult(skipped="no_symbols")
    request_time = _utc(now or datetime.now(UTC))
    timeout = float(_setting(config, "tiingo_news_timeout_seconds", "tiingo_news_request_timeout_seconds", default=DEFAULT_TIMEOUT_SECONDS))
    token = _token(config)
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    all_items: dict[str, list[NewsDTO]] = {symbol: [] for batch in batches for symbol in batch}
    failed: list[tuple[str, ...]] = []
    errors: list[str] = []
    returned = 0

    for batch in batches:
        try:
            response = http_get(
                str(_setting(config, "tiingo_news_endpoint", default=ENDPOINT)),
                params=_request_params(batch, request_time, config),
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            )
            status = getattr(response, "status_code", None)
            if status in {401, 403, 429}:
                label = _error_label(response)
                failed.append(batch)
                errors.append(label)
                logger.warning("Tiingo News batch failed (%s) symbols=%s", label, " ".join(batch))
                continue
            response.raise_for_status()
            payload = response.json()
            rows = _rows(payload)
            if not isinstance(payload, list) and not (
                isinstance(payload, dict)
                and any(isinstance(payload.get(key), list) for key in ("data", "news", "results"))
            ):
                raise ValueError("invalid response shape")
            parsed = _parse_articles(rows, batch)
        except Exception as exc:
            label = _error_label(exc=exc)
            failed.append(batch)
            errors.append(label)
            logger.warning("Tiingo News request failed (%s) symbols=%s", label, " ".join(batch))
            continue

        returned += len(rows)
        for symbol, items in parsed.items():
            all_items.setdefault(symbol, []).extend(items)

    # Deduplicate across batches as well as within a single provider response.
    # This also unions Tiingo ticker/tag enrichment when a wire copy appears
    # under the same article id or canonical URL more than once.
    all_items = {symbol: deduplicate(items) for symbol, items in all_items.items()}
    # Keep only non-empty ticker lists in normal operation, while retaining an
    # empty key for successful requested symbols is useful to callers that need
    # coverage accounting.  The scheduler can simply iterate its own symbols.
    if not any(all_items.values()) and failed and len(failed) == len(batches):
        skipped = "request_failed"
    else:
        skipped = None
    return TiingoFetchResult(
        items_by_ticker=all_items,
        batches=tuple(batches),
        returned=returned,
        failed_batches=tuple(failed),
        errors=tuple(errors),
        skipped=skipped,
    )


__all__ = [
    "ENDPOINT",
    "PROVIDER",
    "TiingoFetchResult",
    "fetch_tiingo_news",
]
