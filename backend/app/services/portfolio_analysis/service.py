from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompanyProfile, Portfolio, PortfolioAnalysisRun, Security, StockProfile
from app.services.portfolio.performance import build_summary

from .data_loader import load_joint_returns
from .risk_metrics import calculate_metrics
from .schemas import PortfolioAnalysisRequest


MODEL_VERSION = "portfolio-risk-v1.0"
COVERAGE_NOTICE = "历史数据仅覆盖 2021 年之后，不能代表完整市场周期"
ANALYSIS_CACHE_DAYS = 7


def _finite_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def _position_snapshot(db: Session, portfolio: Portfolio) -> tuple[list[dict], list[str]]:
    summary = build_summary(db, portfolio)
    symbols = [row["symbol"] for row in summary["positions"]]
    profiles = {row.ticker: row for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all()} if symbols else {}
    company = {row.symbol: row for row in db.scalars(select(CompanyProfile).where(CompanyProfile.symbol.in_(symbols))).all()} if symbols else {}
    securities = {row.id: row for row in db.scalars(select(Security).where(Security.id.in_([p["security_id"] for p in summary["positions"] if p["security_id"]]))).all()} if symbols else {}
    positions: list[dict] = []
    warnings: list[str] = []
    for row in summary["positions"]:
        if not row["valuation_available"] or row["base_currency_market_value"] is None:
            warnings.append(f'{row["symbol"]} 缺少价格或汇率，无法纳入当前市值权重')
            continue
        profile = profiles.get(row["symbol"])
        fmp_profile = company.get(row["symbol"])
        security = securities.get(row["security_id"])
        positions.append({
            "symbol": row["symbol"], "quantity": row["total_quantity"],
            "market_value": row["base_currency_market_value"], "currency": row["currency"],
            "asset_type": security.instrument_type if security else None,
            "sector": (profile.official_sector if profile else None) or (fmp_profile.sector if fmp_profile else None),
            "industry": (profile.official_industry if profile else None) or (fmp_profile.industry if fmp_profile else None),
            "current_price": row["current_price"], "price_source": row["price_source"], "price_as_of": row["price_as_of"],
        })
    return positions, warnings


