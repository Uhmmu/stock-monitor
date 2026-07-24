from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import (
    StockDiscoveryCandidate,
    StockDiscoveryRun,
    StockDiscoveryUsage,
    User,
    WatchlistItem,
)
from app.services.discovery.schemas import DiscoverySettingsUpdate
from app.services.discovery.service import (
    DiscoveryCooldownError,
    candidate_detail_payload,
    create_discovery_run,
    discovery_run_payload,
    discovery_settings,
    latest_discovery_payload,
    monthly_spend,
    settings_payload,
    update_discovery_settings,
)
from app.services.portfolio.transaction_service import get_or_create_default_portfolio
from app.services.securities import resolve_security


router = APIRouter(prefix="/api/discovery", dependencies=[Depends(get_current_user)])


class RefreshIn(BaseModel):
    # Kept for compatibility with clients deployed before discovery became
    # manual-only. Every accepted request is now an explicit paid rerun.
    force: bool = False


def _owned_run(db: Session, user_id: int, run_id: int) -> StockDiscoveryRun:
    run = db.scalar(select(StockDiscoveryRun).where(StockDiscoveryRun.id == run_id, StockDiscoveryRun.user_id == user_id))
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该机会发现批次")
    return run


@router.get("/latest")
def discovery_latest(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return latest_discovery_payload(db, user.id)


@router.get("/runs")
def discovery_history(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    runs = db.scalars(select(StockDiscoveryRun).where(StockDiscoveryRun.user_id == user.id)
                      .order_by(StockDiscoveryRun.requested_at.desc()).limit(limit)).all()
    return [discovery_run_payload(db, run, include_candidates=False) for run in runs]


@router.get("/runs/{run_id}")
def discovery_run(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return discovery_run_payload(db, _owned_run(db, user.id, run_id))


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def discovery_refresh(payload: RefreshIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not get_settings().perplexity_api_key.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "无法运行：尚未配置 Perplexity API Key。")
    portfolio = get_or_create_default_portfolio(db, user.id)
    try:
        run, should_queue = create_discovery_run(db, portfolio, user.id)
    except DiscoveryCooldownError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    if should_queue:
        from app.tasks.celery_app import run_stock_discovery
        run_stock_discovery.delay(run.id)
    return {"run_id": run.id, "status": run.status, "queued": should_queue}


@router.get("/settings")
def discovery_settings_get(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return settings_payload(db, user.id)


@router.patch("/settings")
def discovery_settings_patch(
    payload: DiscoverySettingsUpdate,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    update_discovery_settings(db, user.id, payload)
    return settings_payload(db, user.id)


@router.get("/candidates/{candidate_id}")
def discovery_candidate(candidate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = candidate_detail_payload(db, user.id, candidate_id)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该研究候选")
    return payload


def _owned_candidate(db: Session, user_id: int, candidate_id: int) -> StockDiscoveryCandidate:
    row = db.scalar(select(StockDiscoveryCandidate).join(StockDiscoveryRun)
        .where(StockDiscoveryCandidate.id == candidate_id, StockDiscoveryRun.user_id == user_id))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该研究候选")
    return row


@router.post("/candidates/{candidate_id}/watchlist", status_code=status.HTTP_201_CREATED)
def candidate_to_watchlist(candidate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    candidate = _owned_candidate(db, user.id, candidate_id)
    ticker = candidate.normalized_ticker
    if not ticker or len(ticker) > 16:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "该候选暂无可用的本地股票代码")
    existing = db.scalar(select(WatchlistItem).where(WatchlistItem.ticker == ticker))
    if existing:
        return {"ticker": ticker, "status": "already_watched", "watchlist_id": existing.id}
    security_id = (candidate.normalized_data or {}).get("security_id")
    try:
        security = resolve_security(db, security_id=security_id, source="local" if security_id else "yahoo", yahoo_symbol=ticker)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    defaults = get_settings()
    row = WatchlistItem(
        security_id=security.id, ticker=security.yahoo_symbol or ticker,
        threshold_20m=defaults.default_threshold_20m, threshold_1h=defaults.default_threshold_1h,
        threshold_day=defaults.default_threshold_day,
    )
    db.add(row); db.commit(); db.refresh(row)
    candidate.display_status = "already_watched"; candidate.filter_status = "already_watched"; db.commit()
    from app.tasks.celery_app import sync_ticker_full
    sync_ticker_full.delay(row.ticker)
    return {"ticker": row.ticker, "status": "added", "watchlist_id": row.id}


@router.post("/candidates/{candidate_id}/dismiss")
def candidate_dismiss(candidate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    candidate = _owned_candidate(db, user.id, candidate_id)
    candidate.dismissed = True; db.commit()
    return {"id": candidate.id, "dismissed": True}


@router.post("/candidates/{candidate_id}/researched")
def candidate_researched(candidate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    candidate = _owned_candidate(db, user.id, candidate_id)
    candidate.researched = True; db.commit()
    return {"id": candidate.id, "researched": True}


@router.get("/usage")
def discovery_usage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = discovery_settings(db, user.id)
    rows = db.execute(select(StockDiscoveryUsage, StockDiscoveryRun)
        .join(StockDiscoveryRun, StockDiscoveryRun.id == StockDiscoveryUsage.run_id)
        .where(StockDiscoveryRun.user_id == user.id)
        .order_by(StockDiscoveryRun.requested_at.desc()).limit(50)).all()
    return {
        "month_to_date_cost_usd": monthly_spend(db, user.id), "monthly_budget_usd": config.monthly_budget_usd,
        "runs": [{"run_id": run.id, "requested_at": run.requested_at, "model": run.model_used or run.model_requested,
                  "total_cost_usd": usage.total_cost_usd, "finance_search_calls": usage.finance_search_calls,
                  "web_search_calls": usage.web_search_calls} for usage, run in rows],
    }
