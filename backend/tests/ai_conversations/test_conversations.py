import asyncio
import importlib
from types import SimpleNamespace

import pytest
from app.ai.conversations.router import router as conversation_router
from app.ai.conversations.runtime import ConversationRuntimeRegistry
from app.ai.conversations.schemas import (
    ConversationCreateRequest,
    ConversationMessageCreateRequest,
    ConversationUpdateRequest,
    RegenerateRequest,
)
from app.ai.conversations.service import ConversationService
from app.ai.enums import AIErrorCode
from app.ai.exceptions import AIError
from app.ai.schemas import (
    AIRespondResponse,
    AIStreamEvent,
    AIUsageSummary,
    Citation,
)
from app.ai.schemas import (
    AIToolCallRecord as ToolRecord,
)
from app.ai_rich_content.schemas import MarkdownPart, RichContentDocument
from app.auth import create_token
from app.database import Base, get_db
from app.models import (
    AIConversation,
    AIMessage,
    AIMessageCitation,
    AIToolCallRecord,
    ExternalSearchRun,
    ExternalSearchRunEvent,
    Portfolio,
    User,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class FakeOrchestrator:
    def __init__(self):
        self.histories = []

    def result(self):
        return AIRespondResponse(
            request_id="request",
            response_id="provider-response",
            answer="基于已存新闻的回答。[S1]",
            status="completed",
            citations=[Citation(key="S1", source_id="news:1", title="Stored news", source_type="news", url="https://example.test/news")],
            tool_calls=[ToolRecord(
                tool_call_id="call-1",
                tool="get_latest_news",
                status="success",
                summary="读取 1 条新闻",
                returned_item_count=1,
                normalized_arguments={"symbol": "MSFT"},
                arguments_hash="a" * 64,
            )],
            usage=AIUsageSummary(input_tokens=10, output_tokens=8, total_tokens=18, tool_calls=1),
        )

    async def respond(self, **kwargs):
        self.histories.append(kwargs.get("history") or [])
        return self.result()

    async def stream(self, **kwargs):
        self.histories.append(kwargs.get("history") or [])
        result = self.result()
        yield AIStreamEvent(type="response.started", data={"request_id": "request"})
        yield AIStreamEvent(type="context.ready", data={"selected_tools": ["get_latest_news"]})
        yield AIStreamEvent(type="tool.started", data={"tool_call_id": "call-1", "tool": "get_latest_news", "display_name": "正在读取最新新闻"})
        yield AIStreamEvent(type="tool.completed", data=result.tool_calls[0].model_dump(mode="json"))
        yield AIStreamEvent(type="response.delta", data={"delta": result.answer})
        yield AIStreamEvent(type="citation.map", data={"citations": [item.model_dump(mode="json") for item in result.citations]})
        yield AIStreamEvent(type="response.completed", data={
            "status": "completed",
            "answer": result.answer,
            "response_id": result.response_id,
            "tool_calls": [item.model_dump(mode="json") for item in result.tool_calls],
            "usage": result.usage.model_dump(mode="json"),
        }, persistence={"tool_calls": result.tool_calls})


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, Portfolio.__table__, AIConversation.__table__, AIMessage.__table__,
        AIMessageCitation.__table__, AIToolCallRecord.__table__, ExternalSearchRun.__table__,
        ExternalSearchRunEvent.__table__,
    ])
    session = Session(engine)
    yield session
    session.close()


def user(db, name):
    item = User(username=name, password_hash="x", status="active", role="user")
    db.add(item); db.commit(); db.refresh(item)
    return item


def test_conversation_crud_ownership_soft_delete_and_restore(db):
    owner = user(db, "owner")
    outsider = user(db, "outsider")
    service = ConversationService(db, FakeOrchestrator(), runtime=ConversationRuntimeRegistry())
    conversation = service.create_conversation(owner.id, ConversationCreateRequest(active_symbol="msft"), request_id="r")
    assert service.get_conversation(conversation.id, owner.id).active_symbols == ["MSFT"]
    with pytest.raises(AIError) as denied:
        service.get_conversation(conversation.id, outsider.id)
    assert denied.value.code == AIErrorCode.conversation_not_found
    renamed = service.update_conversation(conversation.id, owner.id, body=ConversationUpdateRequest(title="微软研究"), request_id="r")
    assert renamed.title == "微软研究" and renamed.title_source == "user"
    asyncio.run(service.delete_conversation(conversation.id, owner.id, request_id="r"))
    assert service.list_conversations(owner.id, status="deleted", page=1, limit=30).total == 1
    restored = service.restore_conversation(conversation.id, owner.id, request_id="r")
    assert restored.status == "active" and restored.deleted_at is None


