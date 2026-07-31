from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.research.exceptions import ResearchError
from app.research.security import normalize_symbol

from .enums import MemoryScope, MemoryType


class Schema(BaseModel):
    model_config = ConfigDict(
        extra="forbid", from_attributes=True, str_strip_whitespace=True
    )


MemoryOrigin = Literal[
    "explicit_user_request",
    "assistant_proposal",
    "conversation_extraction",
    "decision_derived",
    "manual_entry",
    "imported",
]


class MemoryCreate(Schema):
    memory_type: MemoryType
    scope: MemoryScope = MemoryScope.global_
    scope_key: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=200)
    content: str = Field(min_length=2, max_length=4000)
    structured_value: dict[str, Any] | list[Any] | None = None
    importance: int = Field(50, ge=0, le=100)
    confidence: float | None = Field(None, ge=0, le=1)
    expires_at: datetime | None = None
    stale_after: datetime | None = None
    proposed: bool = False
    origin: MemoryOrigin = "manual_entry"
    source_conversation_id: int | None = Field(None, gt=0)
    source_message_id: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def scope_key_required(self):
        if self.scope != MemoryScope.global_ and not self.scope_key:
            raise ValueError("scope_key is required for non-global memories")
        if self.scope == MemoryScope.global_:
            self.scope_key = None
        return self


class MemoryPatch(Schema):
    memory_type: MemoryType | None = None
    scope: MemoryScope | None = None
    scope_key: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=200)
    content: str | None = Field(None, min_length=2, max_length=4000)
    structured_value: dict[str, Any] | list[Any] | None = None
    importance: int | None = Field(None, ge=0, le=100)
    expires_at: datetime | None = None
    stale_after: datetime | None = None


class MemoryEventOut(Schema):
    id: int
    event_type: str
    before_value: dict[str, Any] | None
    after_value: dict[str, Any] | None
    conversation_id: int | None
    message_id: int | None
    created_at: datetime


class MemoryOut(Schema):
    id: int
    memory_type: str
    scope: str
    scope_key: str | None
    status: str
    title: str | None
    content: str
    structured_value: dict[str, Any] | list[Any] | None
    origin: str
    confidence: float | None
    importance: int
    source_conversation_id: int | None
    source_message_id: int | None
    source_decision_id: int | None
    effective_from: datetime | None
    expires_at: datetime | None
    stale_after: datetime | None
    last_confirmed_at: datetime | None
    last_used_at: datetime | None
    supersedes_memory_id: int | None
    conflict_group: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    archived_at: datetime | None


class MemoryDetailOut(MemoryOut):
    events: list[MemoryEventOut] = Field(default_factory=list)


class MemoryPage(Schema):
    items: list[MemoryOut]
    total: int
    limit: int
    cursor: str | None = None


class MemorySettingsOut(Schema):
    enabled: bool
    use_in_context: bool
    candidate_extraction_enabled: bool
    max_active_memories: int


class MemorySettingsPatch(Schema):
    enabled: bool | None = None
    use_in_context: bool | None = None
    candidate_extraction_enabled: bool | None = None


class ForgetRequest(Schema):
    query: str = Field(min_length=1, max_length=500)
    delete: bool = False


class ForgetResult(Schema):
    matched: list[MemoryOut]
    changed: bool
    requires_selection: bool


DecisionType = Literal[
    "buy",
    "add",
    "hold",
    "reduce",
    "sell",
    "avoid",
    "watch",
    "rebalance",
    "hedge",
    "research",
    "thesis",
]
TimeHorizon = Literal["days", "weeks", "months", "years", "long_term", "unspecified"]


def _symbol(value: str) -> str:
    try:
        return normalize_symbol(value)
    except ResearchError as exc:
        raise ValueError(exc.message) from exc


