from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from hashlib import sha256
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field

from app.ai_rich_content.factories import build_candidates
from app.ai_rich_content.prompting import build_candidate_prompt
from app.ai_rich_content.schemas import RichBlockCandidate
from app.ai_tools.enums import ToolStatus
from app.ai_tools.executor import ToolExecutor
from app.ai_tools.schemas import (
    ToolCallRequest,
    ToolExecutionContext,
    ToolExecutionResult,
)
from app.config import get_settings

from .budgets import OrchestratorBudget
from .citations import CitationBuilder
from .context_trimmer import ContextTrimmer
from .enums import AIErrorCode
from .exceptions import AIError, ProviderError
from .providers.base import BaseModelProvider
from .providers.schemas import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
)
from .schemas import AIToolCallRecord, Citation
from .serializers import serialize_tool_result, warning_codes

EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]

_SENSITIVE_ARGUMENT_PARTS = {
    "api_key", "authorization", "cookie", "credential", "password", "secret",
    "token", "raw_content", "article_body", "sec_body", "transactions", "orders",
}

_EXTERNAL_SEARCH_TOOLS = {
    "search_web", "search_latest_news_web", "search_official_company_sources",
    "search_financial_reports_web", "search_publications_web", "run_deep_web_research",
}


def _bounded_argument_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:30]:
            normalized_key = str(key)[:64]
            if any(part in normalized_key.lower() for part in _SENSITIVE_ARGUMENT_PARTS):
                result[normalized_key] = "[redacted]"
            else:
                result[normalized_key] = _bounded_argument_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_bounded_argument_value(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return value[:500]
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:500]


def persistence_arguments(executor: ToolExecutor, call: ProviderToolCall) -> tuple[dict[str, Any], str | None]:
    """Return validated, bounded tool arguments for persistence only."""
    try:
        adapter = executor.registry.get(call.name)
        validated = adapter.arguments_model.model_validate(call.arguments)
        raw_arguments = validated.model_dump(mode="json", exclude_none=True)
        raw_encoded = json.dumps(raw_arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        normalized = _bounded_argument_value(raw_arguments)
        # External queries can contain sensitive user context. Persist only a
        # non-reversible fingerprint and length; the sanitized query is sent to
        # Exa in-memory and never copied into tool audit rows.
        if call.name in _EXTERNAL_SEARCH_TOOLS and isinstance(normalized, dict) and "query" in normalized:
            normalized["query"] = "[redacted external query]"
            normalized["query_hash"] = sha256(raw_encoded.encode()).hexdigest()
            normalized["query_length"] = len(str(raw_arguments.get("query") or ""))
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) > 4096:
            return {}, sha256(raw_encoded.encode()).hexdigest()
        return normalized, sha256(raw_encoded.encode()).hexdigest()
    except Exception:  # noqa: BLE001 -- invalid/provider-supplied arguments must not escape.
        return {}, None


class ToolLoopResult(BaseModel):
    answer: str
    status: str = "completed"
    response_id: str | None = None
    tool_results: list[ToolExecutionResult] = Field(default_factory=list)
    tool_calls: list[AIToolCallRecord] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    model_rounds: int = 0
    warnings: list[str] = Field(default_factory=list)
    block_candidates: list[RichBlockCandidate] = Field(default_factory=list)


