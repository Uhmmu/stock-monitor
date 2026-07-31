"""Synchronize executed trading-journal rows into authoritative portfolio trades.

The journal is user-facing context, while ``TradeTransaction`` is the source of
truth for derived holdings.  Journal-created transactions use a stable source
key so edits and deletes can be reconciled idempotently without duplicating a
trade.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import Portfolio, Security, TradeLog, TradeTransaction
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .position_builder import rebuild_symbol_position


_DIRECTION_TYPES = {
    "买入": "buy",
    "卖出": "sell",
    "buy": "buy",
    "sell": "sell",
}


@dataclass(frozen=True)
class _JournalTrade:
    row_index: int
    security_id: int | None
    symbol: str
    transaction_type: str
    quantity: float
    price: float
    fees: float
    currency: str
    note: str | None


def _security_for_row(db: Session, item: dict) -> Security | None:
    security_id = item.get("security_id")
    if security_id:
        security = db.get(Security, security_id)
        if security is not None:
            return security
    ticker = str(item.get("ticker") or "").strip().upper()
    if not ticker:
        return None
    return db.scalar(
        select(Security)
        .where(
            (func.upper(Security.yahoo_symbol) == ticker)
            | (func.upper(Security.display_symbol) == ticker)
            | (func.upper(Security.finnhub_symbol) == ticker)
        )
        .limit(1)
    )


def _as_trade(
    db: Session,
    portfolio: Portfolio,
    log: TradeLog,
    item: dict,
    row_index: int,
) -> _JournalTrade | None:
    direction = str(item.get("direction") or "").strip()
    transaction_type = _DIRECTION_TYPES.get(direction) or _DIRECTION_TYPES.get(
        direction.lower()
    )
    if transaction_type is None:
        return None
    ticker = str(item.get("ticker") or "").strip().upper()
    try:
        quantity = float(item.get("quantity"))
        price = float(item.get("price"))
        fees = float(item.get("fee") or 0.0)
    except (TypeError, ValueError):
        return None
    if not ticker or quantity <= 0 or price <= 0 or fees < 0:
        return None

    security = _security_for_row(db, item)
    symbol = (
        (security.yahoo_symbol or security.finnhub_symbol)
        if security is not None
        else ticker
    )
    currency = (
        (security.currency if security is not None else None)
        or portfolio.base_currency
        or "USD"
    ).upper()
    context = " · ".join(
        value
        for value in (
            str(item.get("strategy") or "").strip(),
            str(item.get("result") or "").strip(),
        )
        if value
    )
    note_parts = [value for value in (log.note, context) if value]
    return _JournalTrade(
        row_index=row_index,
        security_id=security.id if security is not None else None,
        symbol=symbol.upper(),
        transaction_type=transaction_type,
        quantity=quantity,
        price=price,
        fees=fees,
        currency=currency,
        note=" · ".join(note_parts) or None,
    )


def _expected_trades(
    db: Session, portfolio: Portfolio, log: TradeLog
) -> list[_JournalTrade]:
    rows = list(log.table_rows or [])
    if not rows and log.ticker:
        rows = [
            {
                "ticker": log.ticker,
                "direction": log.direction,
                "quantity": log.quantity,
                "price": log.price,
                "fee": 0.0,
            }
        ]
        keys = [-1]
    else:
        keys = list(range(len(rows)))
    return [
        trade
        for item, key in zip(rows, keys)
        if (trade := _as_trade(db, portfolio, log, item, key))
    ]


def sync_trade_log_transactions(
    db: Session, portfolio: Portfolio, log: TradeLog
) -> bool:
    """Upsert one log's executed rows and rebuild every affected holding."""
    if log.id is None:
        db.flush()
    expected = {
        trade.row_index: trade for trade in _expected_trades(db, portfolio, log)
    }
    existing_rows = list(
        db.scalars(
            select(TradeTransaction).where(
                TradeTransaction.portfolio_id == portfolio.id,
                TradeTransaction.source_log_id == log.id,
            )
        ).all()
    )
    existing = {txn.source_log_row_index: txn for txn in existing_rows}
    affected_symbols: set[str] = set()
    changed = False

    for row_index, trade in expected.items():
        txn = existing.pop(row_index, None)
        if txn is None:
            txn = TradeTransaction(
                portfolio_id=portfolio.id,
                source="journal",
                source_log_id=log.id,
                source_log_row_index=row_index,
            )
            db.add(txn)
            changed = True
        old_symbol = txn.symbol
        values = {
            "security_id": trade.security_id,
            "symbol": trade.symbol,
            "transaction_type": trade.transaction_type,
            "quantity": trade.quantity,
            "price": trade.price,
            "fees": trade.fees,
            "currency": trade.currency,
            "trade_date": log.trade_date,
            "account": None,
            "note": trade.note,
        }
        if any(getattr(txn, key, None) != value for key, value in values.items()):
            if old_symbol:
                affected_symbols.add(old_symbol)
            for key, value in values.items():
                setattr(txn, key, value)
            changed = True
        affected_symbols.add(trade.symbol)

    for txn in existing.values():
        affected_symbols.add(txn.symbol)
        db.delete(txn)
        changed = True

    if not changed:
        return False
    db.flush()
    for symbol in affected_symbols:
        rebuild_symbol_position(db, portfolio.id, symbol)
    return True


def delete_trade_log_transactions(
    db: Session, portfolio: Portfolio, log: TradeLog
) -> bool:
    """Remove all portfolio trades owned by a log before the log is deleted."""
    txns = list(
        db.scalars(
            select(TradeTransaction).where(
                TradeTransaction.portfolio_id == portfolio.id,
                TradeTransaction.source_log_id == log.id,
            )
        ).all()
    )
    if not txns:
        return False
    symbols = {txn.symbol for txn in txns}
    for txn in txns:
        db.delete(txn)
    db.flush()
    for symbol in symbols:
        rebuild_symbol_position(db, portfolio.id, symbol)
    return True


def reconcile_user_trade_logs(db: Session, portfolio: Portfolio) -> bool:
    """Backfill or repair journal trades created before synchronization existed."""
    logs = list(
        db.scalars(
            select(TradeLog)
            .where(TradeLog.user_id == portfolio.user_id)
            .order_by(TradeLog.id)
        ).all()
    )
    changed = False
    for log in logs:
        changed = sync_trade_log_transactions(db, portfolio, log) or changed
    return changed
