import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from app.ai.orchestrator import AIOrchestrator
from app.ai.providers.mock import MockProvider
from app.ai.providers.registry import ProviderRegistry
from app.ai.providers.schemas import (
    ProviderResponse,
    ProviderStreamEvent,
    ProviderToolCall,
)
from app.ai.enums import AIErrorCode
from app.ai.exceptions import ProviderError
from app.ai.router import router
from app.ai.schemas import (
    AIRespondRequest,
    AIRespondResponse,
    AIStreamEvent,
    AIUsageSummary,
)
from app.ai_tools import tool_registry
from app.ai_tools.enums import ResultMode, ToolStatus
from app.ai_tools.schemas import ToolExecutionResult, ToolExecutionStats
from app.auth import create_token
from app.config import get_settings
from app.database import Base, get_db
from app.models import User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class Executor:
    async def execute_many(self, calls, context):
        now = datetime.now(UTC)
        return [ToolExecutionResult(
            tool_call_id="executor", tool_name=call.tool, tool_version="1.0.0", status=ToolStatus.success,
            data={"symbol":call.arguments.get("symbol"),"price":100}, summary="Stored price.",
            sources=[{"source_id":"price:MSFT","title":"MSFT stored price","source_type":"price"}],
            stats=ToolExecutionStats(started_at=now,completed_at=now,duration_ms=1,result_mode=ResultMode.standard,estimated_output_chars=100),
        ) for call in calls]


def configure_mock(provider):
    settings=get_settings(); old=(settings.ai_provider,settings.ai_model,settings.ai_allowed_models,settings.ai_enabled)
    settings.ai_provider="mock"; settings.ai_model="mock-model"; settings.ai_allowed_models="mock-model"; settings.ai_enabled=True
    registry=ProviderRegistry(); registry.register(provider)
    return settings,old,registry


def restore(settings,old):
    settings.ai_provider,settings.ai_model,settings.ai_allowed_models,settings.ai_enabled=old


def test_orchestrator_tool_call_citation_repair_and_stream_events():
    responses=[
        ProviderResponse(tool_calls=[ProviderToolCall(id="c1",name="get_latest_price",arguments={"symbol":"MSFT"})],finish_reason="tool_calls"),
        ProviderResponse(content="价格为 100。[S99]",finish_reason="stop"),
        ProviderResponse(content="价格为 100。[S1]",finish_reason="stop"),
    ]
    provider=MockProvider(responses); settings,old,providers=configure_mock(provider)
    try:
        orchestrator=AIOrchestrator(registry=tool_registry,executor=Executor(),provider_registry=providers)
        result=asyncio.run(orchestrator.respond(request=AIRespondRequest(message="MSFT price",active_symbol="MSFT",stream=False),user=SimpleNamespace(id=1),request_id="req"))
        assert result.answer.startswith("价格为 100。[S1]")
        assert "**信息来源**" in result.answer
        assert result.rich_content is not None
        assert [c.key for c in result.citations]==["S1"]
        assert result.usage.model_rounds==3 and result.tool_calls[0].tool=="get_latest_price"
    finally: restore(settings,old)


def test_orchestrator_falls_back_from_luna_to_haiku():
    class ClaudeMock(MockProvider):
        provider_name = "claude_compatible"

    primary = MockProvider([ProviderResponse(), ProviderResponse()])
    fallback = ClaudeMock([ProviderResponse(content="Haiku 正常回答", finish_reason="stop")])
    settings = get_settings()
    fields = (
        "ai_provider", "ai_model", "ai_allowed_models", "ai_enabled", "ai_api_base",
        "ai_api_key", "translation_base_url", "translation_api_key",
    )
    old = tuple(getattr(settings, field) for field in fields)
    settings.ai_provider = "mock"
    settings.ai_model = "gpt-5.6-luna"
    settings.ai_allowed_models = "gpt-5.6-luna,claude-haiku-4-5-20251001"
    settings.ai_enabled = True
    settings.ai_api_base = "https://gpt.test/v1"
    settings.ai_api_key = "gpt-key"
    settings.translation_base_url = "https://claude.test/v1"
    settings.translation_api_key = "claude-key"
    providers = ProviderRegistry()
    providers.register(primary)
    providers.register(fallback)
    try:
        orchestrator = AIOrchestrator(registry=tool_registry, executor=Executor(), provider_registry=providers)
        result = asyncio.run(orchestrator.respond(
            request=AIRespondRequest(message="hello", stream=False),
            user=SimpleNamespace(id=1), request_id="fallback",
        ))
        assert "Haiku 正常回答" in result.answer
        assert primary.requests and all(request.model == "gpt-5.6-luna" for request in primary.requests)
        assert fallback.requests[0].model == "claude-haiku-4-5-20251001"
        assert result.warnings[-1] == "gpt-5.6-luna 不可用，已自动切换到 claude-haiku-4-5-20251001。"
    finally:
        for field, value in zip(fields, old, strict=True):
            setattr(settings, field, value)


