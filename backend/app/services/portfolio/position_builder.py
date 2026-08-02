"""Persist derived positions/lots from the authoritative transaction history.

The invariant (Section 4): the aggregated `PortfolioPosition` and the
`PortfolioPositionLot` rows are a *cache*, never a primary write. Every mutation
path funnels through `rebuild_symbol_position`, which deletes and recomputes the
affected symbol's derived rows from its `TradeTransaction` history.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    PortfolioPosition,
    PortfolioPositionLot,
    TradeTransaction,
)

from .lot_matcher import rebuild_symbol


def rebuild_symbol_position(db: Session, portfolio_id: int, symbol: str) -> PortfolioPosition | None:
    """Recompute one symbol's derived position + lots from its transactions.

    Returns the persisted position, or None when the net position is flat/empty
    (in which case any stale derived rows are removed). Does not commit — the
    caller owns the transaction boundary.
    """
    value = symbol.upper()
    txns = list(
        db.scalars(
            select(TradeTransaction).where(
                TradeTransaction.portfolio_id == portfolio_id,
                TradeTransaction.symbol == value,
                TradeTransaction.authority_status == "active",
            )
        ).all()
    )
    result = rebuild_symbol(txns)

    # wipe derived lots for this symbol; they are always recomputed
    db.execute(
        delete(PortfolioPositionLot).where(
            PortfolioPositionLot.portfolio_id == portfolio_id,
            PortfolioPositionLot.symbol == value,
        )
    )

    existing = db.scalar(
        select(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio_id,
            PortfolioPosition.symbol == value,
        )
    )

    security_id = next((t.security_id for t in txns if t.security_id), None)

    # Closed positions remain represented by their transactions, not by an empty
    # derived holding row.
    if result.total_quantity <= 0 and not (existing is not None and existing.authority_source == "ibkr_flex"):
        if existing is not None:
            db.delete(existing)
        return None

    if existing is None:
        existing = PortfolioPosition(portfolio_id=portfolio_id, symbol=value)
        db.add(existing)

    existing.security_id = security_id
    if existing.authority_source != "ibkr_flex":
        existing.total_quantity = result.total_quantity
        existing.average_cost = result.average_cost
        existing.total_cost = result.total_cost
        existing.currency = result.currency
    existing.last_transaction_at = result.last_transaction_at

    for lot in result.lots:
        db.add(
            PortfolioPositionLot(
                portfolio_id=portfolio_id,
                symbol=value,
                source_transaction_id=lot.source_transaction_id,
                original_quantity=lot.original_quantity,
                remaining_quantity=lot.remaining_quantity,
                purchase_price=lot.purchase_price,
                purchase_date=lot.purchase_date,
                allocated_fees=lot.allocated_fees,
                currency=lot.currency,
                status=lot.status,
            )
        )
    db.flush()
    return existing


def rebuild_all_positions(db: Session, portfolio_id: int) -> list[PortfolioPosition]:
    """Rebuild every symbol that appears in the portfolio's transaction history."""
    symbols = list(
        db.scalars(
            select(TradeTransaction.symbol)
            .where(
                TradeTransaction.portfolio_id == portfolio_id,
                TradeTransaction.authority_status == "active",
            )
            .distinct()
        ).all()
    )
    out: list[PortfolioPosition] = []
    for symbol in symbols:
        position = rebuild_symbol_position(db, portfolio_id, symbol)
        if position is not None:
            out.append(position)
    return out
