from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NewsItem, NewsProviderState
from app.services import marketaux
from app.services.news import NewsDTO
from app.services.news_store import persist_news


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"meta": {"returned": len(self._data)}, "data": self._data}


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def _config(**overrides):
    values = {
        "marketaux_enabled": True,
        "marketaux_api_key": "test-token",
        "marketaux_max_requests_per_day": 100,
        "marketaux_batch_size": 5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _empty_get(calls):
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response([])

    return get


def test_quota_resets_on_new_utc_day(db):
    db.add(NewsProviderState(
        provider="marketaux",
        quota_utc_date=date(2026, 7, 21),
        request_count=100,
        next_batch_index=0,
    ))
    db.commit()
    calls = []

    result = marketaux.fetch_marketaux_news(
        db,
        ["AAPL"],
        config=_config(),
        now=datetime(2026, 7, 22, 0, 0, tzinfo=UTC),
        http_get=_empty_get(calls),
    )

    state = db.scalar(select(NewsProviderState))
    assert len(calls) == 1
    assert result.usage == 1
    assert state.quota_utc_date == date(2026, 7, 22)
    assert state.request_count == 1


def test_quota_exhausted_skips_http_request(db, caplog):
    db.add(NewsProviderState(
        provider="marketaux",
        quota_utc_date=date(2026, 7, 22),
        request_count=100,
        next_batch_index=0,
    ))
    db.commit()

    def unexpected_get(*args, **kwargs):
        raise AssertionError("HTTP request must not be sent")

    result = marketaux.fetch_marketaux_news(
        db,
        ["AAPL"],
        config=_config(marketaux_max_requests_per_day=250),
        now=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        http_get=unexpected_get,
    )

    assert result.skipped == "daily_quota_exhausted"
    assert result.remaining == 0
    assert "Marketaux daily quota exhausted." in caplog.text


def test_batches_rotate_one_per_execution(db):
    calls = []
    symbols = ["K", "J", "I", "H", "G", "F", "E", "D", "C", "B", "A"]
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)

    for index in range(3):
        marketaux.fetch_marketaux_news(
            db,
            symbols,
            config=_config(),
            now=now + timedelta(hours=2 * index),
            http_get=_empty_get(calls),
        )

    requested = [call[1]["params"]["symbols"] for call in calls]
    assert requested == ["A,B,C,D,E", "F,G,H,I,J", "K"]
    state = db.scalar(select(NewsProviderState))
    assert state.next_batch_index == 0
    assert state.request_count == 3


def test_two_hour_interval_skips_without_incrementing_quota(db):
    calls = []
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)

    first = marketaux.fetch_marketaux_news(
        db,
        ["AAPL", "MSFT"],
        config=_config(),
        now=now,
        http_get=_empty_get(calls),
    )
    skipped = marketaux.fetch_marketaux_news(
        db,
        ["AAPL", "MSFT"],
        config=_config(),
        now=now + timedelta(hours=1, minutes=59),
        http_get=_empty_get(calls),
    )
    due = marketaux.fetch_marketaux_news(
        db,
        ["AAPL", "MSFT"],
        config=_config(),
        now=now + timedelta(hours=2),
        http_get=_empty_get(calls),
    )

    state = db.scalar(select(NewsProviderState))
    assert first.usage == 1
    assert skipped.skipped == "interval_not_elapsed"
    assert skipped.usage == 1
    assert due.usage == 2
    assert len(calls) == 2
    assert state.request_count == 2
    assert marketaux._utc(state.last_execution_at) == now + timedelta(hours=2)


def test_marketaux_deduplicates_by_uuid_then_normalized_url(db):
    rows = [
        {
            "uuid": "uuid-1",
            "title": "Apple launches a product",
            "url": "https://example.com/story?utm_source=feed",
            "published_at": "2026-07-22T10:00:00Z",
            "source": "example.com",
            "entities": [{"symbol": "AAPL", "match_score": 90}],
        },
        {
            "uuid": "uuid-1",
            "title": "Duplicate UUID",
            "url": "https://other.example/duplicate",
            "entities": [{"symbol": "AAPL", "match_score": 80}],
        },
        {
            "uuid": "uuid-2",
            "title": "Duplicate URL",
            "url": "https://example.com/story?fbclid=tracking",
            "entities": [{"symbol": "AAPL", "match_score": 70}],
        },
    ]

    result = marketaux.fetch_marketaux_news(
        db,
        ["AAPL"],
        config=_config(),
        now=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        http_get=lambda *args, **kwargs: _Response(rows),
    )

    assert result.returned == 3
    assert [item.external_id for item in result.items_by_ticker["AAPL"]] == ["uuid-1"]


def test_marketaux_persistence_rejects_duplicate_url_and_uuid(db, monkeypatch):
    monkeypatch.setattr("app.services.news_store.archive.append_raw_news", lambda *args: None)
    first = NewsDTO(
        provider="marketaux",
        ticker="AAPL",
        external_id="uuid-1",
        title="First",
        url="https://example.com/story?utm_source=feed",
    )
    duplicate_url = NewsDTO(
        provider="marketaux",
        ticker="AAPL",
        external_id="uuid-2",
        title="Second",
        url="https://example.com/story?fbclid=tracking",
    )

    saved = persist_news(db, "AAPL", date(2026, 7, 22), [first, duplicate_url])
    db.commit()
    duplicate_uuid = NewsDTO(
        provider="marketaux",
        ticker="AAPL",
        external_id="uuid-1",
        title="Third",
        url="https://other.example/story",
    )
    saved_again = persist_news(db, "AAPL", date(2026, 7, 22), [duplicate_uuid])

    assert len(saved) == 1
    assert saved_again == []
    assert len(db.scalars(select(NewsItem).where(NewsItem.provider == "marketaux")).all()) == 1


def test_marketaux_url_deduplication_applies_across_providers(db, monkeypatch):
    monkeypatch.setattr("app.services.news_store.archive.append_raw_news", lambda *args: None)
    yahoo = NewsDTO(
        provider="yfinance",
        ticker="AAPL",
        title="Already stored",
        url="https://example.com/shared",
    )
    marketaux_dto = NewsDTO(
        provider="marketaux",
        ticker="AAPL",
        external_id="uuid-shared",
        title="Already stored through Marketaux",
        url="https://example.com/shared",
    )

    persist_news(db, "AAPL", date(2026, 7, 22), [yahoo])
    db.commit()
    saved = persist_news(db, "AAPL", date(2026, 7, 22), [marketaux_dto])

    assert saved == []
    assert len(db.scalars(select(NewsItem)).all()) == 1


@pytest.mark.parametrize(
    "config",
    [
        _config(marketaux_enabled=False),
        _config(marketaux_api_key=""),
    ],
)
def test_disabled_provider_never_touches_http_or_quota(db, config):
    def unexpected_get(*args, **kwargs):
        raise AssertionError("HTTP request must not be sent")

    result = marketaux.fetch_marketaux_news(
        db,
        ["AAPL"],
        config=config,
        http_get=unexpected_get,
    )

    assert result.skipped == "disabled"
    assert db.scalar(select(NewsProviderState)) is None
