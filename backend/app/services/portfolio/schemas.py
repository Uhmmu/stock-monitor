"""Pydantic schemas for the portfolio/holdings API."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_CURRENCIES = {"USD", "HKD", "CNY", "EUR", "JPY", "GBP", "CAD", "AUD"}
# Full operational support in v0.4; the rest are stored but not yet fully derived.
SUPPORTED_TRANSACTION_TYPES = {
    "buy", "sell", "dividend", "fee", "deposit", "withdrawal", "split", "transfer_in", "transfer_out",
}
FULLY_SUPPORTED_TYPES = {"buy", "sell", "dividend", "fee"}


class ManualPositionIn(BaseModel):
    """Holdings-page manual entry. Internally creates a transaction — never writes
    the aggregated position directly."""

    symbol: str = Field(min_length=1, max_length=16)
    security_id: int | None = Field(default=None, gt=0)
    source: str | None = Field(default=None, pattern="^(yahoo|finnhub|local)$")
    yahoo_symbol: str | None = Field(default=None, max_length=32)
    finnhub_symbol: str | None = Field(default=None, max_length=32)
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    trade_date: date
    fees: float = Field(default=0.0, ge=0)
    currency: str = Field(default="USD", max_length=8)
    account: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    transaction_type: str = Field(default="buy", max_length=16)

    @field_validator("symbol")
    @classmethod
    def _norm_symbol(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker.replace("-", "").replace(".", "").isalnum():
            raise ValueError("股票代码格式无效")
        return ticker

    @field_validator("currency")
    @classmethod
    def _norm_currency(cls, value: str) -> str:
        cur = (value or "USD").strip().upper()
        if cur not in SUPPORTED_CURRENCIES:
            raise ValueError(f"暂不支持的币种：{cur}")
        return cur

    @field_validator("transaction_type")
    @classmethod
    def _norm_type(cls, value: str) -> str:
        kind = (value or "buy").strip().lower()
        if kind not in SUPPORTED_TRANSACTION_TYPES:
            raise ValueError(f"暂不支持的交易类型：{kind}")
        return kind


class TransactionIn(BaseModel):
    """Generic transaction create/edit payload."""

    portfolio_id: int | None = Field(default=None, gt=0)
    symbol: str = Field(min_length=1, max_length=16)
    security_id: int | None = Field(default=None, gt=0)
    transaction_type: str = Field(default="buy", max_length=16)
    quantity: float = Field(ge=0)
    price: float = Field(ge=0)
    fees: float = Field(default=0.0, ge=0)
    currency: str = Field(default="USD", max_length=8)
    trade_date: date
    account: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("symbol")
    @classmethod
    def _norm_symbol(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker.replace("-", "").replace(".", "").isalnum():
            raise ValueError("股票代码格式无效")
        return ticker

    @field_validator("currency")
    @classmethod
    def _norm_currency(cls, value: str) -> str:
        cur = (value or "USD").strip().upper()
        if cur not in SUPPORTED_CURRENCIES:
            raise ValueError(f"暂不支持的币种：{cur}")
        return cur

    @field_validator("transaction_type")
    @classmethod
    def _norm_type(cls, value: str) -> str:
        kind = (value or "buy").strip().lower()
        if kind not in SUPPORTED_TRANSACTION_TYPES:
            raise ValueError(f"暂不支持的交易类型：{kind}")
        return kind


class TransactionOut(BaseModel):
    id: int
    symbol: str
    transaction_type: str
    quantity: float
    price: float
    fees: float
    currency: str
    trade_date: date
    account: str | None
    note: str | None
    source: str
    model_config = ConfigDict(from_attributes=True)