def test_orchestrator_tries_terra_before_cross_provider_fallback_for_sol():
    class ModelAwareProvider(MockProvider):
        async def create_response(self, request):
            self.requests.append(request.model_copy(deep=True))
            if request.model == "gpt-5.6-sol":
                raise ProviderError(
                    AIErrorCode.provider_unavailable,
                    "temporary failure",
                    retryable=True,
                    status_code=503,
                )
            return ProviderResponse(content="Terra 正常回答", finish_reason="stop")

    provider = ModelAwareProvider()
    settings = get_settings()
    fields = ("ai_provider", "ai_model", "ai_allowed_models", "ai_enabled", "ai_api_base", "ai_api_key")
    old = tuple(getattr(settings, field) for field in fields)
    settings.ai_provider = "mock"
    settings.ai_model = "gpt-5.6-sol"
    settings.ai_allowed_models = "gpt-5.6-sol,gpt-5.6-terra"
    settings.ai_enabled = True
    settings.ai_api_base = "https://gpt.test/v1"
    settings.ai_api_key = "gpt-key"
    providers = ProviderRegistry()
    providers.register(provider)
    try:
        result = asyncio.run(AIOrchestrator(
            registry=tool_registry, executor=Executor(), provider_registry=providers,
        ).respond(
            request=AIRespondRequest(message="hello", stream=False),
            user=SimpleNamespace(id=1), request_id="sol-fallback",
        ))
        assert [item.model for item in provider.requests] == ["gpt-5.6-sol", "gpt-5.6-terra"]
        assert "Terra 正常回答" in result.answer
        assert result.warnings[-1] == "gpt-5.6-sol 不可用，已自动切换到 gpt-5.6-terra。"
    finally:
        for field, value in zip(fields, old, strict=True):
            setattr(settings, field, value)


def test_orchestrator_stream_events():
    stream_provider=MockProvider([ProviderResponse(content="直接回答",finish_reason="stop")]); settings,old,providers=configure_mock(stream_provider)
    async def collect():
        orchestrator=AIOrchestrator(registry=tool_registry,executor=Executor(),provider_registry=providers)
        return [event async for event in orchestrator.stream(request=AIRespondRequest(message="hello",stream=True),user=SimpleNamespace(id=1),request_id="stream")]
    try:
        events=asyncio.run(collect()); types=[event.type for event in events]
        assert types[0]=="response.started" and "context.ready" in types and "response.delta" in types
        assert types[-3:]==["citation.map","response.rich_content.completed","response.completed"]
        assert sum(item in {"error","response.completed"} for item in types)==1
    finally: restore(settings,old)


def test_orchestrator_forwards_provider_text_deltas_without_replaying_answer():
    class ChunkedProvider(MockProvider):
        async def stream_response(self, request):
            self.requests.append(request.model_copy(deep=True))
            yield ProviderStreamEvent(type="response_started", response_id="chunked")
            for chunk in ("真", "正", "流式"):
                await asyncio.sleep(0)
                yield ProviderStreamEvent(type="text_delta", response_id="chunked", text_delta=chunk)
            yield ProviderStreamEvent(type="response_completed", response_id="chunked")

    provider=ChunkedProvider(); settings,old,providers=configure_mock(provider)

    async def collect():
        orchestrator=AIOrchestrator(registry=tool_registry,executor=Executor(),provider_registry=providers)
        return [event async for event in orchestrator.stream(request=AIRespondRequest(message="hello",stream=True),user=SimpleNamespace(id=1),request_id="stream-chunks")]

    try:
        events=asyncio.run(collect())
        assert [event.data["delta"] for event in events if event.type=="response.delta"] == ["真", "正", "流式"]
        assert events[-3].type == "citation.map"
        assert events[-2].type == "response.rich_content.completed"
        assert events[-1].type == "response.completed"
    finally: restore(settings,old)