def test_non_streaming_persists_history_citations_tools_and_regenerate(db):
    owner = user(db, "researcher")
    orchestrator = FakeOrchestrator()
    service = ConversationService(db, orchestrator, runtime=ConversationRuntimeRegistry())
    conversation = service.create_conversation(owner.id, ConversationCreateRequest(), request_id="r")
    principal = SimpleNamespace(id=owner.id)
    first = asyncio.run(service.respond_message(
        conversation.id, principal,
        ConversationMessageCreateRequest(message="第一问", stream=False),
        request_id="r1",
    ))
    assert first.conversation.title == "第一问"
    assert first.assistant_message.status == "completed"
    assert first.assistant_message.citation_count == 1
    assert first.assistant_message.tool_call_count == 1
    assert first.assistant_message.citations[0].url == "https://example.test/news"
    stored_tool = db.query(AIToolCallRecord).filter_by(assistant_message_id=first.assistant_message.id).one()
    assert stored_tool.normalized_arguments == {"symbol": "MSFT"}
    assert stored_tool.arguments_hash == "a" * 64
    second = asyncio.run(service.respond_message(
        conversation.id, principal,
        ConversationMessageCreateRequest(message="继续分析", stream=False),
        request_id="r2",
    ))
    assert [message.role for message in orchestrator.histories[-1]] == ["user", "assistant"]
    regenerated = asyncio.run(service.respond_regenerate(
        conversation.id, int(second.assistant_message.id), principal,
        RegenerateRequest(stream=False), request_id="r3",
    ))
    assert regenerated.assistant_message.generation_index == 2
    page = service.list_messages(conversation.id, owner.id, page=1, limit=20)
    assert len(page.items) == 5
    assert sum(item.role == "assistant" for item in page.items) == 3
    asyncio.run(service.respond_message(
        conversation.id, principal,
        ConversationMessageCreateRequest(message="下一轮", stream=False),
        request_id="r4",
    ))
    assert [message.content for message in orchestrator.histories[-1]] == [
        "第一问", "基于已存新闻的回答。[S1]", "继续分析", "基于已存新闻的回答。[S1]",
    ]


def test_rich_content_persists_with_markdown_fallback_and_is_opt_in(db):
    owner = user(db, "rich-researcher")

    class RichOrchestrator(FakeOrchestrator):
        def result(self):
            result = super().result()
            document = RichContentDocument(
                schema_version=1,
                parts=[
                    MarkdownPart(
                        part_id="markdown_0",
                        content="基于已存新闻的回答。[S1]",
                    )
                ],
                fallback_markdown="基于已存新闻的回答。[S1]",
            )
            return result.model_copy(
                update={
                    "answer": document.fallback_markdown,
                    "rich_content": document,
                }
            )

    service = ConversationService(
        db,
        RichOrchestrator(),
        runtime=ConversationRuntimeRegistry(),
    )
    conversation = service.create_conversation(
        owner.id,
        ConversationCreateRequest(),
        request_id="rich",
    )
    pair = asyncio.run(
        service.respond_message(
            conversation.id,
            SimpleNamespace(id=owner.id),
            ConversationMessageCreateRequest(message="富内容", stream=False),
            request_id="rich",
        )
    )
    stored = db.get(AIMessage, pair.assistant_message.id)
    assert stored is not None
    assert stored.content == "基于已存新闻的回答。[S1]"
    assert stored.content_schema_version == 1
    assert stored.content_format == "rich_markdown"
    assert stored.content_parts["schema_version"] == 1

    legacy = service.get_message(
        conversation.id,
        int(pair.assistant_message.id),
        owner.id,
        rich_content=False,
    )
    rich = service.get_message(
        conversation.id,
        int(pair.assistant_message.id),
        owner.id,
        rich_content=True,
    )
    assert legacy.content_parts is None
    assert legacy.model_dump(exclude_none=True).get("content_parts") is None
    assert rich.content_parts is not None
    assert rich.content_parts.fallback_markdown == stored.content


