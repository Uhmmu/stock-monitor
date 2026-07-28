from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from .data_loader import load_joint_returns


SECTOR_ETFS = {
    "Technology": "XLK", "Semiconductors": "SOXX", "Financial Services": "XLF", "Financials": "XLF",
    "Healthcare": "XLV", "Health Care": "XLV", "Consumer Cyclical": "XLY", "Industrials": "XLI",
    "Energy": "XLE", "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
    "Communication Services": "XLC", "Consumer Defensive": "XLP",
}
ASSET_DEFAULTS = {"ETF": .9, "FUND": .9, "EQUITY": 1.0, "STOCK": 1.0}


def estimate_sensitivities(db: Session, symbol: str, sector: str | None, asset_type: str | None) -> dict:
    factor_symbols = ["SPY"]
    sector_etf = SECTOR_ETFS.get(sector or "")
    if sector_etf:
        factor_symbols.append(sector_etf)
    weights = {item: 1 / (len(factor_symbols) + 1) for item in [symbol, *factor_symbols]}
    loaded = load_joint_returns(db, [symbol, *factor_symbols], weights, mode="common_start")
    complete = loaded.returns.dropna(how="any")
    market_default = ASSET_DEFAULTS.get((asset_type or "").upper(), 1.0)
    result = {"market_beta": market_default, "sector_beta": .5 if sector_etf else 0.0, "rate_sensitivity": -.00025, "fx_sensitivity": 1.0, "growth_sensitivity": .5, "value_sensitivity": .2, "volatility_sensitivity": -.03, "confidence": "low", "method": "asset_type_default", "observations": len(complete)}
    if len(complete) < 60 or symbol not in complete or "SPY" not in complete:
        return result
    columns = ["SPY"] + ([sector_etf] if sector_etf and sector_etf in complete else [])
    x = complete[columns].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    coefficients, *_ = np.linalg.lstsq(x, complete[symbol].to_numpy(dtype=float), rcond=None)
    result.update({"market_beta": float(np.clip(coefficients[1], -1, 3)), "confidence": "high" if len(complete) >= 500 else "medium", "method": "historical_regression", "observations": len(complete)})
    if len(columns) > 1:
        result["sector_beta"] = float(np.clip(coefficients[2], -1, 3))
    return result


def factor_return(sensitivity: dict, *, market_shock: float, sector_shock: float, rate_change_bp: float, fx_shock: float, style_shock: float, volatility_change: float) -> float:
    value = (
        sensitivity["market_beta"] * market_shock
        + sensitivity["sector_beta"] * sector_shock
        + sensitivity["rate_sensitivity"] * rate_change_bp
        + sensitivity["fx_sensitivity"] * fx_shock
        + sensitivity["growth_sensitivity"] * style_shock
        + sensitivity["volatility_sensitivity"] * volatility_change
    )
    return float(np.clip(value, -.95, 2.0))
