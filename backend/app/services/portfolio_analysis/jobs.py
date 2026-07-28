from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioAnalysisRun

from .scenario_analysis import calculate_scenario_analysis
from .schemas import ScenarioAnalysisRequest, StressTestRequest
from .stress_test import calculate_stress_test


ASYNC_MODEL_VERSION = "portfolio-scenario-v1.0"


def create_analysis_job(db: Session, portfolio: Portfolio, analysis_type: str, payload: dict) -> PortfolioAnalysisRun:
    from .service import _position_snapshot
    positions, snapshot_warnings = _position_snapshot(db, portfolio)
    run = PortfolioAnalysisRun(
        portfolio_id=portfolio.id, analysis_type=analysis_type, status="pending",
        input_snapshot_json={"request": payload, "portfolio": positions, "snapshot_warnings": snapshot_warnings},
        assumptions_json={"numeric_engine": "python", "ai_numeric_generation": False},
        result_json={}, model_version=ASYNC_MODEL_VERSION,
    )
    db.add(run); db.commit(); db.refresh(run)
    return run


def execute_analysis_job(db: Session, run_id: int) -> dict:
    run = db.get(PortfolioAnalysisRun, run_id)
    if run is None:
        return {"status": "missing"}
    if run.status == "completed":
        return run.result_json
    run.status = "running"; db.commit()
    try:
        portfolio = db.get(Portfolio, run.portfolio_id)
        if portfolio is None:
            raise ValueError("组合不存在")
        payload = run.input_snapshot_json.get("request", run.input_snapshot_json)
        positions = run.input_snapshot_json.get("portfolio")
        if run.analysis_type == "stress_test":
            result = calculate_stress_test(db, portfolio, StressTestRequest.model_validate(payload), positions_override=positions)
        elif run.analysis_type == "scenario_analysis":
            result = calculate_scenario_analysis(db, portfolio, ScenarioAnalysisRequest.model_validate(payload), positions_override=positions)
        elif run.analysis_type == "monte_carlo":
            from .monte_carlo import calculate_monte_carlo
            from .schemas import MonteCarloInput
            result = calculate_monte_carlo(db, portfolio, MonteCarloInput.model_validate(payload), positions_override=positions)
        elif run.analysis_type == "optimization":
            from .optimizer import calculate_optimization
            from .schemas import OptimizationRequest
            result = calculate_optimization(db, portfolio, OptimizationRequest.model_validate(payload), positions_override=positions, include_stress_comparison=True)
        else:
            raise ValueError(f"不支持的分析类型：{run.analysis_type}")
        run.result_json, run.status, run.completed_at = result, "completed", datetime.now(UTC)
        if result.get("cache_key"):
            run.assumptions_json = {**run.assumptions_json, "cache_key": result["cache_key"], "cache_parts": result.get("cache_parts", {})}
        if result.get("model_version"):
            run.model_version = result["model_version"]
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        run = db.get(PortfolioAnalysisRun, run_id)
        if run:
            run.status, run.error_message, run.completed_at = "failed", str(exc)[:2000], datetime.now(UTC)
            db.commit()
        return {"status": "failed", "message": str(exc)}
