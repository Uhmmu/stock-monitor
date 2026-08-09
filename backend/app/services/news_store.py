from datetime import UTC, date, datetime, timedelta
from dataclasses import replace
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select

from app.models import NewsItem
from app.config import get_settings
from app.services import archive
from app.services.news import (
    MARKET_TICKER,
    NewsDTO,
    canonical_story_id,
    normalize_title,
    normalize_url,
    title_similarity,
)


_TITLE_DEDUPE_WINDOW = timedelta(hours=48)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_payload(dto: NewsDTO) -> dict:
    """Return raw provider data plus durable provenance metadata.

    NewsItem predates cross-provider story enrichment and has no dedicated
    columns for tags/crawl timestamps.  Keep those values in JSON until a
    future schema migration can expose first-class columns.
    """
    payload = dict(dto.raw_payload or {}) if isinstance(dto.raw_payload, dict) else {}
    providers = sorted({dto.provider, *(dto.provider_sources or [])}, key=str.casefold)
    if providers:
        payload["_provider_sources"] = providers
    if dto.tags:
        payload["_news_tags"] = sorted({str(tag).strip() for tag in dto.tags if str(tag).strip()}, key=str.casefold)
    if dto.crawl_at:
        value = _utc(dto.crawl_at)
        if value:
            payload["_provider_crawl_at"] = value.isoformat()
    if dto.canonical_story_id:
        payload["_canonical_story_id"] = dto.canonical_story_id
    return payload


def _provider_list(dto: NewsDTO) -> list[str]:
    return sorted({dto.provider, *(dto.provider_sources or [])}, key=str.casefold)


def _provider_metadata(dto: NewsDTO) -> dict:
    def iso(value: datetime | None) -> str | None:
        normalised = _utc(value)
        return normalised.isoformat() if normalised else None

    # Keep publisher time and provider discovery time as separate fields.  The
    # nested provider map makes enrichment additive when another feed reports
    # the same canonical story later.
    return {
        "provider": dto.provider,
        "external_id": dto.external_id,
        "published_at": iso(dto.published_at),
        "crawl_at": iso(dto.crawl_at),
        "source": dto.source,
        "symbols": sorted({str(value).strip() for value in dto.symbols if str(value).strip()}, key=str.casefold),
        "tags": sorted({str(value).strip() for value in dto.tags if str(value).strip()}, key=str.casefold),
    }


def _metadata_for_dto(dto: NewsDTO) -> dict:
    return {
        "providers": {dto.provider: _provider_metadata(dto)},
        "provider_sources": _provider_list(dto),
        "tags": sorted({str(value).strip() for value in dto.tags if str(value).strip()}, key=str.casefold),
        "symbols": sorted({str(value).strip() for value in dto.symbols if str(value).strip()}, key=str.casefold),
        "canonical_story_id": dto.canonical_story_id,
    }


def _merge_payloads(existing: dict | None, incoming: dict) -> dict:
    merged = dict(existing or {}) if isinstance(existing, dict) else {}
    incoming_map = dict(incoming or {}) if isinstance(incoming, dict) else {}
    incoming_crawl_at = incoming_map.get("_provider_crawl_at")
    incoming_story_id = incoming_map.get("_canonical_story_id")
    existing_records = merged.pop("_provider_records", None)
    incoming_records = incoming_map.pop("_provider_records", None)
    records = []
    if isinstance(existing_records, list):
        records.extend(row for row in existing_records if isinstance(row, dict))
    elif merged:
        records.append(dict(merged))
    if isinstance(incoming_records, list):
        records.extend(row for row in incoming_records if isinstance(row, dict))
    elif incoming_map:
        records.append(dict(incoming_map))
    if records:
        merged["_provider_records"] = records
    sources = set()
    for payload in (*records, merged, incoming_map):
        values = payload.get("_provider_sources") if isinstance(payload, dict) else None
        if isinstance(values, list):
            sources.update(str(value) for value in values if str(value).strip())
    if sources:
        merged["_provider_sources"] = sorted(sources, key=str.casefold)
    tags = set()
    for payload in (*records, merged, incoming_map):
        values = payload.get("_news_tags") if isinstance(payload, dict) else None
        if isinstance(values, list):
            tags.update(str(value) for value in values if str(value).strip())
    if tags:
        merged["_news_tags"] = sorted(tags, key=str.casefold)
    canonical = incoming_map.get("_canonical_story_id") or merged.get("_canonical_story_id")
    if canonical:
        merged["_canonical_story_id"] = canonical
    if incoming_crawl_at:
        merged["_provider_crawl_at"] = incoming_crawl_at
    if incoming_story_id:
        merged["_canonical_story_id"] = incoming_story_id
    return merged