def test_stream_has_single_terminal_and_persists_before_completion(db):
    owner = user(db, "streamer")
    service = ConversationService(db, FakeOrchestrator(), runtime=ConversationRuntimeRegistry())
    conversation = service.create_conversation(owner.id, ConversationCreateRequest(), request_id="r")

    async def collect():
        return [event async for event in service.stream_message(
            conversation.id, SimpleNamespace(id=owner.id),
            ConversationMessageCreateRequest(message="流式问题"), request_id="stream",
        )]

    events = asyncio.run(collect())
    types = [event.type for event in events]
    assert types[0:2] == ["conversation.started", "message.created"]
    assert types[-2:] == ["message.persisted", "response.completed"]
    assert sum(value in {"response.completed", "error"} for value in types) == 1
    assistant_id = events[0].data["assistant_message_id"]
    persisted = service.get_message(conversation.id, assistant_id, owner.id)
    assert persisted.status == "completed" and persisted.content.endswith("[S1]")


def test_stop_cancels_process_local_generation_and_keeps_status(db):
    owner = user(db, "stopper")
    started = asyncio.Event()

    class SlowOrchestrator(FakeOrchestrator):
        async def stream(self, **kwargs):
            yield AIStreamEvent(type="response.started", data={})
            started.set()
            await asyncio.Event().wait()

    service = ConversationService(db, SlowOrchestrator(), runtime=ConversationRuntimeRegistry())
    conversation = service.create_conversation(owner.id, ConversationCreateRequest(), request_id="r")

    async def scenario():
        async def consume():
            return [event async for event in service.stream_message(
                conversation.id, SimpleNamespace(id=owner.id),
                ConversationMessageCreateRequest(message="请停止"), request_id="r",
            )]
        task = asyncio.create_task(consume())
        await started.wait()
        stopped = await service.stop_generation(conversation.id, owner.id, request_id="stop")
        await asyncio.gather(task, return_exceptions=True)
        return stopped

    stopped = asyncio.run(scenario())
    assert stopped.stopped and stopped.assistant_message_id is not None
    message = service.get_message(conversation.id, stopped.assistant_message_id, owner.id)
    assert message.status == "cancelled"


def test_router_crud_stream_ownership_and_openapi(db, monkeypatch):
    owner = user(db, "api-owner")
    outsider = user(db, "api-outsider")
    app = FastAPI()
    app.include_router(conversation_router)

    def session_override():
        yield db

    app.dependency_overrides[get_db] = session_override
    router_module = importlib.import_module("app.ai.conversations.router")
    monkeypatch.setattr(router_module, "_orchestrator", lambda gw: FakeOrchestrator())
    client = TestClient(app)
    owner_headers = {"Authorization": f"Bearer {create_token(owner.id)}"}
    outsider_headers = {"Authorization": f"Bearer {create_token(outsider.id)}"}

    created = client.post("/api/ai/v1/conversations", headers=owner_headers, json={"active_symbol": "MSFT"})
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    assert client.get(f"/api/ai/v1/conversations/{conversation_id}", headers=outsider_headers).status_code == 404
    injected = client.post("/api/ai/v1/conversations", headers=owner_headers, json={"user_id": outsider.id})
    assert injected.status_code == 422 and injected.json()["error"]["code"] == "AI_REQUEST_INVALID"

    with client.stream("POST", f"/api/ai/v1/conversations/{conversation_id}/messages", headers=owner_headers, json={"message": "分析新闻", "stream": True}) as response:
        stream_text = "".join(response.iter_text())
    assert response.status_code == 200
    assert stream_text.count("event: response.completed") == 1
    assert "event: message.persisted" in stream_text and "reasoning" not in stream_text
    assert "normalized_arguments" not in stream_text and "arguments_hash" not in stream_text
    messages = client.get(f"/api/ai/v1/conversations/{conversation_id}/messages", headers=owner_headers).json()["items"]
    assert len(messages) == 2 and messages[-1]["citations"][0]["key"] == "S1"
    regenerated = client.post(
        f"/api/ai/v1/conversations/{conversation_id}/messages/{messages[-1]['id']}/regenerate",
        headers=owner_headers,
        json={"stream": False},
    )
    assert regenerated.status_code == 200 and regenerated.json()["assistant_message"]["generation_index"] == 2
    assert client.post(f"/api/ai/v1/conversations/{conversation_id}/archive", headers=owner_headers).json()["status"] == "archived"
    assert client.delete(f"/api/ai/v1/conversations/{conversation_id}", headers=owner_headers).status_code == 204
    assert client.post(f"/api/ai/v1/conversations/{conversation_id}/restore", headers=owner_headers).json()["status"] == "active"
    assert "/api/ai/v1/conversations/{conversation_id}/messages" in app.openapi()["paths"]