def run_metrics_analysis(db: Session, portfolio: Portfolio, request: PortfolioAnalysisRequest) -> dict:
    positions, warnings = _position_snapshot(db, portfolio)
    total_value = sum(float(row["market_value"]) for row in positions)
    snapshot = {
        "portfolio_id": portfolio.id, "base_currency": portfolio.base_currency,
        "positions": [{**row, "weight": row["market_value"] / total_value if total_value else 0.0} for row in positions],
    }
    assumptions = {
        "benchmark": request.benchmark.upper(), "history_period": request.history_period,
        "confidence_level": request.confidence_level, "mode": request.mode,
        "covariance_method": request.covariance_method, "risk_free_rate": 0.0,
        "price_adjustment": "本地验证 EOD；缺失时 FMP 优先、Yahoo auto_adjust 回退",
        "annualization_days": 252,
    }
    run = PortfolioAnalysisRun(
        portfolio_id=portfolio.id, analysis_type="metrics", status="running",
        input_snapshot_json=_finite_json(snapshot), assumptions_json=assumptions,
        result_json={}, model_version=MODEL_VERSION,
    )
    db.add(run)
    db.flush()
    if not positions or total_value <= 0:
        result = {
            "run_id": run.id, "status": "insufficient_data", "portfolio_value": total_value,
            "data_period": {"start": None, "end": None, "mode": request.mode},
            "metrics": {}, "asset_risk_contributions": [], "sector_risk_contributions": [],
            "correlation_matrix": {}, "portfolio_curve": [], "drawdown_curve": [],
            "confidence": "low", "confidence_reasons": ["当前组合没有可估值的持仓"],
            "warnings": warnings + ["空持仓或持仓均缺少当前估值"], "coverage_warning": COVERAGE_NOTICE,
            "model_version": MODEL_VERSION,
        }
        _complete_run(db, run, result)
        return result

    weights = {row["symbol"]: row["market_value"] / total_value for row in positions}
    loaded = load_joint_returns(db, list(weights), weights, mode=request.mode)
    warnings.extend(loaded.warnings)
    benchmark = load_joint_returns(db, [request.benchmark.upper()], {request.benchmark.upper(): 1.0}, mode="common_start")
    warnings.extend([f"基准：{item}" for item in benchmark.warnings])
    if loaded.portfolio_returns.empty:
        result = {
            "run_id": run.id, "status": "insufficient_data", "portfolio_value": total_value,
            "data_period": {"start": None, "end": None, "mode": request.mode}, "metrics": {},
            "asset_risk_contributions": [], "sector_risk_contributions": [], "correlation_matrix": {},
            "portfolio_curve": [], "drawdown_curve": [], "confidence": "low",
            "confidence_reasons": ["没有足够的联合有效收益率"], "warnings": warnings,
            "coverage_warning": COVERAGE_NOTICE, "model_version": MODEL_VERSION,
        }
        _complete_run(db, run, result)
        return result

    effective_symbols = [s for s in loaded.returns.columns if s in weights]
    effective_total = sum(weights[s] for s in effective_symbols)
    normalized_weights = pd.Series({s: weights[s] / effective_total for s in effective_symbols})
    sectors = {row["symbol"]: row.get("sector") or "未分类" for row in positions}
    calculated = calculate_metrics(
        loaded.portfolio_returns, loaded.returns[effective_symbols], normalized_weights,
        sectors, benchmark.portfolio_returns if not benchmark.portfolio_returns.empty else None,
        request.covariance_method,
    )
    start = loaded.portfolio_returns.index.min().date() if hasattr(loaded.portfolio_returns.index.min(), "date") else loaded.portfolio_returns.index.min()
    end = loaded.portfolio_returns.index.max().date() if hasattr(loaded.portfolio_returns.index.max(), "date") else loaded.portfolio_returns.index.max()
    years = (end - start).days / 365.25
    concentration = max(weights.values(), default=0.0)
    confidence_reasons: list[str] = []
    if years < 2:
        confidence_reasons.append("有效历史数据少于 2 年")
    if concentration > 0.4:
        confidence_reasons.append("组合单一持仓集中度较高")
    missing_weight = 1 - effective_total
    if missing_weight > 0.05:
        confidence_reasons.append(f"约 {missing_weight:.1%} 当前市值缺少有效历史行情")
    confidence = "high" if not confidence_reasons and years >= 4 else "medium" if years >= 2 and missing_weight < 0.2 else "low"
    result = {
        "run_id": run.id, "status": "completed", "portfolio_value": total_value,
        "base_currency": portfolio.base_currency,
        "data_period": {"start": start.isoformat(), "end": end.isoformat(), "mode": request.mode},
        "data_start_date": start.isoformat(), "data_end_date": end.isoformat(),
        "asset_data_start_dates": loaded.actual_start_dates, "price_sources": loaded.sources,
        **calculated, "confidence": confidence, "confidence_reasons": confidence_reasons,
        "warnings": list(dict.fromkeys(warnings)), "coverage_warning": COVERAGE_NOTICE,
        "model_version": MODEL_VERSION, "assumptions": assumptions,
    }
    result = _finite_json(result)
    run.price_data_start_date, run.price_data_end_date = start, end
    _complete_run(db, run, result)
    return result


def _complete_run(db: Session, run: PortfolioAnalysisRun, result: dict) -> None:
    run.status = "completed"
    run.result_json = _finite_json(result)
    run.completed_at = datetime.now(UTC)
    db.commit()


def latest_metrics(db: Session, portfolio_id: int) -> dict | None:
    run = db.scalar(select(PortfolioAnalysisRun).where(
        PortfolioAnalysisRun.portfolio_id == portfolio_id,
        PortfolioAnalysisRun.analysis_type == "metrics",
        PortfolioAnalysisRun.status == "completed",
        PortfolioAnalysisRun.completed_at >= datetime.now(UTC) - timedelta(days=ANALYSIS_CACHE_DAYS),
    ).order_by(PortfolioAnalysisRun.created_at.desc(), PortfolioAnalysisRun.id.desc()).limit(1))
    return run.result_json if run else None