def _enrich_existing(item: NewsItem, dto: NewsDTO) -> None:
    story_id = dto.canonical_story_id or canonical_story_id(dto)
    dto = dto if dto.canonical_story_id else replace(dto, canonical_story_id=story_id)
    incoming_payload = _json_payload(dto)
    item.raw_payload = _merge_payloads(item.raw_payload, incoming_payload)
    symbols = sorted({str(value).strip() for value in [*(item.symbols or []), *(dto.symbols or [])] if str(value).strip()}, key=str.casefold)
    item.symbols = symbols or None
    if hasattr(item, "canonical_story_id"):
        item.canonical_story_id = getattr(item, "canonical_story_id", None) or dto.canonical_story_id
    if hasattr(item, "provider_sources"):
        current_sources = getattr(item, "provider_sources", None) or []
        item.provider_sources = sorted({str(value).strip() for value in [*current_sources, *_provider_list(dto)] if str(value).strip()}, key=str.casefold)
    if hasattr(item, "provider_metadata"):
        metadata = dict(getattr(item, "provider_metadata", None) or {})
        providers = dict(metadata.get("providers") or {})
        # Older rows may have been written as a flat provider record; retain it
        # under its provider key before adding the new enrichment.
        if not providers and metadata.get("provider"):
            providers[str(metadata["provider"])] = metadata
        providers[dto.provider] = _provider_metadata(dto)
        merged_tags = sorted({str(value).strip() for value in [*(metadata.get("tags") or []), *(dto.tags or [])] if str(value).strip()}, key=str.casefold)
        metadata.update({
            "providers": providers,
            "provider_sources": getattr(item, "provider_sources", _provider_list(dto)),
            "tags": merged_tags,
            "symbols": symbols,
            "canonical_story_id": getattr(item, "canonical_story_id", None),
        })
        item.provider_metadata = metadata
    if not item.summary and dto.summary:
        item.summary = dto.summary
    elif dto.summary and len(dto.summary.strip()) > len((item.summary or "").strip()):
        item.summary = dto.summary
    if not item.source and dto.source:
        item.source = dto.source
    if not item.image_url and dto.image_url:
        item.image_url = dto.image_url
    if not item.published_at and dto.published_at:
        item.published_at = _utc(dto.published_at)


def _find_title_duplicate(db, dto: NewsDTO) -> NewsItem | None:
    published_at = _utc(dto.published_at)
    if published_at is None:
        return None
    lower, upper = published_at - _TITLE_DEDUPE_WINDOW, published_at + _TITLE_DEDUPE_WINDOW
    candidates = db.scalars(
        select(NewsItem).where(
            NewsItem.scope == dto.scope,
            NewsItem.published_at >= lower,
            NewsItem.published_at <= upper,
        )
    ).all()
    normalized = normalize_title(dto.title)
    for candidate in candidates:
        candidate_title = normalize_title(candidate.title)
        if normalized and normalized == candidate_title:
            return candidate
        if title_similarity(dto.title, candidate.title) >= 0.86:
            return candidate
    return None


