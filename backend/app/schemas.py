from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    threshold_20m: float | None = Field(default=None, gt=0)
    threshold_1h: float | None = Field(default=None, gt=0)
    threshold_day: float | None = Field(default=None, gt=0)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker.replace("-", "").replace(".", "").isalnum():
            raise ValueError("股票代码格式无效")
        return ticker


class WatchlistUpdate(BaseModel):
    enabled: bool | None = None
    threshold_20m: float | None = Field(default=None, gt=0)
    threshold_1h: float | None = Field(default=None, gt=0)
    threshold_day: float | None = Field(default=None, gt=0)


class WatchlistOut(WatchlistCreate):
    id: int
    enabled: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SettingsUpdate(BaseModel):
    threshold_20m: float = Field(gt=0)
    threshold_1h: float = Field(gt=0)
    threshold_day: float = Field(gt=0)
    alert_cooldown_minutes: int = Field(ge=5, le=1440)
    investigation_interval_minutes: int = Field(ge=5, le=120)
    investigation_duration_minutes: int = Field(ge=20, le=1440)


class SettingsOut(SettingsUpdate):
    price_poll_minutes: int
