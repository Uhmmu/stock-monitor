from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai_rich_content.schemas import RichContentDocument
from app.external_search.enums import WebAccessMode
from app.research.exceptions import ResearchError
from app.research.security import normalize_symbol

PAGE_CONTEXTS = {"portfolio", "company", "news", "valuation", "technical", "calendar", "discovery"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _symbol(value: str) -> str:
    try:
        return normalize_symbol(value)
    except ResearchError as exc:
        raise ValueError(exc.message) from exc


class AIRespondRequest(StrictModel):
    message: str = Field(min_length=1, max_length=12000)
    active_symbol: str | None = None
    active_symbols: list[str] = Field(default_factory=list, max_length=20)
    active_portfolio_id: int | None = Field(None, gt=0)
    page_context: str | None = None
    stream: bool = True
    allowed_tools: list[str] | None = None
    denied_tools: list[str] = Field(default_factory=list)
    model: str | None = Field(None, min_length=1, max_length=200)
    web_access_mode: WebAccessMode = WebAccessMode.off
    deep_search_confirmed: bool = False
    user_message_id: int | None = Field(None, gt=0, exclude=True)
    assistant_message_id: int | None = Field(None, gt=0, exclude=True)
    generation_index: int | None = Field(None, ge=1, exclude=True)

    @field_validator("active_symbol")
    @classmethod
    def normalize_active_symbol(cls, value: str | None) -> str | None:
        return _symbol(value) if value else None

    @field_validator("active_symbols")
    @classmethod
    def normalize_active_symbols(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(_symbol(value) for value in values))

    @field_validator("page_context")
    @classmethod
    def page_context_allowed(cls, value: str | None) -> str | None:
        if value is not None and value not in PAGE_CONTEXTS:
            raise ValueError("unsupported page context")
        return value

    @field_validator("allowed_tools", "denied_tools")
    @classmethod
    def unique_tools(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if len(values) > 60:
            raise ValueError("too many tool names")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def merge_active_symbols(self):
        if self.active_symbol:
            self.active_symbols = [self.active_symbol] + [symbol for symbol in self.active_symbols if symbol != self.active_symbol]
        return self


class Citation(StrictModel):
    key: str
    source_id: str
    title: str
    source_type: str
    symbol: str | None = None
    provider: str | None = None
    authority: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    market_timestamp: datetime | None = None
    fetched_at: datetime | None = None
    persisted_at: datetime | None = None
    market_session: str | None = None
    data_status: str | None = None
    provider_role: str | None = None
    locator: str | None = None
    url: str | None = None


class AIToolCallRecord(StrictModel):
    tool_call_id: str
    tool: str
    status: str
    tool_version: str | None = None
    result_mode: str | None = None
    summary: str | None = None
    duration_ms: int = 0
    original_item_count: int | None = None
    returned_item_count: int | None = None
    warning_codes: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    truncated: bool = False
    error_code: str | None = None
    retryable: bool = False
    reused: bool = False
    external_provider: str | None = None
    external_request_id: str | None = None
    external_run_id: str | None = None
    cost_usd: float | None = None
    cost_estimated: bool = False
    # Persistence-only metadata. These fields are deliberately excluded from
    # API responses and SSE events.
    normalized_arguments: dict[str, Any] = Field(default_factory=dict, exclude=True)
    arguments_hash: str | None = Field(None, exclude=True)


class AIUsageSummary(StrictModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_rounds: int = 0
    tool_calls: int = 0


class AIRespondResponse(StrictModel):
    request_id: str
    response_id: str | None = None
    answer: str
    status: Literal["completed", "partial", "error"]
    citations: list[Citation] = Field(default_factory=list)
    tool_calls: list[AIToolCallRecord] = Field(default_factory=list)
    usage: AIUsageSummary
    warnings: list[str] = Field(default_factory=list)
    rich_content: RichContentDocument | None = None


class AIErrorDetail(StrictModel):
    code: str
    message: str
    retryable: bool = False


class AIErrorResponse(StrictModel):
    request_id: str
    error: AIErrorDetail


class AIStreamEvent(StrictModel):
    type: str
    data: dict[str, Any]
    persistence: dict[str, Any] = Field(default_factory=dict, exclude=True)
