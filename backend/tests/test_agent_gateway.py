from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.models import Portfolio, StockDiscoveryRun, User


@pytest.fixture
def db():
    # StaticPool + check_same_thread=False: TestClient serves requests from
    # another thread against this one in-memory database.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def owner(db):
    user = User(username="gateway-user", password_hash="x", role="user", status="active")
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="持仓", base_currency="USD")
    db.add(portfolio); db.commit()
    return user, portfolio


@pytest.fixture
def client(db, monkeypatch):
    from app.database import get_db
    from app.config import get_settings
    # Deliberately NOT a context manager: entering it would run the full
    # startup lifespan against this minimal SQLite schema.
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setenv("AGENT_GATEWAY_TOKEN", "test-token")
    get_settings.cache_clear()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def _run(db, owner, **overrides):
    user, portfolio = owner
    from datetime import UTC, datetime
    values = dict(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key=f"gw-{id(owner)}",
        trigger="manual", discovery_mode="pi_agent", status="running",
        stage="pi_planning", requested_at=datetime.now(UTC),
        model_requested="gpt-5.6-sol", portfolio_snapshot_hash="g" * 64,
    )
    values.update(overrides)
    run = StockDiscoveryRun(**values)
    db.add(run); db.commit()
    return run


def test_tools_requires_gateway_token(client):
    response = client.get("/api/agent/v1/tools")
    assert response.status_code == 401


def test_tools_rejects_wrong_token(client):
    response = client.get("/api/agent/v1/tools", headers={"X-Agent-Token": "wrong"})
    assert response.status_code == 401


def test_tools_lists_only_allowlisted_tools(client):
    response = client.get("/api/agent/v1/tools", headers={"X-Agent-Token": "test-token"})
    assert response.status_code == 200
    names = {tool["function"]["name"] for tool in response.json()["tools"]}
    assert "get_portfolio_summary" in names
    assert "get_relevant_user_memories" not in names
    assert "search_web" in names


def test_execute_rejects_tool_outside_allowlist(client, db, owner):
    user, _ = owner
    run = _run(db, owner)
    response = client.post("/api/agent/v1/execute", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": run.id, "user_id": user.id, "tool": "list_user_memories", "arguments": {},
    })
    assert response.status_code == 403


def test_execute_rejects_foreign_run(client, db, owner):
    user, _ = owner
    other = User(username="other-user", password_hash="x", role="user", status="active")
    db.add(other); db.commit()
    run = _run(db, owner)
    response = client.post("/api/agent/v1/execute", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": run.id, "user_id": other.id, "tool": "get_latest_price", "arguments": {"symbol": "AAPL"},
    })
    assert response.status_code == 404


def test_progress_rejects_unknown_user(client, owner):
    response = client.post("/api/agent/v1/progress", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": 1, "user_id": 999999, "event_type": "research_started",
    })
    assert response.status_code == 404


def test_progress_records_event_for_owned_run(client, db, owner):
    from sqlalchemy import select
    from app.models import StockDiscoveryAgentEvent
    run = _run(db, owner)
    response = client.post("/api/agent/v1/progress", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": run.id, "user_id": run.user_id, "event_type": "candidate_discovered",
        "detail": "ANET", "funnel_stats": {"candidates_discovered": 1},
    })
    assert response.status_code == 200
    db.expire_all()
    events = db.scalars(select(StockDiscoveryAgentEvent).where(StockDiscoveryAgentEvent.run_id == run.id)).all()
    assert len(events) == 1
    assert events[0].event_type == "candidate_discovered"
    refreshed = db.get(StockDiscoveryRun, run.id)
    assert refreshed.funnel_stats == {"candidates_discovered": 1}


def test_progress_rejects_invalid_event_type(client, owner):
    user, _ = owner
    response = client.post("/api/agent/v1/progress", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": 1, "user_id": user.id, "event_type": "chain_of_thought_dump",
    })
    assert response.status_code == 422


def test_tools_unknown_scope_is_rejected(client):
    response = client.get("/api/agent/v1/tools?scope=does_not_exist", headers={"X-Agent-Token": "test-token"})
    assert response.status_code == 404


def test_scope_filters_tool_listing(client, monkeypatch):
    from app.ai_tools.scopes import TOOL_SCOPES
    monkeypatch.setitem(TOOL_SCOPES, "test_subset", frozenset({"get_market_context", "search_web"}))
    response = client.get("/api/agent/v1/tools?scope=test_subset", headers={"X-Agent-Token": "test-token"})
    assert response.status_code == 200
    names = {tool["function"]["name"] for tool in response.json()["tools"]}
    assert names == {"get_market_context", "search_web"}
    assert response.json()["scope"] == "test_subset"


def test_execute_enforces_requested_scope(client, db, owner, monkeypatch):
    from app.ai_tools.scopes import TOOL_SCOPES
    monkeypatch.setitem(TOOL_SCOPES, "test_subset", frozenset({"get_market_context"}))
    user, _ = owner
    run = _run(db, owner)
    blocked = client.post("/api/agent/v1/execute", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": run.id, "user_id": user.id, "tool": "get_latest_price",
        "arguments": {"symbol": "AAPL"}, "tool_scope": "test_subset",
    })
    assert blocked.status_code == 403
    unknown = client.post("/api/agent/v1/execute", headers={"X-Agent-Token": "test-token"}, json={
        "run_id": run.id, "user_id": user.id, "tool": "get_latest_price",
        "arguments": {"symbol": "AAPL"}, "tool_scope": "missing_scope",
    })
    assert unknown.status_code == 404
