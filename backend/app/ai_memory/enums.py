from enum import StrEnum


class MemoryStatus(StrEnum):
    proposed = "proposed"
    active = "active"
    rejected = "rejected"
    stale = "stale"
    expired = "expired"
    archived = "archived"
    deleted = "deleted"


class MemoryType(StrEnum):
    investment_style = "investment_style"
    risk_policy = "risk_policy"
    portfolio_constraint = "portfolio_constraint"
    valuation_preference = "valuation_preference"
    market_preference = "market_preference"
    research_preference = "research_preference"
    communication_preference = "communication_preference"
    long_term_goal = "long_term_goal"
    project_context = "project_context"
    watchlist_interest = "watchlist_interest"
    recurring_workflow = "recurring_workflow"
    general_preference = "general_preference"


class MemoryScope(StrEnum):
    global_ = "global"
    portfolio = "portfolio"
    symbol = "symbol"
    project = "project"
    page_context = "page_context"


class DecisionStatus(StrEnum):
    draft = "draft"
    active = "active"
    executed = "executed"
    partially_executed = "partially_executed"
    cancelled = "cancelled"
    invalidated = "invalidated"
    closed = "closed"
    archived = "archived"

