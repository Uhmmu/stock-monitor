from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialStatementSnapshot, Portfolio, PortfolioAnalysisRun, ValuationSnapshot

from .data_loader import load_joint_returns
from .factor_model import estimate_sensitivities
from .return_engine import annualized_return
from .schemas import ExpectedReturnRequest
from .service import _finite_json, _position_snapshot


MODEL_VERSION = "expected-return-blend-v1.0"
MODEL_WEIGHTS = {"historical": .20, "capm": .30, "fundamental": .35, "forward": .15}


def _number(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            result = float(value)
            return result / 100 if abs(result) > 2 else result
    return None


def _fundamental_model(db: Session, symbol: str) -> tuple[float | None, list[str]]:
    row = db.scalar(select(FinancialStatementSnapshot).where(FinancialStatementSnapshot.ticker == symbol).order_by(FinancialStatementSnapshot.synced_at.desc()).limit(1))
    if row is None:
        return None, []
    payload = {
        **(row.income_statement if isinstance(row.income_statement, dict) else {}),
        **(row.cash_flow if isinstance(row.cash_flow, dict) else {}),
    }
    growth = _number(payload, "earnings_growth", "revenue_growth", "net_income_growth")
    dividend = _number(payload, "dividend_yield") or 0.0
    buyback = _number(payload, "buyback_yield") or 0.0
    if growth is None:
        return None, []
    return float(np.clip(growth + dividend + buyback, -.25, .35)), ["盈利增长", *( ["股息"] if dividend else []), *( ["回购"] if buyback else [])]


def _forward_model(db: Session, symbol: str) -> tuple[float | None, list[str]]:
    row = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == symbol).order_by(ValuationSnapshot.snapshot_date.desc()).limit(1))
    payload = row.payload if row and isinstance(row.payload, dict) else {}
    upside = _number(payload, "analyst_upside", "target_upside", "forward_return")
    return (float(np.clip(upside, -.4, .5)), ["分析师/估值前瞻"]) if upside is not None else (None, [])


def calculate_expected_return(db: Session, portfolio: Portfolio, request: ExpectedReturnRequest, *, positions_override: list[dict] | None = None) -> dict:
    positions, warnings = (positions_override, []) if positions_override is not None else _position_snapshot(db, portfolio)
    total = sum(float(row["market_value"]) for row in positions)
    if not positions or total <= 0:
        return {"status": "insufficient_data", "message": "当前组合没有可估值持仓", "confidence": "low", "assets": [], "warnings": warnings}
    weights = {row["symbol"]: float(row["market_value"]) / total for row in positions}
    loaded = load_joint_returns(db, list(weights), weights, mode="dynamic_available")
    warnings.extend(loaded.warnings)
    asset_rows = []
    for position in positions:
        symbol = position["symbol"]
        series = loaded.returns[symbol].dropna() if symbol in loaded.returns else None
        historical = annualized_return(series.tail(5 * 252)) if series is not None and len(series) >= 60 else None
        ewma = float(series.ewm(span=126).mean().iloc[-1] * 252) if series is not None and len(series) >= 60 else None
        if historical is not None and ewma is not None:
            historical = float(np.clip(.6 * historical + .4 * ewma, -.3, .4))
        sensitivity = estimate_sensitivities(db, symbol, position.get("sector"), position.get("asset_type"))
        capm = float(np.clip(request.risk_free_rate + sensitivity["market_beta"] * request.equity_risk_premium, -.1, .3))
        fundamental, fundamental_drivers = _fundamental_model(db, symbol)
        forward, forward_drivers = _forward_model(db, symbol)
        models = {"historical": historical, "capm": capm, "fundamental": fundamental, "forward": forward}
        available = {key: value for key, value in models.items() if value is not None}
        denominator = sum(MODEL_WEIGHTS[key] for key in available)
        normalized = {key: MODEL_WEIGHTS[key] / denominator for key in available}
        base = sum(available[key] * normalized[key] for key in available)
        annual_vol = float(series.std(ddof=1) * np.sqrt(252)) if series is not None and len(series) > 1 else .25
        spread = float(np.clip(annual_vol * .45, .04, .22))
        confidence = "high" if len(available) == 4 and series is not None and len(series) >= 756 else "medium" if len(available) >= 2 and series is not None and len(series) >= 252 else "low"
        drivers = ["CAPM", *fundamental_drivers, *forward_drivers]
        asset_rows.append({"symbol": symbol, "weight": weights[symbol], "bear": float(np.clip(base - spread, -.8, 1)), "base": float(base), "bull": float(np.clip(base + spread, -.8, 1)), "confidence": confidence, "models": models, "model_weights": normalized, "drivers": drivers, "warnings": [] if fundamental is not None else ["基本面隐含收益数据不足"]})
    portfolio_base = sum(row["weight"] * row["base"] for row in asset_rows)
    portfolio_bear = sum(row["weight"] * row["bear"] for row in asset_rows)
    portfolio_bull = sum(row["weight"] * row["bull"] for row in asset_rows)
    confidence = min((row["confidence"] for row in asset_rows), key={"low": 0, "medium": 1, "high": 2}.get)
    return _finite_json({"status": "completed", "portfolio_value": total, "portfolio": {"bear": portfolio_bear, "base": portfolio_base, "bull": portfolio_bull, "confidence": confidence}, "assets": asset_rows, "assumptions": {"risk_free_rate": request.risk_free_rate, "equity_risk_premium": request.equity_risk_premium, "model_weights": MODEL_WEIGHTS}, "confidence": confidence, "warnings": warnings, "model_version": MODEL_VERSION})


def run_expected_return(db: Session, portfolio: Portfolio, request: ExpectedReturnRequest) -> dict:
    positions, snapshot_warnings = _position_snapshot(db, portfolio)
    result = calculate_expected_return(db, portfolio, request, positions_override=positions)
    if snapshot_warnings:
        result["warnings"] = list(dict.fromkeys([*result.get("warnings", []), *snapshot_warnings]))
    run = PortfolioAnalysisRun(portfolio_id=portfolio.id, analysis_type="expected_return", status="completed", input_snapshot_json={"request": request.model_dump(mode="json"), "portfolio": positions}, assumptions_json=result.get("assumptions", {}), result_json=result, model_version=MODEL_VERSION, completed_at=datetime.now(UTC))
    db.add(run); db.commit(); db.refresh(run)
    return {**result, "run_id": run.id}
