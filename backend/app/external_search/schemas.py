from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    AgentRunStatus,
    DeepSearchEffort,
    SearchFreshness,
    SearchType,
    WebAccessMode,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchProviderRequest(StrictModel):
    query: str = Field(min_length=1, max_length=4000)
    search_type: SearchType = SearchType.auto
    num_results: int = Field(8, ge=1, le=10)
    category: Literal["company", "people", "publication", "news", "personal site", "financial report"] | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=50)
    exclude_domains: list[str] = Field(default_factory=list, max_length=100)
    start_published_date: datetime | None = None
    end_published_date: datetime | None = None
    content_mode: Literal["highlights", "text"] = "highlights"
    max_age_hours: int | None = Field(None, ge=-1, le=8760)
    max_content_characters: int | None = Field(None, ge=100, le=15000)
    livecrawl_timeout_ms: int | None = Field(None, ge=1000, le=30000)
    moderation: bool = True
    freshness: SearchFreshness = SearchFreshness.balanced


class ExternalSearchResult(StrictModel):
    result_id: str
    title: str
    url: str
    normalized_url: str
    domain: str
    published_at: datetime | None = None
    author: str | None = None
    highlights: list[str] = Field(default_factory=list)
    text: str | None = None
    provider: str = "exa"
    provider_request_id: str | None = None
    retrieved_at: datetime
    source_kind: str = "web_search"
    authority_tier: str = "unknown"
    freshness_mode: str | None = None


class SearchProviderResponse(StrictModel):
    results: list[ExternalSearchResult] = Field(default_factory=list)
    request_id: str | None = None
    search_type: str | None = None
    cost_usd: Decimal | None = None
    cost_estimated: bool = False
    usage: dict[str, Any] = Field(default_factory=dict)


class AgentRunCreateRequest(StrictModel):
    query: str = Field(min_length=1, max_length=12000)
    effort: DeepSearchEffort
    output_schema: dict[str, Any] | None = None
    system_prompt: str | None = Field(None, max_length=4000)
    metadata: dict[str, str] = Field(default_factory=dict)


class ExternalGroundingSource(StrictModel):
    source_id: str
    title: str
    url: str
    normalized_url: str
    domain: str
    field: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    authority_tier: str = "unknown"


class AgentRun(StrictModel):
    id: str
    status: AgentRunStatus
    stop_reason: str | None = None
    output_text: str | None = None
    output_structured: dict[str, Any] | list[Any] | None = None
    grounding: list[ExternalGroundingSource] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    cost_usd: Decimal | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message_safe: str | None = None


class AgentRunEvent(StrictModel):
    event_id: str | None = None
    event_type: str
    status: AgentRunStatus | None = None
    run: AgentRun | None = None
    source_count: int | None = None
    created_at: datetime | None = None


class DeepRunCreateAPIRequest(StrictModel):
    conversation_id: int = Field(gt=0)
    user_message_id: int | None = Field(None, gt=0)
    assistant_message_id: int | None = Field(None, gt=0)
    query: str = Field(min_length=1, max_length=12000)
    web_access_mode: WebAccessMode
    confirmation: bool = False
    generation_index: int = Field(1, ge=1)

    @field_validator("web_access_mode")
    @classmethod
    def deep_only(cls, value: WebAccessMode) -> WebAccessMode:
        if not value.is_deep:
            raise ValueError("a Deep Search mode is required")
        return value


class DeepRunOut(StrictModel):
    run_id: str
    conversation_id: int | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    provider: str
    mode: WebAccessMode
    effort: DeepSearchEffort
    status: AgentRunStatus
    termination_reason: str | None = None
    text: str | None = None
    structured: dict[str, Any] | list[Any] | None = None
    sources: list[ExternalGroundingSource] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    cost_usd: Decimal | None = None
    cost_estimated: bool = True
    error_code: str | None = None
    error_message_safe: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    last_synced_at: datetime | None = None


class DeepRunEventOut(StrictModel):
    id: int
    event_type: str
    status: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
