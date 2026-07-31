from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .enums import FreshnessStatus, SourceAuthority, SourceType, WarningSeverity

T = TypeVar("T")


class ResearchSource(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    source_id: str
    source_type: SourceType
    title: str
    symbol: str | None = None
    provider: str | None = None
    authority: SourceAuthority = SourceAuthority.unknown
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


class ResearchFreshness(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    as_of: datetime | None = None
    status: FreshnessStatus
    age_seconds: int | None = None
    ttl_seconds: int | None = None
    reason: str | None = None


class ResearchWarning(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    code: str
    message: str
    severity: WarningSeverity = WarningSeverity.warning


class ResearchMeta(BaseModel):
    request_id: str
    generated_at: datetime
    symbol: str | None = None
    symbols: list[str] = Field(default_factory=list)
    page: int | None = None
    page_size: int | None = None
    total: int | None = None
    data_version: str = "v1"


class ResearchResponse(BaseModel, Generic[T]):
    data: T
    sources: list[ResearchSource] = Field(default_factory=list)
    freshness: ResearchFreshness
    warnings: list[ResearchWarning] = Field(default_factory=list)
    meta: ResearchMeta


class ResearchErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ResearchErrorResponse(BaseModel):
    request_id: str
    error: ResearchErrorDetail
