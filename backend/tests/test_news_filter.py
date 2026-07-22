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


def test_company_keeps_recent_long_term_news_but_market_does_not():
    old = datetime.now(UTC) - timedelta(days=8)
    assert filter_news(_dto(published_at=old))
    assert not filter_news(_dto(scope="market", published_at=old))


def test_drops_blacklisted_source():
    assert not filter_news(_dto(source="Stocktwits"))


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
    assert not is_blacklisted_news_source(source)
    assert filter_news(_dto(source=source))


def test_source_normalization_uses_canonical_domain_and_domain_boundary():
    assert normalize_news_source("https://www.seekingalpha.com/") == "seekingalpha.com"
    assert normalize_news_source("Seeking Alpha") == "seekingalpha.com"
    assert normalize_news_source("news.seekingalpha.com") == "news.seekingalpha.com"
    assert not is_blacklisted_news_source("notseekingalpha.com")
    assert filter_news(_dto(source="notseekingalpha.com"))


def test_marketaux_uses_the_same_quality_ranking_pipeline():
    dto = _dto(
        provider="marketaux",
        source="news.seekingalpha.com",
        title="3 stocks to buy now with technical analysis",
        published_at=datetime.now(UTC) - timedelta(days=7),
    )
    assert filter_news(dto)


def test_keeps_low_quality_title_for_downranking_not_hard_deletion():
    assert filter_news(_dto(title="3 stocks to buy now"))
    assert filter_news(_dto(title="AAPL technical analysis for traders"))


def test_keeps_informative_title_when_summary_is_short():
    assert filter_news(_dto(summary="too short", raw_content=None))


def test_missing_published_at_not_dropped_by_age():
    assert filter_news(_dto(published_at=None))


def test_market_time_window_is_shorter():
    assert not filter_news(_dto(scope="market", published_at=datetime.now(UTC) - timedelta(hours=80)))
