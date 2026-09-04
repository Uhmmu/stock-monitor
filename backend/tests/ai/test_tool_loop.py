import asyncio
from datetime import UTC, datetime

from app.ai.budgets import OrchestratorBudget
from app.ai.providers.base import BaseModelProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.schemas import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderToolCall,
    ProviderToolDefinition,
)
from app.ai.tool_loop import ToolCallingLoop
from app.ai_tools.enums import ResultMode, ToolStatus
from app.ai_tools.schemas import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolExecutionStats,
)


def tool_result(call):
    now=datetime.now(UTC)
    return ToolExecutionResult(tool_call_id="executor-id",tool_name=call.tool,tool_version="1.0.0",status=ToolStatus.success,data={"price":100},summary="stored",sources=[{"source_id":f"price:{call.arguments.get('symbol','x')}","title":"Stored price","source_type":"price"}],stats=ToolExecutionStats(started_at=now,completed_at=now,duration_ms=2,result_mode=ResultMode.standard,estimated_output_chars=100))


class Executor:
    def __init__(self): self.calls=[]
    async def execute_many(self,calls,context):
        self.calls.extend(calls); return [tool_result(call) for call in calls]


def context():
    return ToolExecutionContext(request_id="r",user_id=1,caller="test",allowed_tools={"get_latest_price"},max_total_output_chars=80000)


def provider_request():
    return ProviderRequest(model="m",messages=[ProviderMessage(role="system",content="s"),ProviderMessage(role="user",content="u")])


def test_direct_answer_and_single_tool_roundtrip():
    direct=asyncio.run(ToolCallingLoop(Executor()).run(provider=MockProvider([ProviderResponse(content="ok",finish_reason="stop")]),provider_request=provider_request(),tool_context=context(),limits=OrchestratorBudget()))
    assert direct.answer=="ok" and direct.model_rounds==1
    executor=Executor(); provider=MockProvider([
        ProviderResponse(tool_calls=[ProviderToolCall(id="c1",name="get_latest_price",arguments={"symbol":"MSFT"})],finish_reason="tool_calls"),
        ProviderResponse(content="Price fact [S1]",finish_reason="stop"),
    ])
    result=asyncio.run(ToolCallingLoop(executor).run(provider=provider,provider_request=provider_request(),tool_context=context(),limits=OrchestratorBudget()))
    assert result.answer.endswith("[S1]") and len(executor.calls)==1 and result.tool_calls[0].tool_call_id=="c1"
    assert provider.requests[1].messages[-1].role=="tool" and "untrusted research data" in provider.requests[1].messages[-1].content


def test_duplicate_calls_reuse_across_rounds():
    call=lambda ident: ProviderToolCall(id=ident,name="get_latest_price",arguments={"symbol":"MSFT"})
    provider=MockProvider([ProviderResponse(tool_calls=[call("c1")],finish_reason="tool_calls"),ProviderResponse(tool_calls=[call("c2")],finish_reason="tool_calls"),ProviderResponse(content="done [S1]",finish_reason="stop")])
    executor=Executor(); result=asyncio.run(ToolCallingLoop(executor).run(provider=provider,provider_request=provider_request(),tool_context=context(),limits=OrchestratorBudget()))
    assert len(executor.calls)==1 and result.tool_calls[-1].reused


def test_duplicate_calls_are_deduplicated_within_one_round():
    calls=[ProviderToolCall(id=ident,name="get_latest_price",arguments={"symbol":"MSFT"}) for ident in ("c1","c2")]
    provider=MockProvider([ProviderResponse(tool_calls=calls,finish_reason="tool_calls"),ProviderResponse(content="done [S1]",finish_reason="stop")])
    executor=Executor(); result=asyncio.run(ToolCallingLoop(executor).run(provider=provider,provider_request=provider_request(),tool_context=context(),limits=OrchestratorBudget()))
    assert len(executor.calls)==1 and len(result.tool_calls)==2 and result.tool_calls[1].reused


def test_illegal_tool_is_not_executed_and_model_recovers():
    provider=MockProvider([ProviderResponse(tool_calls=[ProviderToolCall(id="bad",name="write_position",arguments={})],finish_reason="tool_calls"),ProviderResponse(content="cannot do that",finish_reason="stop")])
    executor=Executor(); result=asyncio.run(ToolCallingLoop(executor).run(provider=provider,provider_request=provider_request(),tool_context=context(),limits=OrchestratorBudget()))
    assert not executor.calls and result.tool_calls[0].status=="denied"


def test_empty_response_retries_once():
    provider=MockProvider([ProviderResponse(),ProviderResponse(content="recovered",finish_reason="stop")])
    result=asyncio.run(ToolCallingLoop(Executor()).run(provider=provider,provider_request=provider_request(),tool_context=context(),limits=OrchestratorBudget()))
    assert result.answer=="recovered" and len(provider.requests)==2


class ArgumentStreamingProvider(BaseModelProvider):
    provider_name = "mock"

    def __init__(self, rounds):
        self.rounds = [list(events) for events in rounds]
        self.requests = []

    async def create_response(self, request):
        raise AssertionError("streaming path must not fall back to create_response")

    async def stream_response(self, request):
        self.requests.append(request.model_copy(deep=True))
        events = self.rounds.pop(0) if self.rounds else [
            ProviderStreamEvent(type="response_started"),
            ProviderStreamEvent(type="text_delta", text_delta="fallback answer"),
            ProviderStreamEvent(type="response_completed"),
        ]
        for event in events:
            yield event

    def supports_tools(self, model):
        return True

    def supports_streaming(self, model):
        return True


def test_tool_planning_events_stream_when_tool_names_resolve():
    definition = ProviderToolDefinition(
        name="get_latest_price",
        description="stored price",
        parameters={"type": "object", "properties": {"symbol": {"type": "string"}}},
    )
    events = [
        ProviderStreamEvent(type="response_started"),
        ProviderStreamEvent(type="tool_call_arguments_delta", tool_call_id="c1", tool_name="get_lat"),
        ProviderStreamEvent(type="tool_call_arguments_delta", tool_call_id="c1", tool_name="get_latest_price"),
        ProviderStreamEvent(type="tool_call_arguments_delta", tool_call_id="c1", tool_name="get_latest_price"),
        ProviderStreamEvent(type="tool_call_arguments_delta", tool_call_id="c2", tool_name="not_a_real_tool"),
        ProviderStreamEvent(type="tool_call_completed", tool_call_id="c1", tool_name="get_latest_price", arguments={"symbol": "MSFT"}),
        ProviderStreamEvent(type="response_completed"),
    ]
    final_round = [
        ProviderStreamEvent(type="response_started"),
        ProviderStreamEvent(type="text_delta", text_delta="Price fact"),
        ProviderStreamEvent(type="response_completed"),
    ]
    provider = ArgumentStreamingProvider([events, final_round])
    captured = []

    async def sink(event, data):
        captured.append((event, data))

    request = ProviderRequest(
        model="m",
        messages=[ProviderMessage(role="user", content="u")],
        tools=[definition],
    )
    result = asyncio.run(ToolCallingLoop(Executor()).run(
        provider=provider, provider_request=request, tool_context=context(),
        limits=OrchestratorBudget(), event_sink=sink, use_provider_stream=True,
    ))
    planning = [data for event, data in captured if event == "tool.planning"]
    assert planning == [{"tool_call_id": "c1", "tool": "get_latest_price"}]
    # The round still executes normally after the planning announcements.
    assert result.answer and result.tool_calls[0].tool == "get_latest_price"
    assert ("tool.started", {"tool_call_id": "c1", "tool": "get_latest_price"}) in captured
