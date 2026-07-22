from datetime import date

from sqlalchemy import or_, select

from app.models import NewsItem
from app.services import archive
from app.services.news import MARKET_TICKER, NewsDTO, normalize_url


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
        duplicate_conditions = [NewsItem.scope == dto.scope, NewsItem.fingerprint == fingerprint]
        if dto.provider in {"marketaux", "fmp"}:
            # URL deduplication is cross-provider so the same publisher article
            # is not reinserted after Yahoo or Finnhub found it first.
            duplicate_conditions.extend([
                (NewsItem.scope == dto.scope) & (NewsItem.normalized_url == normalized_url),
                (NewsItem.scope == dto.scope) & (NewsItem.url == dto.url),
            ])
            if dto.external_id:
                duplicate_conditions.append(
                    (NewsItem.scope == dto.scope) & (NewsItem.provider == dto.provider) & (NewsItem.external_id == dto.external_id)
                )
        exists = db.scalar(select(NewsItem.id).where(or_(*duplicate_conditions)))
        if exists:
            continue
        relevance, sentiment = scores[position] if scores else (None, None)
        item = NewsItem(
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
            image_url=None,
            symbols=dto.symbols or None,
            news_type=dto.news_type,
            raw_payload=dto.raw_payload or None,
            published_at=dto.published_at,
            relevance_score=relevance,
            sentiment_score=sentiment,
        )
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
                "payload": dto.raw_payload,
            }
        )
    # Market news is not associated with a security. Its internal storage
    # sentinel deliberately cannot be used as an archive directory ticker.
    if raw_records and ticker != MARKET_TICKER:
        archive.append_raw_news(ticker, market_date, raw_records)
    return saved


def news_for_day(db, ticker: str, market_date: date) -> list[NewsItem]:
    from datetime import datetime, time, timezone

    start = datetime.combine(market_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(market_date, time.max, tzinfo=timezone.utc)
    rows = db.scalars(
        select(NewsItem)
        .where(NewsItem.ticker == ticker, NewsItem.found_at >= start, NewsItem.found_at <= end)
        .order_by(NewsItem.published_at.desc().nullslast(), NewsItem.found_at.desc())
    ).all()
    return list(rows)