def persist_news(
    db,
    ticker: str,
    market_date: date,
    dtos: list[NewsDTO],
    scores: list[tuple[float | None, float | None]] | None = None,
) -> list[NewsItem]:
    saved: list[NewsItem] = []
    raw_records: list[dict] = []
    for position, dto in enumerate(dtos):
        fingerprint = dto.fingerprint
        normalized_url = normalize_url(dto.url)
        story_id = dto.canonical_story_id or canonical_story_id(dto)
        duplicate_conditions = [and_(NewsItem.scope == dto.scope, NewsItem.fingerprint == fingerprint)]
        # URL identity is global: Marketaux, Tiingo, Yahoo and Finnhub may all
        # report the same publisher article with provider-specific IDs.
        if normalized_url:
            duplicate_conditions.extend([
                (NewsItem.scope == dto.scope) & (NewsItem.normalized_url == normalized_url),
                (NewsItem.scope == dto.scope) & (NewsItem.url == dto.url),
            ])
        if dto.external_id:
            duplicate_conditions.append(
                (NewsItem.scope == dto.scope) & (NewsItem.provider == dto.provider) & (NewsItem.external_id == dto.external_id)
            )
        if hasattr(NewsItem, "canonical_story_id"):
            duplicate_conditions.append((NewsItem.scope == dto.scope) & (NewsItem.canonical_story_id == story_id))
        exists = db.scalar(select(NewsItem.id).where(or_(*duplicate_conditions)))
        existing_item = db.get(NewsItem, exists) if exists else _find_title_duplicate(db, dto)
        if existing_item:
            _enrich_existing(existing_item, dto)
            continue
        relevance, sentiment = scores[position] if scores else (None, None)
        dto = dto if dto.canonical_story_id else replace(dto, canonical_story_id=story_id)
        payload = _json_payload(dto)
        item_values = dict(
            ticker=ticker,
            provider=dto.provider,
            external_id=dto.external_id,
            fingerprint=fingerprint,
            scope=dto.scope,
            topic=dto.topic,
            importance_score=dto.importance_score,
            quality_score=dto.quality_score,
            cluster_key=dto.cluster_key,
            title=dto.title[:512],
            url=dto.url,
            normalized_url=normalized_url,
            source=dto.source,
            summary=dto.summary,
            raw_content=dto.raw_content,
            image_url=dto.image_url,
            symbols=dto.symbols or None,
            news_type=dto.news_type,
            raw_payload=payload or None,
            published_at=_utc(dto.published_at),
            relevance_score=relevance,
            sentiment_score=sentiment,
        )
        if hasattr(NewsItem, "canonical_story_id"):
            item_values["canonical_story_id"] = story_id
            item_values["provider_sources"] = _provider_list(dto)
            item_values["provider_metadata"] = _metadata_for_dto(dto)
        item = NewsItem(**item_values)
        db.add(item)
        saved.append(item)
        raw_records.append(
            {
                "provider": dto.provider,
                "external_id": dto.external_id,
                "fingerprint": fingerprint,
                "title": dto.title,
                "url": dto.url,
                "source": dto.source,
                "summary": dto.summary,
                "published_at": dto.published_at,
                "symbols": dto.symbols,
                "news_type": dto.news_type,
                "scope": dto.scope,
                "topic": dto.topic,
                "payload": payload,
            }
        )
    # Market news is not associated with a security. Its internal storage
    # sentinel deliberately cannot be used as an archive directory ticker.
    if raw_records and ticker != MARKET_TICKER:
        archive.append_raw_news(ticker, market_date, raw_records)
    return saved


def news_for_day(db, ticker: str, market_date: date) -> list[NewsItem]:
    from datetime import datetime, time

    zone = ZoneInfo(get_settings().market_timezone)
    start = datetime.combine(market_date, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(market_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    timestamp = func.coalesce(NewsItem.published_at, NewsItem.found_at)
    rows = db.scalars(
        select(NewsItem)
        .where(NewsItem.ticker == ticker, timestamp >= start, timestamp < end)
        .order_by(NewsItem.published_at.desc().nullslast(), NewsItem.found_at.desc())
    ).all()
    return list(rows)
