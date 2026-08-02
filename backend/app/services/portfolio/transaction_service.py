"""Transaction CRUD + portfolio bootstrap.

Every write here follows the Section 4 sequence: mutate the authoritative
`TradeTransaction` row, then rebuild the affected symbol's derived position/lots.
The manual holdings entry (Section 5) is just a `buy` transaction created through
the same path — the derived position is never written directly.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Portfolio, Security, TradeTransaction

from .position_builder import rebuild_symbol_position
from .schemas import ManualPositionIn, TransactionIn
from .investment_ledger import assert_manual_write_allowed


def get_or_create_default_portfolio(db: Session, user_id: int) -> Portfolio:
    """Each user gets one auto-provisioned default portfolio; schema allows more."""
    portfolio = db.scalar(
        select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id).limit(1)
    )
    if portfolio is None:
        portfolio = Portfolio(user_id=user_id, slug="default", name="我的持仓")
        db.add(portfolio)
        db.flush()
    return portfolio


def _resolve_security_id(db: Session, symbol: str, security_id: int | None) -> int | None:
    """Cheap local link to an existing Security — never a network validation.

    Enrichment only; a trade write must succeed even when the symbol was never
    onboarded through the securities resolver.
    """
    if security_id:
        return security_id
    value = symbol.strip().upper()
    security = db.scalar(
        select(Security).where(
            func.upper(Security.yahoo_symbol) == value
        )
    )
    if security is None:
        security = db.scalar(
            select(Security).where(func.upper(Security.display_symbol) == value)
        )
    return security.id if security else None


def create_transaction(db: Session, portfolio: Portfolio, payload: TransactionIn) -> TradeTransaction:
    assert_manual_write_allowed(db, portfolio, payload.symbol)
    security_id = _resolve_security_id(db, payload.symbol, payload.security_id)
    txn = TradeTransaction(
        portfolio_id=portfolio.id,
        security_id=security_id,
        symbol=payload.symbol,
        transaction_type=payload.transaction_type,
        quantity=payload.quantity,
        price=payload.price,
        fees=payload.fees,
        currency=payload.currency,
        trade_date=payload.trade_date,
        account=payload.account,
        note=payload.note,
        source="manual",
        source_type="manual",
        authority_source="manual",
        authority_status="active",
    )
    db.add(txn)
    db.flush()
    rebuild_symbol_position(db, portfolio.id, payload.symbol)
    db.commit()
    db.refresh(txn)
    return txn


def create_manual_position(db: Session, portfolio: Portfolio, payload: ManualPositionIn) -> TradeTransaction:
    """Holdings-page manual entry → a transaction (default buy), then rebuild."""
    txn_in = TransactionIn(
        portfolio_id=portfolio.id,
        symbol=payload.symbol,
        security_id=payload.security_id,
        transaction_type=payload.transaction_type,
        quantity=payload.quantity,
        price=payload.price,
        fees=payload.fees,
        currency=payload.currency,
        trade_date=payload.trade_date,
        account=payload.account,
        note=payload.note,
    )
    return create_transaction(db, portfolio, txn_in)


def update_transaction(
    db: Session, portfolio: Portfolio, txn: TradeTransaction, payload: TransactionIn
) -> TradeTransaction:
    if txn.authority_status != "active" or txn.authority_source == "ibkr_flex":
        raise ValueError("该交易来自 IBKR 或已被 IBKR 账本替代，券商事实不可在项目内修改。")
    assert_manual_write_allowed(db, portfolio, payload.symbol)
    old_symbol = txn.symbol
    txn.security_id = _resolve_security_id(db, payload.symbol, payload.security_id)
    txn.symbol = payload.symbol
    txn.transaction_type = payload.transaction_type
    txn.quantity = payload.quantity
    txn.price = payload.price
    txn.fees = payload.fees
    txn.currency = payload.currency
    txn.trade_date = payload.trade_date
    txn.account = payload.account
    txn.note = payload.note
    db.flush()
    # a symbol edit leaves two positions to reconcile
    if old_symbol != payload.symbol:
        rebuild_symbol_position(db, portfolio.id, old_symbol)
    rebuild_symbol_position(db, portfolio.id, payload.symbol)
    db.commit()
    db.refresh(txn)
    return txn


def delete_transaction(db: Session, portfolio: Portfolio, txn: TradeTransaction) -> None:
    if txn.authority_status != "active" or txn.authority_source == "ibkr_flex":
        raise ValueError("该交易来自 IBKR 或已被 IBKR 账本替代，券商事实不可在项目内删除。")
    symbol = txn.symbol
    db.delete(txn)
    db.flush()
    rebuild_symbol_position(db, portfolio.id, symbol)
    db.commit()


def list_transactions(db: Session, portfolio: Portfolio, symbol: str | None = None) -> list[TradeTransaction]:
    stmt = select(TradeTransaction).where(
        TradeTransaction.portfolio_id == portfolio.id,
        TradeTransaction.authority_status == "active",
    )
    if symbol:
        stmt = stmt.where(TradeTransaction.symbol == symbol.upper())
    stmt = stmt.order_by(TradeTransaction.trade_date.desc(), TradeTransaction.id.desc())
    return list(db.scalars(stmt).all())


def get_transaction(db: Session, portfolio: Portfolio, txn_id: int) -> TradeTransaction | None:
    return db.scalar(
        select(TradeTransaction).where(
            TradeTransaction.id == txn_id,
            TradeTransaction.portfolio_id == portfolio.id,
        )
    )
