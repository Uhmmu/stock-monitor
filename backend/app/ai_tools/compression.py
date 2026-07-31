from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from .enums import ResultMode


@dataclass
class CompressionResult:
    data: Any
    original_item_count: int | None
    returned_item_count: int | None
    chars: int
    truncated: bool
    warnings: list[dict[str, str]]


def json_default(value: Any):
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Decimal): return float(value)
    if hasattr(value, "value"): return value.value
    return str(value)


def json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=json_default, separators=(",", ":")))


class ToolResultCompressor:
    text_limits: ClassVar[dict[str, int]] = {"title": 300, "summary": 1500, "ai_summary": 3000, "text_summary": 3000,
                   "content": 3000, "evidence": 2000, "reasoning": 2000, "analysis_summary": 3000}

    def _clean(self, value: Any, key: str = "", depth: int = 0) -> Any:
        if depth > 8: return None
        if isinstance(value, dict):
            result = {}
            for raw_key, item in value.items():
                field = str(raw_key)
                if field.lower() in {"raw_payload", "response_json", "prompt", "credentials", "authorization", "tool_results"}: continue
                cleaned = self._clean(item, field, depth + 1)
                if cleaned not in (None, [], {}): result[field] = cleaned
            return result
        if isinstance(value, (list, tuple)): return [item for raw in value if (item := self._clean(raw, key, depth + 1)) not in (None, [], {})]
        if isinstance(value, str):
            limit = self.text_limits.get(key, 4000)
            return value if len(value) <= limit else value[: limit - 1] + "…"
        return value

    def compress(self, *, tool_name: str, data: Any, result_mode: ResultMode, max_chars: int, max_items: int | None) -> CompressionResult:
        clean = self._clean(data)
        original = len(clean) if isinstance(clean, list) else None
        mode_limit = {ResultMode.compact: 10, ResultMode.standard: 30, ResultMode.detailed: 100}[result_mode]
        item_limit = min(x for x in (max_items, mode_limit) if x is not None)
        truncated = False
        if isinstance(clean, list) and len(clean) > item_limit:
            clean, truncated = clean[:item_limit], True
        while json_size(clean) > max_chars:
            truncated = True
            if isinstance(clean, list) and clean:
                clean = clean[:max(0, len(clean) - 1)]
            elif isinstance(clean, dict):
                # Preserve valid JSON by progressively shrinking nested lists and strings.
                changed = False
                for key in reversed(list(clean)):
                    value = clean[key]
                    if isinstance(value, list) and value:
                        clean[key] = value[:max(0, len(value) // 2)]; changed = True; break
                    if isinstance(value, str) and len(value) > 128:
                        clean[key] = value[:max(128, len(value) // 2)] + "…"; changed = True; break
                if not changed and clean:
                    clean.pop(next(reversed(clean))); changed = True
                if not changed: break
            else: break
        returned = len(clean) if isinstance(clean, list) else None
        warnings = ([{"code": "TOOL_RESULT_TRUNCATED", "message": f"{tool_name} output was deterministically truncated to its item or character budget.", "severity": "warning"}] if truncated else [])
        return CompressionResult(clean, original, returned, json_size(clean), truncated, warnings)


def deduplicate_sources(sources: list[Any]) -> list[dict[str, Any]]:
    result, seen = [], set()
    for item in sources:
        value = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        locator = value.get("locator")
        if locator and (locator.startswith("/") or ".." in locator): value["locator"] = None
        for field, limit in (("title", 300), ("url", 2048), ("locator", 512), ("provider", 200)):
            if isinstance(value.get(field), str) and len(value[field]) > limit: value[field] = value[field][:limit - 1] + "…"
        key = value.get("source_id") or json.dumps(value, sort_keys=True, default=json_default)
        if key not in seen:
            seen.add(key); result.append(value)
    return sorted(result, key=lambda item: str(item.get("source_id", "")))
