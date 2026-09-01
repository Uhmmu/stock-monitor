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
from app.models import BacktestEquityPoint, BacktestRun, BacktestTrade, CryptoInstrument, User
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


# --- Goal 5: deployments, signals and paper trading ------------------------


class DeploymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_key: str
    instrument_id: int
    interval: str
    target_exposure: float = Field(default=1.0, ge=0.25, le=1.0)


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class PaperAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_cash: Decimal = Field(default=Decimal("10000"), ge=100, le=10_000_000)
    leverage_cap: Decimal = Field(default=Decimal("1"), ge=1, le=3)
    taker_fee_bps: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    maker_fee_bps: Decimal = Field(default=Decimal("2"), ge=0, le=100)
    spread_bps: Decimal = Field(default=Decimal("2"), ge=0, le=100)
    slippage_bps: Decimal = Field(default=Decimal("2"), ge=0, le=200)
    maintenance_margin_ratio: Decimal = Field(default=Decimal("0.005"), gt=0, le=Decimal("0.1"))
    liquidation_fee_bps: Decimal = Field(default=Decimal("50"), ge=0, le=500)


class PaperOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: int
    side: str
    order_type: str
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    leverage: Decimal = Field(default=Decimal("1"), ge=1, le=3)
    position_side: str = "BOTH"
    client_order_id: str | None = Field(default=None, min_length=8, max_length=64)


class PaperResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str
    initial_cash: Decimal | None = Field(default=None, ge=100, le=10_000_000)
    strategy_metadata: dict = Field(default_factory=dict)


def _require_signal_enabled() -> None:
    if not get_settings().quant_signal_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "信号生成当前已暂停")


def _require_paper_enabled() -> None:
    if not get_settings().quant_paper_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "模拟盘当前已暂停")


@router.get("/deployments")
def deployments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    return {"items": [signal_service.deployment_payload(db, row) for row in signal_service.list_deployments(db, user.id)]}


