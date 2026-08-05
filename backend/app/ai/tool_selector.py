from __future__ import annotations

from dataclasses import dataclass, field

from app.ai_tools.registry import ToolRegistry
from app.config import get_settings
from app.external_search.enums import WebAccessMode


@dataclass
class ToolSelection:
    tool_names: list[str]
    reasons: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


DOMAIN_RULES = {
    "portfolio": ("持仓", "仓位", "成本", "盈亏", "组合", "portfolio", "position", "holding"),
    "news": ("新闻", "舆情", "消息", "风险", "news", "headline", "event"),
    "sec": ("sec", "10-q", "10-k", "8-k", "披露", "内部人", "filing", "insider"),
    "valuation": ("估值", "合理价", "贵不贵", "dcf", "valuation", "fair value"),
    "technical": ("技术面", "支撑", "压力", "均线", "rsi", "macd", "technical", "support", "resistance"),
    "financials": ("财务", "营收", "利润", "现金流", "负债", "financial", "revenue", "earnings", "cash flow"),
    "calendar": ("财报日", "分红", "拆股", "日历", "calendar", "dividend", "split"),
    "ownership": ("国会", "议员", "名人持仓", "13f", "ownership", "congress", "institutional"),
    "discovery": ("机会发现", "候选股", "资金流", "discovery", "candidate", "flow"),
    "market": ("价格", "股价", "涨跌", "price", "market"),
    "company": ("公司", "业务", "概况", "company", "profile"),
    "memory": (
        "记忆",
        "记住",
        "忘记",
        "投资决策",
        "投资逻辑",
        "复盘",
        "memory",
        "decision",
        "review",
    ),
}

PREFERRED = {
    # Historical analysis runs are intentionally excluded here. They can
    # contain an older position snapshot and must not be treated as current
    # holdings merely because the user mentioned their portfolio.
    "portfolio": ["get_portfolio_summary", "get_portfolio_positions", "get_position_detail"],
    "news": ["get_latest_news", "search_news", "get_news_detail"],
    "sec": ["get_sec_filings", "get_sec_events", "get_sec_financial_facts", "get_insider_trades"],
    "valuation": ["get_latest_valuation", "get_valuation_history", "compare_valuations"],
    "technical": ["get_technical_analysis", "get_technical_levels", "compare_technical_signals"],
    "financials": ["get_financial_summary", "get_financial_trends", "get_financial_statements"],
    "calendar": ["get_calendar_events", "get_calendar_event_detail"],
    "ownership": ["get_company_ownership_activity", "get_congress_trades", "get_institutional_holdings", "get_tracked_figures"],
    "discovery": ["get_discovery_runs", "get_discovery_run", "get_discovery_candidates"],
    "market": ["get_latest_price", "get_price_history", "get_market_context"],
    "company": ["get_company_snapshot", "get_company_profile", "get_company_peers"],
    "memory": [
        "get_relevant_user_memories",
        "list_user_memories",
        "list_investment_decisions",
        "get_decisions_for_symbol",
    ],
}


PERSONAL_POSITION_TERMS = (
    "我的股票", "我的个股", "我的证券", "我的标的", "我持有", "我买的",
    "我买了", "我现在的", "我每只", "我每个", "我账户里的",
)
POSITION_SUBJECT_TERMS = ("股票", "个股", "证券", "标的")
POSITION_METRIC_TERMS = (
    "盈利", "收益", "盈亏", "亏损", "赚钱", "回报", "涨跌", "表现", "百分比",
)


def has_current_portfolio_intent(message: str) -> bool:
    """Recognize current-user holding questions without relying on one keyword.

    Chinese users often say "我现在的每一个股票" instead of the more formal
    "我的持仓". Requiring a personal-ownership phrase plus a security subject
    and a position metric keeps company-profit questions out of private tools.
    """
    text = message.casefold()
    if any(term in text for term in DOMAIN_RULES["portfolio"]):
        return True
    return (
        any(term in text for term in PERSONAL_POSITION_TERMS)
        and any(term in text for term in POSITION_SUBJECT_TERMS)
        and any(term in text for term in POSITION_METRIC_TERMS)
    )


class ToolSelector:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def select(self, *, message: str, page_context: str | None, active_symbol: str | None, allowed_tools: set[str] | None, denied_tools: set[str], web_access_mode: WebAccessMode = WebAccessMode.off) -> ToolSelection:
        known = {item.name for item in self.registry.list()}
        unknown = ((allowed_tools or set()) | denied_tools) - known
        if unknown:
            raise ValueError(f"unknown tool names: {', '.join(sorted(unknown))}")
        eligible = known if allowed_tools is None else known & allowed_tools
        eligible -= denied_tools
        selected: list[str] = []
        reasons: dict[str, str] = {}

        def add(name: str, reason: str) -> None:
            if name in eligible and name not in selected:
                selected.append(name); reasons[name] = reason

        text = message.casefold()
        domains = [domain for domain, words in DOMAIN_RULES.items() if any(word in text for word in words)]
        if has_current_portfolio_intent(message) and "portfolio" not in domains:
            domains.insert(0, "portfolio")
        if page_context in PREFERRED and page_context not in domains:
            domains.append(page_context)
        if not domains:
            domains = ["company", "market"]
        for domain in domains:
            for name in PREFERRED[domain]:
                add(name, f"matched {domain} intent")
        for name in ("get_company_snapshot", "get_company_profile", "get_latest_price"):
            add(name, "baseline company context")
        external = {
            "search_web", "search_latest_news_web", "search_official_company_sources",
            "search_financial_reports_web", "search_publications_web", "run_deep_web_research",
        }
        if web_access_mode == WebAccessMode.search:
            if any(word in text for word in ("新闻", "最新", "今天", "刚刚", "实时", "突发", "news", "latest", "breaking")):
                add("search_latest_news_web", "normal web mode with current-news intent")
            if any(word in text for word in ("官网", "公告", "投资者关系", "official", "announcement", "investor relations")):
                add("search_official_company_sources", "normal web mode with official-source intent")
            if any(word in text for word in ("财报", "年报", "季报", "filing", "financial report", "earnings report")):
                add("search_financial_reports_web", "normal web mode with financial-report intent")
            if any(word in text for word in ("论文", "研究论文", "paper", "publication", "research study")):
                add("search_publications_web", "normal web mode with publication intent")
            if not any(name in selected for name in external):
                add("search_web", "normal web mode")
            # Keep the external surface small and predictable per request.
            web_selected = [name for name in selected if name in external][:3]
            selected = [name for name in selected if name not in external] + web_selected
        elif web_access_mode.is_deep:
            add("run_deep_web_research", f"user-selected {web_access_mode.value} mode")
            selected = [name for name in selected if name not in external or name == "run_deep_web_research"]
        else:
            selected = [name for name in selected if name not in external]
        reasons = {name: reasons[name] for name in selected}
        settings = get_settings()
        soft = min(max(settings.ai_tool_selection_max_tools, 1), 30)
        hard = min(max(settings.ai_tool_selection_hard_max_tools, 1), 30)
        limit = min(soft, hard)
        warnings = []
        if len(selected) > limit:
            selected = selected[:limit]
            reasons = {name: reasons[name] for name in selected}
            warnings.append("Tool selection was truncated to the configured limit.")
        return ToolSelection(selected, reasons, warnings)
