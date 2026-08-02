from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IbkrRequestInfo(BaseModel):
    method: str
    path: str
    query: dict[str, Any] = Field(default_factory=dict)


class IbkrOperationResult(BaseModel):
    success: bool = True
    operation: str
    timestamp: datetime
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    request: IbkrRequestInfo
    status_code: int | None = None
    normalized: Any = None
    raw: Any = None
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class IbkrAccount(BaseModel):
    account_id: str
    display_name: str | None = None
    currency: str | None = None
    brokerage_access: bool | None = None


class IbkrAccountSummary(BaseModel):
    account_id: str
    net_liquidation: Any = None
    total_cash: Any = None
    buying_power: Any = None
    available_funds: Any = None
    excess_liquidity: Any = None
    initial_margin: Any = None
    maintenance_margin: Any = None
    unrealized_pnl: Any = None
    realized_pnl: Any = None
    base_currency: str | None = None


class IbkrPosition(BaseModel):
    symbol: str | None = None
    conid: int | str | None = None
    asset_class: str | None = None
    exchange: str | None = None
    currency: str | None = None
    position: Any = None
    average_cost: Any = None
    market_price: Any = None
    market_value: Any = None
    unrealized_pnl: Any = None
    realized_pnl: Any = None
    account_id: str


class IbkrLoginRequest(BaseModel):
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)
    save_credentials: bool = False


class IbkrSavedCredentialsStatus(BaseModel):
    saved: bool
    username_hint: str = ""
