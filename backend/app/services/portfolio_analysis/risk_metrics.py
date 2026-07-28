from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from .return_engine import TRADING_DAYS, annualized_return, compounded_period_returns, wealth_curve


def covariance_matrix(returns: pd.DataFrame, method: str = "ledoit_wolf") -> pd.DataFrame:
    complete = returns.dropna(how="any")
    columns = list(returns.columns)
    if complete.empty:
        return pd.DataFrame(np.zeros((len(columns), len(columns))), index=columns, columns=columns)
    if len(columns) == 1:
        value = float(complete.iloc[:, 0].var(ddof=1)) if len(complete) > 1 else 0.0
        return pd.DataFrame([[max(0.0, value)]], index=columns, columns=columns)
    if method == "sample":
        return complete.cov()
    if method == "ewma":
        return complete.ewm(span=60, adjust=False).cov().loc[complete.index[-1]]
    # Ledoit-Wolf shrinkage toward a scaled identity. This compact analytical
    # implementation keeps the risk engine usable in minimal worker images
    # without adding a second numerical runtime solely for this estimator.
    values = complete.to_numpy(dtype=float)
    centered = values - values.mean(axis=0)
    n_samples, n_features = centered.shape
    sample = centered.T @ centered / n_samples
    target_mean = float(np.trace(sample) / n_features)
    target = np.eye(n_features) * target_mean
    delta = float(np.square(sample - target).sum())
    if delta <= 0:
        shrunk = sample
    else:
        beta = sum(float(np.square(np.outer(row, row) - sample).sum()) for row in centered) / (n_samples ** 2)
        shrinkage = min(1.0, max(0.0, beta / delta))
        shrunk = shrinkage * target + (1 - shrinkage) * sample
    return pd.DataFrame(shrunk, index=columns, columns=columns)


def drawdown_details(returns: pd.Series) -> dict:
    curve = wealth_curve(returns)
    if curve.empty:
        return {"value": None, "start_date": None, "trough_date": None, "recovery_date": None, "unrecovered": None, "longest_duration_days": None, "recovery_days": None}
    peaks = curve.cummax()
    drawdown = curve / peaks - 1
    trough = drawdown.idxmin()
    peak_value = peaks.loc[trough]
    start_candidates = curve.loc[:trough][curve.loc[:trough] >= peak_value - 1e-12]
    start = start_candidates.index[-1]
    recovery_candidates = curve.loc[trough:][curve.loc[trough:] >= peak_value - 1e-12]
    recovery = recovery_candidates.index[0] if len(recovery_candidates) else None
    durations: list[int] = []
    current = 0
    for underwater in (drawdown < 0):
        current = current + 1 if underwater else 0
        durations.append(current)
    return {
        "value": float(drawdown.min()),
        "start_date": start.isoformat(),
        "trough_date": trough.isoformat(),
        "recovery_date": recovery.isoformat() if recovery is not None else None,
        "unrecovered": recovery is None,
        "longest_duration_days": int(max(durations, default=0)),
        "recovery_days": int((recovery - trough).days) if recovery is not None else None,
    }


def historical_var_cvar(returns: pd.Series, confidence: float) -> tuple[float | None, float | None]:
    clean = returns.dropna()
    if clean.empty:
        return None, None
    threshold = float(clean.quantile(1 - confidence))
    tail = clean[clean <= threshold]
    return threshold, float(tail.mean()) if not tail.empty else threshold


def risk_contributions(covariance: pd.DataFrame, weights: pd.Series) -> list[dict]:
    weights = weights.reindex(covariance.columns).fillna(0.0)
    vector = weights.to_numpy(dtype=float)
    cov = covariance.to_numpy(dtype=float) * TRADING_DAYS
    variance = float(vector @ cov @ vector)
    volatility = math.sqrt(max(variance, 0.0))
    if volatility <= 0:
        return [{"symbol": s, "weight": float(weights[s]), "risk_contribution": 0.0, "contribution_amount": 0.0} for s in covariance.columns]
    marginal = cov @ vector / volatility
    amount = vector * marginal
    return [
        {"symbol": symbol, "weight": float(weights[symbol]), "risk_contribution": float(amount[i] / volatility), "contribution_amount": float(amount[i])}
        for i, symbol in enumerate(covariance.columns)
    ]


