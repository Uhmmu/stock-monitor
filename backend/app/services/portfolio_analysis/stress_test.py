from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from app.models import Portfolio

from .data_loader import _local_prices
from .factor_model import SECTOR_ETFS, estimate_sensitivities, factor_return
from .scenario_presets import PRESET_MAP
from .schemas import StressTestRequest
from .service import _position_snapshot


PROXY_NOTICE = "该结果基于市场、行业、利率和汇率敏感度估算，并非组合在对应历史时期的真实表现。"


def _period_return(db: Session, symbol: str, start: date, end: date) -> float | None:
    prices, _ = _local_prices(db, symbol)
    if prices.empty:
        return None
    selected = prices[(prices.index.date >= start) & (prices.index.date <= end)]
    if len(selected) < 2:
        return None
    return float(selected.iloc[-1] / selected.iloc[0] - 1)


def _scenario_values(request: StressTestRequest) -> dict:
    preset = PRESET_MAP.get(request.scenario_code or "")
    if preset:
        return preset.model_dump()
    return {
        "code": "custom", "name": "自定义压力测试", "description": "用户设置的因子冲击。", "mode": request.mode,
        "market_shock": request.market_shock, "sector_shocks": request.sector_shocks,
        "style_shocks": request.style_shocks, "interest_rate_change_bp": request.interest_rate_change_bp,
        "currency_shocks": request.currency_shocks, "volatility_change": request.volatility_change,
        "start_date": request.start_date, "end_date": request.end_date,
    }


