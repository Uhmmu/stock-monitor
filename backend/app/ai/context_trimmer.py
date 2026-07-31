from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .enums import AIErrorCode
from .exceptions import AIError
from .providers.schemas import ProviderMessage


class TrimmedContext(BaseModel):
    messages: list[ProviderMessage]
    chars: int
    warnings: list[str] = Field(default_factory=list)


def _chars(messages: list[ProviderMessage]) -> int:
    return len(json.dumps([message.model_dump(mode="json") for message in messages], ensure_ascii=False, separators=(",", ":")))


class ContextTrimmer:
    """Deterministically trim tool data while preserving message pair integrity."""

    def trim(self, messages: list[ProviderMessage], max_chars: int) -> TrimmedContext:
        values = [message.model_copy(deep=True) for message in messages]
        if _chars(values) <= max_chars:
            return TrimmedContext(messages=values, chars=_chars(values))
        if _chars(values[:2]) > max_chars:
            raise AIError(AIErrorCode.context_too_large, "The fixed request context exceeds its budget.", status_code=422)
        warnings = ["Older or detailed tool context was trimmed to the context budget."]

        # First preserve every assistant/tool pair and remove only bulky data.
        for message in values:
            if message.role != "tool" or not message.content or "\n" not in message.content:
                continue
            prefix, raw = message.content.split("\n", 1)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("data") is not None:
                payload["data"] = None
                payload.setdefault("warnings", []).append({"code": "AI_CONTEXT_TRIMMED"})
                message.content = prefix + "\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
            if _chars(values) <= max_chars:
                return TrimmedContext(messages=values, chars=_chars(values), warnings=warnings)

        # Then drop complete older assistant-tool groups. The latest group is
        # retained because it has the highest relevance for the next turn.
        groups: list[tuple[int, int]] = []
        index = 2
        while index < len(values):
            if values[index].role == "assistant" and values[index].tool_calls:
                end = index + 1
                while end < len(values) and values[end].role == "tool":
                    end += 1
                groups.append((index, end))
                index = end
            else:
                index += 1
        for start, end in reversed(groups[:-1]):
            del values[start:end]
            if _chars(values) <= max_chars:
                return TrimmedContext(messages=values, chars=_chars(values), warnings=warnings)

        if _chars(values) > max_chars:
            raise AIError(AIErrorCode.context_too_large, "Tool context cannot fit without breaking the latest tool-call pair.", status_code=422)
        return TrimmedContext(messages=values, chars=_chars(values), warnings=warnings)
