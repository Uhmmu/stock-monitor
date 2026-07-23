"""Portfolio holdings domain.

Single source of truth: TradeTransaction rows. Positions and lots are derived
state, always rebuildable from transactions. Services here never mutate the
aggregated position table as a primary operation — they rebuild it from history.
"""
from app.services.portfolio.performance import (
    build_position_detail,
    build_summary,
)
from app.services.portfolio.portfolio_health import build_health
from app.services.portfolio.position_builder import (
    rebuild_all_positions,
    rebuild_symbol_position,
)
from app.services.portfolio.position_technical import build_position_technical
from app.services.portfolio.schemas import (
    ManualPositionIn,
    TransactionIn,
    TransactionOut,
)
from app.services.portfolio.transaction_service import (
    create_manual_position,
    create_transaction,
    delete_transaction,
    get_or_create_default_portfolio,
    get_transaction,
    list_transactions,
    update_transaction,
)

__all__ = [
    "ManualPositionIn",
    "TransactionIn",
    "TransactionOut",
    "build_health",
    "build_position_detail",
    "build_position_technical",
    "build_summary",
    "create_manual_position",
    "create_transaction",
    "delete_transaction",
    "get_or_create_default_portfolio",
    "get_transaction",
    "list_transactions",
    "rebuild_all_positions",
    "rebuild_symbol_position",
    "update_transaction",
]
