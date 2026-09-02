from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioAnalysisRun, PortfolioPosition

from .scenario_presets import VISIBLE_SCENARIO_CODES
from .scenario_analysis import calculate_scenario_analysis
from .schemas import (
    MonteCarloInput,
    OptimizationRequest,
    PortfolioAnalysisRequest,
    ScenarioAnalysisRequest,
    StressTestRequest,
)
from .stress_test import calculate_stress_test


ASYNC_MODEL_VERSION = "portfolio-scenario-v1.0"
PRELOAD_REFRESH_DAYS = 7
PRELOAD_ACTIVE_DEDUPE_HOURS = 24
PRELOAD_FAILED_COOLDOWN_HOURS = 24
PRELOAD_LOAD_LIMIT = 2.0
PRELOAD_MIN_MEM_AVAILABLE_BYTES = 700 * 1024 * 1024
PRELOAD_TIMEZONE = ZoneInfo("Asia/Shanghai")

# These payloads intentionally mirror the current frontend defaults. Keep the
# values boring and explicit: changing a default is a cache/schema decision.
METRICS_PRELOAD_REQUEST = {
    "benchmark": "SPY",
    "confidence_level": 0.95,
    "covariance_method": "ledoit_wolf",
    "mode": "common_start",
    "history_period": "max_available",
}
STRESS_PRELOAD_REQUEST = {
    "mode": "proxy_scenario",
    "scenario_code": "recession",
    "start_date": None,
    "end_date": None,
    "market_shock": -0.20,
    "nasdaq_shock": 0.0,
    "sector_shocks": {"Technology": -0.25},
    "style_shocks": {},
    "interest_rate_change_bp": 100,
    "currency_shocks": {"USD": 0.05},
    "volatility_change": 0.0,
    "use_fundamental_modifiers": True,
}
MONTE_CARLO_PRELOAD_REQUEST = {
    "horizon_years": 1,
    "simulations": 5000,
    "method": "block_bootstrap",
    "block_length": 10,
    "rebalance_frequency": "quarterly",
    "monthly_contribution": 0.0,
    "target_value": None,
    "confidence_levels": [0.8, 0.95],
    "random_seed": 42,
    "force_refresh": True,
}
OPTIMIZATION_PRELOAD_REQUEST = {
    "objective": "balanced",
    "target_return": None,
    "covariance_method": "ledoit_wolf",
    "constraints": {
        "long_only": True,
        "min_position_weight": 0.0,
        "max_position_weight": 0.20,
        "max_sector_weight": 0.35,
        "min_cash_weight": 0.03,
        "max_cash_weight": 0.40,
        "max_turnover": 0.25,
        "minimum_positions": None,
        "locked_symbols": [],
        "do_not_sell_symbols": [],
        "excluded_symbols": [],
        "allow_new_symbols": False,
        "only_current_positions": True,
        "minimum_trade_amount": 0.0,
        "fractional_shares": True,
    },
}


def preload_specs(portfolio_id: int) -> list[tuple[str, dict]]:
    """Return one deterministic weekly batch in execution order."""
    metrics = {**METRICS_PRELOAD_REQUEST, "portfolio_id": portfolio_id}
    stress = {**copy.deepcopy(STRESS_PRELOAD_REQUEST), "portfolio_id": portfolio_id}
    scenarios = [
        (
            "scenario_analysis",
            {"portfolio_id": portfolio_id, "scenario_code": code, "use_fundamental_modifiers": True},
        )
        for code in VISIBLE_SCENARIO_CODES
    ]
    optimization = {**copy.deepcopy(OPTIMIZATION_PRELOAD_REQUEST), "portfolio_id": portfolio_id}
    monte_carlo = {**copy.deepcopy(MONTE_CARLO_PRELOAD_REQUEST), "portfolio_id": portfolio_id}
    return [
        ("metrics", metrics),
        ("stress_test", stress),
        *scenarios,
        ("optimization", optimization),
        ("monte_carlo", monte_carlo),
    ]


def _aware(value: datetime | None, *, default: datetime | None = None) -> datetime:
    current = value or default or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _run_time(run: PortfolioAnalysisRun) -> datetime:
    return _aware(run.completed_at or run.created_at)


def _is_preload_run(run: PortfolioAnalysisRun) -> bool:
    snapshot = run.input_snapshot_json if isinstance(run.input_snapshot_json, dict) else {}
    marker = snapshot.get("preload")
    assumptions = run.assumptions_json if isinstance(run.assumptions_json, dict) else {}
    return (
        isinstance(marker, dict) and marker.get("scheduled") is True
    ) or assumptions.get("preload") is True