def calculate_stress_test(db: Session, portfolio: Portfolio, request: StressTestRequest, *, positions_override: list[dict] | None = None) -> dict:
    positions, valuation_warnings = (positions_override, []) if positions_override is not None else _position_snapshot(db, portfolio)
    total_value = sum(float(row["market_value"]) for row in positions)
    if not positions or total_value <= 0:
        return {"status": "insufficient_data", "message": "当前组合没有可估值持仓", "scenario_mode": request.mode, "confidence": "low", "warnings": valuation_warnings, "asset_results": [], "sector_results": []}
    scenario = _scenario_values(request)
    mode = scenario["mode"]
    start = scenario.get("start_date") or request.start_date
    end = scenario.get("end_date") or request.end_date
    if mode == "historical_replay" and (start is None or end is None):
        return {"status": "invalid_input", "message": "真实历史回放缺少日期区间", "scenario_mode": mode, "confidence": "low", "asset_results": [], "sector_results": []}
    if mode == "historical_replay" and start.year < 2021:
        return {"status": "invalid_input", "message": "2021 年之前的区间不能标记为真实历史回放，请使用代理情景", "scenario_mode": mode, "confidence": "low", "asset_results": [], "sector_results": []}

    asset_rows: list[dict] = []
    actual_count = proxy_count = factor_count = 0
    for position in positions:
        symbol, sector = position["symbol"], position.get("sector") or "未分类"
        weight = float(position["market_value"]) / total_value
        sensitivity = None
        method = "factor_model"
        confidence = "low"
        estimated = None
        if mode == "historical_replay":
            estimated = _period_return(db, symbol, start, end)
            if estimated is not None:
                method, confidence, actual_count = "actual", "high", actual_count + 1
            else:
                proxy_symbol = SECTOR_ETFS.get(sector)
                proxy_return = _period_return(db, proxy_symbol, start, end) if proxy_symbol else None
                if proxy_return is not None:
                    estimated, method, confidence, proxy_count = proxy_return, "proxy", "medium", proxy_count + 1
        if estimated is None:
            sensitivity = estimate_sensitivities(db, symbol, sector, position.get("asset_type"))
            sector_shock = float(scenario.get("sector_shocks", {}).get(sector, scenario.get("sector_shocks", {}).get("Semiconductors", 0.0) if "semiconductor" in (position.get("industry") or "").lower() else 0.0))
            currency = position.get("currency") or portfolio.base_currency
            fx_shock = float(scenario.get("currency_shocks", {}).get(currency, 0.0))
            style = float(scenario.get("style_shocks", {}).get("growth", 0.0) + scenario.get("style_shocks", {}).get("value", 0.0))
            market_shock = float(scenario.get("market_shock", 0.0)) + request.nasdaq_shock * (0.6 if sector == "Technology" else 0.1)
            estimated = factor_return(sensitivity, market_shock=market_shock, sector_shock=sector_shock, rate_change_bp=float(scenario.get("interest_rate_change_bp", 0.0)), fx_shock=fx_shock, style_shock=style, volatility_change=float(scenario.get("volatility_change", 0.0)))
            method, confidence, factor_count = "factor_model", sensitivity["confidence"], factor_count + 1
        # Fundamental modifiers are intentionally bounded and neutral until a
        # persisted, comparable fundamental signal is present.
        modifiers = {"valuation_modifier": 1.0, "quality_modifier": 1.0, "leverage_modifier": 1.0}
        if request.use_fundamental_modifiers and estimated < 0:
            estimated = float(np.clip(estimated * np.prod(list(modifiers.values())), -.95, 2.0))
        contribution = weight * estimated
        asset_rows.append({
            "symbol": symbol, "sector": sector, "current_weight": weight, "estimated_return": estimated,
            "portfolio_loss_contribution": contribution, "estimated_value_change": total_value * contribution,
            "method": method, "confidence": confidence, "sensitivity": sensitivity, "modifiers": modifiers,
        })

    portfolio_return = sum(row["portfolio_loss_contribution"] for row in asset_rows)
    sector_values: dict[str, float] = defaultdict(float)
    for row in asset_rows:
        sector_values[row["sector"]] += row["portfolio_loss_contribution"]
    sector_rows = [{"sector": sector, "portfolio_loss_contribution": value, "estimated_value_change": total_value * value} for sector, value in sorted(sector_values.items(), key=lambda x: x[1])]
    equal_weight_return = sum(row["estimated_return"] for row in asset_rows) / len(asset_rows)
    if mode == "historical_replay":
        spy_return = _period_return(db, "SPY", start, end)
    else:
        spy_return = float(scenario.get("market_shock", 0.0))
    if actual_count == len(asset_rows):
        quality = "actual"
    elif actual_count > 0:
        quality = "mixed"
    else:
        quality = "proxy"
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    confidence = min((row["confidence"] for row in asset_rows), key=lambda value: confidence_rank[value])
    warnings = list(valuation_warnings)
    if mode != "historical_replay" or quality != "actual":
        warnings.append(PROXY_NOTICE)
    worst_asset = min(asset_rows, key=lambda row: row["portfolio_loss_contribution"])
    worst_sector = min(sector_rows, key=lambda row: row["portfolio_loss_contribution"])
    return {
        "status": "completed", "scenario": {**scenario, "start_date": start.isoformat() if start else None, "end_date": end.isoformat() if end else None},
        "scenario_mode": mode, "data_quality": quality, "actual_asset_count": actual_count,
        "proxy_asset_count": proxy_count, "factor_model_asset_count": factor_count,
        "portfolio_value": total_value, "estimated_portfolio_return": portfolio_return,
        "estimated_loss_amount": total_value * portfolio_return, "spy_return": spy_return,
        "equal_weight_return": equal_weight_return, "concentration_amplification": portfolio_return - equal_weight_return,
        "largest_loss_contributor": worst_asset["symbol"], "largest_loss_sector": worst_sector["sector"],
        "asset_results": sorted(asset_rows, key=lambda row: row["portfolio_loss_contribution"]),
        "sector_results": sector_rows, "confidence": confidence, "warnings": warnings,
        "explanation": _explain(portfolio_return, worst_asset["symbol"], worst_sector["sector"], quality),
    }


def _explain(portfolio_return: float, symbol: str, sector: str, quality: str) -> str:
    direction = "下跌" if portfolio_return < 0 else "上涨"
    return f"模型估计组合在该假设下{direction}约 {abs(portfolio_return):.1%}；影响最大的持仓为 {symbol}，影响最大的行业为 {sector}。数据质量为 {quality}。"
