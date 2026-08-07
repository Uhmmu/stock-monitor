from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import get_settings

from .prompt import SYSTEM_INSTRUCTIONS, build_input
from .schemas import DiscoveryResult


_PERPLEXITY_TOOL_INSTRUCTIONS = (
    "Use finance_search for financial and market claims. Use web_search only for current qualitative flow, "
    "breadth, policy, catalyst, or sentiment context that finance_search cannot provide."
)
_EXA_TOOL_INSTRUCTIONS = (
    "Use the attached Financial Datasets provider for ticker screening, prices, fundamentals, earnings, "
    "financial statements, valuation, SEC filings, ownership, and other financial or market claims. Use Exa "
    "web research for current qualitative flow, breadth, policy, catalysts, sentiment, and primary-source "
    "confirmation that Financial Datasets cannot provide."
)
EXA_SYSTEM_INSTRUCTIONS = SYSTEM_INSTRUCTIONS.replace(
    _PERPLEXITY_TOOL_INSTRUCTIONS,
    _EXA_TOOL_INSTRUCTIONS,
)


class ExaError(RuntimeError):
    code = "upstream_error"
    retryable = False

    def __init__(self, message: str, *, raw_response: dict | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class ExaConfigurationError(ExaError):
    code = "missing_api_key"


class ExaAuthenticationError(ExaError):
    code = "authentication_failed"


class ExaBudgetError(ExaError):
    code = "upstream_budget_exceeded"


class ExaRateLimitError(ExaError):
    code = "rate_limited"
    retryable = True


class ExaTransientError(ExaError):
    code = "temporarily_unavailable"
    retryable = True


class ExaResponseError(ExaError):
    code = "invalid_response"


@dataclass(frozen=True)
class ExaAgentResult:
    parsed: DiscoveryResult
    raw_response: dict
    output_text: str
    grounding: list[dict]
    usage: dict
    finance_data_calls: int
    web_search_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_cost_usd: float
    model_cost_usd: float
    total_cost_usd: float
    model: str = "exa-agent"


def build_request(*, context: dict, effort: str) -> dict:
    return {
        "query": build_input(context),
        "systemPrompt": EXA_SYSTEM_INSTRUCTIONS,
        "effort": effort,
        "dataSources": [{"provider": "financial_datasets"}],
        "outputSchema": DiscoveryResult.model_json_schema(),
    }


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        value = value.get("count", value.get("calls", value.get("invocations", 0)))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cost_parts(payload: dict) -> tuple[float, float, float]:
    costs = payload.get("costDollars") or {}
    if isinstance(costs, (int, float)):
        return 0.0, float(costs), float(costs)
    total = _number(costs.get("total") or costs.get("totalCost"))
    data_source_costs = costs.get("dataSources") or costs.get("dataSource") or costs.get("connect") or {}
    data_source_total = (
        sum(_number(value) for value in data_source_costs.values())
        if isinstance(data_source_costs, dict)
        else _number(data_source_costs)
    )
    tool = _number(costs.get("search") or costs.get("searches")) + data_source_total
    if not total:
        total = sum(_number(value) for value in costs.values() if isinstance(value, (int, float)))
    tool = min(tool, total)
    return tool, max(0.0, total - tool), total


def parse_agent_response(payload: dict) -> ExaAgentResult:
    status = payload.get("status")
    if status != "completed":
        reason = payload.get("failReason") or payload.get("failureReason") or payload.get("stopReason")
        raise ExaResponseError(f"Exa Agent 未完成请求：{reason or status or '未知状态'}", raw_response=payload)
    output = payload.get("output") or {}
    structured = output.get("structured")
    if not isinstance(structured, dict):
        raise ExaResponseError("Exa Agent 响应不含结构化结果", raw_response=payload)
    try:
        parsed = DiscoveryResult.model_validate(structured)
    except (ValidationError, ValueError) as exc:
        raise ExaResponseError("Exa Agent 返回的 JSON 不符合机会发现结构", raw_response=payload) from exc
    usage = payload.get("usage") or {}
    data_calls = (
        usage.get("dataSources")
        or usage.get("dataSourceCalls")
        or usage.get("data_source_calls")
        or {}
    )
    if isinstance(data_calls, dict):
        finance_calls = _count(data_calls.get("financial_datasets"))
    else:
        finance_calls = _count(data_calls)
    search_calls = _count(usage.get("searches", usage.get("searchCalls", usage.get("search_calls", 0))))
    input_tokens = _count(usage.get("inputTokens", usage.get("input_tokens", 0)))
    output_tokens = _count(usage.get("outputTokens", usage.get("output_tokens", 0)))
    total_tokens = _count(usage.get("totalTokens", usage.get("total_tokens", input_tokens + output_tokens)))
    tool_cost, model_cost, total_cost = _cost_parts(payload)
    return ExaAgentResult(
        parsed=parsed,
        raw_response=payload,
        output_text=json.dumps(structured, ensure_ascii=False),
        grounding=output.get("grounding") or [],
        usage=usage,
        finance_data_calls=finance_calls,
        web_search_calls=search_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        tool_cost_usd=tool_cost,
        model_cost_usd=model_cost,
        total_cost_usd=total_cost,
    )


def _headers(key: str) -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Exa-Beta": settings.exa_agent_beta,
    }


def _checked_json(response: httpx.Response) -> dict:
    if response.status_code in (401, 403):
        raise ExaAuthenticationError("Exa API Key 无效或无 Agent / Financial Datasets 权限")
    if response.status_code == 402:
        raise ExaBudgetError("Exa 账户余额或 API Key 预算不足")
    if response.status_code == 429:
        raise ExaRateLimitError("Exa Agent 当前请求受限")
    if response.status_code >= 500:
        raise ExaTransientError("Exa Agent 服务暂时不可用")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExaResponseError("Exa Agent 返回了非 JSON 响应") from exc
    if response.status_code >= 400:
        detail = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("tag")
        raise ExaResponseError(str(detail or f"Exa Agent 请求失败（HTTP {response.status_code}）"), raw_response=payload)
    return payload


def run_agent(request: dict) -> ExaAgentResult:
    settings = get_settings()
    key = settings.exa_api_key.strip()
    if not key:
        raise ExaConfigurationError("尚未配置 Exa API Key")
    started = time.monotonic()
    try:
        response = httpx.post(
            settings.exa_agent_url,
            headers=_headers(key),
            json=request,
            timeout=min(60, settings.exa_agent_timeout_seconds),
        )
        payload = _checked_json(response)
        run_id = str(payload.get("id") or "")
        if not run_id:
            raise ExaResponseError("Exa Agent 未返回 run id", raw_response=payload)
        while payload.get("status") in ("queued", "running"):
            if time.monotonic() - started >= settings.exa_agent_timeout_seconds:
                raise ExaTransientError("Exa Agent 深度研究超时")
            time.sleep(max(0.25, settings.exa_agent_poll_interval_seconds))
            response = httpx.get(
                f"{settings.exa_agent_url.rstrip('/')}/{run_id}",
                headers=_headers(key),
                timeout=min(60, settings.exa_agent_timeout_seconds),
            )
            payload = _checked_json(response)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise ExaTransientError("Exa Agent 请求暂时不可用") from exc
    return parse_agent_response(payload)
