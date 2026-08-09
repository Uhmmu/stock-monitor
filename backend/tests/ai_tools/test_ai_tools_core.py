import asyncio
import json
from datetime import date

import pytest
from app.ai_tools import tool_registry
from app.ai_tools.adapters.base import BaseToolAdapter
from app.ai_tools.budgets import estimate_tokens
from app.ai_tools.catalog import (
    ComparePriceArguments,
    FinancialCompareArguments,
    NewsArguments,
    PortfolioPositionsArguments,
    SearchNewsArguments,
    SecFilingsArguments,
)
from app.ai_tools.compression import (
    ToolResultCompressor,
    deduplicate_sources,
    json_size,
)
from app.ai_tools.enums import ResultMode, ToolStatus
from app.ai_tools.executor import ToolExecutor
from app.ai_tools.registry import ToolRegistry
from app.ai_tools.schemas import (
    AdapterResult,
    ToolArguments,
    ToolDefinition,
    ToolExecutionContext,
)
from app.ai.tool_selector import ToolSelector
from app.research.schemas import ResearchFreshness
from pydantic import ValidationError


def definition(name="test_tool", **updates):
    values=dict(name=name,domain="test",title="Test",description="Use this tool for deterministic stored test data. It is read-only, private-safe, never refreshes providers, searches the web, or calls a model.",input_schema=ToolArguments.model_json_schema(),cache_ttl_seconds=0)
    values.update(updates); return ToolDefinition(**values)


class Adapter(BaseToolAdapter):
    arguments_model=ToolArguments
    def __init__(self, name="test_tool", result=None, delay=0): self.definition=definition(name); self.result=result or AdapterResult(data=[{"value":"ok"}]); self.delay=delay; self.calls=0
    async def execute(self,args,context,gateway):
        self.calls+=1
        if self.delay: await asyncio.sleep(self.delay)
        return self.result


def context(**updates):
    values=dict(request_id="req",user_id=1,caller="test",max_total_output_chars=50000)
    values.update(updates); return ToolExecutionContext(**values)


def test_builtin_registry_is_explicit_complete_and_serializable():
    definitions=tool_registry.list(enabled_only=False)
    assert len(definitions)==79
    assert len({item.name for item in definitions})==79
    assert all(item.read_only and item.version=="1.0.0" for item in definitions)
    assert all(item.input_schema.get("additionalProperties") is False for item in definitions)
    assert all(item.output_schema and item.output_schema.get("title")=="ToolExecutionResult" for item in definitions)
    json.dumps(tool_registry.export_openai_tools())
    assert len(tool_registry.list(domain="sec"))==6
    assert len(tool_registry.list(domain="memory"))==7


def test_registry_rejects_duplicate_and_schema_mismatch():
    registry=ToolRegistry(); registry.register(Adapter())
    with pytest.raises(ValueError,match="duplicate"): registry.register(Adapter())
    bad=Adapter("another_tool"); bad.definition=definition("another_tool",input_schema={"type":"object"})
    with pytest.raises(ValueError,match="schema mismatch"): registry.register(bad)


def test_strict_argument_validation_and_normalization():
    assert NewsArguments(symbol=" msft ").symbol=="MSFT"
    assert PortfolioPositionsArguments(symbols=["msft","MSFT","aapl"]).symbols==["MSFT","AAPL"]
    assert SecFilingsArguments(symbol="msft",form_types=["10-q","8-k"]).form_types==["10-Q","8-K"]
    with pytest.raises(ValidationError): NewsArguments(symbol="../../etc/passwd")
    with pytest.raises(ValidationError): SearchNewsArguments(query="x"*501)
    with pytest.raises(ValidationError): NewsArguments(user_id=2)
    with pytest.raises(ValidationError): ComparePriceArguments(symbols=[f"A{i}" for i in range(11)])
    with pytest.raises(ValidationError): FinancialCompareArguments(symbols=["MSFT","AAPL"],metrics=["payload.secret"])
    with pytest.raises(ValidationError): SecFilingsArguments(symbol="MSFT",start_date=date(2026,2,1),end_date=date(2026,1,1))


def test_selector_combines_news_with_realtime_market_tools():
    selection = ToolSelector(tool_registry).select(
        message="Why did MSFT stock price move? 最近有什么新闻和盘中变化？",
        page_context=None,
        active_symbol="MSFT",
        allowed_tools=None,
        denied_tools=set(),
    )
    assert {"get_latest_news", "search_news"}.issubset(selection.tool_names)
    assert {"get_realtime_quote", "get_intraday_summary", "get_intraday_bars"}.issubset(selection.tool_names)


def test_compression_preserves_json_and_enforces_limits():
    compressor=ToolResultCompressor(); data=[{"title":"x"*500,"summary":"中"*3000,"empty":None} for _ in range(30)]
    result=compressor.compress(tool_name="test_tool",data=data,result_mode=ResultMode.compact,max_chars=3000,max_items=50)
    json.dumps(result.data,ensure_ascii=False); assert result.truncated
    assert result.original_item_count==30 and result.returned_item_count<=10
    assert json_size(result.data)<=3000 and all("empty" not in row for row in result.data)
    assert estimate_tokens("中文abc")>0


