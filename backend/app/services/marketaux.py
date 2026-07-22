from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Callable

import httpx
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models import NewsProviderState
from app.services.news import NewsDTO, normalize_url


logger = logging.getLogger(__name__)

_PROVIDER = "marketaux"
_ENDPOINT = "https://api.marketaux.com/v1/news/all"
_FREE_TIER_HARD_LIMIT = 100
_EXECUTION_INTERVAL = timedelta(hours=2)
_INITIAL_LOOKBACK = timedelta(hours=48)
_REQUEST_TIMEOUT = 15.0


@dataclass(frozen=True)
class MarketauxFetchResult:
    items_by_ticker: dict[str, list[NewsDTO]] = field(default_factory=dict)
    batch: tuple[str, ...] = ()
    returned: int = 0
    usage: int = 0
    remaining: int = _FREE_TIER_HARD_LIMIT
    skipped: str | None = None


@dataclass(frozen=True)
class _Reservation:
    status: str
    batch: tuple[str, ...] = ()
    usage: int = 0
    remaining: int = 0
    last_successful_fetch: datetime | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _effective_limit(configured: int) -> int:
    """Configuration may lower the quota, but can never raise the free-tier cap."""
    return min(max(int(configured), 0), _FREE_TIER_HARD_LIMIT)


def _batches(symbols: list[str], batch_size: int) -> list[tuple[str, ...]]:
    size = max(int(batch_size), 1)
    normalized = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    return [tuple(normalized[index:index + size]) for index in range(0, len(normalized), size)]


def _locked_state(db, now: datetime) -> NewsProviderState:
    state = db.scalar(
        select(NewsProviderState)
        .where(NewsProviderState.provider == _PROVIDER)
        .with_for_update()
    )
    if state is None:
        state = NewsProviderState(
            provider=_PROVIDER,
            quota_utc_date=now.date(),
            request_count=0,
            next_batch_index=0,
        )
        db.add(state)
        db.flush()
    if state.quota_utc_date != now.date():
        state.quota_utc_date = now.date()
        state.request_count = 0
    return state


def _reserve_request(
    db,
    batches: list[tuple[str, ...]],
    now: datetime,
    max_requests: int,
) -> _Reservation:
    """Durably reserve one request immediately before dispatch.

    The row lock makes the daily cap strict even if two workers start the task at
    the same time. The committed reservation also survives a worker restart.
    """
    limit = _effective_limit(max_requests)
    state = _locked_state(db, now)
    last_execution = _utc(state.last_execution_at) if state.last_execution_at else None
    if last_execution is not None and now < last_execution + _EXECUTION_INTERVAL:
        usage = state.request_count
        db.commit()  # Persist a UTC-date reset even when this execution is gated.
        return _Reservation(
            status="interval_not_elapsed",
            usage=usage,
            remaining=max(limit - usage, 0),
        )

    # A due provider execution is recorded even when quota prevents a request,
    # so the 15-minute parent scheduler cannot repeatedly execute Marketaux.
    state.last_execution_at = now
    if state.request_count >= limit:
        usage = state.request_count
        db.commit()
        return _Reservation(status="daily_quota_exhausted", usage=usage, remaining=0)

    batch_index = state.next_batch_index % len(batches)
    batch = batches[batch_index]
    state.next_batch_index = (batch_index + 1) % len(batches)
    state.request_count += 1
    usage = state.request_count
    last_successful_fetch = state.last_successful_fetch
    db.commit()
    return _Reservation(
        status="request_reserved",
        batch=batch,
        usage=usage,
        remaining=limit - usage,
        last_successful_fetch=last_successful_fetch,
    )


def _mark_success(db, request_started_at: datetime) -> None:
    state = _locked_state(db, request_started_at)
    previous = _utc(state.last_successful_fetch) if state.last_successful_fetch else None
    if previous is None or previous < request_started_at:
        # Use request start, not response completion, so news published in flight
        # remains eligible for the next poll.
        state.last_successful_fetch = request_started_at
    db.commit()


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _article_symbols(row: dict[str, Any], requested: set[str]) -> list[str]:
    matches: dict[str, float] = {}
    entities = row.get("entities")
    if not isinstance(entities, list):
        return []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        symbol = str(entity.get("symbol") or "").strip().upper()
        if symbol not in requested:
            continue
        try:
            score = float(entity.get("match_score") or 0)
        except (TypeError, ValueError):
            score = 0
        matches[symbol] = max(matches.get(symbol, 0), score)
    return sorted(matches, key=lambda symbol: (matches[symbol], symbol), reverse=True)


