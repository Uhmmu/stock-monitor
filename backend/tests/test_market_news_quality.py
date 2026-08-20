"""Regression tests for the 2026-08-20 market news fixes.

Covers: market-scope topic hard filter, Yahoo index market feed, Marketaux
incremental market window, Reuters fast-skip article fetch, and provider
diversification of the ranked market news page.
"""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NewsItem, NewsProviderState
from app.services import marketaux
from app.services.article_fetch import fetch_article
from app.services.news import (
    MARKET_INDEX_TICKERS,
    NewsDTO,
    filter_news,
    prepare_news,
)
from app.services.news_store import persist_news


def _dto(**kw) -> NewsDTO:
    base = dict(
        provider="finnhub",
        ticker="__MARKET__",
        scope="market",
        title="Federal Reserve signals rate cut at next FOMC meeting",
        url="https://example.test/fed",
        summary="The Federal Reserve opened the door to an interest rate cut at the upcoming FOMC meeting.",
        published_at=datetime.now(UTC),
    )
    base.update(kw)
    return NewsDTO(**base)


def test_market_scope_rejects_unclassified_company_noise():
    noise_summary = "A short provider blurb without market-level keywords."
    assert filter_news(_dto(title="Fed officials signal rate cut at next FOMC meeting"))
    assert not filter_news(_dto(title="Rundoo Inks $30 Million in Series B Financing", summary=noise_summary))
    assert not filter_news(_dto(title="Sunshine Pictures IPO Day 3 GMP points to listing gain", summary=noise_summary))
    assert not filter_news(_dto(title="LIC gets RBI nod to raise stake in HDFC Bank to nearly 10 percent", summary=noise_summary))


def test_company_scope_still_accepts_unclassified_titles():
    dto = _dto(scope="company", ticker="AAPL", title="Apple event without market keywords",
               summary="A short provider blurb without market-level keywords.")
    assert filter_news(dto)


def test_prepare_news_market_filters_noise_before_persist():
    items = [
        _dto(title="Fed rate cut expectations rise after CPI inflation report"),
        _dto(title="Welspun Living stock to buy today for multibagger returns"),
    ]
    final, stats = prepare_news(items, scope="market", now=datetime.now(UTC), limit=10)
    assert [dto.title for dto in final] == [items[0].title]
    assert stats["accepted"] == 1


def test_market_index_tickers_are_yahoo_style():
    assert "^GSPC" in MARKET_INDEX_TICKERS
    assert all(ticker.startswith("^") for ticker in MARKET_INDEX_TICKERS)


def test_yfinance_market_news_dtos_marks_market_scope(monkeypatch):
    from app.tasks.celery_app import _yfinance_market_news_dtos

    def fake_yf(ticker: str):
        assert ticker in MARKET_INDEX_TICKERS
        return [NewsDTO(provider="yfinance", ticker=ticker, title="Nasdaq composite rallies on tech earnings",
                        url=f"https://example.test/{ticker}")]

    monkeypatch.setattr("app.services.news._yfinance_news_dtos", fake_yf)
    items = _yfinance_market_news_dtos()
    assert items and all(item.scope == "market" for item in items)


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"meta": {"returned": len(self._data)}, "data": self._data}


def _config(**overrides):
    values = {
        "marketaux_enabled": True,
        "marketaux_api_key": "test-token",
        "marketaux_max_requests_per_day": 100,
        "marketaux_batch_size": 5,
        "marketaux_market_requests_reserve": 12,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def test_marketaux_market_news_uses_incremental_window(db):
    previous_success = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
    db.add(NewsProviderState(
        provider="marketaux_market",
        quota_utc_date=date(2026, 8, 19),
        request_count=0,
        next_batch_index=0,
        last_successful_fetch=previous_success,
    ))
    db.commit()
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response([])

    marketaux.fetch_marketaux_market_news(
        db,
        config=_config(),
        now=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        http_get=http_get,
    )

    assert calls, "market request must be dispatched"
    published_after = calls[0][1]["params"]["published_after"]
    assert published_after == previous_success.strftime("%Y-%m-%dT%H:%M:%S")


def test_marketaux_market_news_initial_window_stays_48h(db):
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response([])

    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    marketaux.fetch_marketaux_market_news(
        db,
        config=_config(),
        now=now,
        http_get=http_get,
    )

    published_after = calls[0][1]["params"]["published_after"]
    expected = (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S")
    assert published_after == expected


def test_reuters_articles_skip_extraction_without_network(monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("no HTTP or browser request allowed for reuters.com")

    monkeypatch.setattr("app.services.article_fetch.httpx.get", unexpected_fetch)
    monkeypatch.setattr("app.services.article_fetch._fetch_with_browser", unexpected_fetch)
    for url in (
        "https://www.reuters.com/markets/us/some-story-2026-08-20/",
        "https://reuters.com/business/finance/another-story/",
    ):
        result = fetch_article(url)
        assert not result.success
        assert result.error_code == "quality_blocked"


def test_non_reuters_domains_not_gated():
    from app.services.article_fetch import _is_unfetchable_news_domain

    assert _is_unfetchable_news_domain("https://www.reuters.com/markets/us/story/")
    assert _is_unfetchable_news_domain("https://reuters.com/business/finance/story/")
    assert not _is_unfetchable_news_domain("https://www.cnbc.com/2026/08/20/some-story.html")
    assert not _is_unfetchable_news_domain("https://notreuters.com/story/")


def _market_row(provider: str, title: str, quality: float, published_at: datetime) -> NewsItem:
    return NewsItem(
        ticker="__MARKET__",
        scope="market",
        provider=provider,
        fingerprint=title,
        title=title,
        url=f"https://example.test/{provider}/{title}",
        quality_score=quality,
        importance_score=0.5,
        published_at=published_at,
    )


def test_ranked_market_page_caps_single_provider(db, monkeypatch):
    from app.api.routes import list_market_news

    monkeypatch.setattr("app.services.news_store.archive.append_raw_news", lambda *a: None)
    now = datetime.now(UTC)
    rows = [
        _market_row("finnhub", f"reuters-wire-{index}", 1.0, now - timedelta(minutes=index))
        for index in range(12)
    ] + [
        _market_row("marketaux", f"market-story-{index}", 0.9, now - timedelta(minutes=index))
        for index in range(6)
    ]
    db.add_all(rows)
    db.commit()

    result = list_market_news(20, 0, None, "ranked", db)
    providers = [item["provider"] for item in result["items"]]
    assert providers.count("finnhub") <= 13  # cap = 2/3 of 20
    assert "marketaux" in providers


def test_ranked_market_page_fills_when_one_provider_dominates(db):
    from app.api.routes import list_market_news

    now = datetime.now(UTC)
    db.add_all([_market_row("finnhub", f"wire-{index}", 1.0, now - timedelta(minutes=index)) for index in range(8)])
    db.commit()

    result = list_market_news(20, 0, None, "ranked", db)
    assert len(result["items"]) == 8  # soft quota: never leave a thin page


def test_latest_market_sort_unchanged(db):
    from app.api.routes import list_market_news

    now = datetime.now(UTC)
    db.add_all([
        _market_row("finnhub", "older", 1.0, now - timedelta(hours=2)),
        _market_row("marketaux", "newer", 0.2, now),
    ])
    db.commit()

    result = list_market_news(20, 0, None, "latest", db)
    assert [item["title"] for item in result["items"]] == ["newer", "older"]
