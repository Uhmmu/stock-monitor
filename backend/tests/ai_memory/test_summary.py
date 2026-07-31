import asyncio
import json
from types import SimpleNamespace

from app.ai.providers.schemas import ProviderResponse, ProviderUsage
from app.ai_memory.summaries.service import ConversationSummaryService
from app.database import Base
from app.models import AIConversation, AIMessage, User
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_incremental_summary_versions_and_old_snapshot_fallback(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(
        username="summary", password_hash="x", role="user", status="active"
    )
    db.add(user)
    db.flush()
    conversation = AIConversation(user_id=user.id, title="summary")
    db.add(conversation)
    db.flush()
    for role, content in (("user", "分析 MSFT"), ("assistant", "先看基本面")):
        db.add(
            AIMessage(
                user_id=user.id,
                conversation_id=conversation.id,
                role=role,
                status="completed",
                content=content,
            )
        )
    db.commit()

    structured = {
        "conversation_goal": "分析 MSFT",
        "current_topics": ["基本面"],
        "symbols": ["MSFT"],
        "confirmed_user_statements": [],
        "confirmed_facts": [],
        "current_conclusions": [],
        "open_questions": ["估值如何"],
        "planned_actions": [],
        "important_constraints": [],
        "decision_candidates": [],
        "memory_candidates": [],
        "time_sensitive_items": [],
    }

    class Provider:
        async def create_response(self, request):
            return ProviderResponse(
                content=json.dumps(
                    {
                        "summary_text": "用户正在分析 MSFT 的基本面。",
                        "structured_summary": structured,
                    }
                ),
                finish_reason="stop",
                usage=ProviderUsage(input_tokens=20, output_tokens=10),
            )

    monkeypatch.setattr(
        "app.ai_memory.summaries.service.endpoint_for_model",
        lambda model, settings: ("https://provider.test", "key"),
    )
    monkeypatch.setattr(
        "app.ai_memory.summaries.service.get_provider_registry",
        lambda: SimpleNamespace(get=lambda name: Provider()),
    )
    service = ConversationSummaryService(db)
    first = service.request_refresh(conversation.id, user.id, force=True)
    first = asyncio.run(service.process(first.id))
    assert first.status == "completed"
    assert service.current(conversation.id, user.id).id == first.id

    db.add(
        AIMessage(
            user_id=user.id,
            conversation_id=conversation.id,
            role="user",
            status="completed",
            content="继续看估值",
        )
    )
    db.commit()
    second = service.request_refresh(conversation.id, user.id, force=True)
    assert second.from_message_id > first.through_message_id
    second = asyncio.run(service.process(second.id))
    assert second.version == 2 and second.status == "completed"
    assert db.get(type(first), first.id).status == "superseded"

    class InvalidProvider:
        calls = 0

        async def create_response(self, request):
            self.calls += 1
            return ProviderResponse(content="not-json", finish_reason="stop")

    invalid = InvalidProvider()
    monkeypatch.setattr(
        "app.ai_memory.summaries.service.get_provider_registry",
        lambda: SimpleNamespace(get=lambda name: invalid),
    )
    db.add(
        AIMessage(
            user_id=user.id,
            conversation_id=conversation.id,
            role="user",
            status="completed",
            content="这次摘要会失败",
        )
    )
    db.commit()
    failed = service.request_refresh(conversation.id, user.id, force=True)
    failed = asyncio.run(service.process(failed.id))
    assert failed.status == "failed"
    assert invalid.calls == 2
    assert service.current(conversation.id, user.id).id == second.id
    db.close()
