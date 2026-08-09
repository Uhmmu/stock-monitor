import importlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NewsItem
from app.services.article_fetch import ArticleFetchResult


tasks = importlib.import_module("app.tasks.celery_app")


def _news(request_id: str = "request-1") -> NewsItem:
    return NewsItem(
        ticker="AAPL",
        provider="test",
        fingerprint="fingerprint-1",
        title="Apple reports quarterly results",
        url="https://example.test/article",
        summary="Original provider summary with enough context.",
        ai_summary_status="queued",
        ai_summary_request_id=request_id,
    )


def _database(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(tasks, "SessionLocal", lambda: Session(engine))
    return engine


def _fetch_result(*, success=True):
    return ArticleFetchResult(
        url="https://example.test/article",
        final_url="https://publisher.test/article",
        title="Publisher title",
        content="Full article body " * 30 if success else None,
        method="http" if success else "playwright",
        success=success,
        quality=.9 if success else 0,
        error=None if success else "no content",
        error_code=None if success else "article_body_not_found",
    )


def _analysis(source_quality="high"):
    return {
        "summary_zh": "中文总结",
        "key_points": ["关键事实一", "关键事实二", "关键事实三"],
        "companies": ["Apple"],
        "tickers": ["AAPL"],
        "industries": ["Technology"],
        "event_type": "other",
        "sentiment": "neutral",
        "market_impact": "数据不足",
        "importance": 50,
        "source_quality": source_quality,
        "confidence": .8,
        "facts": ["Apple 公布消息。"],
    }


def test_news_summary_task_persists_result_and_status(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        db.add(item)
        db.commit()
        news_id = item.id

    monkeypatch.setattr(tasks, "fetch_article", lambda _url: _fetch_result())
    monkeypatch.setattr(tasks, "summarize_news", lambda _title, _content, source_quality: (_analysis(source_quality), "gpt-5.6-luna", {}))

    result = tasks.summarize_news_item.run(news_id, "request-1")

    assert result == {"status": "completed", "news_id": news_id}
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.ai_summary_status == "completed"
        assert item.ai_summary == "中文总结"
        assert item.ai_summary_model == "gpt-5.6-luna"
        assert item.ai_summary_version == "news_summary_v1"
        assert item.ai_summary_created_at is not None
        assert item.article_content.startswith("Full article body")
        assert item.content_fetch_method == "http"


def test_news_summary_task_does_not_overwrite_newer_request(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news(request_id="newer-request")
        db.add(item)
        db.commit()
        news_id = item.id

    monkeypatch.setattr(tasks, "summarize_news", lambda *_args: (_ for _ in ()).throw(AssertionError("must not run")))

    assert tasks.summarize_news_item.run(news_id, "older-request")["status"] == "superseded"
    with Session(engine) as db:
        assert db.get(NewsItem, news_id).ai_summary_status == "queued"


def test_news_summary_task_redelivery_does_not_repeat_ai(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        item.ai_summary = "已保存中文摘要"
        item.ai_analysis = _analysis()
        item.ai_summary_status = "completed"
        item.ai_summary_model = "gpt-5.6-luna"
        item.ai_summary_version = tasks.NEWS_SUMMARY_VERSION
        db.add(item)
        db.commit()
        news_id = item.id
    monkeypatch.setattr(tasks, "fetch_article", lambda _url: (_ for _ in ()).throw(AssertionError("must not fetch")))
    monkeypatch.setattr(tasks, "summarize_news", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not call AI")))

    assert tasks.summarize_news_item.run(news_id, "request-1") == {"status": "completed", "news_id": news_id}


def test_news_summary_task_degrades_to_provider_summary(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        db.add(item)
        db.commit()
        news_id = item.id

    captured = {}
    monkeypatch.setattr(tasks, "fetch_article", lambda _url: _fetch_result(success=False))
    monkeypatch.setattr(tasks, "summarize_news", lambda _title, content, source_quality: (captured.update(content=content, source_quality=source_quality) or _analysis(source_quality), "gpt-5.6-luna", {}))

    assert tasks.summarize_news_item.run(news_id, "request-1")["status"] == "degraded"
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.ai_summary_status == "degraded"
        assert item.article_content is None
        assert item.content_fetch_method == "metadata_fallback"
        assert item.content_fetch_error_code == "article_body_not_found"
    assert captured == {"content": "Original provider summary with enough context.", "source_quality": "low"}


def test_news_summary_task_retries_transient_fetch_without_repeating_ai(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        db.add(item)
        db.commit()
        news_id = item.id
    result = _fetch_result(success=False)
    object.__setattr__(result, "error_code", "network_timeout")
    ai_calls = []
    monkeypatch.setattr(tasks, "fetch_article", lambda _url: result)
    monkeypatch.setattr(tasks, "summarize_news", lambda _title, _content, source_quality: (ai_calls.append(1) or _analysis(source_quality), "gpt-5.6-luna", {}))

    assert tasks.summarize_news_item.run(news_id, "request-1")["status"] == "degraded"
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.ai_summary_next_retry_at is not None
        item.ai_summary_status = "queued"
        item.ai_summary_request_id = "request-2"
        db.commit()

    assert tasks.summarize_news_item.run(news_id, "request-2")["status"] == "degraded"
    assert len(ai_calls) == 1


def test_transient_refetch_failure_preserves_existing_article(monkeypatch):
    engine = _database(monkeypatch)
    original = "Previously fetched publisher article " * 30
    fetched_at = datetime(2026, 8, 9, 12, tzinfo=UTC)
    with Session(engine) as db:
        item = _news()
        item.article_content = original
        item.article_content_hash = "existing-hash"
        item.content_final_url = "https://publisher.test/original"
        item.content_fetch_method = "http"
        item.content_fetch_status = "completed"
        item.content_fetch_quality = .9
        item.content_fetched_at = fetched_at
        db.add(item)
        db.commit()
        news_id = item.id
    failed = _fetch_result(success=False)
    object.__setattr__(failed, "error_code", "network_timeout")
    captured = {}
    monkeypatch.setattr(tasks, "fetch_article", lambda _url: failed)
    monkeypatch.setattr(tasks, "summarize_news", lambda _title, content, source_quality: (captured.update(content=content, source_quality=source_quality) or _analysis(source_quality), "gpt-5.6-luna", {}))

    assert tasks.summarize_news_item.run(news_id, "request-1")["status"] == "degraded"
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.article_content == original
        assert item.content_final_url == "https://publisher.test/original"
        assert item.content_fetch_method == "http"
        assert item.content_fetched_at.replace(tzinfo=UTC) == fetched_at
    assert captured == {"content": original, "source_quality": "high"}


def test_news_summary_task_does_not_treat_long_provider_content_as_fetched_article(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        item.raw_content = "Long provider synopsis that is not proven to be the publisher article. " * 30
        db.add(item)
        db.commit()
        news_id = item.id

    captured = {}
    monkeypatch.setattr(tasks, "fetch_article", lambda _url: _fetch_result(success=False))
    monkeypatch.setattr(tasks, "summarize_news", lambda _title, content, source_quality: (captured.update(content=content) or _analysis(source_quality), "gpt-5.6-luna", {}))

    assert tasks.summarize_news_item.run(news_id, "request-1")["status"] == "degraded"
    assert captured["content"] == "Original provider summary with enough context."


def test_news_summary_task_records_ai_failure_for_retry(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        db.add(item); db.commit(); news_id = item.id
    monkeypatch.setattr(tasks, "fetch_article", lambda _url: _fetch_result())
    monkeypatch.setattr(tasks, "summarize_news", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("provider timeout")))

    assert tasks.summarize_news_item.run(news_id, "request-1")["status"] == "failed"
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.ai_summary_status == "failed"
        assert item.ai_summary_next_retry_at is not None


def test_reconciliation_only_claims_yesterday_and_today(monkeypatch):
    engine = _database(monkeypatch)
    now = datetime.now(UTC)
    with Session(engine) as db:
        recent = _news("recent")
        recent.fingerprint = "recent"
        recent.published_at = now - timedelta(hours=2)
        recent.ai_summary_status = "pending"
        old = _news("old")
        old.fingerprint = "old"
        old.published_at = now - timedelta(days=3)
        old.ai_summary_status = "pending"
        db.add_all([recent, old]); db.commit()
        recent_id = recent.id
    queued = []
    monkeypatch.setattr(tasks.summarize_news_item, "apply_async", lambda args, priority: queued.append((args, priority)))

    result = tasks.reconcile_news_enrichment.run()

    assert result["claimed"] == 1
    assert queued[0][0][0] == recent_id


def test_news_enrichment_bounds_follow_market_timezone(monkeypatch):
    monkeypatch.setattr(tasks.settings, "market_timezone", "America/New_York")

    start, end = tasks._news_enrichment_bounds(datetime(2026, 8, 10, 3, 30, tzinfo=UTC))

    assert start == datetime(2026, 8, 8, 4, tzinfo=UTC)
    assert end == datetime(2026, 8, 10, 4, tzinfo=UTC)


def test_news_detail_reads_persisted_result_without_generation(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        item.ai_summary = "已保存中文摘要"
        item.ai_analysis = _analysis()
        item.ai_summary_status = "completed"
        item.article_content = "Persisted publisher article"
        db.add(item); db.commit(); news_id = item.id
        monkeypatch.setattr(tasks, "summarize_news", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("detail must not call AI")))

        from app.api.routes import news_detail
        detail = news_detail(news_id, db)

    assert detail["ai_summary"] == "已保存中文摘要"
    assert detail["article_content"] == "Persisted publisher article"


def test_static_news_routes_precede_numeric_detail_route():
    from app.api.routes import router

    get_paths = [route.path for route in router.routes if "GET" in (getattr(route, "methods", None) or set())]
    detail_index = get_paths.index("/api/news/{news_id}")
    assert get_paths.index("/api/news/archive") < detail_index
    assert get_paths.index("/api/news/weekly") < detail_index