def normalized_signature(call: ProviderToolCall) -> str:
    payload = json.dumps(call.arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(f"{call.name}:{payload}".encode()).hexdigest()


def external_metadata(result: ToolExecutionResult) -> dict[str, Any]:
    data = result.data if isinstance(result.data, dict) else {}
    return {
        "external_provider": "exa" if result.tool_name.startswith("search_") or result.tool_name == "run_deep_web_research" else None,
        "external_request_id": data.get("provider_request_id"),
        "external_run_id": data.get("run_id"),
        "cost_usd": float(data["cost_usd"]) if data.get("cost_usd") is not None else None,
        "cost_estimated": bool(data.get("cost_estimated")),
    }


class ToolCallingLoop:
    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def _call_provider(
        self,
        provider: BaseModelProvider,
        request: ProviderRequest,
        *,
        stream: bool,
        event_sink: EventSink | None = None,
    ) -> ProviderResponse:
        if not stream or not provider.supports_streaming(request.model):
            return await provider.create_response(request)
        content: list[str] = []; calls: list[ProviderToolCall] = []; usage = None; response_id = None
        async for event in provider.stream_response(request.model_copy(update={"stream": True})):
            response_id = event.response_id or response_id
            if event.type == "text_delta" and event.text_delta:
                content.append(event.text_delta)
                if event_sink:
                    await event_sink("response.delta", {"delta": event.text_delta})
            elif event.type == "tool_call_completed" and event.tool_call_id and event.tool_name:
                calls.append(ProviderToolCall(id=event.tool_call_id, name=event.tool_name, arguments=event.arguments or {}))
            elif event.type == "usage":
                usage = event.usage
            elif event.type == "error":
                if content:
                    return ProviderResponse(response_id=response_id, content="".join(content), finish_reason="error", usage=usage)
                try:
                    error_code = AIErrorCode(event.error_code) if event.error_code else AIErrorCode.stream_interrupted
                except ValueError:
                    error_code = AIErrorCode.stream_interrupted
                raise ProviderError(
                    error_code,
                    event.error_message or "Model stream interrupted.",
                    retryable=error_code == AIErrorCode.stream_interrupted,
                    status_code=502,
                )
        joined_content = "".join(content)
        if calls and joined_content and event_sink:
            # A provider may emit a short preamble before deciding to call a
            # tool. It is not part of the final answer, so clear the provisional
            # text before the next model round starts.
            await event_sink("response.reset", {})
        return ProviderResponse(response_id=response_id, content=joined_content or None, tool_calls=calls, finish_reason="tool_calls" if calls else "stop", usage=usage)

    async def run(
        self, *, provider: BaseModelProvider, provider_request: ProviderRequest,
        tool_context: ToolExecutionContext, limits: OrchestratorBudget,
        event_sink: EventSink | None = None, use_provider_stream: bool = False,
    ) -> ToolLoopResult:
        request = provider_request.model_copy(deep=True)
        seen: dict[str, ToolExecutionResult] = {}
        retry_counts: dict[str, int] = {}
        all_results: list[ToolExecutionResult] = []
        records: list[AIToolCallRecord] = []
        block_candidates: list[RichBlockCandidate] = []
        prompted_candidate_count = 0
        citations = CitationBuilder(); warnings: list[str] = []
        input_tokens = output_tokens = 0; response_id = None; empty_retried = False
        started = perf_counter(); force_final = False

        async def emit(event: str, data: dict[str, Any]) -> None:
            if event_sink:
                await event_sink(event, data)

        for round_number in range(1, limits.max_model_rounds + 1):
            if perf_counter() - started >= limits.max_total_duration_seconds:
                raise AIError(AIErrorCode.provider_timeout, "AI request exceeded its total time limit.", retryable=True, status_code=504)
            trimmed = ContextTrimmer().trim(request.messages, limits.max_context_chars)
            request.messages = trimmed.messages
            warnings.extend(item for item in trimmed.warnings if item not in warnings)
            response = await self._call_provider(
                provider,
                request,
                stream=use_provider_stream,
                event_sink=emit if use_provider_stream else None,
            )
            response_id = response.response_id or response_id
            if response.usage:
                input_tokens += response.usage.input_tokens or 0; output_tokens += response.usage.output_tokens or 0
            if response.content and not response.tool_calls:
                status = "partial" if response.finish_reason in {"length", "error"} else "completed"
                if response.finish_reason == "length":
                    warnings.append("Model output reached its length limit.")
                elif response.finish_reason == "error":
                    warnings.append("Model stream was interrupted after partial text was received.")
                return ToolLoopResult(
                    answer=response.content[:limits.max_answer_chars], status=status, response_id=response_id,
                    tool_results=all_results, tool_calls=records, citations=citations.collect(all_results),
                    usage=ProviderUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens),
                    model_rounds=round_number, warnings=warnings,
                    block_candidates=block_candidates,
                )
            if not response.tool_calls:
                if not empty_retried:
                    empty_retried = True
                    request.messages.append(ProviderMessage(role="system", content="Return a useful final answer. If data is unavailable, state that explicitly."))
                    continue
                raise AIError(AIErrorCode.response_empty, "Model returned an empty response.", status_code=502)

            assistant = ProviderMessage(role="assistant", content=response.content, tool_calls=response.tool_calls)
            request.messages.append(assistant)
            round_calls = response.tool_calls[:limits.max_tool_calls_per_round]
            if len(response.tool_calls) > len(round_calls):
                warnings.append("Per-round tool call limit was reached.")
            remaining = limits.max_tool_calls - len({key for key in seen})
            if remaining <= 0:
                force_final = True
                round_calls = []
            else:
                round_calls = round_calls[:remaining]

            unique: list[ProviderToolCall] = []
            reused: list[tuple[ProviderToolCall, ToolExecutionResult]] = []
            pending_duplicates: list[ProviderToolCall] = []
            pending_signatures: set[str] = set()
            for call in round_calls:
                signature = normalized_signature(call)
                if signature in pending_signatures:
                    pending_duplicates.append(call)
                elif signature in seen:
                    previous = seen[signature]
                    if previous.error and previous.error.retryable and retry_counts.get(signature, 0) < 1:
                        retry_counts[signature] = 1
                        pending_signatures.add(signature)
                        unique.append(call)
                    else:
                        reused.append((call, previous))
                else:
                    pending_signatures.add(signature)
                    unique.append(call)
            valid: list[ProviderToolCall] = []
            known = tool_context.allowed_tools or set()
            for call in unique:
                normalized_arguments, arguments_hash = persistence_arguments(self.executor, call)
                if call.name not in known or call.name in tool_context.denied_tools:
                    request.messages.append(ProviderMessage(role="tool", tool_call_id=call.id, name=call.name, content=json.dumps({"status":"error","error":{"code":"TOOL_NOT_ALLOWED","message":"This tool is not allowed for this request."}})))
                    records.append(AIToolCallRecord(
                        tool_call_id=call.id,
                        tool=call.name,
                        status="denied",
                        normalized_arguments=normalized_arguments,
                        arguments_hash=arguments_hash,
                    ))
                else:
                    valid.append(call)

            for call in valid:
                await emit("tool.started", {"tool_call_id": call.id, "tool": call.name})
                if call.name == "run_deep_web_research":
                    await emit("deep_search.created", {"effort": tool_context.web_access_mode.removeprefix("deep_"), "status": "queued"})
                    await emit("deep_search.started", {"stage": "searching", "message": "正在搜索公开来源"})
            if valid:
                calls = [ToolCallRequest(tool=call.name, arguments=call.arguments) for call in valid]
                executed = await self.executor.execute_many(calls, tool_context)
                for call, result in zip(valid, executed, strict=True):
                    normalized_arguments, arguments_hash = persistence_arguments(self.executor, call)
                    result = result.model_copy(deep=True, update={"tool_call_id": call.id})
                    seen[normalized_signature(call)] = result; all_results.append(result)
                    content, result_citations = serialize_tool_result(result, citations, max(1000, limits.max_tool_result_chars - sum(r.stats.estimated_output_chars for r in all_results[:-1])))
                    request.messages.append(ProviderMessage(role="tool", tool_call_id=call.id, name=call.name, content=content))
                    if get_settings().ai_rich_content_enabled:
                        built, rich_warnings = build_candidates(
                            result,
                            result_citations,
                        )
                        block_candidates.extend(built)
                        warnings.extend(
                            warning
                            for warning in rich_warnings
                            if warning not in warnings
                        )
                    record = AIToolCallRecord(
                        tool_call_id=call.id,
                        tool=call.name,
                        tool_version=result.tool_version,
                        status=result.status.value,
                        result_mode=result.stats.result_mode.value,
                        summary=(result.summary[:500] if result.summary else None),
                        duration_ms=result.stats.duration_ms,
                        original_item_count=result.stats.original_item_count,
                        returned_item_count=result.stats.returned_item_count,
                        warning_codes=warning_codes(result),
                        source_ids=[str(source.get("source_id")) for source in result.sources if isinstance(source, dict) and source.get("source_id")][:100],
                        cache_hit=result.stats.cache_hit,
                        truncated=result.stats.truncated,
                        error_code=result.error.code if result.error else None,
                        retryable=result.error.retryable if result.error else False,
                        normalized_arguments=normalized_arguments,
                        arguments_hash=arguments_hash,
                        **external_metadata(result),
                    )
                    records.append(record)
                    event = "tool.failed" if result.status in {ToolStatus.error, ToolStatus.timeout, ToolStatus.denied} else "tool.completed"
                    await emit(event, record.model_dump(mode="json"))
                    if call.name == "run_deep_web_research":
                        deep_data = result.data if isinstance(result.data, dict) else {}
                        if result.status in {ToolStatus.success, ToolStatus.partial}:
                            await emit("deep_search.completed", {"run_id": deep_data.get("run_id"), "status": deep_data.get("status", "completed"), "source_count": len(result.sources)})
                            if deep_data.get("cost_usd") is not None:
                                await emit("deep_search.cost", {"run_id": deep_data.get("run_id"), "cost_usd": float(deep_data["cost_usd"]), "estimated": bool(deep_data.get("cost_estimated"))})
                        else:
                            terminal = "deep_search.cancelled" if result.error and result.error.code == "DEEP_SEARCH_CANCELLED" else "deep_search.failed"
                            await emit(terminal, {"run_id": deep_data.get("run_id"), "status": result.status.value, "message": result.error.message if result.error else "Deep research failed."})

            for call in pending_duplicates:
                original = seen.get(normalized_signature(call))
                if original is not None:
                    reused.append((call, original))

            for call, original in reused:
                normalized_arguments, arguments_hash = persistence_arguments(self.executor, call)
                result = original.model_copy(deep=True, update={"tool_call_id": call.id})
                content, _ = serialize_tool_result(result, citations, limits.max_tool_result_chars)
                request.messages.append(ProviderMessage(role="tool", tool_call_id=call.id, name=call.name, content=content))
                records.append(AIToolCallRecord(
                    tool_call_id=call.id,
                    tool=call.name,
                    tool_version=result.tool_version,
                    status=result.status.value,
                    result_mode=result.stats.result_mode.value,
                    summary=(result.summary[:500] if result.summary else None),
                    duration_ms=0,
                    original_item_count=result.stats.original_item_count,
                    returned_item_count=result.stats.returned_item_count,
                    warning_codes=warning_codes(result),
                    source_ids=[str(source.get("source_id")) for source in result.sources if isinstance(source, dict) and source.get("source_id")][:100],
                    cache_hit=True,
                    truncated=result.stats.truncated,
                    error_code=result.error.code if result.error else None,
                    retryable=result.error.retryable if result.error else False,
                    reused=True,
                    normalized_arguments=normalized_arguments,
                    arguments_hash=arguments_hash,
                    **external_metadata(result),
                ))

            if len(block_candidates) > prompted_candidate_count:
                candidate_prompt = build_candidate_prompt(block_candidates)
                if candidate_prompt:
                    request.messages.append(
                        ProviderMessage(role="system", content=candidate_prompt)
                    )
                    prompted_candidate_count = len(block_candidates)

            total_chars = sum(result.stats.estimated_output_chars for result in all_results)
            if total_chars >= limits.max_tool_result_chars or len(seen) >= limits.max_tool_calls:
                force_final = True
            if force_final or round_number == limits.max_model_rounds - 1:
                request.messages.append(ProviderMessage(role="system", content="Tool and context budget has been reached. Answer now using only available information. Do not call additional tools."))
                request.tools = []; request.tool_choice = "none"; force_final = True

        raise AIError(AIErrorCode.tool_loop_limit, "Model did not produce a final answer within the allowed rounds.", status_code=502)
