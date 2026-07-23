"""Rebuild position lots and aggregate figures from transaction history.

Average-cost accounting for open positions. The lot model is kept intentionally
granular (one open lot per buy, drawn down FIFO on sells) so partial exits retain
correct remaining quantities without exposing a realized-PnL feature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class LotState:
    """A still-open (or partially-open) purchase lot, derived from a buy transaction."""

    source_transaction_id: int | None
    original_quantity: float
    remaining_quantity: float
    purchase_price: float
    purchase_date: date | None
    allocated_fees: float
    currency: str
    status: str = "open"


@dataclass
class RebuildResult:
    """The derived state for one symbol, computed purely from its transactions."""

    total_quantity: float = 0.0
    average_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"
    last_transaction_at: date | None = None
    lots: list[LotState] = field(default_factory=list)


def _txn_sort_key(txn) -> tuple:
    # chronological, then by insertion id so same-day ordering is stable
    return (txn.trade_date, txn.id or 0)


def rebuild_symbol(transactions: list) -> RebuildResult:
    """Fold a symbol's full transaction history into aggregate figures + open lots.

    Uses average-cost: sells reduce quantity while the lot list is drawn down FIFO
    so the schema carries real per-lot remainders.
    """
    result = RebuildResult()
    if not transactions:
        return result

    open_lots: list[LotState] = []
    avg_cost = 0.0
    qty = 0.0
    currency = transactions[0].currency or "USD"
    last_at: date | None = None

    for txn in sorted(transactions, key=_txn_sort_key):
        kind = (txn.transaction_type or "buy").lower()
        currency = txn.currency or currency
        last_at = txn.trade_date if last_at is None else max(last_at, txn.trade_date)

        if kind in ("buy", "transfer_in"):
            new_qty = qty + txn.quantity
            # blend fees into cost basis so average_cost reflects true landed cost
            added_cost = txn.quantity * txn.price + (txn.fees or 0.0)
            if new_qty > 0:
                avg_cost = (avg_cost * qty + added_cost) / new_qty
            qty = new_qty
            open_lots.append(
                LotState(
                    source_transaction_id=txn.id,
                    original_quantity=txn.quantity,
                    remaining_quantity=txn.quantity,
                    purchase_price=txn.price,
                    purchase_date=txn.trade_date,
                    allocated_fees=txn.fees or 0.0,
                    currency=txn.currency or currency,
                )
            )
        elif kind in ("sell", "transfer_out"):
            sell_qty = min(txn.quantity, qty) if qty > 0 else 0.0
            qty -= sell_qty
            _drawdown_lots(open_lots, sell_qty)
            if qty <= 1e-9:
                qty = 0.0
                avg_cost = 0.0
        elif kind == "split":
            ratio = txn.quantity or 0.0
            if ratio > 0 and qty > 0:
                qty *= ratio
                avg_cost /= ratio
                for lot in open_lots:
                    lot.remaining_quantity *= ratio
                    lot.original_quantity *= ratio
                    lot.purchase_price /= ratio
        # deposit/withdrawal touch cash only — not modelled at symbol level here

    result.total_quantity = round(qty, 8)
    result.average_cost = round(avg_cost, 8) if qty > 0 else 0.0
    result.total_cost = round(qty * avg_cost, 8) if qty > 0 else 0.0
    result.currency = currency
    result.last_transaction_at = last_at
    result.lots = [lot for lot in open_lots if lot.remaining_quantity > 1e-9]
    for lot in result.lots:
        lot.status = "open" if abs(lot.remaining_quantity - lot.original_quantity) < 1e-9 else "partial"
    return result


def _drawdown_lots(lots: list[LotState], quantity: float) -> None:
    """Reduce open lots FIFO by `quantity`. Mutates lots in place."""
    remaining = quantity
    for lot in lots:
        if remaining <= 1e-9:
            break
        take = min(lot.remaining_quantity, remaining)
        lot.remaining_quantity -= take
        remaining -= take