class EvidenceCreate(Schema):
    source_id: str = Field(min_length=1, max_length=256)
    source_type: str = Field("unknown", max_length=64)
    origin: Literal["internal", "web", "deep_search", "user_statement"] = "internal"
    title: str = Field(min_length=1, max_length=300)
    symbol: str | None = Field(None, max_length=32)
    provider: str | None = Field(None, max_length=64)
    authority: str | None = Field(None, max_length=128)
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    as_of: datetime | None = None
    url: str | None = Field(None, max_length=2000)
    locator: str | None = Field(None, max_length=500)
    evidence_summary: str = Field(min_length=1, max_length=1000)
    evidence_role: Literal[
        "supports", "contradicts", "risk", "context", "invalidation"
    ] = "context"

    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value):
        return _symbol(value) if value else None


class DecisionCreate(Schema):
    title: str = Field(min_length=1, max_length=240)
    decision_type: DecisionType
    symbols: list[str] = Field(default_factory=list, max_length=20)
    portfolio_id: int | None = Field(None, gt=0)
    decision_date: date = Field(default_factory=date.today)
    time_horizon: TimeHorizon = "unspecified"
    target_review_at: datetime | None = None
    action: str = Field(min_length=1, max_length=4000)
    position_intent: str | None = Field(None, max_length=64)
    target_weight: Decimal | None = Field(None, ge=0, le=1)
    target_quantity: Decimal | None = Field(None, ge=0)
    target_price_min: Decimal | None = Field(None, ge=0)
    target_price_max: Decimal | None = Field(None, ge=0)
    thesis: list[str] = Field(default_factory=list, max_length=30)
    catalysts: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=30)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    open_questions: list[str] = Field(default_factory=list, max_length=30)
    confidence: float | None = Field(None, ge=0, le=1)
    priority: int = Field(50, ge=0, le=100)
    source_conversation_id: int | None = Field(None, gt=0)
    source_user_message_id: int | None = Field(None, gt=0)
    source_assistant_message_id: int | None = Field(None, gt=0)
    evidence: list[EvidenceCreate] = Field(default_factory=list, max_length=30)

    @field_validator("symbols")
    @classmethod
    def clean_symbols(cls, values):
        return list(dict.fromkeys(_symbol(value) for value in values))

    @field_validator(
        "thesis",
        "catalysts",
        "risks",
        "invalidation_conditions",
        "assumptions",
        "open_questions",
    )
    @classmethod
    def bounded_lines(cls, values):
        return [value[:1000] for value in values if value.strip()]

    @model_validator(mode="after")
    def price_range(self):
        if (
            self.target_price_min is not None
            and self.target_price_max is not None
            and self.target_price_min > self.target_price_max
        ):
            raise ValueError("target_price_min cannot exceed target_price_max")
        return self


class DecisionPatch(Schema):
    title: str | None = Field(None, min_length=1, max_length=240)
    decision_type: DecisionType | None = None
    symbols: list[str] | None = Field(None, max_length=20)
    portfolio_id: int | None = Field(None, gt=0)
    decision_date: date | None = None
    time_horizon: TimeHorizon | None = None
    target_review_at: datetime | None = None
    action: str | None = Field(None, min_length=1, max_length=4000)
    position_intent: str | None = Field(None, max_length=64)
    target_weight: Decimal | None = Field(None, ge=0, le=1)
    target_quantity: Decimal | None = Field(None, ge=0)
    target_price_min: Decimal | None = Field(None, ge=0)
    target_price_max: Decimal | None = Field(None, ge=0)
    thesis: list[str] | None = Field(None, max_length=30)
    catalysts: list[str] | None = Field(None, max_length=30)
    risks: list[str] | None = Field(None, max_length=30)
    invalidation_conditions: list[str] | None = Field(None, max_length=30)
    assumptions: list[str] | None = Field(None, max_length=30)
    open_questions: list[str] | None = Field(None, max_length=30)
    confidence: float | None = Field(None, ge=0, le=1)
    priority: int | None = Field(None, ge=0, le=100)

    @field_validator("symbols")
    @classmethod
    def clean_symbols(cls, values):
        return (
            None
            if values is None
            else list(dict.fromkeys(_symbol(value) for value in values))
        )