def test_stream_completion_preserves_markdown_instead_of_model_repair_rewrite():
    streamed = "## 结论\n\n**需要跟踪：**资本开支增速 [S99]"
    provider=MockProvider([
        ProviderResponse(content=streamed,finish_reason="stop"),
        ProviderResponse(content="\\*\\*需要跟踪：\\*\\*资本开支增速",finish_reason="stop"),
    ])
    settings,old,providers=configure_mock(provider)

    async def collect():
        orchestrator=AIOrchestrator(registry=tool_registry,executor=Executor(),provider_registry=providers)
        return [event async for event in orchestrator.stream(request=AIRespondRequest(message="hello",stream=True),user=SimpleNamespace(id=1),request_id="stream-markdown")]

    try:
        events=asyncio.run(collect())
        deltas="".join(event.data["delta"] for event in events if event.type=="response.delta")
        completed=next(event for event in events if event.type=="response.completed")
        assert "**需要跟踪：**" in deltas
        assert "**需要跟踪：**" in completed.data["answer"]
        assert "[S99]" not in completed.data["answer"]
        assert len(provider.requests) == 1
    finally: restore(settings,old)


class FakeOrchestrator:
    async def respond(self, *, request, user, request_id):
        return AIRespondResponse(request_id=request_id,answer="ok",status="completed",usage=AIUsageSummary())
    async def stream(self, *, request, user, request_id):
        yield AIStreamEvent(type="response.started",data={"request_id":request_id})
        yield AIStreamEvent(type="response.delta",data={"delta":"ok"})
        yield AIStreamEvent(type="response.completed",data={"request_id":request_id,"status":"completed","answer":"ok"})


def build_client(monkeypatch):
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine,tables=[User.__table__]); db=Session(engine)
    user=User(username="ai-user",password_hash="x",status="active",role="user"); db.add(user); db.commit(); db.refresh(user)
    app=FastAPI(); app.include_router(router)
    def session_override(): yield db
    app.dependency_overrides[get_db]=session_override
    monkeypatch.setattr("app.ai.router._orchestrator",lambda gw:FakeOrchestrator())
    return TestClient(app),db,user


def test_router_auth_strict_json_sse_config_health_and_openapi(monkeypatch):
    client,db,user=build_client(monkeypatch); headers={"Authorization":f"Bearer {create_token(user.id)}"}
    try:
        assert client.post("/api/ai/v1/respond",json={"message":"x","stream":False}).status_code==401
        response=client.post("/api/ai/v1/respond",headers=headers,json={"message":"hello","stream":False})
        assert response.status_code==200 and response.json()["answer"]=="ok"
        injected=client.post("/api/ai/v1/respond",headers=headers,json={"message":"x","stream":False,"provider":"evil","user_id":999})
        assert injected.status_code==422 and injected.json()["error"]["code"]=="AI_REQUEST_INVALID"
        empty=client.post("/api/ai/v1/respond",headers=headers,json={"message":"","stream":False})
        assert empty.status_code==422 and empty.json()["error"]["code"]=="AI_REQUEST_INVALID"
        unknown=client.post("/api/ai/v1/respond",headers=headers,json={"message":"x","stream":False,"allowed_tools":["evil"]})
        assert unknown.status_code==422 and unknown.json()["error"]["code"]=="AI_REQUEST_INVALID"
        with client.stream("POST","/api/ai/v1/respond",headers=headers,json={"message":"hello","stream":True}) as streamed:
            text="".join(streamed.iter_text())
        assert streamed.headers["content-type"].startswith("text/event-stream")
        blocks=[block for block in text.split("\n\n") if block]
        assert all(json.loads(block.split("data: ",1)[1]) for block in blocks)
        assert text.count("event: response.completed")==1 and "reasoning" not in text
        config=client.get("/api/ai/v1/config",headers=headers)
        assert config.status_code==200
        assert "response_modes" not in config.json()
        assert {item["family"] for item in config.json()["models"]} >= {"claude","gpt"}
        assert client.get("/api/ai/v1/health",headers=headers).json()["tool_count"]==87
        assert "/api/ai/v1/respond" in client.app.openapi()["paths"]
    finally: db.close()
