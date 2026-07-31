from __future__ import annotations

import json

from .adapters.base import BaseToolAdapter
from .enums import ToolErrorCode
from .exceptions import ToolError


class ToolRegistry:
    def __init__(self): self._adapters: dict[str, BaseToolAdapter] = {}

    def register(self, adapter: BaseToolAdapter) -> None:
        definition = adapter.definition
        if definition.name in self._adapters: raise ValueError(f"duplicate tool name: {definition.name}")
        if adapter.arguments_model.model_json_schema() != definition.input_schema:
            raise ValueError(f"input schema mismatch for {definition.name}")
        json.dumps(definition.model_dump(mode="json"))
        self._adapters[definition.name] = adapter

    def get(self, name: str) -> BaseToolAdapter:
        try: return self._adapters[name]
        except KeyError as exc: raise ToolError(ToolErrorCode.not_found, "The requested tool does not exist.") from exc

    def list(self, *, domain: str | None = None, enabled_only: bool = True):
        values = [a.definition for a in self._adapters.values()]
        if domain is not None: values = [d for d in values if d.domain == domain]
        if enabled_only: values = [d for d in values if d.enabled]
        return sorted(values, key=lambda d: d.name)

    def export_openai_tools(self, *, allowed_tools: set[str] | None = None, domain: str | None = None):
        definitions = self.list(domain=domain)
        if allowed_tools is not None: definitions = [d for d in definitions if d.name in allowed_tools]
        return [{"type": "function", "function": {"name": d.name, "description": d.description, "parameters": d.input_schema}} for d in definitions]


tool_registry = ToolRegistry()

