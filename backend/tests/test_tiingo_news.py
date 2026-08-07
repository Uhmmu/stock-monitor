from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NewsItem
from app.services import news_tiingo
from app.services.news import NewsDTO, deduplicate, filter_news
from app.services.news_store import persist_news


class _Response:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", news_tiingo.ENDPOINT)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._payload


def _config(**overrides):
    values = {
        "tiingo_news_enabled": True,
        "tiingo_api_token": "unit-test-token",
        "tiingo_news_batch_size": 2,
        "tiingo_news_limit": 50,
        "tiingo_news_lookback_hours": 48,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _article(identifier="story-1", *, tickers=None, title="NVIDIA expands AI capacity"):
    return {
        "id": identifier,
        "title": title,
        "url": "https://www.example.com/story/?utm_source=tiingo",
        "description": "A provider description long enough to retain.",
        "publishedDate": "2026-08-07T10:00:00Z",
        "crawlDate": "2026-08-07T10:05:00Z",
        "source": "Reuters",
        "tickers": tickers or ["NVDA"],
        "tags": ["AI", "Semiconductors"],
    }


def test_tiingo_normalizes_publish_and_crawl_metadata_without_conflating_them():
    result = news_tiingo.fetch_tiingo_news(
        ["NVDA"],
        config=_config(),
        now=datetime(2026, 8, 7, 12, tzinfo=UTC),
        http_get=lambda *args, **kwargs: _Response([_article()]),
    )

    dto = result.items_by_ticker["NVDA"][0]
    assert dto.published_at == datetime(2026, 8, 7, 10, tzinfo=UTC)
    assert dto.crawl_at == datetime(2026, 8, 7, 10, 5, tzinfo=UTC)
    assert dto.published_at != dto.crawl_at
    assert dto.symbols == ["NVDA"]
    assert dto.tags == ["AI", "Semiconductors"]
    assert dto.raw_payload["crawlDate"] == "2026-08-07T10:05:00Z"


def test_tiingo_duplicate_wire_rows_union_tickers_and_tags():
    first = _article("same", tickers=["NVDA"], title="NVIDIA expands AI capacity")
    second = _article("same", tickers=["AMD"], title="NVIDIA expands AI capacity")
    second["tags"] = ["Earnings"]
    result = news_tiingo.fetch_tiingo_news(
        ["NVDA", "AMD"],
        config=_config(tiingo_news_batch_size=10),
        http_get=lambda *args, **kwargs: _Response([first, second]),
    )

    assert len(result.items_by_ticker["NVDA"]) == 1
    assert result.items_by_ticker["NVDA"][0].symbols == ["AMD", "NVDA"]
    assert result.items_by_ticker["NVDA"][0].tags == ["AI", "Earnings", "Semiconductors"]


def test_tiingo_requests_only_tracked_symbols_in_deterministic_batches():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        symbols = kwargs["params"]["tickers"].split(",")
        return _Response([_article(identifier=f"story-{symbols[0]}", tickers=symbols)])

    result = news_tiingo.fetch_tiingo_news(
        ["MSFT", "NVDA", "AAPL"],
        config=_config(tiingo_news_batch_size=2),
        now=datetime(2026, 8, 7, 12, tzinfo=UTC),
        http_get=get,
    )

    assert [call[1]["params"]["tickers"] for call in calls] == ["AAPL,MSFT", "NVDA"]
    assert result.batches == (("AAPL", "MSFT"), ("NVDA",))
    assert set(result.items_by_ticker) == {"AAPL", "MSFT", "NVDA"}
    assert all("unit-test-token" not in str(error) for error in result.errors)


def test_tiingo_disabled_provider_never_touches_http():
    def unexpected_get(*args, **kwargs):
        raise AssertionError("disabled Tiingo must not send HTTP")

    result = news_tiingo.fetch_tiingo_news(
        ["AAPL"], config=_config(tiingo_news_enabled=False), http_get=unexpected_get
    )
    assert result.skipped == "disabled"


def test_malformed_provider_url_is_filtered_without_aborting_batch():
    dto = NewsDTO(provider="tiingo", ticker="AAPL", title="Apple reports quarterly results", url="https://[bad")
    assert filter_news(dto) is False


def test_tiingo_partial_failure_keeps_successful_batches_and_classifies_status(caplog):
    responses = iter([_Response([_article(tickers=["AAPL"])]), _Response(status_code=429), _Response(status_code=403)])

    result = news_tiingo.fetch_tiingo_news(
        ["AAPL", "MSFT", "NVDA"],
        config=_config(tiingo_news_batch_size=1),
        now=datetime(2026, 8, 7, 12, tzinfo=UTC),
        http_get=lambda *args, **kwargs: next(responses),
    )

    assert result.partial_failure
    assert len(result.items_by_ticker["AAPL"]) == 1
    assert result.failed_batches == (("MSFT",), ("NVDA",))
    assert result.errors == ("HTTP 429", "HTTP 403")
    assert result.skipped is None
    assert "unit-test-token" not in caplog.text


@pytest.mark.parametrize("status", [401, 403, 429])
def test_tiingo_auth_and_rate_limit_failures_do_not_raise(status):
    result = news_tiingo.fetch_tiingo_news(
        ["AAPL"],
        config=_config(),
        http_get=lambda *args, **kwargs: _Response(status_code=status),
    )
    assert result.skipped == "request_failed"
    assert result.errors == (f"HTTP {status}",)


def test_tiingo_all_batches_failed_is_not_reported_as_partial():
    result = news_tiingo.fetch_tiingo_news(
        ["AAPL", "MSFT"],
        config=_config(tiingo_news_batch_size=1),
        http_get=lambda *args, **kwargs: _Response(status_code=503),
    )
    assert result.partial_failure is False
    assert result.skipped == "request_failed"


def test_tiingo_invalid_payload_is_isolated_as_request_failure():
    result = news_tiingo.fetch_tiingo_news(
        ["AAPL"], config=_config(), http_get=lambda *args, **kwargs: _Response({"unexpected": True})
    )
    assert result.skipped == "request_failed"
    assert result.errors == ("ValueError",)


def test_cross_provider_url_and_title_dedupe_merges_metadata():
    published = datetime(2026, 8, 7, 10, tzinfo=UTC)
    first = NewsDTO(
        provider="yahoo",
        ticker="NVDA",
        title="NVIDIA expands AI capacity",
        url="https://example.com/story",
        external_id="y-1",
        published_at=published,
        symbols=["NVDA"],
        raw_payload={"publisher": "Yahoo"},
    )
    second = NewsDTO(
        provider="tiingo",
        ticker="NVDA",
        title="NVIDIA expands AI capacity - Reuters",
        url="https://www.example.com/story/?utm_medium=feed",
        external_id="t-1",
        published_at=published + timedelta(minutes=5),
        crawl_at=published + timedelta(minutes=7),
        symbols=["NVDA", "AMD"],
        tags=["AI", "Semiconductors"],
        raw_payload={"id": "t-1", "crawlDate": "2026-08-07T10:07:00Z"},
    )

    merged = deduplicate([first, second])

    assert len(merged) == 1
    assert merged[0].provider_sources == ["tiingo", "yahoo"]
    assert merged[0].symbols == ["AMD", "NVDA"]
    assert merged[0].tags == ["AI", "Semiconductors"]
    assert merged[0].crawl_at == published + timedelta(minutes=7)
    assert len(merged[0].raw_payload["_provider_records"]) == 2


def test_title_dedupe_requires_time_window():
    old = NewsDTO(
        provider="yahoo",
        ticker="AAPL",
        title="Apple announces quarterly results",
        url="https://old.example/story",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    recent = NewsDTO(
        provider="tiingo",
        ticker="AAPL",
        title="Apple announces quarterly results",
        url="https://new.example/story",
        published_at=datetime(2026, 8, 7, tzinfo=UTC),
    )
    assert len(deduplicate([old, recent])) == 2


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def test_persistence_enriches_existing_story_with_tiingo_metadata(db, monkeypatch):
    monkeypatch.setattr("app.services.news_store.archive.append_raw_news", lambda *args: None)
    published = datetime(2026, 8, 7, 10, tzinfo=UTC)
    existing = NewsDTO(
        provider="yfinance",
        ticker="NVDA",
        title="NVIDIA expands AI capacity",
        url="https://example.com/story",
        published_at=published,
        symbols=["NVDA"],
        raw_payload={"publisher": "Yahoo"},
    )
    tiingo = NewsDTO(
        provider="tiingo",
        ticker="NVDA",
        title="NVIDIA expands AI capacity - Reuters",
        url="https://www.example.com/story/?utm_source=tiingo",
        external_id="t-1",
        published_at=published + timedelta(minutes=5),
        crawl_at=published + timedelta(minutes=7),
        symbols=["NVDA", "AMD"],
        tags=["AI"],
        raw_payload={"id": "t-1", "crawlDate": "2026-08-07T10:07:00Z"},
    )

    assert len(persist_news(db, "NVDA", date(2026, 8, 7), [existing])) == 1
    db.commit()
    assert persist_news(db, "NVDA", date(2026, 8, 7), [tiingo]) == []

    row = db.scalar(select(NewsItem))
    assert row.provider == "yfinance"
    assert row.canonical_story_id
    assert row.provider_sources == ["tiingo", "yfinance"]
    assert row.provider_metadata["providers"]["tiingo"]["crawl_at"] == "2026-08-07T10:07:00+00:00"
    assert row.symbols == ["AMD", "NVDA"]
    assert row.raw_payload["_news_tags"] == ["AI"]
    assert row.raw_payload["_provider_sources"] == ["tiingo", "yfinance"]
    assert row.raw_payload["_provider_crawl_at"] == "2026-08-07T10:07:00+00:00"