def calculate_metrics(
    portfolio_returns: pd.Series,
    asset_returns: pd.DataFrame,
    weights: pd.Series,
    sectors: dict[str, str],
    benchmark_returns: pd.Series | None,
    covariance_method: str,
    risk_free_rate: float = 0.0,
) -> dict:
    annual_return = annualized_return(portfolio_returns)
    annual_volatility = float(portfolio_returns.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(portfolio_returns) > 1 else 0.0
    cumulative = float((1 + portfolio_returns).prod() - 1) if len(portfolio_returns) else None
    downside = portfolio_returns[portfolio_returns < 0]
    downside_vol = float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(TRADING_DAYS)) if len(downside) else 0.0
    dd = drawdown_details(portfolio_returns)
    var95, cvar95 = historical_var_cvar(portfolio_returns, 0.95)
    var99, cvar99 = historical_var_cvar(portfolio_returns, 0.99)
    excess = (annual_return - risk_free_rate) if annual_return is not None else None
    sharpe = excess / annual_volatility if excess is not None and annual_volatility > 0 else None
    sortino = excess / downside_vol if excess is not None and downside_vol > 0 else None
    calmar = annual_return / abs(dd["value"]) if annual_return is not None and dd["value"] not in (None, 0) else None
    beta = None
    if benchmark_returns is not None:
        paired = pd.concat([portfolio_returns.rename("portfolio"), benchmark_returns.rename("benchmark")], axis=1).dropna()
        if len(paired) > 1:
            variance = float(paired["benchmark"].var(ddof=1))
            beta = float(paired.cov().loc["portfolio", "benchmark"] / variance) if variance > 0 else None
    covariance = covariance_matrix(asset_returns, covariance_method)
    contributions = risk_contributions(covariance, weights)
    sector_amounts: dict[str, float] = defaultdict(float)
    for row in contributions:
        sector_amounts[sectors.get(row["symbol"]) or "未分类"] += row["contribution_amount"]
    total_amount = sum(sector_amounts.values())
    sector_rows = [
        {"sector": sector, "risk_contribution": amount / total_amount if total_amount else 0.0, "contribution_amount": amount}
        for sector, amount in sorted(sector_amounts.items(), key=lambda x: abs(x[1]), reverse=True)
    ]
    weekly = compounded_period_returns(portfolio_returns, "W-FRI")
    monthly = compounded_period_returns(portfolio_returns, "ME")
    correlation = asset_returns.corr(min_periods=20).fillna(0.0)
    curve = wealth_curve(portfolio_returns)
    drawdown_curve = curve / curve.cummax() - 1
    return {
        "metrics": {
            "annual_return": annual_return, "annual_volatility": annual_volatility, "cumulative_return": cumulative,
            "max_drawdown": dd["value"], "longest_drawdown_duration_days": dd["longest_duration_days"],
            "drawdown_recovery_days": dd["recovery_days"], "worst_day_return": float(portfolio_returns.min()) if len(portfolio_returns) else None,
            "worst_week_return": float(weekly.min()) if len(weekly) else None, "worst_month_return": float(monthly.min()) if len(monthly) else None,
            "var_95": var95, "cvar_95": cvar95, "var_99": var99, "cvar_99": cvar99,
            "sharpe_ratio": sharpe, "sortino_ratio": sortino, "calmar_ratio": calmar, "beta": beta,
            "downside_volatility": downside_vol, "hhi": float(np.square(weights).sum()),
        },
        "max_drawdown_detail": dd,
        "asset_risk_contributions": contributions,
        "sector_risk_contributions": sector_rows,
        "correlation_matrix": {symbol: {other: float(correlation.loc[symbol, other]) for other in correlation.columns} for symbol in correlation.index},
        "covariance_matrix": {symbol: {other: float(covariance.loc[symbol, other]) for other in covariance.columns} for symbol in covariance.index},
        "portfolio_curve": [{"date": idx.isoformat(), "value": float(value)} for idx, value in curve.items()],
        "drawdown_curve": [{"date": idx.isoformat(), "value": float(value)} for idx, value in drawdown_curve.items()],
    }
