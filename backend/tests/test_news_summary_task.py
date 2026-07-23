import importlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NewsItem


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


def test_news_summary_task_persists_result_and_status(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        db.add(item)
        db.commit()
        news_id = item.id

    monkeypatch.setattr(tasks, "fetch_article_text", lambda _url: "Full article body " * 30)
    monkeypatch.setattr(tasks, "summarize_news", lambda _title, _content: ("中文总结", "fast-model"))

    result = tasks.summarize_news_item.run(news_id, "request-1")

    assert result == {"status": "completed", "news_id": news_id}
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.ai_summary_status == "completed"
        assert item.ai_summary == "中文总结"
        assert item.ai_summary_model == "fast-model"
        assert item.ai_summary_created_at is not None
        assert item.raw_content.startswith("Full article body")


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


def test_news_summary_task_records_failure_for_retry(monkeypatch):
    engine = _database(monkeypatch)
    with Session(engine) as db:
        item = _news()
        db.add(item)
        db.commit()
        news_id = item.id

    monkeypatch.setattr(tasks, "fetch_article_text", lambda _url: None)
    monkeypatch.setattr(tasks, "summarize_news", lambda *_args: (_ for _ in ()).throw(TimeoutError("provider timeout")))

    assert tasks.summarize_news_item.run(news_id, "request-1")["status"] == "failed"
    with Session(engine) as db:
        item = db.get(NewsItem, news_id)
        assert item.ai_summary_status == "failed"
        assert "TimeoutError" in item.ai_summary_last_error
