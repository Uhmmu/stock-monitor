from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.providers.schemas import ProviderMessage
from app.ai.schemas import Citation
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


class ConversationContextMixin(StrictModel):
    active_symbol: str | None = None
    active_symbols: list[str] = Field(default_factory=list, max_length=20)
    active_portfolio_id: int | None = Field(None, gt=0)
    page_context: str | None = None

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

    @model_validator(mode="after")
    def merge_active_symbols(self):
        if self.active_symbol:
            self.active_symbols = [self.active_symbol] + [value for value in self.active_symbols if value != self.active_symbol]
        return self


class ConversationCreateRequest(ConversationContextMixin):
    message: str | None = Field(None, min_length=1, max_length=12000)
    title: str | None = Field(None, min_length=1, max_length=200)
    model: str | None = Field(None, min_length=1, max_length=200)
    web_access_mode: WebAccessMode | None = None


class ConversationUpdateRequest(StrictModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    archived: bool | None = None
    active_symbol: str | None = None
    active_symbols: list[str] | None = Field(None, max_length=20)
    active_portfolio_id: int | None = Field(None, gt=0)
    page_context: str | None = None
    model: str | None = Field(None, min_length=1, max_length=200)
    web_access_mode: WebAccessMode | None = None

    @field_validator("active_symbol")
    @classmethod
    def normalize_active_symbol(cls, value: str | None) -> str | None:
        return _symbol(value) if value else None

    @field_validator("active_symbols")
    @classmethod
    def normalize_active_symbols(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else list(dict.fromkeys(_symbol(value) for value in values))

    @field_validator("page_context")
    @classmethod
    def page_context_allowed(cls, value: str | None) -> str | None:
        if value is not None and value not in PAGE_CONTEXTS:
            raise ValueError("unsupported page context")
        return value


class ConversationMessageCreateRequest(ConversationContextMixin):
    message: str = Field(min_length=1, max_length=12000)
    model: str | None = Field(None, min_length=1, max_length=200)
    stream: bool = True
    allowed_tools: list[str] | None = Field(None, max_length=60)
    denied_tools: list[str] = Field(default_factory=list, max_length=60)
    web_access_mode: WebAccessMode | None = None
    deep_search_confirmed: bool = False

    @field_validator("allowed_tools", "denied_tools")
    @classmethod
    def unique_tools(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else list(dict.fromkeys(values))


class RegenerateRequest(StrictModel):
    stream: bool = True
    model: str | None = Field(None, min_length=1, max_length=200)
    web_access_mode: WebAccessMode | None = None
    deep_search_confirmed: bool = False


class ConversationOut(StrictModel):
    id: int
    title: str
    title_source: str
    status: Literal["active", "archived", "deleted"]
    active_symbol: str | None = None
    active_symbols: list[str] = Field(default_factory=list)
    active_portfolio_id: int | None = None
    page_context: str | None = None
    model: str | None = None
    web_access_mode: WebAccessMode = WebAccessMode.off
    message_count: int
    completed_message_count: int
    last_message_preview: str | None = None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    archived_at: datetime | None = None
    deleted_at: datetime | None = None


class ConversationPage(StrictModel):
    items: list[ConversationOut]
    page: int
    limit: int
    total: int
    has_more: bool


class ToolCallRecordOut(StrictModel):
    id: int
    tool_call_id: str
    tool_name: str
    display_name: str
    status: str
    summary: str | None = None
    warning_codes: list[str] = Field(default_factory=list)
    returned_item_count: int | None = None
    cache_hit: bool = False
    truncated: bool = False
    reused: bool = False
    external_provider: str | None = None
    external_run_id: str | None = None
    cost_usd: float | None = None
    cost_estimated: bool = False
    created_at: datetime
    completed_at: datetime | None = None


class MessageOut(StrictModel):
    id: int
    conversation_id: int
    role: Literal["user", "assistant"]
    status: Literal["pending", "streaming", "completed", "partial", "failed", "cancelled"]
    content: str
    content_format: str
    content_schema_version: int | None = None
    content_parts: RichContentDocument | None = None
    parent_message_id: int | None = None
    reply_to_message_id: int | None = None
    regenerated_from_message_id: int | None = None
    generation_index: int
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_call_count: int = 0
    citation_count: int = 0
    web_access_mode: WebAccessMode = WebAccessMode.off
    external_search_call_count: int = 0
    deep_search_run_id: str | None = None
    external_search_cost_usd: float | None = None
    error_code: str | None = None
    error_message_safe: str | None = None
    has_partial_content: bool = False
    citations: list[Citation] = Field(default_factory=list)
    tool_calls: list[ToolCallRecordOut] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    updated_at: datetime


class MessagePage(StrictModel):
    items: list[MessageOut]
    page: int
    limit: int
    total: int
    has_more: bool


class MessagePairResponse(StrictModel):
    conversation: ConversationOut
    user_message: MessageOut
    assistant_message: MessageOut


class StopResponse(StrictModel):
    stopped: bool
    assistant_message_id: int | None = None


class ActiveGenerationResponse(StrictModel):
    active: bool
    assistant_message_id: int | None = None
    runtime_mode: str = "single_process"


class ConversationHistoryContext(BaseModel):
    messages: list[ProviderMessage]
    message_ids: list[int]
    estimated_chars: int
    summary_snapshot_id: int | None = None
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
