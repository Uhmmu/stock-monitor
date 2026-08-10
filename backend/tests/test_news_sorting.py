from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import list_market_news
from app.database import Base
from app.models import NewsItem


def _row(title: str, quality: float, importance: float, published_at: datetime) -> NewsItem:
    return NewsItem(
        ticker="__MARKET__",
        scope="market",
        provider="test",
        fingerprint=title,
        title=title,
        url=f"https://example.test/{title}",
        quality_score=quality,
        importance_score=importance,
        published_at=published_at,
    )


def test_market_news_supports_ranked_and_latest_sorting():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add_all([
            _row("high-quality-old", .9, .3, now - timedelta(days=2)),
            _row("high-quality-important", .9, .8, now - timedelta(days=3)),
            _row("newest", .7, .1, now),
        ])
        db.commit()

        ranked = list_market_news(20, 0, None, "ranked", db)
        latest = list_market_news(20, 0, None, "latest", db)

    assert [row["title"] for row in ranked["items"]] == [
        "high-quality-important", "high-quality-old", "newest",
    ]
    assert [row["title"] for row in latest["items"]] == [
        "newest", "high-quality-old", "high-quality-important",
    ]
