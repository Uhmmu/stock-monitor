"""Named capability scopes for registry tools.

Chat AI selects tools per request through the orchestrator; service-side
agents (currently the Pi discovery sidecar) authenticate through the agent
gateway and are handed a *named scope* resolved here, so every caller shares
one ``ToolRegistry`` / ``ToolExecutor`` and capability filtering stays
declarative instead of being duplicated per surface or embedded in prompts.

Add a new scope by registering another entry in ``TOOL_SCOPES``; tool names
must exist in the registry (validated lazily by ``export_openai_tools``).
"""

from __future__ import annotations

# Scope for the Opportunity Discovery research agent: stored project data
# first, Exa retrieval second. Memory/AI-chat-only tools, realtime quotes and
# discovery introspection are intentionally excluded.
OPPORTUNITY_RESEARCH_TOOLS: frozenset[str] = frozenset({
    "list_research_capabilities",
    # portfolio
    "get_portfolio_summary", "get_portfolio_overview", "get_portfolio_positions",
    "get_position_detail", "get_portfolio_risk_analysis", "get_portfolio_performance",
    "get_portfolio_equity_curve", "get_portfolio_drawdown",
    "get_portfolio_return_attribution", "get_position_performance",
    "get_position_transaction_timeline", "get_position_open_lots",
    "get_completed_trades", "get_trade_statistics", "get_dividend_history",
    "get_fee_and_tax_summary", "get_cash_flow_summary", "get_currency_exposure",
    # company / market
    "get_company_profile", "get_company_snapshot", "get_company_peers",
    "get_latest_price", "get_price_history", "compare_price_performance",
    "get_market_context",
    # news
    "get_latest_news", "search_news", "get_news_detail", "get_news_archives",
    # sec / ownership
    "get_sec_filings", "get_sec_filing_detail", "get_sec_events",
    "get_sec_financial_facts", "get_insider_trades", "get_institutional_holdings",
    "get_company_ownership_activity",
    # financials / valuation / technical / calendar
    "get_financial_summary", "get_financial_statements",
    "compare_financial_metrics", "get_financial_trends",
    "get_latest_valuation", "get_valuation_history", "compare_valuations",
    "get_technical_analysis", "get_technical_levels",
    "compare_technical_signals", "get_technical_chart_reference",
    "get_calendar_events", "get_calendar_event_detail",
    # external retrieval (Exa) — still budgeted/privacy-filtered by the executor
    "search_web", "search_latest_news_web", "search_official_company_sources",
    "search_financial_reports_web", "search_publications_web",
    "run_deep_web_research",
    # options / mood
    "get_options_overview", "get_symbol_options_summary",
    "get_mood_overview", "get_mood_history", "get_mood_validation",
})


TOOL_SCOPES: dict[str, frozenset[str]] = {
    "opportunity_research": OPPORTUNITY_RESEARCH_TOOLS,
}

DEFAULT_AGENT_TOOL_SCOPE = "opportunity_research"


class UnknownToolScope(KeyError):
    """Raised when a caller asks for a scope that is not registered."""


def resolve_tool_scope(name: str | None) -> frozenset[str]:
    """Return the tool set for a scope name (default: opportunity_research)."""
    key = (name or "").strip() or DEFAULT_AGENT_TOOL_SCOPE
    try:
        return TOOL_SCOPES[key]
    except KeyError:
        raise UnknownToolScope(key) from None
