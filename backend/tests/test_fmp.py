from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NewsItem, NewsProviderState
from app.services import fmp
from app.services.news import NewsDTO
from app.services.news_store import persist_news


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://fmp.test/news")
            raise httpx.HTTPStatusError("failed", request=request, response=httpx.Response(self.status_code, request=request))


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def config(**overrides):
    values = {
        "fmp_enabled": True, "fmp_api_key": "secret", "fmp_base_url": "https://fmp.test/stable",
        "fmp_news_batch_size": 2, "fmp_request_timeout_seconds": 15, "fmp_daily_call_limit": 200,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


ARTICLE = {
    "id": 7, "symbol": "AAPL,MSFT", "title": "Apple and Microsoft update", "text": "Details",
    "url": "https://example.test/story", "image": "https://example.test/image.jpg", "site": "Example",
    "publishedDate": "2026-07-22 10:00:00",
}


def test_parses_stock_news_for_multiple_symbols_and_header():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response([ARTICLE])

    rows = fmp.fetch_stock_news(["msft", "aapl"], config=config(), http_get=get)

    assert {row.ticker for row in rows} == {"AAPL", "MSFT"}
    assert all(row.news_type == "article" and row.raw_payload == ARTICLE for row in rows)
    assert calls[0][1]["params"] == {"symbols": "AAPL,MSFT"}
    assert calls[0][1]["headers"] == {"apikey": "secret"}
    assert "apikey" not in calls[0][0]


def test_empty_result_and_press_release_mapping():
    assert fmp.fetch_stock_news(["AAPL"], config=config(), http_get=lambda *args, **kwargs: Response([])) == []
    row = fmp.fetch_press_releases(["AAPL"], config=config(), http_get=lambda *args, **kwargs: Response([{**ARTICLE, "symbol": "AAPL"}]))[0]
    assert row.news_type == "press_release"
    assert row.ticker == "AAPL"


def test_multi_symbol_request_falls_back_to_single_symbol_requests():
    calls = []

    def get(url, **kwargs):
        symbols = kwargs["params"]["symbols"]
        calls.append(symbols)
        if "," in symbols:
            return Response([], 400)
        return Response([{**ARTICLE, "symbol": symbols}])

    rows = fmp.fetch_stock_news(["AAPL", "MSFT"], config=config(), http_get=get)

    assert calls == ["AAPL,MSFT", "AAPL", "MSFT"]
    assert {row.ticker for row in rows} == {"AAPL", "MSFT"}


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_errors_do_not_escape(status):
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        return Response([], status)

    assert fmp.fetch_stock_news(["AAPL"], config=config(), http_get=get) == []
    assert len(calls) == (1 if status == 403 else 3)


def test_timeout_does_not_escape():
    assert fmp.fetch_stock_news(
        ["AAPL"], config=config(), http_get=lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TimeoutException("slow")),
    ) == []


def test_scheduler_fetch_rotates_batches_and_observes_daily_limit(db):
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"]["symbols"])
        return Response([])

    result = fmp.fetch_fmp_news(db, ["A", "B", "C"], config=config(fmp_daily_call_limit=2), now=datetime(2026, 7, 22, tzinfo=UTC), http_get=get)
    blocked = fmp.fetch_fmp_news(db, ["A", "B", "C"], config=config(fmp_daily_call_limit=2), now=datetime(2026, 7, 22, 2, tzinfo=UTC), http_get=get)

    assert result.batch == ("A", "B")
    assert calls == ["A,B", "A,B"]
    assert blocked.skipped == "daily_limit_reached"
    assert db.scalar(select(NewsProviderState)).request_count == 2


def test_fmp_deduplicates_against_existing_provider(db, monkeypatch):
    monkeypatch.setattr("app.services.news_store.archive.append_raw_news", lambda *args: None)
    persist_news(db, "AAPL", date(2026, 7, 22), [NewsDTO(provider="yfinance", ticker="AAPL", title="Old", url="https://example.test/shared")])
    db.commit()
    saved = persist_news(db, "AAPL", date(2026, 7, 22), [NewsDTO(provider="fmp", ticker="AAPL", external_id="fmp-1", title="New", url="https://example.test/shared")])
    assert saved == []
    assert len(db.scalars(select(NewsItem)).all()) == 1


@pytest.mark.parametrize("cfg", [config(fmp_enabled=False), config(fmp_api_key="")])
def test_disabled_provider_never_touches_http_or_quota(db, cfg):
    result = fmp.fetch_fmp_news(db, ["AAPL"], config=cfg, http_get=lambda *args, **kwargs: pytest.fail("HTTP must not be sent"))
    assert result.skipped == "disabled"
    assert db.scalar(select(NewsProviderState)) is None
