from __future__ import annotations

import pandas as pd


TRADING_DAYS = 252


def compounded_period_returns(returns: pd.Series, frequency: str) -> pd.Series:
    if returns.empty:
        return returns
    return (1 + returns).resample(frequency).prod() - 1


def wealth_curve(returns: pd.Series) -> pd.Series:
    return (1 + returns).cumprod()


def annualized_return(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    total = float((1 + returns).prod())
    if total <= 0:
        return -1.0
    return total ** (TRADING_DAYS / len(returns)) - 1
