from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from app.config import get_settings

from .schemas import OpportunityBatch


class AnalysisError(RuntimeError):
    code = "analysis_output_invalid"
    retryable = False


SYSTEM_PROMPT = """你是一名严谨的 buy-side research analyst。你的任务是从外部搜索结果与项目本地事实中发现值得进一步研究的股票机会。

硬性规则：
1. Perplexity Search 结果只用于 Why now、新闻事件、行业逻辑、市场情绪与投资者关注点。
2. 当前价格、PE、市值和财报数字只能引用 local_data；搜索摘要中的这些数字不得当作财务证据。
3. 不得编造数据。证据不足时明确写“数据不足”，并降低 confidence。
4. 区分事实与判断；每条 evidence.type 只能是 financial、news、market。
5. 不输出买入、卖出、仓位或目标价建议；action 只能使用关注、深入研究、等待确认。
6. 排除当前持仓中的股票。优先寻找与组合互补且有明确 Why now 的机会。
7. 使用中文输出，ticker 使用规范交易代码。
8. 严格使用 required_output_schema 指定的字段名和类型；不要增加或改名字段。
"""


@dataclass(frozen=True)
class AnalysisResult:
    parsed: OpportunityBatch
    output_text: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


def _json_schema() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "opportunity_discovery_v05",
            "strict": True,
            "schema": OpportunityBatch.model_json_schema(),
        },
    }


_CATEGORIES = {"估值错杀", "行业趋势", "盈利改善", "事件驱动", "技术反转", "长期成长"}
_ACTIONS = {"关注", "深入研究", "等待确认"}


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return "；".join(str(item).strip() for item in value.values() if str(item).strip())
    return str(value).strip() if value is not None else ""


def _category(item: dict) -> list[str]:
    supplied = [_text(value) for value in _as_list(item.get("category"))]
    valid = [value for value in supplied if value in _CATEGORIES]
    if valid:
        return list(dict.fromkeys(valid))
    searchable = " ".join(
        _text(item.get(key))
        for key in ("title", "summary", "why_now", "thesis", "sector")
    )
    for keywords, category in (
        (("低估", "错杀", "估值"), "估值错杀"),
        (("盈利", "利润", "现金流", "业绩"), "盈利改善"),
        (("事件", "催化", "监管", "发布"), "事件驱动"),
        (("反转", "技术面"), "技术反转"),
        (("长期", "成长", "复利"), "长期成长"),
    ):
        if any(keyword in searchable for keyword in keywords):
            return [category]
    return ["行业趋势"]


def _normalize_opportunity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the compact schema some OpenAI-compatible endpoints emit.

    The configured endpoint may accept ``response_format`` without enforcing it.
    Preserve the model's facts while adapting harmless field-name/type variations
    instead of turning a paid discovery run into a generic persistence failure.
    """
    normalized = {
        "market_condition": _text(payload.get("market_condition")) or "数据不足",
        "opportunities": [],
    }
    for raw in _as_list(payload.get("opportunities"))[:12]:
        if not isinstance(raw, dict) or not _text(raw.get("ticker")):
            continue
        why_now = [_text(value) for value in _as_list(raw.get("why_now")) if _text(value)]
        thesis = raw.get("thesis")
        thesis_text = _text(thesis)
        summary = _text(raw.get("summary")) or thesis_text or (why_now[0] if why_now else "")
        title = _text(raw.get("title")) or summary or (
            f"{_text(raw.get('company_name')) or _text(raw.get('ticker'))} 研究机会"
        )
        evidence = []
        for row in _as_list(raw.get("evidence")):
            if isinstance(row, dict):
                evidence_type = _text(row.get("type"))
                content = _text(row.get("content")) or _text(row.get("fact"))
            else:
                evidence_type, content = "market", _text(row)
            if content:
                evidence.append({
                    "type": evidence_type if evidence_type in {"financial", "news", "market"} else "market",
                    "content": content,
                })
        if not evidence:
            evidence = [{"type": "market", "content": "数据不足，需进一步核对"}]
        risks = [
            _text(value)
            for value in _as_list(raw.get("risks") or raw.get("key_risks"))
            if _text(value)
        ] or ["数据覆盖不足"]
        catalysts = [
            _text(value)
            for value in _as_list(raw.get("catalysts"))
            if _text(value)
        ]
        confidence = raw.get("confidence", 0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0
        if 0 <= confidence <= 1:
            confidence *= 100
        action = [
            _text(value)
            for value in _as_list(raw.get("action"))
            if _text(value) in _ACTIONS
        ] or ["等待确认"]
        normalized["opportunities"].append({
            "title": title,
            "ticker": _text(raw.get("ticker")),
            "category": _category(raw),
            "summary": summary or "值得进一步研究，但当前依据有限",
            "why_now": why_now or ["近期催化剂仍需进一步确认"],
            "evidence": evidence,
            "catalysts": catalysts,
            "risks": risks,
            "valuation_view": _text(raw.get("valuation_view")) or "数据不足",
            "confidence": max(0, min(100, round(confidence))),
            "action": action,
        })
    return normalized


def parse_opportunity_output(text: str) -> OpportunityBatch:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise AnalysisError("机会发现引擎返回了无效 JSON") from exc
    try:
        return OpportunityBatch.model_validate(payload)
    except ValidationError:
        try:
            return OpportunityBatch.model_validate(_normalize_opportunity_payload(payload))
        except ValidationError as exc:
            raise AnalysisError("机会发现引擎返回的数据结构无法识别") from exc


def analyze_opportunities(*, search_results: list[dict], local_context: dict, max_output_tokens: int) -> AnalysisResult:
    settings = get_settings()
    if not settings.openai_api_key.strip():
        raise RuntimeError("尚未配置 OPENAI_API_KEY")
    model = settings.model_important
    payload = {
        "search_results": search_results,
        "local_data": local_context,
        "required_output": {
            "market_condition": "当时市场环境的简短描述",
            "opportunities": "1-12 个符合固定结构的机会",
        },
        "required_output_schema": {
            "market_condition": "string",
            "opportunities": [{
                "title": "string",
                "ticker": "string",
                "category": ["估值错杀|行业趋势|盈利改善|事件驱动|技术反转|长期成长"],
                "summary": "string",
                "why_now": ["string"],
                "evidence": [{"type": "financial|news|market", "content": "string"}],
                "catalysts": ["string"],
                "risks": ["string"],
                "valuation_view": "string",
                "confidence": "integer 0-100",
                "action": ["关注|深入研究|等待确认"],
            }],
        },
    }
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ],
        response_format=_json_schema(),
        max_completion_tokens=max_output_tokens,
    )
    text = response.choices[0].message.content or ""
    parsed = parse_opportunity_output(text)
    usage = response.usage
    return AnalysisResult(
        parsed=parsed,
        output_text=text,
        model=model,
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )
