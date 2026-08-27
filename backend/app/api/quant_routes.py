"""Authenticated, research-only crypto quant/backtest API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import BacktestEquityPoint, BacktestRun, BacktestTrade, User
from app.services.quant.backtest import service


router = APIRouter(prefix="/api/crypto/quant", dependencies=[Depends(get_current_user)])


class BacktestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_key: str
    instrument_ids: list[int] = Field(min_length=1, max_length=3)
    interval: str
    start_at: datetime
    end_at: datetime
    target_exposure: float = Field(default=1.0, ge=0.25, le=1.0)
    initial_capital: Decimal = Field(default=Decimal("100000"), ge=1000, le=1_000_000)
    leverage: Decimal = Field(default=Decimal("1"), ge=1, le=3)
    taker_fee_bps: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    spread_bps: Decimal = Field(default=Decimal("2"), ge=0, le=100)
    slippage_bps: Decimal = Field(default=Decimal("2"), ge=0, le=200)
    split_mode: str = "full"


def _owned(db: Session, user_id: int, run_id: int) -> BacktestRun:
    row = service.owned_run(db, user_id, run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该回测")
    return row


@router.get("/definitions")
def definitions(db: Session = Depends(get_db)):
    return service.definitions_payload(db)


@router.get("/features/status")
@router.get("/features")
def features(db: Session = Depends(get_db)):
    return service.features_payload(db)


@router.get("/status")
def quant_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    active = db.scalar(select(func.count()).select_from(BacktestRun).where(
        BacktestRun.user_id == user.id, BacktestRun.status.in_(service.ACTIVE_STATUSES),
    )) or 0
    return {"enabled": get_settings().crypto_quant_enabled, "active_runs": active, "features": service.features_payload(db)}


@router.post("/backtests", status_code=status.HTTP_202_ACCEPTED)
def create_backtest(payload: BacktestCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not get_settings().crypto_quant_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "量化研究任务当前已暂停")
    try:
        run = service.create_run(db, user_id=user.id, **payload.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    from app.tasks.celery_app import run_crypto_backtest
    queued = run_crypto_backtest.delay(run.id)
    return {**service.run_payload(db, run), "task_id": queued.id}


@router.get("/backtests")
def backtests(
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return service.list_runs(db, user.id, limit, offset)


@router.get("/backtests/compare")
def compare_backtests(
    run_ids: str = Query(min_length=3, max_length=128),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    try:
        ids = list(dict.fromkeys(int(value) for value in run_ids.split(",") if value.strip()))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "run_ids 必须为逗号分隔整数") from exc
    if not 2 <= len(ids) <= 4:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请选择 2–4 个回测")
    rows = [_owned(db, user.id, run_id) for run_id in ids]
    return {"items": [service.run_payload(db, row) for row in rows]}


@router.get("/backtests/{run_id}")
def backtest_detail(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.run_payload(db, _owned(db, user.id, run_id))


@router.get("/backtests/{run_id}/equity")
def backtest_equity(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned(db, user.id, run_id)
    rows = db.scalars(select(BacktestEquityPoint).where(BacktestEquityPoint.run_id == run.id).order_by(BacktestEquityPoint.timestamp))
    return {"items": [{"time": row.timestamp, "nav": row.nav, "equity": row.nav, "cash": row.cash,
                        "exposure": row.gross_exposure, "drawdown": row.drawdown} for row in rows]}


@router.get("/backtests/{run_id}/trades")
def backtest_trades(
    run_id: int, limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    run = _owned(db, user.id, run_id)
    query = select(BacktestTrade).where(BacktestTrade.run_id == run.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(BacktestTrade.fill_time, BacktestTrade.id).limit(limit).offset(offset))
    return {"items": [{"id": row.id, "time": row.fill_time, "instrument_id": row.instrument_id,
                        "side": row.side, "quantity": row.quantity, "price": row.price, "fee": row.fee,
                        "slippage": row.slippage, "funding": row.funding, "reason": row.reason} for row in rows],
            "total": total, "limit": limit, "offset": offset}


@router.post("/backtests/{run_id}/cancel")
def cancel_backtest(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.run_payload(db, service.cancel_run(db, _owned(db, user.id, run_id)))


@router.post("/backtests/{run_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
def rerun_backtest(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        run = service.rerun(db, _owned(db, user.id, run_id))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    from app.tasks.celery_app import run_crypto_backtest
    queued = run_crypto_backtest.delay(run.id)
    return {**service.run_payload(db, run), "task_id": queued.id}
