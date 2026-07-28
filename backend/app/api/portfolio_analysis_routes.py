from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.services.portfolio.transaction_service import get_or_create_default_portfolio
from app.services.portfolio_analysis import PortfolioAnalysisRequest, run_metrics_analysis
from app.services.portfolio_analysis.jobs import create_analysis_job
from app.services.portfolio_analysis.scenario_presets import preset_catalog
from app.services.portfolio_analysis.schemas import ExpectedReturnRequest, MonteCarloInput, OptimizationRequest, ScenarioAnalysisRequest, StressTestRequest
from app.services.portfolio_analysis.expected_return import run_expected_return
from app.services.portfolio_analysis.optimizer import optimization_presets
from app.services.portfolio_analysis.service import ANALYSIS_CACHE_DAYS, latest_metrics
from app.models import PortfolioAnalysisRun
from sqlalchemy import select


router = APIRouter(prefix="/api/portfolio/analysis", dependencies=[Depends(get_current_user)])


@router.post("/metrics")
def create_metrics(payload: PortfolioAnalysisRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if payload.portfolio_id is not None and payload.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    return run_metrics_analysis(db, portfolio, payload)


@router.get("/metrics/{portfolio_id}")
def get_metrics(portfolio_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if portfolio.id != portfolio_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    result = latest_metrics(db, portfolio.id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该组合尚无风险分析记录")
    return result


@router.get("/scenarios/presets")
def scenario_presets():
    return {"presets": preset_catalog()}


def _queue(db: Session, portfolio, analysis_type: str, payload: dict) -> dict:
    run = create_analysis_job(db, portfolio, analysis_type, payload)
    from app.tasks.celery_app import run_portfolio_analysis
    run_portfolio_analysis.delay(run.id)
    return {"job_id": run.id, "status": run.status, "analysis_type": analysis_type}


@router.post("/stress-test", status_code=status.HTTP_202_ACCEPTED)
def stress_test(payload: StressTestRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if payload.portfolio_id is not None and payload.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    return _queue(db, portfolio, "stress_test", payload.model_dump(mode="json"))


@router.post("/scenario-analysis", status_code=status.HTTP_202_ACCEPTED)
def scenario_analysis(payload: ScenarioAnalysisRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if payload.portfolio_id is not None and payload.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    return _queue(db, portfolio, "scenario_analysis", payload.model_dump(mode="json"))


@router.post("/expected-return")
def expected_return(payload: ExpectedReturnRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if payload.portfolio_id is not None and payload.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    return run_expected_return(db, portfolio, payload)


@router.post("/monte-carlo", status_code=status.HTTP_202_ACCEPTED)
def monte_carlo(payload: MonteCarloInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if payload.portfolio_id is not None and payload.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    return _queue(db, portfolio, "monte_carlo", payload.model_dump(mode="json"))


@router.get("/optimization-presets")
def get_optimization_presets():
    return optimization_presets()


@router.post("/optimize", status_code=status.HTTP_202_ACCEPTED)
def optimize(payload: OptimizationRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    if payload.portfolio_id is not None and payload.portfolio_id != portfolio.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该组合")
    return _queue(db, portfolio, "optimization", payload.model_dump(mode="json"))


@router.get("/jobs/{job_id}")
def analysis_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    run = db.scalar(select(PortfolioAnalysisRun).where(PortfolioAnalysisRun.id == job_id, PortfolioAnalysisRun.portfolio_id == portfolio.id))
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该分析任务")
    return {"job_id": run.id, "analysis_type": run.analysis_type, "status": run.status, "result": run.result_json if run.status == "completed" else None, "error_message": run.error_message, "created_at": run.created_at, "completed_at": run.completed_at}


@router.get("/history")
def analysis_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = get_or_create_default_portfolio(db, user.id)
    runs = db.scalars(select(PortfolioAnalysisRun).where(PortfolioAnalysisRun.portfolio_id == portfolio.id).order_by(PortfolioAnalysisRun.created_at.desc(), PortfolioAnalysisRun.id.desc()).limit(100)).all()
    now = datetime.now(UTC)
    serialized = []
    for run in runs:
        completed_at = run.completed_at
        if completed_at is not None and completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        anchor = completed_at or run.created_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        expires_at = anchor + timedelta(days=ANALYSIS_CACHE_DAYS)
        snapshot = run.input_snapshot_json if isinstance(run.input_snapshot_json, dict) else {}
        request_snapshot = snapshot.get("request", {})
        serialized.append({
            "job_id": run.id,
            "analysis_type": run.analysis_type,
            "status": run.status,
            "result": run.result_json,
            "input_request": request_snapshot if isinstance(request_snapshot, dict) else {},
            "model_version": run.model_version,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "expires_at": expires_at,
            "is_fresh": run.status == "completed" and expires_at > now,
            "error_message": run.error_message,
        })
    return {"cache_days": ANALYSIS_CACHE_DAYS, "runs": serialized}