@router.post("/deployments", status_code=status.HTTP_201_CREATED)
def create_deployment(payload: DeploymentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    try:
        row = signal_service.create_deployment(
            db, user_id=user.id, strategy_key=payload.strategy_key,
            instrument_id=payload.instrument_id, interval=payload.interval,
            target_exposure=payload.target_exposure,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return signal_service.deployment_payload(db, row)


def _owned_deployment(db: Session, user_id: int, deployment_id: int):
    from app.services.quant import signals as signal_service
    row = signal_service.owned_deployment(db, user_id, deployment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该策略部署")
    return row


@router.post("/deployments/{deployment_id}/pause")
def pause_deployment(deployment_id: int, payload: StatusChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    return signal_service.deployment_payload(
        db, signal_service.set_deployment_status(
            db, _owned_deployment(db, user.id, deployment_id), status="paused", reason=payload.reason,
        ),
    )


@router.post("/deployments/{deployment_id}/resume")
def resume_deployment(deployment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    return signal_service.deployment_payload(
        db, signal_service.set_deployment_status(db, _owned_deployment(db, user.id, deployment_id), status="active"),
    )


@router.get("/signals")
def signals(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    try:
        return signal_service.list_signals(db, user.id, status=status_filter, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/signals/runs")
def signal_runs(
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    return signal_service.list_signal_runs(db, user.id, limit=limit, offset=offset)


@router.get("/signals/{signal_id}")
def signal_detail(signal_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    row = signal_service.get_signal(db, user.id, signal_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该信号")
    return signal_service.signal_payload(db, row)


@router.post("/signals/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_signals(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import signals as signal_service
    _require_signal_enabled()
    recent = signal_service.manual_generation_cooldown(db)
    if recent is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "手动触发冷却中，请稍后再试")
    from app.tasks.celery_app import run_quant_signal_generation
    queued = run_quant_signal_generation.delay()
    return {"status": "queued", "task_id": queued.id}


@router.get("/paper")
def paper_account_view(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    account = paper_service.owned_account(db, user.id)
    if account is None:
        return {"account": None}
    return {"account": paper_service.account_payload(db, account)}


@router.post("/paper/account", status_code=status.HTTP_201_CREATED)
def create_paper_account(payload: PaperAccountCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    try:
        account, created = paper_service.ensure_account(
            db, user_id=user.id, initial_cash=payload.initial_cash,
            leverage_cap=payload.leverage_cap, taker_fee_bps=payload.taker_fee_bps,
            maker_fee_bps=payload.maker_fee_bps,
            spread_bps=payload.spread_bps, slippage_bps=payload.slippage_bps,
            maintenance_margin_ratio=payload.maintenance_margin_ratio,
            liquidation_fee_bps=payload.liquidation_fee_bps,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if created != "created":
        raise HTTPException(status.HTTP_409_CONFLICT, "模拟盘账户已存在；资金与成本以首次创建为准")
    return {"account": paper_service.account_payload(db, account)}


def _owned_paper_account(db: Session, user_id: int):
    from app.services.quant import paper as paper_service
    account = paper_service.owned_account(db, user_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "请先创建模拟盘账户")
    return account


@router.post("/paper/pause")
def pause_paper(payload: StatusChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return {"account": paper_service.account_payload(
        db, paper_service.set_account_status(db, _owned_paper_account(db, user.id), status="paused", reason=payload.reason),
    )}


@router.post("/paper/resume")
def resume_paper(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return {"account": paper_service.account_payload(
        db, paper_service.set_account_status(db, _owned_paper_account(db, user.id), status="active"),
    )}


@router.post("/paper/process", status_code=status.HTTP_202_ACCEPTED)
def process_paper(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    account = _owned_paper_account(db, user.id)
    from app.tasks.celery_app import process_paper_signals
    queued = process_paper_signals.delay(account.id)
    return {"status": "queued", "account_id": account.id, "task_id": queued.id}


@router.post("/paper/reconcile")
def reconcile_paper(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    account = _owned_paper_account(db, user.id)
    record = paper_service.reconcile_account(db, account)
    return {"reconciliation": paper_service.reconciliation_payload(record),
            "account": paper_service.account_payload(db, account)}


@router.post("/paper/reconcile/repair")
def repair_paper(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    account = _owned_paper_account(db, user.id)
    record = paper_service.reconcile_account(db, account, repair=True)
    return {"reconciliation": paper_service.reconciliation_payload(record),
            "account": paper_service.account_payload(db, account)}


@router.post("/paper/orders", status_code=status.HTTP_201_CREATED)
def create_paper_order(
    payload: PaperOrderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    try:
        order = paper_service.submit_manual_order(
            db, _owned_paper_account(db, user.id), instrument_id=payload.instrument_id,
            side=payload.side, order_type=payload.order_type, quantity=payload.quantity,
            limit_price=payload.limit_price, leverage=payload.leverage,
            position_side=payload.position_side, client_order_id=payload.client_order_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return paper_service.order_payload(db, order)


@router.post("/paper/orders/{order_id}/cancel")
def cancel_paper_order(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    try:
        order = paper_service.cancel_order(db, _owned_paper_account(db, user.id), order_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return paper_service.order_payload(db, order)


@router.post("/paper/reset", status_code=status.HTTP_201_CREATED)
def reset_paper_account(
    payload: PaperResetRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    if payload.confirm != "RESET PAPER":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "必须明确输入 RESET PAPER")
    run = paper_service.reset_account(
        db, _owned_paper_account(db, user.id), initial_cash=payload.initial_cash,
        strategy_metadata=payload.strategy_metadata,
    )
    return {"run": paper_service.run_payload(db, run),
            "account": paper_service.account_payload(db, _owned_paper_account(db, user.id))}


@router.get("/paper/runs")
def paper_runs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return paper_service.list_runs(db, _owned_paper_account(db, user.id))


@router.get("/paper/fills")
def paper_fills(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return paper_service.list_fills(db, _owned_paper_account(db, user.id), limit=limit)


@router.get("/paper/ledger")
def paper_ledger(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return paper_service.list_ledger(db, _owned_paper_account(db, user.id), limit=limit)


@router.get("/paper/config")
def paper_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    account = _owned_paper_account(db, user.id)
    state = paper_service.account_payload(db, account)
    return {
        "execution_mode": "paper", "market_data": "binance_production_public",
        "credentials_required": False, "authenticated_trading_available": False,
        "costs": state["costs"], "leverage_cap": state["leverage_cap"],
        "supported": {"markets": ["spot", "futures"], "order_types": ["market", "limit"]},
        "instruments": [
            {"id": row.id, "provider_symbol": row.provider_symbol,
             "market_type": "spot" if row.market == "spot" else "futures", "kind": row.kind}
            for row in db.scalars(select(CryptoInstrument).where(
                CryptoInstrument.venue == "binance",
                CryptoInstrument.market.in_(["spot", "usdm_futures"]),
                CryptoInstrument.status == "trading",
            ).order_by(CryptoInstrument.market, CryptoInstrument.provider_symbol))
        ],
    }


@router.get("/paper/orders")
def paper_orders(
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return paper_service.list_orders(db, _owned_paper_account(db, user.id).id, limit=limit, offset=offset)


@router.get("/paper/reconciliations")
def paper_reconciliations(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    from app.services.quant import paper as paper_service
    _require_paper_enabled()
    return paper_service.list_reconciliations(db, _owned_paper_account(db, user.id).id, limit=limit)
