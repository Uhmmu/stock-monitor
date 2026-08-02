from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class FlexStatementMetadata(BaseModel):
    account_id: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    period: str | None = None
    generated_at: datetime | None = None
    extra_fields: dict[str, str] = Field(default_factory=dict)


class FlexRecord(BaseModel):
    section: str
    source_index: int
    source_id: str
    account_id: str | None = None
    symbol: str | None = None
    conid: str | None = None
    currency: str | None = None
    asset_category: str | None = None
    description: str | None = None
    report_date: date | None = None
    occurred_at: datetime | None = None
    amount: Decimal | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    raw_fields: dict[str, str] = Field(default_factory=dict)
    extra_fields: dict[str, str] = Field(default_factory=dict)


class FlexParsedReport(BaseModel):
    metadata: FlexStatementMetadata
    source_hash: str
    parser_version: str
    records: dict[str, list[FlexRecord]] = Field(default_factory=dict)
    present_sections: list[str] = Field(default_factory=list)
    unknown_sections: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @property
    def record_count(self) -> int:
        return sum(len(rows) for rows in self.records.values())
