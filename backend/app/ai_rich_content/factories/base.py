from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field

from app.ai.schemas import Citation
from app.ai_tools.compression import json_default
from app.ai_tools.schemas import ToolExecutionResult
from app.research.security import safe_external_url

from ..fallback import block_fallback_markdown
from ..registry import RichBlockRegistry, rich_block_registry
from ..schemas import (
    BlockFreshness,
    BlockInteractionConfig,
    RichBlock,
    RichBlockCandidate,
)


class RichBlockFactoryContext(BaseModel):
    citations: list[Citation] = Field(default_factory=list)
    timezone: str = "Asia/Shanghai"
    max_block_data_chars: int = 30000
    max_chart_points: int = 500
    max_chart_series: int = 5
    max_table_rows: int = 100
    max_table_columns: int = 12
    max_timeline_items: int = 30
    max_news_sources: int = 10
    max_metrics: int = 16


class BaseRichBlockFactory(ABC):
    supported_tool_names: set[str]

    @abstractmethod
    def build(
        self,
        *,
        tool_result: ToolExecutionResult,
        context: RichBlockFactoryContext,
    ) -> list[RichBlockCandidate]:
        raise NotImplementedError


def mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [mapping(item) for item in value if mapping(item)]
    body = mapping(value)
    for key in ("items", "rows", "results", "events", "positions"):
        if isinstance(body.get(key), list):
            return [mapping(item) for item in body[key] if mapping(item)]
    return []


def decimal_value(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def datetime_value(value: Any, *, end_of_day: bool = False) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(
            value.year,
            value.month,
            value.day,
            23 if end_of_day else 0,
            59 if end_of_day else 0,
            tzinfo=UTC,
        )
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(value[:10])
            except ValueError:
                return None
            return datetime(
                parsed_date.year,
                parsed_date.month,
                parsed_date.day,
                tzinfo=UTC,
            )
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def warning_texts(result: ToolExecutionResult) -> list[str]:
    output = []
    for item in result.warnings:
        value = mapping(item)
        text = value.get("message") if value else str(item)
        if text and text not in output:
            output.append(str(text)[:500])
    return output[:20]


def block_freshness(result: ToolExecutionResult) -> BlockFreshness:
    raw = mapping(result.freshness)
    status = str(raw.get("status") or "unknown").lower()
    normalized = {
        "live": "fresh",
        "current": "fresh",
        "fresh": "fresh",
        "aging": "aging",
        "stale": "stale",
        "expired": "stale",
    }.get(status, "unknown")
    as_of = datetime_value(raw.get("as_of"))
    retrieved = datetime_value(raw.get("retrieved_at")) or result.stats.completed_at
    label = None
    if as_of:
        label = f"截至 {as_of.astimezone(UTC):%Y-%m-%d %H:%M} UTC"
    elif normalized == "unknown":
        label = "数据时间未知"
    return BlockFreshness(
        as_of=as_of,
        retrieved_at=retrieved,
        status=normalized,
        label=label,
    )


def safe_url(value: Any) -> str | None:
    return safe_external_url(value if isinstance(value, str) else None)


def stable_block_id(tool_result: ToolExecutionResult, block_type: str, index: int) -> str:
    digest = sha256(
        f"{tool_result.tool_name}:{tool_result.tool_call_id}:{block_type}:{index}".encode()
    ).hexdigest()[:12]
    return f"block_{block_type}_{digest}"


def create_candidate(
    *,
    tool_result: ToolExecutionResult,
    context: RichBlockFactoryContext,
    block_type: str,
    data: dict[str, Any],
    index: int = 0,
    title: str | None = None,
    subtitle: str | None = None,
    description: str,
    recommended_position: str = "after_related_text",
    interaction: BlockInteractionConfig | None = None,
    registry: RichBlockRegistry = rich_block_registry,
) -> RichBlockCandidate:
    block_id = stable_block_id(tool_result, block_type, index)
    citation_keys = list(dict.fromkeys(item.key for item in context.citations))[:100]
    source_ids = list(dict.fromkeys(item.source_id for item in context.citations))[:100]
    block = RichBlock(
        block_id=block_id,
        block_type=block_type,
        block_version=1,
        title=title,
        subtitle=subtitle,
        data=data,
        citation_keys=citation_keys,
        source_ids=source_ids,
        freshness=block_freshness(tool_result),
        warnings=warning_texts(tool_result),
        fallback_markdown="pending",
        interaction=interaction,
    )
    block = registry.validate_block(block)
    encoded = json.dumps(
        block.data,
        ensure_ascii=False,
        separators=(",", ":"),
        default=json_default,
    )
    if len(encoded) > context.max_block_data_chars:
        raise ValueError(f"{block_type} block data exceeds its configured budget")
    fallback = block_fallback_markdown(
        block_type, block.data, title=title
    )[:30000]
    block = block.model_copy(update={"fallback_markdown": fallback})
    return RichBlockCandidate(
        block_id=block.block_id,
        block_type=block.block_type,
        block_version=block.block_version,
        tool_name=tool_result.tool_name,
        tool_call_id=tool_result.tool_call_id,
        relevance_hint=description[:300],
        recommended_position=recommended_position,
        block=block,
    )


def display_number(value: Any, unit: str | None = None) -> str:
    number = decimal_value(value)
    if number is None:
        return "数据不足"
    amount = float(number)
    magnitude = abs(amount)
    if magnitude >= 1_000_000_000:
        rendered = f"{amount / 1_000_000_000:.2f}B"
    elif magnitude >= 1_000_000:
        rendered = f"{amount / 1_000_000:.2f}M"
    elif magnitude >= 1_000:
        rendered = f"{amount:,.0f}"
    else:
        rendered = f"{amount:,.2f}".rstrip("0").rstrip(".")
    if unit in {"percent", "%"}:
        return f"{rendered}%"
    return f"{rendered} {unit}".strip() if unit and unit not in {"currency"} else rendered


def clean_identifier(value: Any, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:\-]", "-", str(value or default))[:128]
    return cleaned or default


def downsample_points(points: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(points) <= limit:
        return points
    if limit <= 2:
        return [points[0], points[-1]][:limit]
    indexes = {
        round(index * (len(points) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [points[index] for index in sorted(indexes)]
