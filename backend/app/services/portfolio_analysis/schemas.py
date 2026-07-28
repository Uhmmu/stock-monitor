from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class PortfolioPosition(BaseModel):
    symbol: str
    quantity: float
    market_value: float
    currency: str
    asset_type: str | None = None
    sector: str | None = None
    industry: str | None = None


class PortfolioAnalysisInput(BaseModel):
    portfolio_id: int
    positions: list[PortfolioPosition]
    benchmark: str = "SPY"
    base_currency: str = "USD"
    history_period: str = "max_available"
    confidence_level: float = Field(default=0.95, ge=0.9, le=0.999)


class PortfolioAnalysisRequest(BaseModel):
    portfolio_id: int | None = Field(default=None, gt=0)
    benchmark: str = Field(default="SPY", min_length=1, max_length=32)
    history_period: str = "max_available"
    confidence_level: Literal[0.95, 0.99] = 0.95
    mode: Literal["common_start", "dynamic_available"] = "common_start"
    covariance_method: Literal["ledoit_wolf", "sample", "ewma"] = "ledoit_wolf"


class ScenarioDefinition(BaseModel):
    code: str
    name: str
    description: str
    mode: Literal["historical_replay", "proxy_scenario", "custom_scenario"]
    market_shock: float = 0.0
    sector_shocks: dict[str, float] = Field(default_factory=dict)
    style_shocks: dict[str, float] = Field(default_factory=dict)
    interest_rate_change_bp: float = 0.0
    currency_shocks: dict[str, float] = Field(default_factory=dict)
    volatility_change: float = 0.0
    start_date: date | None = None
    end_date: date | None = None


class StressTestRequest(BaseModel):
    portfolio_id: int | None = Field(default=None, gt=0)
    scenario_code: str | None = None
    mode: Literal["historical_replay", "proxy_scenario", "custom_scenario"] = "proxy_scenario"
    start_date: date | None = None
    end_date: date | None = None
    market_shock: float = Field(default=0.0, ge=-0.8, le=0.8)
    nasdaq_shock: float = Field(default=0.0, ge=-0.8, le=0.8)
    sector_shocks: dict[str, float] = Field(default_factory=dict)
    style_shocks: dict[str, float] = Field(default_factory=dict)
    interest_rate_change_bp: float = Field(default=0.0, ge=-1000, le=1000)
    currency_shocks: dict[str, float] = Field(default_factory=dict)
    volatility_change: float = Field(default=0.0, ge=-1.0, le=3.0)
    use_fundamental_modifiers: bool = True

    def model_post_init(self, __context) -> None:
        if any(not -0.9 <= value <= 0.9 for value in self.sector_shocks.values()):
            raise ValueError("行业冲击必须在 -90% 至 90% 之间")
        if any(not -0.9 <= value <= 0.9 for value in self.style_shocks.values()):
            raise ValueError("风格冲击必须在 -90% 至 90% 之间")
        if any(not -0.5 <= value <= 0.5 for value in self.currency_shocks.values()):
            raise ValueError("汇率冲击必须在 -50% 至 50% 之间")
        if self.mode == "historical_replay" and (self.start_date is None or self.end_date is None or self.start_date >= self.end_date):
            raise ValueError("真实历史回放需要有效的开始和结束日期")


class ScenarioAnalysisRequest(BaseModel):
    portfolio_id: int | None = Field(default=None, gt=0)
    scenario_code: str
    use_fundamental_modifiers: bool = True


class ExpectedReturnRequest(BaseModel):
    portfolio_id: int | None = Field(default=None, gt=0)
    risk_free_rate: float = Field(default=0.04, ge=-0.05, le=0.2)
    equity_risk_premium: float = Field(default=0.05, ge=0.0, le=0.2)


class MonteCarloInput(BaseModel):
    portfolio_id: int | None = Field(default=None, gt=0)
    horizon_years: Literal[1, 3, 5] = 1
    simulations: Literal[1000, 5000, 10000] = 5000
    method: Literal["multivariate_normal", "block_bootstrap", "student_t"] = "block_bootstrap"
    block_length: int = Field(default=10, ge=5, le=20)
    rebalance_frequency: Literal["none", "monthly", "quarterly", "annual"] = "quarterly"
    monthly_contribution: float = Field(default=0.0, ge=0.0, le=1_000_000)
    target_value: float | None = Field(default=None, gt=0)
    confidence_levels: list[float] = Field(default_factory=lambda: [0.8, 0.95])
    random_seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    force_refresh: bool = False

    def model_post_init(self, __context) -> None:
        if any(level not in {0.8, 0.9, 0.95, 0.99} for level in self.confidence_levels):
            raise ValueError("不支持的置信水平")


class OptimizationConstraints(BaseModel):
    long_only: bool = True
    min_position_weight: float = Field(default=0.0, ge=0.0, le=0.2)
    max_position_weight: float = Field(default=0.20, gt=0.0, le=1.0)
    max_sector_weight: float = Field(default=0.35, gt=0.0, le=1.0)
    min_cash_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    max_cash_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    max_turnover: float = Field(default=0.25, ge=0.0, le=2.0)
    minimum_positions: int | None = Field(default=None, ge=1)
    locked_symbols: list[str] = Field(default_factory=list)
    do_not_sell_symbols: list[str] = Field(default_factory=list)
    excluded_symbols: list[str] = Field(default_factory=list)
    allow_new_symbols: bool = False
    only_current_positions: bool = True
    minimum_trade_amount: float = Field(default=0.0, ge=0.0)
    fractional_shares: bool = True

    def model_post_init(self, __context) -> None:
        if self.min_position_weight > self.max_position_weight:
            raise ValueError("最低仓位不能高于单股最高仓位")
        if self.min_cash_weight > self.max_cash_weight:
            raise ValueError("最低现金比例不能高于最高现金比例")


class OptimizationRequest(BaseModel):
    portfolio_id: int | None = Field(default=None, gt=0)
    objective: Literal["stable", "balanced", "aggressive", "custom", "minimum_variance", "maximum_sharpe", "target_return", "risk_parity", "maximum_diversification", "minimum_cvar"] = "balanced"
    target_return: float | None = Field(default=None, ge=-0.2, le=1.0)
    covariance_method: Literal["ledoit_wolf", "ewma", "sample"] = "ledoit_wolf"
    constraints: OptimizationConstraints = Field(default_factory=OptimizationConstraints)
