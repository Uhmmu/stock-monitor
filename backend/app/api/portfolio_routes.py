"""Holdings (持仓) API.

All endpoints are user-scoped through the user's default portfolio. Writes go
through the transaction service so the aggregated position is always rebuilt from
the authoritative transaction history — the manual-entry endpoint creates a
transaction, never a position row directly (Section 4/5).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import PortfolioPosition, User
from app.services.portfolio import (
    ManualPositionIn,
    TransactionIn,
    TransactionOut,
    build_health,
    build_position_detail,
    build_position_technical,
    build_summary,
    create_manual_position,
    create_transaction,
    delete_transaction,
    get_or_create_default_portfolio,
    get_transaction,
    list_transactions,
    rebuild_all_positions,
    update_transaction,
)

router = APIRouter(prefix="/api/portfolio", dependencies=[Depends(get_current_user)])


def _portfolio(db: Session, user: User):
    return get_or_create_default_portfolio(db, user.id)


@router.get("/summary")
def portfolio_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_summary(db, _portfolio(db, user))


@router.get("/positions")
def portfolio_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_summary(db, _portfolio(db, user))["positions"]


@router.get("/positions/{symbol}")
def position_detail(symbol: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    detail = build_position_detail(db, _portfolio(db, user), symbol)
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


@router.get("/health")
def portfolio_health(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_health(db, _portfolio(db, user))


@router.get("/transactions", response_model=list[TransactionOut])
def transactions_list(
    symbol: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_transactions(db, _portfolio(db, user), symbol)


@router.post("/positions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def manual_position(
    payload: ManualPositionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Holdings-page manual entry → creates a transaction, then rebuilds the position."""
    return create_manual_position(db, _portfolio(db, user), payload)


@router.post("/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def transaction_create(
    payload: TransactionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_transaction(db, _portfolio(db, user), payload)


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
    return update_transaction(db, portfolio, txn, payload)


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
    delete_transaction(db, portfolio, txn)


@router.post("/rebuild")
def portfolio_rebuild(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recompute every derived position from transaction history (maintenance/repair)."""
    portfolio = _portfolio(db, user)
    positions = rebuild_all_positions(db, portfolio.id)
    db.commit()
    return {"rebuilt": len(positions)}
