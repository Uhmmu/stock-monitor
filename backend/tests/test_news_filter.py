from datetime import UTC, datetime, timedelta

import pytest

from app.services import news
from app.services.news import NewsDTO, filter_news, is_blacklisted_news_source, normalize_news_source


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


@pytest.mark.parametrize("source", [
    "Seeking Alpha",
    "seeking alpha",
    "https://seekingalpha.com",
    "www.seekingalpha.com",
    "news.seekingalpha.com",
    "seekingalpha.com",
    "HTTPS://WWW.SEEKINGALPHA.COM/",
])
def test_blacklisted_source_normalizes_display_names_domains_and_subdomains(source):
    assert is_blacklisted_news_source(source)
    assert not filter_news(_dto(source=source))


def test_source_normalization_uses_canonical_domain_and_domain_boundary():
    assert normalize_news_source("https://www.seekingalpha.com/") == "seekingalpha.com"
    assert normalize_news_source("Seeking Alpha") == "seekingalpha.com"
    assert normalize_news_source("news.seekingalpha.com") == "news.seekingalpha.com"
    assert not is_blacklisted_news_source("notseekingalpha.com")
    assert filter_news(_dto(source="notseekingalpha.com"))


def test_marketaux_bypasses_general_quality_filtering():
    dto = _dto(
        provider="marketaux",
        source="news.seekingalpha.com",
        title="3 stocks to buy now with technical analysis",
        published_at=datetime.now(UTC) - timedelta(days=7),
    )
    assert filter_news(dto)


def test_drops_blacklisted_title_keyword():
    assert not filter_news(_dto(title="3 stocks to buy now"))
    assert not filter_news(_dto(title="AAPL technical analysis for traders"))


def test_drops_short_body():
    assert not filter_news(_dto(summary="too short", raw_content=None))


def test_missing_published_at_not_dropped_by_age():
    assert filter_news(_dto(published_at=None))
