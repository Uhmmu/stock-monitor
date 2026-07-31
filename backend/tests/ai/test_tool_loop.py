import asyncio
from datetime import UTC, datetime

from app.ai.budgets import OrchestratorBudget
from app.ai.providers.mock import MockProvider
from app.ai.providers.schemas import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderToolCall,
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
