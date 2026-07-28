from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioAnalysisRun

from .bootstrap import joint_block_bootstrap
from .data_loader import load_joint_returns
from .expected_return import calculate_expected_return
from .risk_metrics import covariance_matrix
from .schemas import ExpectedReturnRequest, MonteCarloInput
from .service import ANALYSIS_CACHE_DAYS, _finite_json, _position_snapshot
from .simulation_metrics import summarize_simulations


MODEL_VERSION = "monte-carlo-v1.0"
BATCH_SIZE = 200


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _rebalance_interval(frequency: str) -> int | None:
    return {"none": None, "monthly": 21, "quarterly": 63, "annual": 252}[frequency]


def _draw_returns(method: str, history: np.ndarray, days: int, count: int, block_length: int, rng: np.random.Generator, expected_daily: np.ndarray, covariance: np.ndarray) -> np.ndarray:
    if method == "block_bootstrap":
        sampled = joint_block_bootstrap(history, days, count, block_length, rng)
        return sampled + (expected_daily - history.mean(axis=0))[None, None, :]
    if method == "multivariate_normal":
        return rng.multivariate_normal(expected_daily, covariance, size=(count, days))
    # Multivariate Student-t with five degrees of freedom and covariance scaling.
    df = 5
    normal = rng.multivariate_normal(np.zeros(history.shape[1]), covariance * (df - 2) / df, size=(count, days))
    scale = np.sqrt(rng.chisquare(df, size=(count, days, 1)) / df)
    return expected_daily[None, None, :] + normal / scale


