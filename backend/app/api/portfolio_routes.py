"""Holdings (持仓) API.

All endpoints are user-scoped through the user's default portfolio. Writes go
through the transaction service so the aggregated position is always rebuilt from
the authoritative transaction history — the manual-entry endpoint creates a
transaction, never a position row directly (Section 4/5).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import PortfolioPosition, User
from app.services.portfolio import (
    ManualPositionIn,
    PortfolioBenchmarkResponse,
    PortfolioBenchmarkUpdate,
    PortfolioHealthResponse,
    PortfolioInterpretationResponse,
    PortfolioStrategyProfileResponse,
    PortfolioStrategyProfileUpdate,
    TransactionIn,
    TransactionOut,
    build_health,
    build_ledger_overview,
    build_ledger_position_detail,
    completed_trades,
    build_benchmark_comparison,
    build_personalized_interpretation,
    build_position_detail,
    build_position_technical,
    build_summary,
    create_manual_position,
    create_transaction,
    delete_transaction,
    get_or_create_default_portfolio,
    get_or_create_strategy_profile,
    get_transaction,
    list_transactions,
    open_lots,
    performance_series,
    profile_catalog,
    rebuild_all_positions,
    reset_strategy_profile,
    return_attribution,
    transaction_events,
    update_strategy_profile,
    update_transaction,
)
from app.services.securities import resolve_security

router = APIRouter(prefix="/api/portfolio", dependencies=[Depends(get_current_user)])


def _portfolio(db: Session, user: User):
    return get_or_create_default_portfolio(db, user.id)


@router.get("/summary")
def portfolio_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_ledger_overview(db, _portfolio(db, user))


def _range_start(value: str) -> date | None:
    today = datetime.now(UTC).date()
    return {
        "1M": today - timedelta(days=31), "3M": today - timedelta(days=93),
        "6M": today - timedelta(days=186), "YTD": date(today.year, 1, 1),
        "1Y": today - timedelta(days=366), "ALL": None,
    }.get(value.upper())


@router.get("/performance")
def portfolio_performance(
    range: str = Query("1Y", pattern="^(1M|3M|6M|YTD|1Y|ALL)$"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return performance_series(db, _portfolio(db, user), start=_range_start(range))


@router.get("/attribution")
def portfolio_attribution(
    start_date: date | None = None, end_date: date | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return return_attribution(db, _portfolio(db, user), start=start_date, end=end_date)


@router.get("/benchmark", response_model=PortfolioBenchmarkResponse)
def portfolio_benchmark(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_benchmark_comparison(_portfolio(db, user))


@router.put("/benchmark", response_model=PortfolioBenchmarkResponse)
def portfolio_benchmark_update(
    payload: PortfolioBenchmarkUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.start_date is not None and payload.start_date > datetime.now(UTC).date():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "入市日期不能晚于今天")
    portfolio = _portfolio(db, user)
    portfolio.benchmark_start_date = payload.start_date
    portfolio.benchmark_portfolio_return_percent = payload.portfolio_return_percent
    portfolio.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(portfolio)
    return build_benchmark_comparison(portfolio)


@router.get("/positions")
def portfolio_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_summary(db, _portfolio(db, user))["positions"]


@router.get("/positions/{symbol}")
def position_detail(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    detail = build_ledger_position_detail(db, _portfolio(db, user), symbol)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该持仓")
    return detail


@router.get("/positions/{symbol}/technical")
def position_technical(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = _portfolio(db, user)
    pos = db.scalar(
        select(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio.id,
            PortfolioPosition.symbol == symbol.upper(),
        )
    )
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该持仓")
    return build_position_technical(db, pos)


@router.get("/health", response_model=PortfolioHealthResponse)
def portfolio_health(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_health(db, _portfolio(db, user))


@router.get("/strategy-profile", response_model=PortfolioStrategyProfileResponse)
def strategy_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"profile": get_or_create_strategy_profile(db, user.id), **profile_catalog()}


@router.put("/strategy-profile", response_model=PortfolioStrategyProfileResponse)
def strategy_profile_update(
    payload: PortfolioStrategyProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        profile = update_strategy_profile(db, user.id, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"profile": profile, **profile_catalog()}


@router.post("/strategy-profile/reset", response_model=PortfolioStrategyProfileResponse)
def strategy_profile_reset(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"profile": reset_strategy_profile(db, user.id), **profile_catalog()}


@router.get("/interpretation", response_model=PortfolioInterpretationResponse)
def portfolio_interpretation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    portfolio = _portfolio(db, user)
    health = build_health(db, portfolio)
    profile = get_or_create_strategy_profile(db, user.id)
    return build_personalized_interpretation(health, profile)


@router.get("/transactions")
def transactions_list(
    symbol: str | None = None,
    event_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    account: str | None = None,
    currency: str | None = None,
    include_superseded: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return transaction_events(
        db, _portfolio(db, user), symbol=symbol, event_type=event_type,
        start=start_date, end=end_date, account=account, currency=currency,
        include_superseded=include_superseded,
    )


@router.get("/completed-trades")
def portfolio_completed_trades(
    symbol: str | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return completed_trades(db, _portfolio(db, user), symbol=symbol)


@router.get("/open-lots")
def portfolio_open_lots(
    symbol: str | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return open_lots(db, _portfolio(db, user), symbol=symbol)


@router.post("/positions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def manual_position(
    payload: ManualPositionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Holdings-page manual entry → creates a transaction, then rebuilds the position."""
    try:
        security = resolve_security(
            db,
            security_id=payload.security_id,
            source=payload.source,
            yahoo_symbol=payload.yahoo_symbol or (payload.symbol if payload.source != "finnhub" else None),
            finnhub_symbol=payload.finnhub_symbol,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    symbol = security.yahoo_symbol or security.finnhub_symbol
    if not symbol:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "该证券暂无可用行情数据源")
    try:
        txn = create_manual_position(
            db,
            _portfolio(db, user),
            payload.model_copy(update={"security_id": security.id, "symbol": symbol}),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    from app.tasks.celery_app import sync_technical_analysis

    sync_technical_analysis.delay(symbol)
    return txn


@router.post("/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def transaction_create(
    payload: TransactionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_transaction(db, _portfolio(db, user), payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.patch("/transactions/{txn_id}", response_model=TransactionOut)
def transaction_update(
    txn_id: int,
    payload: TransactionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    portfolio = _portfolio(db, user)
    txn = get_transaction(db, portfolio, txn_id)
    if txn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该交易记录")
    try:
        return update_transaction(db, portfolio, txn, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/transactions/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
def transaction_delete(
    txn_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    portfolio = _portfolio(db, user)
    txn = get_transaction(db, portfolio, txn_id)
    if txn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该交易记录")
    try:
        delete_transaction(db, portfolio, txn)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/rebuild")
def portfolio_rebuild(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recompute every derived position from transaction history (maintenance/repair)."""
    portfolio = _portfolio(db, user)
    positions = rebuild_all_positions(db, portfolio.id)
    db.commit()
    return {"rebuilt": len(positions)}
