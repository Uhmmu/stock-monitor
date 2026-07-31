from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.config import get_settings
from app.external_search.exceptions import ExternalSearchError
from app.research.exceptions import ResearchError
from app.research.service import ResearchGateway

from .audit import audit_tool_execution
from .budgets import ToolBudgets, estimate_tokens
from .cache import tool_cache
from .compression import (
    ToolResultCompressor,
    deduplicate_sources,
    json_default,
    json_size,
)
from .enums import ResultMode, ToolErrorCode, ToolStatus
from .exceptions import ToolError
from .metrics import tool_metrics
from .policy import ToolPolicy
from .registry import ToolRegistry
from .schemas import (
    ToolCallRequest,
    ToolExecutionContext,
    ToolExecutionError,
    ToolExecutionResult,
    ToolExecutionStats,
)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, gateway: ResearchGateway, *, policy: ToolPolicy | None = None):
        self.registry, self.gateway = registry, gateway
        self.policy = policy or ToolPolicy(); self.compressor = ToolResultCompressor(); self.budgets = ToolBudgets.from_settings()
        self._call_counts: dict[str, int] = {}
        self._external_call_counts: dict[str, int] = {}
        self._live_search_counts: dict[str, int] = {}
        self._deep_search_counts: dict[str, int] = {}

    @staticmethod
    def _stats(started_at, started, mode, *, input_chars=0, timeout=None, **updates):
        completed=datetime.now(UTC)
        return ToolExecutionStats(started_at=started_at,completed_at=completed,duration_ms=max(0,int((time.perf_counter()-started)*1000)),
            result_mode=mode,estimated_input_chars=input_chars,timeout_seconds=timeout,**updates)

    def _error(self, *, call_id, name, version, code, message, status, started_at, started, mode, input_chars=0, retryable=False, details=None, timeout=None):
        return ToolExecutionResult(tool_call_id=call_id,tool_name=name,tool_version=version,status=status,
            stats=self._stats(started_at,started,mode,input_chars=input_chars,timeout=timeout),
            error=ToolExecutionError(code=code,message=message,retryable=retryable,details=details or {}))

    async def execute(self, *, tool_name: str, raw_arguments: dict, context: ToolExecutionContext) -> ToolExecutionResult:
        call_id=str(uuid4()); started_at=datetime.now(UTC); started=time.perf_counter(); version="unknown"
        raw_arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
        input_chars=len(json.dumps(raw_arguments,ensure_ascii=False,default=json_default)); mode=ResultMode.standard
        try:
            adapter=self.registry.get(tool_name); definition=adapter.definition; version=definition.version
            if not get_settings().ai_tools_enabled: raise ToolError(ToolErrorCode.disabled,"The AI tool execution layer is disabled.")
            try: args=adapter.arguments_model.model_validate(raw_arguments)
            except ValidationError as exc:
                raise ToolError(ToolErrorCode.arguments_invalid,"Tool arguments failed validation.",details={"errors":[{"type":e["type"],"loc":[str(x) for x in e["loc"]],"message":e["msg"]} for e in exc.errors()[:20]]}) from exc
            mode=args.result_mode; self.policy.validate(definition,context,mode)
            normal_web_tools = {
                "search_web", "search_latest_news_web", "search_official_company_sources",
                "search_financial_reports_web", "search_publications_web",
            }
            if tool_name in normal_web_tools:
                self._external_call_counts[context.request_id] = self._external_call_counts.get(context.request_id, 0) + 1
                if self._external_call_counts[context.request_id] > min(max(get_settings().exa_max_search_calls_per_ai_request, 1), 3):
                    raise ToolError(ToolErrorCode.call_limit, "Normal web search call limit was exceeded.")
                if str(getattr(args, "freshness", "")) == "live":
                    self._live_search_counts[context.request_id] = self._live_search_counts.get(context.request_id, 0) + 1
                    if self._live_search_counts[context.request_id] > 1:
                        raise ToolError(ToolErrorCode.call_limit, "Live web search is limited to once per AI request.")
            elif tool_name == "run_deep_web_research":
                self._deep_search_counts[context.request_id] = self._deep_search_counts.get(context.request_id, 0) + 1
                if self._deep_search_counts[context.request_id] > 1:
                    raise ToolError(ToolErrorCode.call_limit, "Deep Search is limited to one run per AI request.")
            if context.request_id not in self._call_counts and len(self._call_counts)>=1024:
                self._call_counts.pop(next(iter(self._call_counts)))
            self._call_counts[context.request_id]=self._call_counts.get(context.request_id,0)+1
            if self._call_counts[context.request_id]>context.max_tool_calls:
                raise ToolError(ToolErrorCode.call_limit,f"The execution context call limit of {context.max_tool_calls} was exceeded.")
            start_date=getattr(args,"start_date",None); end_date=getattr(args,"end_date",None)
            if definition.max_date_range_days and start_date and end_date and (end_date-start_date).days>definition.max_date_range_days:
                raise ToolError(ToolErrorCode.arguments_invalid,f"Date range exceeds {definition.max_date_range_days} days.")
            settings=get_settings(); cache_key=adapter.build_cache_key(args,context) if settings.ai_tools_cache_enabled else None
            if cache_key: cache_key=f"{cache_key}:budget:{min(self.budgets.for_mode(mode),context.max_total_output_chars)}"
            if cache_key and (cached:=tool_cache.get(cache_key)):
                cached.tool_call_id=call_id; cached.stats.cache_hit=True; cached.stats.started_at=started_at; cached.stats.completed_at=datetime.now(UTC); cached.stats.duration_ms=max(0,int((time.perf_counter()-started)*1000))
                result=cached
            else:
                configured_max_timeout = (
                    min(max(settings.exa_agent_timeout_seconds, 30.0), 900.0)
                    if tool_name == "run_deep_web_research"
                    else max(.1,min(settings.ai_tools_max_timeout_seconds,30.0))
                )
                timeout=min(definition.default_timeout_seconds,definition.max_timeout_seconds,configured_max_timeout)
                adapter_result=await asyncio.wait_for(adapter.execute(args,context,self.gateway),timeout=timeout)
                budget=min(self.budgets.for_mode(mode),context.max_total_output_chars)
                compressed=self.compressor.compress(tool_name=tool_name,data=adapter_result.data,result_mode=mode,max_chars=max(500,int(budget*.75)),max_items=definition.max_items)
                source_limit={ResultMode.compact:10,ResultMode.standard:50,ResultMode.detailed:100}[mode]
                all_sources=deduplicate_sources(adapter_result.sources); sources=all_sources[:source_limit]
                warnings=[w.model_dump(mode="json") if hasattr(w,"model_dump") else dict(w) for w in adapter_result.warnings]+compressed.warnings
                sources_truncated=len(sources)<len(all_sources)
                if sources_truncated: warnings.append({"code":"TOOL_SOURCES_TRUNCATED","message":"Source references were truncated to the result-mode budget.","severity":"warning"})
                envelope_chars=json_size({"data":compressed.data,"sources":sources,"freshness":adapter_result.freshness,"warnings":warnings})
                while envelope_chars>budget and sources:
                    sources.pop(); sources_truncated=True
                    envelope_chars=json_size({"data":compressed.data,"sources":sources,"freshness":adapter_result.freshness,"warnings":warnings})
                if sources_truncated and not any(w.get("code")=="TOOL_SOURCES_TRUNCATED" for w in warnings):
                    warnings.append({"code":"TOOL_SOURCES_TRUNCATED","message":"Source references were truncated to the result-mode budget.","severity":"warning"})
                    envelope_chars=json_size({"data":compressed.data,"sources":sources,"freshness":adapter_result.freshness,"warnings":warnings})
                if envelope_chars>budget:
                    overhead=json_size({"sources":sources,"freshness":adapter_result.freshness,"warnings":warnings})
                    compressed=self.compressor.compress(tool_name=tool_name,data=compressed.data,result_mode=mode,max_chars=max(100,budget-overhead-100),max_items=definition.max_items)
                    envelope_chars=json_size({"data":compressed.data,"sources":sources,"freshness":adapter_result.freshness,"warnings":warnings})
                if envelope_chars>budget: raise ToolError(ToolErrorCode.result_too_large,"Tool result cannot fit the selected result-mode budget.")
                if envelope_chars>self.budgets.hard: raise ToolError(ToolErrorCode.result_too_large,"Tool result exceeds the hard output limit.")
                stats=self._stats(started_at,started,mode,input_chars=input_chars,timeout=timeout,
                    original_item_count=compressed.original_item_count,returned_item_count=compressed.returned_item_count,
                    estimated_output_chars=envelope_chars,estimated_output_tokens=estimate_tokens(json.dumps(compressed.data,ensure_ascii=False,default=json_default)),truncated=compressed.truncated or sources_truncated)
                status=ToolStatus.partial if adapter_result.partial or any(w.get("severity")=="error" for w in warnings) else ToolStatus.success
                result=ToolExecutionResult(tool_call_id=call_id,tool_name=tool_name,tool_version=version,status=status,data=compressed.data,
                    summary=adapter_result.summary,sources=sources,freshness=(adapter_result.freshness.model_dump(mode="json") if hasattr(adapter_result.freshness,"model_dump") else adapter_result.freshness),warnings=warnings,stats=stats)
                serialized=json.dumps(result.model_dump(mode="json"),ensure_ascii=False,default=json_default,separators=(",",":"))
                result.stats.estimated_output_chars=len(serialized); result.stats.estimated_output_tokens=estimate_tokens(serialized)
                if result.stats.estimated_output_chars>budget: raise ToolError(ToolErrorCode.result_too_large,"Tool result cannot fit the selected result-mode budget.")
                if cache_key and status in {ToolStatus.success,ToolStatus.partial}: tool_cache.set(cache_key,result,definition.cache_ttl_seconds)
        except asyncio.TimeoutError:
            result=self._error(call_id=call_id,name=tool_name,version=version,code=ToolErrorCode.timeout.value,message="Tool execution timed out.",status=ToolStatus.timeout,started_at=started_at,started=started,mode=mode,input_chars=input_chars,retryable=True,timeout=locals().get("timeout"))
        except ToolError as exc:
            status=ToolStatus.denied if exc.code in {ToolErrorCode.not_allowed,ToolErrorCode.disabled,ToolErrorCode.private_data_denied,ToolErrorCode.call_limit,ToolErrorCode.output_budget} else ToolStatus.error
            result=self._error(call_id=call_id,name=tool_name,version=version,code=exc.code.value,message=exc.message,status=status,started_at=started_at,started=started,mode=mode,input_chars=input_chars,retryable=exc.retryable,details=exc.details)
        except ResearchError as exc:
            result=self._error(call_id=call_id,name=tool_name,version=version,code=ToolErrorCode.execution_failed.value,message="Stored research data could not satisfy the tool request.",status=ToolStatus.error,started_at=started_at,started=started,mode=mode,input_chars=input_chars,retryable=exc.code.value in {"SOURCE_UNAVAILABLE","INTERNAL_RESEARCH_ERROR"},details={"research_error_code":exc.code.value})
        except ExternalSearchError as exc:
            status = ToolStatus.denied if exc.status_code in {402, 403, 409} else ToolStatus.error
            result=self._error(call_id=call_id,name=tool_name,version=version,code=exc.code,message=exc.message,status=status,started_at=started_at,started=started,mode=mode,input_chars=input_chars,retryable=exc.retryable)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("ai_tool_unhandled tool_call_id=%s tool=%s",call_id,tool_name)
            result=self._error(call_id=call_id,name=tool_name,version=version,code=ToolErrorCode.execution_failed.value,message="Tool execution failed.",status=ToolStatus.error,started_at=started_at,started=started,mode=mode,input_chars=input_chars)
        if get_settings().ai_tools_audit_enabled: audit_tool_execution(context=context,result=result,arguments=raw_arguments)
        tool_metrics.record(tool_name,result.status.value,result.stats.duration_ms,cache_hit=result.stats.cache_hit,truncated=result.stats.truncated)
        return result

    async def execute_many(self, calls: list[ToolCallRequest], context: ToolExecutionContext) -> list[ToolExecutionResult]:
        maximum=max(1,min(context.max_tool_calls,get_settings().ai_tools_max_calls_per_batch,12))
        accepted=calls[:maximum]; semaphore=asyncio.Semaphore(max(1,min(context.max_parallel_calls,get_settings().ai_tools_max_parallel_calls,8)))
        tasks={}
        async def run(call):
            key=f"{call.tool}:{json.dumps(call.arguments,sort_keys=True,default=json_default,separators=(',',':'))}"
            if key not in tasks:
                async def one():
                    async with semaphore: return await self.execute(tool_name=call.tool,raw_arguments=call.arguments,context=context)
                tasks[key]=asyncio.create_task(one())
            result=await tasks[key]
            return result.model_copy(deep=True,update={"tool_call_id":str(uuid4())})
        results=list(await asyncio.gather(*(run(call) for call in accepted)))
        used=0
        for index,result in enumerate(results):
            if used+result.stats.estimated_output_chars>context.max_total_output_chars:
                results[index]=self._error(call_id=result.tool_call_id,name=result.tool_name,version=result.tool_version,
                    code=ToolErrorCode.output_budget.value,message="The batch output budget was exhausted.",status=ToolStatus.denied,
                    started_at=result.stats.started_at,started=time.perf_counter(),mode=result.stats.result_mode)
                if get_settings().ai_tools_audit_enabled: audit_tool_execution(context=context,result=results[index],arguments=accepted[index].arguments)
                tool_metrics.record(results[index].tool_name,results[index].status.value,results[index].stats.duration_ms)
            else: used+=result.stats.estimated_output_chars
        for call in calls[maximum:]:
            now=datetime.now(UTC); denied=self._error(call_id=str(uuid4()),name=call.tool,version="unknown",code=ToolErrorCode.call_limit.value,
                message=f"The batch call limit of {maximum} was exceeded.",status=ToolStatus.denied,started_at=now,started=time.perf_counter(),mode=ResultMode.standard)
            results.append(denied)
            if get_settings().ai_tools_audit_enabled: audit_tool_execution(context=context,result=denied,arguments=call.arguments)
            tool_metrics.record(call.tool,denied.status.value,denied.stats.duration_ms)
        return results
