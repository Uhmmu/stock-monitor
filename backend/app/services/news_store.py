from datetime import date

from sqlalchemy import or_, select

from app.models import NewsItem
from app.services import archive
from app.services.news import NewsDTO, normalize_url


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
        duplicate_conditions = [NewsItem.fingerprint == fingerprint]
        if dto.provider == "marketaux":
            # URL deduplication is cross-provider so the same publisher article
            # is not reinserted after Yahoo or Finnhub found it first.
            duplicate_conditions.extend([
                NewsItem.normalized_url == normalized_url,
                NewsItem.url == dto.url,
            ])
            if dto.external_id:
                duplicate_conditions.append(
                    (NewsItem.provider == "marketaux") & (NewsItem.external_id == dto.external_id)
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
            title=dto.title[:512],
            url=dto.url,
            normalized_url=normalized_url,
            source=dto.source,
            summary=dto.summary,
            raw_content=dto.raw_content,
            image_url=dto.image_url,
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
                "payload": dto.raw_payload,
            }
        )
    if raw_records:
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