def _portfolio_preload_due(db: Session, portfolio_id: int, now: datetime) -> bool:
    """Use persisted runs as the weekly cursor and debounce failed batches."""
    now = _aware(now)
    fresh_cutoff = now - timedelta(days=PRELOAD_REFRESH_DAYS)
    active_cutoff = now - timedelta(hours=PRELOAD_ACTIVE_DEDUPE_HOURS)
    failed_cutoff = now - timedelta(hours=PRELOAD_FAILED_COOLDOWN_HOURS)
    fresh_metrics = db.scalars(
        select(PortfolioAnalysisRun)
        .where(
            PortfolioAnalysisRun.portfolio_id == portfolio_id,
            PortfolioAnalysisRun.analysis_type == "metrics",
            PortfolioAnalysisRun.status == "completed",
            PortfolioAnalysisRun.completed_at >= fresh_cutoff,
        )
        .order_by(PortfolioAnalysisRun.completed_at.desc(), PortfolioAnalysisRun.id.desc())
        .limit(50)
    ).all()
    latest_metrics = next((run for run in fresh_metrics if _is_preload_run(run)), None)
    if latest_metrics:
        failed_runs = db.scalars(
            select(PortfolioAnalysisRun)
            .where(
                PortfolioAnalysisRun.portfolio_id == portfolio_id,
                PortfolioAnalysisRun.status == "failed",
                func.coalesce(PortfolioAnalysisRun.completed_at, PortfolioAnalysisRun.created_at) >= fresh_cutoff,
            )
            .order_by(func.coalesce(PortfolioAnalysisRun.completed_at, PortfolioAnalysisRun.created_at).desc(), PortfolioAnalysisRun.id.desc())
            .limit(50)
        ).all()
        latest_failed = next((run for run in failed_runs if _is_preload_run(run)), None)
        if latest_failed and _run_time(latest_failed) > _run_time(latest_metrics):
            if _run_time(latest_failed) >= failed_cutoff:
                return False
            return True
        return False

    active = db.scalar(
        select(PortfolioAnalysisRun.id)
        .where(
            PortfolioAnalysisRun.portfolio_id == portfolio_id,
            PortfolioAnalysisRun.status.in_(("pending", "running")),
            PortfolioAnalysisRun.created_at >= active_cutoff,
        )
        .order_by(PortfolioAnalysisRun.created_at.desc(), PortfolioAnalysisRun.id.desc())
        .limit(1)
    )
    if active:
        return False
    failed_runs = db.scalars(
        select(PortfolioAnalysisRun)
        .where(
            PortfolioAnalysisRun.portfolio_id == portfolio_id,
            PortfolioAnalysisRun.status == "failed",
            func.coalesce(PortfolioAnalysisRun.completed_at, PortfolioAnalysisRun.created_at) >= failed_cutoff,
        )
        .order_by(func.coalesce(PortfolioAnalysisRun.completed_at, PortfolioAnalysisRun.created_at).desc(), PortfolioAnalysisRun.id.desc())
        .limit(50)
    ).all()
    failed = next((run for run in failed_runs if _is_preload_run(run)), None)
    return failed is None


def preload_due_portfolio_ids(db: Session, *, now: datetime | None = None) -> list[int]:
    current = _aware(now)
    portfolio_ids = db.scalars(
        select(Portfolio.id)
        .join(PortfolioPosition, PortfolioPosition.portfolio_id == Portfolio.id)
        .where(PortfolioPosition.total_quantity > 0)
        .distinct()
        .order_by(Portfolio.id)
    ).all()
    return [
        portfolio_id
        for portfolio_id in portfolio_ids
        if _portfolio_preload_due(db, portfolio_id, current)
    ]


def claim_preload_batch(db: Session, portfolio_id: int, *, now: datetime | None = None) -> list[int]:
    """Claim one portfolio under its row lock and persist its single snapshot."""
    now = _aware(now)
    portfolio = db.scalar(select(Portfolio).where(Portfolio.id == portfolio_id).with_for_update())
    if portfolio is None or not _portfolio_preload_due(db, portfolio_id, now):
        return []
    from .service import _finite_json, _position_snapshot

    stale_cutoff = now - timedelta(hours=PRELOAD_ACTIVE_DEDUPE_HOURS)
    stale_runs = db.scalars(
        select(PortfolioAnalysisRun).where(
            PortfolioAnalysisRun.portfolio_id == portfolio.id,
            PortfolioAnalysisRun.status.in_(("pending", "running")),
            PortfolioAnalysisRun.created_at < stale_cutoff,
        )
    ).all()
    for stale in stale_runs:
        if _is_preload_run(stale):
            stale.status = "failed"
            stale.error_message = "scheduled preload run timed out while active"
            stale.completed_at = now

    positions, snapshot_warnings = _position_snapshot(db, portfolio)
    batch_id = uuid4().hex
    snapshot = _finite_json(positions)
    runs: list[PortfolioAnalysisRun] = []
    for analysis_type, request in preload_specs(portfolio.id):
        runs.append(
            PortfolioAnalysisRun(
                portfolio_id=portfolio.id,
                analysis_type=analysis_type,
                status="pending",
                input_snapshot_json={
                    "request": request,
                    "portfolio": snapshot,
                    "snapshot_warnings": list(snapshot_warnings),
                    "preload": {"scheduled": True, "batch_id": batch_id},
                },
                assumptions_json={"preload": True, "batch_id": batch_id},
                result_json={},
                model_version=ASYNC_MODEL_VERSION,
            )
        )
    db.add_all(runs)
    db.commit()
    return [run.id for run in runs]