def calculate_monte_carlo(
    db: Session,
    portfolio: Portfolio,
    request: MonteCarloInput,
    *,
    positions_override: list[dict] | None = None,
    returns_override=None,
    expected_override: dict[str, float] | None = None,
) -> dict:
    positions, warnings = (positions_override, []) if positions_override is not None else _position_snapshot(db, portfolio)
    initial = sum(float(row["market_value"]) for row in positions)
    if not positions or initial <= 0:
        return {"status": "insufficient_data", "message": "当前组合没有可估值持仓", "confidence": "low", "limitations": warnings}
    weights_map = {row["symbol"]: float(row["market_value"]) / initial for row in positions}
    if returns_override is None:
        loaded = load_joint_returns(db, list(weights_map), weights_map, mode="common_start")
        returns = loaded.returns.dropna(how="any")
        warnings.extend(loaded.warnings)
        price_end = returns.index.max().isoformat() if not returns.empty else None
    else:
        returns = returns_override.dropna(how="any")
        price_end = returns.index.max().isoformat() if len(returns) else None
    symbols = [symbol for symbol in returns.columns if symbol in weights_map]
    if len(returns) < max(60, request.block_length) or not symbols:
        return {"status": "insufficient_data", "message": "联合历史收益样本不足", "confidence": "low", "limitations": warnings + ["无法构造可靠的联合收益分布"]}
    weights = np.array([weights_map[s] for s in symbols], dtype=float); weights /= weights.sum()
    if expected_override is None:
        expected_result = calculate_expected_return(db, portfolio, ExpectedReturnRequest(portfolio_id=portfolio.id), positions_override=positions)
        expected_map = {row["symbol"]: row["base"] for row in expected_result.get("assets", [])}
    else:
        expected_map = expected_override
        expected_result = {"confidence": "medium", "assumptions": {}}
    expected_annual = np.array([expected_map.get(symbol, .06) for symbol in symbols], dtype=float)
    expected_daily = np.power(1 + np.clip(expected_annual, -.95, 2), 1 / 252) - 1
    covariance = covariance_matrix(returns[symbols], "ledoit_wolf").to_numpy(dtype=float)
    portfolio_snapshot = [(symbol, round(float(weight), 10)) for symbol, weight in zip(symbols, weights)]
    assumptions = {"expected_return_model": expected_result.get("assumptions", {}), "covariance_model": "ledoit_wolf", "trading_days_per_year": 252, "student_t_degrees_of_freedom": 5}
    cache_parts = {"portfolio_hash": _hash(portfolio_snapshot), "price_data_end_date": price_end, "method": request.method, "horizon": request.horizon_years, "simulation_count": request.simulations, "rebalance_frequency": request.rebalance_frequency, "contribution": request.monthly_contribution, "assumption_hash": _hash(assumptions), "block_length": request.block_length, "random_seed": request.random_seed}
    cache_key = _hash(cache_parts)
    if returns_override is None and not request.force_refresh:
        recent = db.scalars(select(PortfolioAnalysisRun).where(PortfolioAnalysisRun.portfolio_id == portfolio.id, PortfolioAnalysisRun.analysis_type == "monte_carlo", PortfolioAnalysisRun.status == "completed", PortfolioAnalysisRun.completed_at >= datetime.now(UTC) - timedelta(days=ANALYSIS_CACHE_DAYS)).order_by(PortfolioAnalysisRun.id.desc()).limit(50)).all()
        for run in recent:
            if run.assumptions_json.get("cache_key") == cache_key:
                return {**run.result_json, "cache_hit": True, "source_run_id": run.id}

    rng = np.random.default_rng(request.random_seed)
    days = request.horizon_years * 252
    terminal = np.empty(request.simulations); drawdowns = np.empty(request.simulations)
    sample_count = min(75, request.simulations); sample_paths = np.empty((sample_count, days + 1), dtype=np.float32); sample_cursor = 0
    checkpoints = sorted(set([0, *range(21, days + 1, 21), days])); fan_values = np.empty((request.simulations, len(checkpoints)), dtype=np.float32)
    rebalance_every = _rebalance_interval(request.rebalance_frequency)
    history = returns[symbols].to_numpy(dtype=float)
    cursor = 0
    while cursor < request.simulations:
        count = min(BATCH_SIZE, request.simulations - cursor)
        generated = np.clip(_draw_returns(request.method, history, days, count, request.block_length, rng, expected_daily, covariance), -.95, 3.0)
        values = np.tile(weights * initial, (count, 1)); totals = np.full(count, initial); peaks = totals.copy(); max_dd = np.zeros(count)
        batch_samples = min(count, sample_count - sample_cursor)
        if batch_samples > 0:
            sample_paths[sample_cursor:sample_cursor + batch_samples, 0] = initial
        fan_values[cursor:cursor + count, 0] = initial
        checkpoint_index = 1
        for day in range(1, days + 1):
            values *= 1 + generated[:, day - 1, :]
            if request.monthly_contribution and day % 21 == 0:
                values += request.monthly_contribution * weights
            totals = values.sum(axis=1)
            if rebalance_every and day % rebalance_every == 0:
                values = totals[:, None] * weights
            peaks = np.maximum(peaks, totals); max_dd = np.minimum(max_dd, totals / peaks - 1)
            if batch_samples > 0:
                sample_paths[sample_cursor:sample_cursor + batch_samples, day] = totals[:batch_samples]
            if checkpoint_index < len(checkpoints) and day == checkpoints[checkpoint_index]:
                fan_values[cursor:cursor + count, checkpoint_index] = totals; checkpoint_index += 1
        terminal[cursor:cursor + count] = totals; drawdowns[cursor:cursor + count] = max_dd
        cursor += count; sample_cursor += batch_samples
    summary = summarize_simulations(initial, terminal, drawdowns, request.target_value)
    fan = [{"day": day, **{f"p{level}": float(np.percentile(fan_values[:, index], level)) for level in (5, 25, 50, 75, 95)}} for index, day in enumerate(checkpoints)]
    limitations = list(warnings)
    years = len(returns) / 252
    if years < 2: limitations.append("历史数据少于 2 年")
    if max(weights) > .4: limitations.append("组合高度集中，模拟区间对单一持仓较敏感")
    if expected_result.get("confidence") == "low": limitations.append("部分预期收益模型缺少基本面数据")
    limitations.append("历史行情主要覆盖 2021 年之后，不能代表完整市场周期")
    confidence = "low" if years < 2 or max(weights) > .6 else "medium" if limitations else "high"
    result = {"status": "completed", "initial_value": initial, "horizon_years": request.horizon_years, "simulations": request.simulations, "method": request.method, **summary, "fan_chart": fan, "sample_paths": [[float(value) for value in row] for row in sample_paths], "terminal_value_sample": [float(value) for value in terminal[:min(1000, len(terminal))]], "max_drawdown_sample": [float(value) for value in drawdowns[:min(1000, len(drawdowns))]], "confidence": confidence, "limitations": list(dict.fromkeys(limitations)), "assumptions": assumptions, "cache_key": cache_key, "cache_parts": cache_parts, "cache_hit": False, "model_version": MODEL_VERSION}
    return _finite_json(result)
