import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config import get_settings
from app.database import Base
from app.external_search.deep_search.service import DeepSearchService
from app.external_search.enums import AgentRunStatus, DeepSearchEffort, WebAccessMode
from app.external_search.exceptions import ExternalSearchError
from app.external_search.providers.mock import MockExternalSearchProvider
from app.external_search.schemas import AgentRun, ExternalGroundingSource
from app.models import AIConversation, AIMessage, ExternalSearchRun, User
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        del record
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(username="deep-user", password_hash="x", role="user", status="active")
    other = User(username="other-user", password_hash="x", role="user", status="active")
    session.add_all([user, other]); session.flush()
    conversation = AIConversation(user_id=user.id, title="research", active_symbols=[], web_access_mode="deep_medium")
    session.add(conversation); session.flush()
    user_message = AIMessage(conversation_id=conversation.id, user_id=user.id, role="user", status="completed", content="question", web_access_mode="deep_medium")
    assistant = AIMessage(conversation_id=conversation.id, user_id=user.id, role="assistant", status="pending", content="", web_access_mode="deep_medium")
    session.add_all([user_message, assistant]); session.commit()
    yield session, user, other, conversation, user_message, assistant
    session.close(); engine.dispose()


@pytest.fixture(autouse=True)
def exa_settings():
    settings = get_settings()
    names = [
        "exa_enabled", "exa_deep_search_enabled", "exa_api_key", "exa_allowed_roles",
        "exa_deep_minimal_enabled", "exa_deep_low_enabled", "exa_deep_medium_enabled",
        "exa_deep_high_enabled", "exa_deep_xhigh_enabled",
        "exa_max_cost_per_ai_request_usd", "exa_deep_max_active_runs_per_user",
        "exa_deep_max_active_runs_global", "exa_deep_high_confirmation_required",
        "exa_deep_xhigh_confirmation_required",
    ]
    previous = {name: getattr(settings, name) for name in names}
    settings.exa_enabled = True
    settings.exa_deep_search_enabled = True
    settings.exa_api_key = "test-only"
    settings.exa_allowed_roles = "user,admin"
    for effort in DeepSearchEffort:
        setattr(settings, f"exa_deep_{effort.value}_enabled", True)
    settings.exa_max_cost_per_ai_request_usd = 1.25
    settings.exa_deep_max_active_runs_per_user = 1
    settings.exa_deep_max_active_runs_global = 2
    settings.exa_deep_high_confirmation_required = True
    settings.exa_deep_xhigh_confirmation_required = True
    yield
    for name, value in previous.items():
        setattr(settings, name, value)


def create(service, db_data, *, mode=WebAccessMode.deep_medium, confirmation=False, generation=1):
    _, user, _, conversation, user_message, assistant = db_data
    return asyncio.run(service.create_run(
        user_id=user.id, role=user.role, conversation_id=conversation.id,
        user_message_id=user_message.id, assistant_message_id=assistant.id,
        query="Public MSFT policy evidence", mode=mode, generation_index=generation,
        confirmation=confirmation,
    ))


def test_create_is_idempotent_and_persists_no_raw_query(db):
    session, _, _, _, _, assistant = db
    provider = MockExternalSearchProvider()
    service = DeepSearchService(session, provider=provider)
    first = create(service, db)
    second = create(service, db)
    assert first.id == second.id
    assert session.query(ExternalSearchRun).count() == 1
    assert first.query_preview_safe is None
    assert first.query_hash and "Public MSFT" not in first.query_hash
    session.refresh(assistant)
    assert assistant.deep_search_run_id == first.id
    assert first.provider_run_id.startswith("mock-run-")


@pytest.mark.parametrize("mode", [WebAccessMode.deep_high, WebAccessMode.deep_xhigh])
def test_high_and_xhigh_require_confirmation(db, mode):
    service = DeepSearchService(db[0], provider=MockExternalSearchProvider())
    with pytest.raises(ExternalSearchError) as raised:
        create(service, db, mode=mode)
    assert raised.value.code == "DEEP_SEARCH_CONFIRMATION_REQUIRED"
    row = create(service, db, mode=mode, confirmation=True)
    assert row.effort == mode.effort.value