def read_system_capacity() -> tuple[float | None, int | None]:
    try:
        load_1m = os.getloadavg()[0]
    except (AttributeError, OSError):
        load_1m = None
    available = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        pass
    if available is None and sys.platform == "darwin":
        try:
            output = subprocess.run(
                ["vm_stat"],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout
            page_size_match = re.search(r"page size of (\d+) bytes", output)
            page_size = int(page_size_match.group(1)) if page_size_match else 4096
            page_counts: dict[str, int] = {}
            for line in output.splitlines():
                match = re.match(r"Pages (free|inactive|speculative):\s+(\d+)\.", line)
                if match:
                    page_counts[match.group(1)] = int(match.group(2))
            if page_counts:
                available = sum(page_counts.values()) * page_size
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return load_1m, available


def capacity_guard(*, now: datetime | None = None, force: bool = False) -> tuple[bool, str | None]:
    current = _aware(now)
    local = current.astimezone(PRELOAD_TIMEZONE)
    if not force and not (7 <= local.hour < 9):
        return False, "outside_window"
    load_1m, mem_available = read_system_capacity()
    if load_1m is None:
        return False, "load_unavailable"
    if load_1m > PRELOAD_LOAD_LIMIT:
        return False, "load_high"
    if mem_available is None:
        return False, "memory_unavailable"
    if mem_available < PRELOAD_MIN_MEM_AVAILABLE_BYTES:
        return False, "memory_low"
    return True, None


def queue_preload_chain(run_ids: list[int]):
    """Queue a single immutable chain; task execution order is the run order."""
    if not run_ids:
        return None
    from celery import chain

    from app.tasks.celery_app import run_portfolio_analysis

    return chain(*(run_portfolio_analysis.si(run_id) for run_id in run_ids)).apply_async()


def schedule_due_preloads(db: Session, *, now: datetime | None = None, force: bool = False) -> dict:
    current = _aware(now)
    allowed, reason = capacity_guard(now=current, force=force)
    if not allowed:
        return {"status": "deferred", "reason": reason, "run_ids": []}
    claimed: list[dict] = []
    errors: list[str] = []
    for portfolio_id in preload_due_portfolio_ids(db, now=current):
        try:
            run_ids = claim_preload_batch(db, portfolio_id, now=current)
        except Exception as exc:
            db.rollback()
            errors.append(f"portfolio {portfolio_id}: {type(exc).__name__}")
            continue
        if not run_ids:
            continue
        claimed.append({"portfolio_id": portfolio_id, "run_ids": run_ids})
    run_ids = [run_id for item in claimed for run_id in item["run_ids"]]
    queued = claimed
    if run_ids:
        try:
            result = queue_preload_chain(run_ids)
        except Exception as exc:
            for run_id in run_ids:
                run = db.get(PortfolioAnalysisRun, run_id)
                if run and run.status in {"pending", "running"}:
                    run.status = "failed"
                    run.error_message = f"preload enqueue failed: {type(exc).__name__}"
                    run.completed_at = current
            db.commit()
            errors.append(f"enqueue: {type(exc).__name__}")
            queued = []
        else:
            for item in claimed:
                item["task_id"] = getattr(result, "id", None)
    if errors:
        return {"status": "partial", "queued": queued, "errors": errors}
    return {"status": "queued" if run_ids else "fresh", "queued": claimed, "run_ids": run_ids}


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
        snapshot_warnings = run.input_snapshot_json.get("snapshot_warnings", [])
        if run.analysis_type == "metrics":
            from .service import run_metrics_analysis

            result = run_metrics_analysis(
                db,
                portfolio,
                PortfolioAnalysisRequest.model_validate(payload),
                run=run,
                positions_override=positions,
                snapshot_warnings=snapshot_warnings,
            )
        elif run.analysis_type == "stress_test":
            result = calculate_stress_test(db, portfolio, StressTestRequest.model_validate(payload), positions_override=positions)
        elif run.analysis_type == "scenario_analysis":
            result = calculate_scenario_analysis(db, portfolio, ScenarioAnalysisRequest.model_validate(payload), positions_override=positions)
        elif run.analysis_type == "monte_carlo":
            from .monte_carlo import calculate_monte_carlo
            result = calculate_monte_carlo(db, portfolio, MonteCarloInput.model_validate(payload), positions_override=positions)
        elif run.analysis_type == "optimization":
            from .optimizer import calculate_optimization
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
