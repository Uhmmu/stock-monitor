"""Pi Agent sidecar client for the agent-driven discovery engine.

The sidecar (see ``pi-agent/`` at the repo root) hosts the research agent
loop: internal tools first, Exa retrieval second, a mandatory counter-evidence
stage, then a terminating structured-output tool call. This client posts one
run request and waits for the final JSON payload (long-poll up to the request
timeout), mirroring the Perplexity/Exa clients' result contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings

from .prompt import PI_SYSTEM_INSTRUCTIONS
from .schemas import DiscoveryResult


class PiAgentError(RuntimeError):
    code = "upstream_error"
    retryable = False

    def __init__(self, message: str, *, raw_response: dict | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class PiAgentConfigurationError(PiAgentError):
    code = "missing_configuration"


class PiAgentTransientError(PiAgentError):
    code = "temporarily_unavailable"
    retryable = True


class PiAgentResponseError(PiAgentError):
    code = "invalid_response"


@dataclass(frozen=True)
class PiAgentResult:
    parsed: DiscoveryResult
    raw_response: dict
    output_text: str
    tool_results: list[dict]
    model: str
    usage: dict
    events: list[dict] = field(default_factory=list)
    finance_search_calls: int = 0
    web_search_calls: int = 0
    deep_search_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_cost_usd: float = 0.0
    model_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


def build_request(
    *, run_id: int, user_id: int, context: dict, model: str,
    max_turns: int, max_web_search_calls: int, deep_effort: str,
    max_output_tokens: int,
) -> dict:
    settings = get_settings()
    return {
        "run_id": run_id,
        "user_id": user_id,
        "model": model,
        "system_prompt": PI_SYSTEM_INSTRUCTIONS,
        "context": context,
        "limits": {
            "max_turns": max_turns,
            "max_web_search_calls": max_web_search_calls,
            "deep_effort": deep_effort,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": settings.pi_agent_timeout_seconds,
        },
        "output_schema": DiscoveryResult.model_json_schema(),
    }


def parse_response(payload: dict) -> PiAgentResult:
    if payload.get("status") != "completed":
        message = str(payload.get("error") or "Pi Agent 未返回完成状态")
        if payload.get("retryable"):
            raise PiAgentTransientError(message, raw_response=payload)
        raise PiAgentResponseError(message, raw_response=payload)
    raw_result = payload.get("result") or {}
    if not isinstance(raw_result, dict):
        raise PiAgentResponseError("Pi Agent 响应缺少 result 对象", raw_response=payload)
    try:
        parsed = DiscoveryResult.model_validate(raw_result)
    except (ValidationError, ValueError) as exc:
        raise PiAgentResponseError("Pi Agent 返回的 JSON 不符合机会发现结构", raw_response=payload) from exc
    usage = payload.get("usage") or {}
    tool_cost = float(usage.get("tool_cost_usd") or 0)
    model_cost = float(usage.get("model_cost_usd") or 0)
    return PiAgentResult(
        parsed=parsed,
        raw_response=payload,
        output_text=str(payload.get("output_text") or ""),
        tool_results=payload.get("tool_results") or [],
        model=str(payload.get("model") or ""),
        usage=usage,
        events=payload.get("events") or [],
        web_search_calls=int(usage.get("web_search_calls") or 0),
        deep_search_calls=int(usage.get("deep_search_calls") or 0),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        tool_cost_usd=tool_cost,
        model_cost_usd=model_cost,
        total_cost_usd=tool_cost + model_cost,
    )


def run_agent(request: dict) -> PiAgentResult:
    settings = get_settings()
    token = settings.agent_gateway_token.strip()
    if not token:
        raise PiAgentConfigurationError("尚未配置 AGENT_GATEWAY_TOKEN（Pi Agent 引擎需要它）")
    base_url = settings.pi_agent_base_url.rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/run",
            headers={"X-Agent-Token": token, "Content-Type": "application/json"},
            json=request,
            timeout=settings.pi_agent_request_timeout_seconds,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise PiAgentTransientError("Pi Agent sidecar 暂时不可用") from exc
    if response.status_code in (401, 403):
        raise PiAgentConfigurationError("Pi Agent sidecar 拒绝了网关令牌")
    if response.status_code == 429:
        raise PiAgentTransientError("Pi Agent sidecar 当前忙碌")
    if response.status_code >= 500:
        raise PiAgentTransientError("Pi Agent sidecar 服务暂时不可用")
    if response.status_code >= 400:
        raise PiAgentResponseError(f"Pi Agent 请求无效（HTTP {response.status_code}）")
    try:
        payload = response.json()
    except ValueError as exc:
        raise PiAgentResponseError("Pi Agent 返回了非 JSON 响应") from exc
    return parse_response(payload)


def usage_from_tool_calls(tool_calls: list[dict]) -> dict:
    """Aggregate per-tool-call costs reported back by the sidecar gateway."""
    web_calls = 0
    deep_calls = 0
    tool_cost = 0.0
    for call in tool_calls:
        name = str(call.get("tool_name") or "")
        cost = float(call.get("cost_usd") or 0)
        tool_cost += cost
        if name == "run_deep_web_research":
            deep_calls += 1
        elif name.startswith("search_"):
            web_calls += 1
    return {
        "web_search_calls": web_calls,
        "deep_search_calls": deep_calls,
        "tool_cost_usd": round(tool_cost, 6),
    }