def test_disabled_effort_and_role_are_rejected_before_provider_charge(db):
    settings = get_settings(); settings.exa_deep_low_enabled = False
    service = DeepSearchService(db[0], provider=MockExternalSearchProvider())
    with pytest.raises(ExternalSearchError) as raised:
        create(service, db, mode=WebAccessMode.deep_low)
    assert raised.value.code == "DEEP_SEARCH_NOT_ALLOWED"
    settings.exa_deep_low_enabled = True
    with pytest.raises(ExternalSearchError) as raised:
        asyncio.run(service.create_run(
            user_id=db[1].id, role="guest", conversation_id=db[3].id,
            user_message_id=db[4].id, assistant_message_id=db[5].id,
            query="public question", mode=WebAccessMode.deep_minimal,
        ))
    assert raised.value.code == "DEEP_SEARCH_NOT_ALLOWED"


def test_sync_completed_saves_output_grounding_usage_cost_and_user_isolation(db):
    session, user, other, _, _, assistant = db
    provider = MockExternalSearchProvider()
    service = DeepSearchService(session, provider=provider)
    row = create(service, db)
    now = datetime.now(UTC)
    provider.runs[row.provider_run_id] = AgentRun(
        id=row.provider_run_id, status=AgentRunStatus.completed,
        stop_reason="schema_satisfied", output_text="Verified public research",
        output_structured={"executive_summary": "ok"},
        grounding=[ExternalGroundingSource(
            source_id="web:1", title="SEC", url="https://sec.gov/a",
            normalized_url="https://sec.gov/a", domain="sec.gov", retrieved_at=now,
            authority_tier="official",
        )],
        usage={"agentComputeUnits": 1, "searches": 2}, cost_usd=Decimal("0.123"),
        completed_at=now,
    )
    completed = asyncio.run(service.sync_run(row.public_id, user.id))
    assert completed.status == "completed"
    assert completed.output_text == "Verified public research"
    assert completed.output_structured == {"executive_summary": "ok"}
    assert completed.grounding[0]["authority_tier"] == "official"
    assert completed.cost_usd == Decimal("0.123")
    assert completed.cost_estimated is False
    session.refresh(assistant)
    assert assistant.external_search_call_count == 1
    assert float(assistant.external_search_cost_usd) == pytest.approx(0.123)
    with pytest.raises(ExternalSearchError) as raised:
        asyncio.run(service.sync_run(row.public_id, other.id))
    assert raised.value.code == "DEEP_SEARCH_RUN_NOT_FOUND" and raised.value.status_code == 404


def test_cancel_is_idempotent_and_updates_assistant(db):
    session, user, _, _, _, assistant = db
    provider = MockExternalSearchProvider(); service = DeepSearchService(session, provider=provider)
    row = create(service, db)
    cancelled = asyncio.run(service.cancel_run(row.public_id, user.id))
    again = asyncio.run(service.cancel_run(row.public_id, user.id))
    assert cancelled.status == again.status == "cancelled"
    session.refresh(assistant)
    assert assistant.status == "cancelled"
    assert assistant.error_code == "DEEP_SEARCH_CANCELLED"


def test_invalid_non_deep_mode_and_budget_reject_before_create(db):
    service = DeepSearchService(db[0], provider=MockExternalSearchProvider())
    with pytest.raises(ExternalSearchError) as raised:
        create(service, db, mode=WebAccessMode.search)
    assert raised.value.code == "DEEP_SEARCH_INVALID_EFFORT"
    get_settings().exa_max_cost_per_ai_request_usd = 0.05
    with pytest.raises(ExternalSearchError) as raised:
        create(service, db, mode=WebAccessMode.deep_medium)
    assert raised.value.code == "DEEP_SEARCH_BUDGET_EXCEEDED"