class EvidenceOut(Schema):
    id: int
    source_id: str
    source_type: str
    origin: str
    title: str
    symbol: str | None
    provider: str | None
    authority: str | None
    published_at: datetime | None
    retrieved_at: datetime | None
    as_of: datetime | None
    url: str | None
    locator: str | None
    evidence_summary: str
    evidence_role: str
    freshness_status: str
    created_at: datetime


class ReviewCreate(Schema):
    review_type: Literal[
        "manual", "scheduled", "event_driven", "post_execution", "post_exit"
    ] = "manual"
    status: Literal["draft", "completed"] = "draft"
    data_as_of: datetime | None = None
    thesis_status: Literal[
        "strengthened", "unchanged", "weakened", "broken", "uncertain"
    ] = "uncertain"
    invalidation_status: Literal[
        "not_triggered", "partially_triggered", "triggered", "unknown"
    ] = "unknown"
    execution_status: str | None = Field(None, max_length=32)
    what_changed: str = Field("", max_length=8000)
    supporting_changes: list[str] = Field(default_factory=list, max_length=30)
    contradicting_changes: list[str] = Field(default_factory=list, max_length=30)
    lessons: list[str] = Field(default_factory=list, max_length=30)
    next_action: str | None = Field(None, max_length=4000)
    linked_message_id: int | None = Field(None, gt=0)
    linked_conversation_id: int | None = Field(None, gt=0)


class ReviewOut(Schema):
    id: int
    review_type: str
    status: str
    reviewed_at: datetime | None
    data_as_of: datetime | None
    thesis_status: str
    invalidation_status: str
    execution_status: str | None
    what_changed: str
    supporting_changes: list[str]
    contradicting_changes: list[str]
    lessons: list[str]
    next_action: str | None
    linked_message_id: int | None
    linked_conversation_id: int | None
    created_at: datetime
    updated_at: datetime


class DecisionOut(Schema):
    id: int
    title: str
    decision_type: str
    status: str
    primary_symbol: str | None
    symbols: list[str]
    portfolio_id: int | None
    decision_date: date
    time_horizon: str
    target_review_at: datetime | None
    review_due: bool = False
    action: str
    position_intent: str | None
    target_weight: Decimal | None
    target_quantity: Decimal | None
    target_price_min: Decimal | None
    target_price_max: Decimal | None
    thesis: list[str]
    catalysts: list[str]
    risks: list[str]
    invalidation_conditions: list[str]
    assumptions: list[str]
    open_questions: list[str]
    confidence: float | None
    priority: int
    source_conversation_id: int | None
    source_user_message_id: int | None
    source_assistant_message_id: int | None
    executed_trade_id: int | None
    executed_at: datetime | None
    invalidated_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    evidence: list[EvidenceOut] = Field(default_factory=list)
    reviews: list[ReviewOut] = Field(default_factory=list)


class DecisionPage(Schema):
    items: list[DecisionOut]
    total: int
    limit: int
    cursor: str | None = None


class ExecuteDecisionRequest(Schema):
    execution_status: Literal["executed", "partially_executed"] = "executed"
    trade_id: int | None = Field(None, gt=0)


class SummarySnapshotOut(Schema):
    id: int
    conversation_id: int
    version: int
    status: str
    from_message_id: int | None
    through_message_id: int | None
    source_message_count: int
    source_character_count: int
    summary_text: str | None
    structured_summary: dict[str, Any]
    provider: str | None
    model: str | None
    prompt_version: str
    input_tokens: int
    output_tokens: int
    estimated_tokens: int
    created_at: datetime
    completed_at: datetime | None
    superseded_at: datetime | None
    error_code: str | None
    error_message_safe: str | None


class SummaryHistoryOut(Schema):
    items: list[SummarySnapshotOut]


class MessageMemoryUsageOut(Schema):
    memories: list[MemoryOut]
    decisions: list[DecisionOut]
    summary_snapshot: SummarySnapshotOut | None