def _parse_articles(rows: list[Any], batch: tuple[str, ...]) -> dict[str, list[NewsDTO]]:
    requested = set(batch)
    result: dict[str, list[NewsDTO]] = {symbol: [] for symbol in batch}
    seen_uuids: set[str] = set()
    seen_urls: set[str] = set()

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        uuid = str(raw.get("uuid") or "").strip()
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not uuid or not title or not url:
            continue
        normalized_url = normalize_url(url)
        if uuid in seen_uuids or normalized_url in seen_urls:
            continue
        symbols = _article_symbols(raw, requested)
        if not symbols:
            continue
        seen_uuids.add(uuid)
        seen_urls.add(normalized_url)
        summary = str(raw.get("description") or raw.get("snippet") or "").strip() or None
        source = str(raw.get("source") or "").strip() or None
        for symbol in symbols:
            result[symbol].append(
                NewsDTO(
                    provider=_PROVIDER,
                    ticker=symbol,
                    external_id=uuid,
                    title=title[:512],
                    url=url,
                    source=source,
                    summary=summary,
                    raw_content=summary,
                    image_url=str(raw.get("image_url") or "").strip() or None,
                    published_at=_parse_datetime(raw.get("published_at")),
                    raw_payload=raw,
                )
            )
    return result


def _error_label(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return f"HTTP {status_code}" if status_code is not None else type(exc).__name__


def fetch_marketaux_news(
    db,
    symbols: list[str],
    *,
    config: Settings | None = None,
    now: datetime | None = None,
    http_get: Callable[..., Any] = httpx.get,
) -> MarketauxFetchResult:
    config = config or get_settings()
    if not config.marketaux_enabled or not config.marketaux_api_key.strip():
        return MarketauxFetchResult(skipped="disabled")

    batches = _batches(symbols, config.marketaux_batch_size)
    if not batches:
        return MarketauxFetchResult(skipped="no_symbols")

    request_started_at = _utc(now or datetime.now(UTC))
    reservation = _reserve_request(
        db,
        batches,
        request_started_at,
        config.marketaux_max_requests_per_day,
    )
    if reservation.status == "interval_not_elapsed":
        return MarketauxFetchResult(
            usage=reservation.usage,
            remaining=reservation.remaining,
            skipped="interval_not_elapsed",
        )
    if reservation.status == "daily_quota_exhausted":
        logger.warning("Marketaux daily quota exhausted.")
        logger.info("Marketaux skipped (daily quota exhausted)")
        return MarketauxFetchResult(
            usage=reservation.usage,
            remaining=0,
            skipped="daily_quota_exhausted",
        )

    batch = reservation.batch
    usage = reservation.usage
    remaining = reservation.remaining
    last_successful_fetch = reservation.last_successful_fetch
    published_after = _utc(last_successful_fetch) if last_successful_fetch else request_started_at - _INITIAL_LOOKBACK
    params = {
        "api_token": config.marketaux_api_key,
        "symbols": ",".join(batch),
        "filter_entities": "true",
        "must_have_entities": "true",
        "group_similar": "true",
        "language": "en",
        "published_after": published_after.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    logger.info("Marketaux request sent. Symbols: %s", " ".join(batch))
    try:
        response = http_get(
            _ENDPOINT,
            params=params,
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("invalid response shape")
    except Exception as exc:
        # Do not log the response URL: it contains api_token in the query string.
        logger.error("Marketaux request failed: %s", _error_label(exc))
        return MarketauxFetchResult(
            batch=batch,
            usage=usage,
            remaining=remaining,
            skipped="request_failed",
        )

    rows = payload["data"]
    items_by_ticker = _parse_articles(rows, batch)
    _mark_success(db, request_started_at)
    logger.info(
        "Marketaux\nBatch: %s\nReturned: %d\nUsage: %d/%d\nRemaining: %d",
        " ".join(batch),
        len(rows),
        usage,
        _effective_limit(config.marketaux_max_requests_per_day),
        remaining,
    )
    return MarketauxFetchResult(
        items_by_ticker=items_by_ticker,
        batch=batch,
        returned=len(rows),
        usage=usage,
        remaining=remaining,
    )
