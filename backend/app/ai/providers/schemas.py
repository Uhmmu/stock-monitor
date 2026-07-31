from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderToolCall(StrictProviderModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ProviderMessage(StrictProviderModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ProviderToolCall] = Field(default_factory=list)


class ProviderToolDefinition(StrictProviderModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ProviderRequest(StrictProviderModel):
    model: str
    messages: list[ProviderMessage]
    tools: list[ProviderToolDefinition] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = "auto"
    temperature: float | None = None
    max_output_tokens: int | None = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderUsage(StrictProviderModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ProviderResponse(StrictProviderModel):
    response_id: str | None = None
    content: str | None = None
    tool_calls: list[ProviderToolCall] = Field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter", "error", "unknown"] = "unknown"
    usage: ProviderUsage | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderStreamEvent(StrictProviderModel):
    type: Literal[
        "response_started", "text_delta", "tool_call_started",
        "tool_call_arguments_delta", "tool_call_completed", "usage",
        "response_completed", "error",
    ]
    response_id: str | None = None
    text_delta: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    arguments: dict[str, Any] | None = None
    usage: ProviderUsage | None = None
    error_code: str | None = None
    error_message: str | None = None
