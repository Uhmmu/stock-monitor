from datetime import UTC, datetime, timedelta

from app.services import news
from app.services.news import NewsDTO, filter_news


def _dto(**kw) -> NewsDTO:
    base = dict(provider="finnhub", ticker="AAPL", title="Apple beats earnings estimates",
                url="https://example.test/a", summary="Apple reported quarterly revenue well above expectations today.")
    base.update(kw)
    return NewsDTO(**base)


def test_keeps_valid_recent_news():
    assert filter_news(_dto(published_at=datetime.now(UTC)))


def test_drops_old_news():
    old = datetime.now(UTC) - timedelta(hours=30)
    assert not filter_news(_dto(published_at=old))


def test_drops_blacklisted_source():
    assert not filter_news(_dto(source="Zacks"))
    assert not filter_news(_dto(source="the motley fool"))


def test_drops_blacklisted_title_keyword():
    assert not filter_news(_dto(title="3 stocks to buy now"))
    assert not filter_news(_dto(title="AAPL technical analysis for traders"))


def test_drops_short_body():
    assert not filter_news(_dto(summary="too short", raw_content=None))


def test_missing_published_at_not_dropped_by_age():
    assert filter_news(_dto(published_at=None))
