"""Portfolio holdings domain.

Single source of truth: TradeTransaction rows. Positions and lots are derived
state, always rebuildable from transactions. Services here never mutate the
aggregated position table as a primary operation — they rebuild it from history.
"""
from app.services.portfolio.performance import (
    build_position_detail,
    build_summary,
)
from app.services.portfolio.investment_ledger import (
    completed_trades,
    govern_manual_transactions,
    overview as build_ledger_overview,
    performance_series,
    open_lots,
    position_detail as build_ledger_position_detail,
    return_attribution,
    transaction_events,
)
from app.services.portfolio.benchmark import build_benchmark_comparison
from app.services.portfolio.portfolio_health import build_health
from app.services.portfolio.personalized_interpretation import build_personalized_interpretation
from app.services.portfolio.position_builder import (
    rebuild_all_positions,
    rebuild_symbol_position,
)
from app.services.portfolio.position_technical import build_position_technical
from app.services.portfolio.schemas import (
    ManualPositionIn,
    PortfolioBenchmarkResponse,
    PortfolioBenchmarkUpdate,
    PortfolioAttributionResponse,
    PortfolioHealthResponse,
    PortfolioInterpretationResponse,
    PortfolioStrategyProfileResponse,
    PortfolioStrategyProfileUpdate,
    PortfolioPerformanceResponse,
    TransactionIn,
    TransactionOut,
)
from app.services.portfolio.strategy_profile import (
    get_or_create_strategy_profile,
    profile_catalog,
    reset_strategy_profile,
    update_strategy_profile,
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
    "PortfolioBenchmarkResponse",
    "PortfolioBenchmarkUpdate",
    "PortfolioAttributionResponse",
    "PortfolioHealthResponse",
    "PortfolioInterpretationResponse",
    "PortfolioStrategyProfileResponse",
    "PortfolioStrategyProfileUpdate",
    "PortfolioPerformanceResponse",
    "TransactionIn",
    "TransactionOut",
    "build_health",
    "build_benchmark_comparison",
    "build_personalized_interpretation",
    "build_position_detail",
    "build_position_technical",
    "build_summary",
    "build_ledger_overview",
    "build_ledger_position_detail",
    "completed_trades",
    "create_manual_position",
    "create_transaction",
    "delete_transaction",
    "get_or_create_default_portfolio",
    "get_or_create_strategy_profile",
    "get_transaction",
    "govern_manual_transactions",
    "list_transactions",
    "performance_series",
    "open_lots",
    "rebuild_all_positions",
    "rebuild_symbol_position",
    "profile_catalog",
    "reset_strategy_profile",
    "return_attribution",
    "transaction_events",
    "update_transaction",
    "update_strategy_profile",
]
