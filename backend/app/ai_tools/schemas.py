from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.research.exceptions import ResearchError
from app.research.security import normalize_symbol

from .enums import ResultMode, ToolStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolDefinition(StrictModel):
    name: str
    version: str = "1.0.0"
    domain: str
    title: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    read_only: bool = True
    requires_auth: bool = True
    contains_private_data: bool = False
    default_timeout_seconds: float = Field(15.0, gt=0, le=900)
    max_timeout_seconds: float = Field(30.0, gt=0, le=900)
    default_result_mode: ResultMode = ResultMode.standard
    supports_result_modes: list[ResultMode] = Field(default_factory=lambda: list(ResultMode))
    max_items: int | None = Field(None, ge=1, le=100)
    max_date_range_days: int | None = Field(None, ge=1, le=3660)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    cache_ttl_seconds: int = Field(0, ge=0, le=600)
    allow_parallel: bool = True

    @model_validator(mode="after")
    def validate_contract(self):
        import re
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", self.name):
            raise ValueError("tool name must be stable snake_case")
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ValueError("tool version must use semantic versioning")
        if len(self.description) < 80:
            raise ValueError("tool description must explain its use and limitations")
        if not self.read_only:
            raise ValueError("AI tools must be read-only")
        return self


class ToolArguments(StrictModel):
    result_mode: ResultMode = ResultMode.standard


class SymbolArguments(ToolArguments):
    symbol: str = Field(min_length=1, max_length=32)

    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value: str) -> str:
        try:
            return normalize_symbol(value)
        except ResearchError as exc:
            raise ValueError(exc.message) from exc


class DateRangeMixin(StrictModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def valid_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class ToolExecutionContext(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    user_id: int = Field(gt=0)
    session_id: str | None = Field(None, max_length=128)
    conversation_id: str | None = Field(None, max_length=128)
    user_message_id: int | None = Field(None, gt=0)
    assistant_message_id: int | None = Field(None, gt=0)
    generation_index: int | None = Field(None, ge=1)
    web_access_mode: str = "off"
    deep_search_confirmed: bool = False
    active_symbol: str | None = Field(None, max_length=32)
    active_portfolio_id: int | None = Field(None, gt=0)
    locale: str = Field("zh-CN", max_length=32)
    timezone: str = Field("Asia/Shanghai", max_length=64)
    caller: Literal["debug_api", "internal", "future_llm", "test"]
    allowed_tools: set[str] | None = None
    denied_tools: set[str] = Field(default_factory=set)
    max_tool_calls: int = Field(12, ge=1, le=12)
    max_parallel_calls: int = Field(4, ge=1, le=8)
    max_total_output_chars: int = Field(50000, ge=1000, le=80000)
    allow_private_data: bool = True

    @field_validator("active_symbol")
    @classmethod
    def normalize_active_symbol(cls, value: str | None) -> str | None:
        if value is None: return None
        try: return normalize_symbol(value)
        except ResearchError as exc: raise ValueError(exc.message) from exc


class ToolExecutionStats(StrictModel):
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    result_mode: ResultMode
    original_item_count: int | None = None
    returned_item_count: int | None = None
    estimated_input_chars: int = 0
    estimated_output_chars: int = 0
    estimated_output_tokens: int | None = None
    truncated: bool = False
    cache_hit: bool = False
    timeout_seconds: float | None = None


class ToolExecutionError(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(StrictModel):
    tool_call_id: str
    tool_name: str
    tool_version: str
    status: ToolStatus
    data: Any = None
    summary: str | None = None
    sources: list[Any] = Field(default_factory=list)
    freshness: Any | None = None
    warnings: list[Any] = Field(default_factory=list)
    stats: ToolExecutionStats
    error: ToolExecutionError | None = None


class ToolCallRequest(StrictModel):
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolBatchRequest(StrictModel):
    calls: list[ToolCallRequest] = Field(min_length=1, max_length=12)


class AdapterResult(StrictModel):
    data: Any = None
    summary: str | None = None
    sources: list[Any] = Field(default_factory=list)
    freshness: Any | None = None
    warnings: list[Any] = Field(default_factory=list)
    partial: bool = False


def empty_stats(mode: ResultMode = ResultMode.standard) -> ToolExecutionStats:
    now = datetime.now(UTC)
    return ToolExecutionStats(started_at=now, completed_at=now, duration_ms=0, result_mode=mode)
