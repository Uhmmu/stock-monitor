from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistCreate(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    security_id: int | None = Field(default=None, gt=0)
    source: str | None = Field(default=None, pattern="^(yahoo|finnhub|local)$")
    yahoo_symbol: str | None = Field(default=None, max_length=32)
    finnhub_symbol: str | None = Field(default=None, max_length=32)
    threshold_20m: float | None = Field(default=None, gt=0)
    threshold_1h: float | None = Field(default=None, gt=0)
    threshold_day: float | None = Field(default=None, gt=0)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        ticker = value.strip().upper()
        if not ticker.replace("-", "").replace(".", "").isalnum():
            raise ValueError("股票代码格式无效")
        return ticker


class SecurityResolveIn(BaseModel):
    security_id: int | None = Field(default=None, gt=0)
    source: str | None = Field(default=None, pattern="^(yahoo|finnhub|local)$")
    yahoo_symbol: str | None = Field(default=None, max_length=32)
    finnhub_symbol: str | None = Field(default=None, max_length=32)


class WatchlistUpdate(BaseModel):
    enabled: bool | None = None
    alert_enabled: bool | None = None
    user_group_id: int | None = None
    display_order: int | None = Field(default=None, ge=0)
    threshold_20m: float | None = Field(default=None, gt=0)
    threshold_1h: float | None = Field(default=None, gt=0)
    threshold_day: float | None = Field(default=None, gt=0)


class WatchlistOut(WatchlistCreate):
    id: int
    enabled: bool
    alert_enabled: bool
    user_group_id: int | None
    display_order: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PriceSnapshotOut(BaseModel):
    id: int
    symbol: str
    exchange: str | None
    currency: str | None
    source_type: str
    provider: str
    provider_symbol: str | None
    provider_role: str | None
    last_price: float
    open_price: float | None
    day_high: float | None
    day_low: float | None
    previous_close: float | None
    price_change: float | None
    price_change_percent: float | None
    day_volume: int | None
    average_volume_10d: float | None
    average_volume_20d: float | None
    relative_volume_20d: float | None
    relative_volume_basis: str | None
    market_timestamp: datetime | None
    trading_date: date | None
    market_session: str
    snapshot_market_session: str
    timestamp_source: str | None
    fetched_at: datetime | None
    persisted_at: datetime | None
    is_delayed: bool | None
    delay_seconds: int | None
    is_stale: bool
    age_seconds: int | None
    stale_after_seconds: int
    age_basis: str


class StockGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()


class StockGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    display_order: int | None = Field(default=None, ge=0)


class PeerCreate(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    security_id: int | None = Field(default=None, gt=0)
    source: str | None = Field(default=None, pattern="^(yahoo|finnhub|local)$")
    yahoo_symbol: str | None = Field(default=None, max_length=32)
    finnhub_symbol: str | None = Field(default=None, max_length=32)

    @field_validator("ticker")
    @classmethod
    def normalize_peer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return WatchlistCreate.normalize_ticker(value)


class OrderUpdate(BaseModel):
    display_order: int = Field(ge=0)


class SettingsUpdate(BaseModel):
    threshold_20m: float = Field(gt=0)
    threshold_1h: float = Field(gt=0)
    threshold_day: float = Field(gt=0)
    alert_cooldown_minutes: int = Field(ge=5, le=1440)
    investigation_interval_minutes: int = Field(ge=5, le=120)
    investigation_duration_minutes: int = Field(ge=20, le=1440)


class SettingsOut(SettingsUpdate):
    price_poll_minutes: int


class UserPriceAlertCreate(BaseModel):
    target_price: float = Field(gt=0, allow_inf_nan=False)
    direction: str = Field(pattern="^(above|below)$")


class GrahamOverride(BaseModel):
    """按请求临时覆盖 Graham 输入，不写回每日快照。"""
    growth_rate: float | None = Field(default=None, ge=-4, le=15, allow_inf_nan=False)
    aaa_yield: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    normalized_eps: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class TradeLogTableRow(BaseModel):
    security_id: int | None = Field(default=None, gt=0)
    ticker: str = Field(default="", max_length=16)
    direction: str = Field(default="", max_length=16)
    quantity: float | None = Field(default=None, ge=0)
    price: float | None = Field(default=None, ge=0)
    fee: float | None = Field(default=None, ge=0)
    strategy: str = Field(default="", max_length=80)
    result: str = Field(default="", max_length=80)

    @field_validator("ticker")
    @classmethod
    def normalize_row_ticker(cls, value: str) -> str:
        return value.strip().upper()

class TradeLogBase(BaseModel):
    trade_date: date
    ticker: str | None = Field(default=None, max_length=16)
    direction: str | None = Field(default=None, max_length=16)
    quantity: float | None = Field(default=None, ge=0)
    price: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=5000)
    content: str | None = Field(default=None, max_length=20000)
    table_rows: list[TradeLogTableRow] = Field(default_factory=list, max_length=50)
    photo_urls: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        ticker = value.strip().upper()
        return ticker or None

    @field_validator("photo_urls")
    @classmethod
    def limit_photo_size(cls, value: list[str]) -> list[str]:
        cleaned = [item for item in value if item.strip()]
        if any(len(item) > 1_200_000 for item in cleaned):
            raise ValueError("单张图片过大")
        return cleaned


class TradeLogCreate(TradeLogBase):
    pass


class TradeLogUpdate(TradeLogBase):
    pass


class TradeLogOut(TradeLogBase):
    id: int
    ai_summary: str | None
    ai_summary_model: str | None
    ai_summary_created_at: datetime | None
    status: str
    source_type: str
    objective_facts: dict
    ibkr_sync_run_id: int | None
    ibkr_position_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
