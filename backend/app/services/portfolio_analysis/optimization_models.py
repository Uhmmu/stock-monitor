from __future__ import annotations

import numpy as np


OBJECTIVE_MAP = {"stable": "minimum_cvar", "balanced": "risk_parity", "aggressive": "maximum_sharpe"}


def raw_target(objective: str, expected: np.ndarray, covariance: np.ndarray, history: np.ndarray) -> np.ndarray:
    objective = OBJECTIVE_MAP.get(objective, objective)
    volatility = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    if objective in {"minimum_variance", "risk_parity"}:
        score = 1 / volatility
    elif objective == "minimum_cvar":
        tail = np.maximum(1e-6, -np.quantile(history, .05, axis=0))
        score = 1 / tail
    elif objective == "maximum_diversification":
        correlation = covariance / np.outer(volatility, volatility)
        score = volatility / np.maximum(np.abs(correlation).sum(axis=1), 1e-6)
    elif objective in {"maximum_sharpe", "target_return"}:
        score = np.maximum(expected - .04, .001) / np.maximum(volatility, 1e-6)
    else:
        score = np.ones(len(expected))
    score = np.maximum(score, 1e-12)
    return score / score.sum()


def scipy_target(objective: str, expected: np.ndarray, covariance: np.ndarray, history: np.ndarray, current: np.ndarray, sectors: list[str], symbols: list[str], constraints, target_return: float | None) -> np.ndarray | None:
    """Solve the continuous constrained problem with SLSQP when SciPy is available."""
    try:
        from scipy.optimize import minimize
    except ImportError:
        return None
    objective = OBJECTIVE_MAP.get(objective, objective)
    volatility = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    def score(x):
        w=x[:-1]; variance=max(float(w@covariance@w),1e-12); regularization=.01*float(np.square(w-current).sum())
        if objective=="minimum_variance" or objective=="target_return": value=variance
        elif objective=="maximum_sharpe": value=-(float(expected@w+.04*x[-1])-.04)/np.sqrt(variance)
        elif objective=="risk_parity":
            contribution=w*(covariance@w); value=float(np.square(contribution-contribution.sum()/max(len(w),1)).sum())
        elif objective=="maximum_diversification": value=-float(w@volatility)/np.sqrt(variance)
        elif objective=="minimum_cvar":
            losses=-(history@w); cutoff=np.quantile(losses,.95); value=float(losses[losses>=cutoff].mean())
        else:value=variance
        return value+regularization
    cons=[{"type":"eq","fun":lambda x:float(x.sum()-1)},{"type":"ineq","fun":lambda x:constraints.max_turnover-.5*(float(np.abs(x[:-1]-current).sum())+float(abs(x[-1])))}]
    for sector in set(sectors):
        indices=[i for i,value in enumerate(sectors) if value==sector]
        cons.append({"type":"ineq","fun":lambda x,idx=indices:constraints.max_sector_weight-float(x[idx].sum())})
    for i,symbol in enumerate(symbols):
        if symbol in constraints.locked_symbols:cons.append({"type":"eq","fun":lambda x,index=i:float(x[index]-current[index])})
        if symbol in constraints.do_not_sell_symbols:cons.append({"type":"ineq","fun":lambda x,index=i:float(x[index]-current[index])})
    if objective=="target_return" and target_return is not None:cons.append({"type":"ineq","fun":lambda x:float(expected@x[:-1]+.04*x[-1]-target_return)})
    bounds=[]
    for symbol in symbols:
        bounds.append((0,0) if symbol in constraints.excluded_symbols else (constraints.min_position_weight,constraints.max_position_weight))
    bounds.append((constraints.min_cash_weight,constraints.max_cash_weight))
    initial=np.append(current*(1-constraints.min_cash_weight),constraints.min_cash_weight)
    result=minimize(score,initial,method="SLSQP",bounds=bounds,constraints=cons,options={"maxiter":600,"ftol":1e-10})
    return result.x[:-1] if result.success and np.all(np.isfinite(result.x)) else None
