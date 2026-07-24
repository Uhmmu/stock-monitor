from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings

from .prompt import SYSTEM_INSTRUCTIONS, build_input
from .schemas import DiscoveryResult


class PerplexityError(RuntimeError):
    code = "upstream_error"
    retryable = False

    def __init__(self, message: str, *, raw_response: dict | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class PerplexityConfigurationError(PerplexityError):
    code = "missing_api_key"


class PerplexityAuthenticationError(PerplexityError):
    code = "authentication_failed"


class PerplexityRateLimitError(PerplexityError):
    code = "rate_limited"
    retryable = True


class PerplexityTransientError(PerplexityError):
    code = "temporarily_unavailable"
    retryable = True


class PerplexityResponseError(PerplexityError):
    code = "invalid_response"


@dataclass(frozen=True)
class AgentResult:
    parsed: DiscoveryResult
    raw_response: dict
    output_text: str
    tool_results: list[dict]
    model: str
    usage: dict
    finance_search_calls: int
    web_search_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_cost_usd: float
    model_cost_usd: float
    total_cost_usd: float


def _inline_schema(schema: dict) -> dict:
    """Inline Pydantic's local refs because Agent schemas reject external refs."""
    definitions = schema.get("$defs", {})

    def expand(value: Any) -> Any:
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        ref = value.get("$ref")
        if ref and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            return expand(copy.deepcopy(definitions[name]))
        return {key: expand(item) for key, item in value.items() if key != "$defs"}

    return expand(schema)


def response_schema() -> dict:
    return _inline_schema(DiscoveryResult.model_json_schema())


def build_request(*, context: dict, model: str, max_steps: int, max_output_tokens: int, enable_web_search: bool) -> dict:
    tools = [{"type": "finance_search"}]
    if enable_web_search:
        tools.append({"type": "web_search"})
    return {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": build_input(context),
        "tools": tools,
        "max_steps": max_steps,
        "max_output_tokens": max_output_tokens,
        "language_preference": "zh",
        "store": False,
        "response_format": {
            "type": "json_schema",
            # Perplexity requires schema names to be alphanumeric (no underscores).
            "json_schema": {"name": "stockdiscoveryv04", "schema": response_schema()},
        },
    }


def _message_text(payload: dict) -> str:
    parts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") in (None, "output_text") and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "".join(parts)


def _tool_outputs(payload: dict) -> tuple[list[dict], int, int]:
    results, finance_count, web_count = [], 0, 0
    for item in payload.get("output") or []:
        kind = str(item.get("type") or "")
        if kind == "finance_results":
            finance_count += 1
            results.append(item)
        elif kind in ("search_results", "web_search_results"):
            web_count += 1
            results.append(item)
    details = ((payload.get("usage") or {}).get("tool_calls_details") or {})
    if isinstance(details, dict):
        def count(value: Any) -> int:
            if isinstance(value, dict):
                value = value.get("count", value.get("calls", value.get("invocations", 0)))
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0
        finance_count = max(finance_count, count(details.get("finance_search", details.get("finance_search_calls", 0))))
        web_count = max(web_count, count(details.get("web_search", details.get("web_search_calls", 0))))
    return results, finance_count, web_count


def parse_agent_response(payload: dict) -> AgentResult:
    if payload.get("status") not in (None, "completed"):
        error = payload.get("error") or {}
        raise PerplexityResponseError(error.get("message") or "Agent API 未完成请求", raw_response=payload)
    output_text = _message_text(payload)
    if not output_text:
        raise PerplexityResponseError("Agent API 响应不含结构化文本", raw_response=payload)
    try:
        parsed = DiscoveryResult.model_validate_json(output_text)
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        raise PerplexityResponseError("Agent API 返回的 JSON 不符合 stock-discovery-schema-v0.4", raw_response=payload) from exc
    tool_results, finance_calls, web_calls = _tool_outputs(payload)
    usage = payload.get("usage") or {}
    costs = usage.get("cost") or {}
    total_cost = float(costs.get("total_cost") or 0)
    tool_cost = float(costs.get("tool_calls_cost") or 0)
    input_cost = float(costs.get("input_cost") or 0)
    output_cost = float(costs.get("output_cost") or 0)
    model_cost = input_cost + output_cost
    if model_cost == 0 and total_cost:
        model_cost = max(0.0, total_cost - tool_cost)
    return AgentResult(
        parsed=parsed, raw_response=payload, output_text=output_text, tool_results=tool_results,
        model=str(payload.get("model") or ""), usage=usage,
        finance_search_calls=finance_calls, web_search_calls=web_calls,
        input_tokens=int(usage.get("input_tokens") or 0), output_tokens=int(usage.get("output_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0), tool_cost_usd=tool_cost,
        model_cost_usd=model_cost, total_cost_usd=total_cost,
    )


def run_agent(request: dict) -> AgentResult:
    settings = get_settings()
    key = settings.perplexity_api_key.strip()
    if not key:
        raise PerplexityConfigurationError("尚未配置 Perplexity API Key")
    try:
        response = httpx.post(
            settings.perplexity_agent_url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=request,
            timeout=settings.perplexity_request_timeout_seconds,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise PerplexityTransientError("Perplexity 请求暂时不可用") from exc
    if response.status_code in (401, 403):
        raise PerplexityAuthenticationError("Perplexity API Key 无效或无 finance_search 权限")
    if response.status_code == 429:
        raise PerplexityRateLimitError("Perplexity 当前请求受限")
    if response.status_code >= 500:
        raise PerplexityTransientError("Perplexity 服务暂时不可用")
    if response.status_code >= 400:
        try:
            detail = (response.json().get("error") or {}).get("message")
        except Exception:
            detail = None
        try:
            raw_error = response.json()
        except ValueError:
            raw_error = None
        raise PerplexityResponseError(detail or f"Perplexity 请求配置无效（HTTP {response.status_code}）", raw_response=raw_error)
    try:
        payload = response.json()
    except ValueError as exc:
        raise PerplexityResponseError("Perplexity 返回了非 JSON 响应") from exc
    return parse_agent_response(payload)