def test_source_dedup_and_absolute_locator_removal():
    rows=deduplicate_sources([{"source_id":"s1","source_type":"news","locator":"/secret/path"},{"source_id":"s1","source_type":"news","locator":"/other"}])
    assert rows==[{"source_id":"s1","source_type":"news","locator":None}]


def test_executor_success_policy_validation_timeout_and_cache(monkeypatch):
    registry=ToolRegistry(); adapter=Adapter(result=AdapterResult(data=[{"title":"stored"}],sources=[{"source_id":"s1","source_type":"news"}],freshness=ResearchFreshness(status="fresh"))); registry.register(adapter)
    executor=ToolExecutor(registry,object())
    result=asyncio.run(executor.execute(tool_name="test_tool",raw_arguments={},context=context()))
    assert result.status==ToolStatus.success and result.sources[0]["source_id"]=="s1"
    invalid=asyncio.run(executor.execute(tool_name="test_tool",raw_arguments={"user_id":2},context=context()))
    assert invalid.error.code=="TOOL_ARGUMENTS_INVALID"
    denied=asyncio.run(executor.execute(tool_name="test_tool",raw_arguments={},context=context(denied_tools={"test_tool"})))
    assert denied.status==ToolStatus.denied
    unknown=asyncio.run(executor.execute(tool_name="unknown",raw_arguments={},context=context()))
    assert unknown.error.code=="TOOL_NOT_FOUND"

    private=Adapter("private_tool"); private.definition=definition("private_tool",contains_private_data=True)
    registry.register(private)
    private_denied=asyncio.run(executor.execute(tool_name="private_tool",raw_arguments={},context=context(allow_private_data=False)))
    assert private_denied.error.code=="TOOL_PRIVATE_DATA_DENIED"

    cached=Adapter("cached_tool"); cached.definition=definition("cached_tool",cache_ttl_seconds=30)
    registry.register(cached)
    first=asyncio.run(executor.execute(tool_name="cached_tool",raw_arguments={},context=context()))
    second=asyncio.run(executor.execute(tool_name="cached_tool",raw_arguments={},context=context()))
    assert not first.stats.cache_hit and second.stats.cache_hit and cached.calls==1
    private_cached=Adapter("private_cached_tool"); private_cached.definition=definition("private_cached_tool",contains_private_data=True,cache_ttl_seconds=30)
    registry.register(private_cached)
    asyncio.run(executor.execute(tool_name="private_cached_tool",raw_arguments={},context=context(user_id=1)))
    other=asyncio.run(executor.execute(tool_name="private_cached_tool",raw_arguments={},context=context(user_id=2)))
    assert not other.stats.cache_hit and private_cached.calls==2

    limited_executor=ToolExecutor(registry,object()); limited_context=context(request_id="limited",max_tool_calls=1)
    asyncio.run(limited_executor.execute(tool_name="test_tool",raw_arguments={},context=limited_context))
    limited=asyncio.run(limited_executor.execute(tool_name="test_tool",raw_arguments={},context=limited_context))
    assert limited.error.code=="TOOL_CALL_LIMIT_EXCEEDED"

    slow=Adapter("slow_tool",delay=.05); slow.definition=definition("slow_tool",default_timeout_seconds=.01,max_timeout_seconds=.01)
    registry.register(slow)
    timed=asyncio.run(executor.execute(tool_name="slow_tool",raw_arguments={},context=context()))
    assert timed.status==ToolStatus.timeout and timed.error.retryable


def test_batch_order_partial_failure_dedup_and_call_limit():
    registry=ToolRegistry(); first=Adapter("first_tool"); registry.register(first)
    class Failing(Adapter):
        async def execute(self,args,context,gateway): raise RuntimeError("secret traceback")
    registry.register(Failing("failing_tool"))
    executor=ToolExecutor(registry,object())
    from app.ai_tools.schemas import ToolCallRequest
    calls=[ToolCallRequest(tool="first_tool"),ToolCallRequest(tool="failing_tool"),ToolCallRequest(tool="first_tool")]
    results=asyncio.run(executor.execute_many(calls,context(max_tool_calls=2)))
    assert [row.tool_name for row in results]==["first_tool","failing_tool","first_tool"]
    assert results[0].status==ToolStatus.success and results[1].status==ToolStatus.error
    assert results[2].error.code=="TOOL_CALL_LIMIT_EXCEEDED"
    assert "traceback" not in results[1].error.message.lower()

    budget_registry=ToolRegistry(); budget_registry.register(Adapter("budget_tool",result=AdapterResult(data={"summary":"x"*300})))
    budget_executor=ToolExecutor(budget_registry,object()); budget_calls=[ToolCallRequest(tool="budget_tool"),ToolCallRequest(tool="budget_tool",arguments={"result_mode":"compact"})]
    budget_results=asyncio.run(budget_executor.execute_many(budget_calls,context(request_id="budget",max_tool_calls=2,max_total_output_chars=1000)))
    assert any(row.error and row.error.code=="TOOL_OUTPUT_BUDGET_EXCEEDED" for row in budget_results)
