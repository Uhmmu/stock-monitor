from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PROMPT_VERSION = "stock-discovery-prompt-v0.6"
SCHEMA_VERSION = "stock-discovery-schema-v0.6"
FILTER_VERSION = "stock-discovery-filter-v0.4"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarketContext(StrictModel):
    summary: str
    risk_regime: Literal["risk_on", "neutral", "risk_off", "mixed", "unknown"]
    liquidity_or_flow_summary: str
    important_market_drivers: list[str]
    data_limitations: list[str]


class OverweightExposure(StrictModel):
    name: str
    exposure_type: Literal["sector", "industry", "theme", "factor", "geography", "currency", "business_model"]
    severity: Literal["low", "medium", "high"]
    evidence: str
    suggested_action: str


class MissingExposure(StrictModel):
    name: str
    exposure_type: Literal["sector", "industry", "theme", "factor", "geography", "currency", "business_model"]
    importance: Literal["low", "medium", "high"]
    reason: str
    suggested_action: str


class PortfolioDiagnosis(StrictModel):
    overall_summary: str
    overweight_exposures: list[OverweightExposure]
    underweight_or_missing_exposures: list[MissingExposure]
    portfolio_strengths: list[str]
    portfolio_vulnerabilities: list[str]


class StrongFlow(StrictModel):
    direction: str
    strength: Literal["low", "medium", "high"]
    evidence: str
    sustainability: Literal["low", "medium", "high", "uncertain"]
    catalyst: str
    risks: list[str]
    related_tickers: list[str]


class EarlyFlow(StrictModel):
    direction: str
    current_attention: Literal["low", "medium"]
    evidence: str
    long_term_case: str
    what_could_trigger_repricing: list[str]
    risks: list[str]
    related_tickers: list[str]


class CapitalFlows(StrictModel):
    strong_current_flows: list[StrongFlow]
    weak_or_early_flows: list[EarlyFlow]


class FinancialSnapshot(StrictModel):
    price: float | None
    market_cap: float | None
    pe_trailing: float | None
    pe_forward: float | None
    price_to_sales: float | None
    ev_to_ebitda: float | None
    revenue_growth: float | None
    earnings_growth: float | None
    gross_margin: float | None
    operating_margin: float | None
    free_cash_flow: float | None
    free_cash_flow_margin: float | None
    return_on_invested_capital: float | None
    net_debt_or_cash: float | None
    analyst_consensus: str | None
    data_periods: list[str]


class CandidateSource(StrictModel):
    title: str
    url: str
    source_type: Literal["finance", "company", "filing", "news", "research", "other"]


class Candidate(StrictModel):
    ticker: str
    company_name: str
    exchange: str | None
    country: str | None
    sector: str | None
    industry: str | None
    market_cap: float | None
    currency: str | None
    discovery_reason: str
    portfolio_fit: str
    diversification_effect: Literal["positive", "neutral", "negative", "uncertain"]
    overlap_with_existing_holdings: list[str]
    business_quality_summary: str
    investment_thesis: list[str]
    capital_flow_context: str
    valuation_context: str
    why_now: str
    financial_snapshot: FinancialSnapshot
    quality_level: Literal["high", "medium", "low", "uncertain"]
    valuation_level: Literal["cheap", "reasonable", "elevated", "extreme", "uncertain"]
    momentum_state: Literal["cold", "neutral", "improving", "strong", "euphoric", "uncertain"]
    candidate_priority: Literal["high", "medium", "low"]
    confidence: float = Field(ge=0, le=1)
    major_risks: list[str]
    thesis_breakers: list[str]
    facts_to_verify_locally: list[str]
    sources: list[CandidateSource]


class CandidateGroup(StrictModel):
    group_id: str
    group_name: str
    group_type: Literal["strong_flow", "quality_core", "portfolio_complement", "contrarian", "early_theme", "defensive", "watch_only"]
    group_summary: str
    candidates: list[Candidate]


class AvoidCandidate(StrictModel):
    ticker: str
    company_name: str
    reason: str
    valuation_or_risk_issue: str
    reconsideration_condition: str


class ResearchAction(StrictModel):
    action: str
    priority: Literal["high", "medium", "low"]
    reason: str


class DiscoveryResult(StrictModel):
    analysis_date: date
    market_context: MarketContext
    portfolio_diagnosis: PortfolioDiagnosis
    capital_flow_directions: CapitalFlows
    candidate_groups: list[CandidateGroup]
    avoid_or_overheated: list[AvoidCandidate]
    portfolio_actions_for_research: list[ResearchAction]
    limitations: list[str]


class DiscoverySettingsUpdate(BaseModel):
    discovery_mode: Literal["search_local", "agent_finance"] | None = None
    max_output_tokens: int | None = Field(default=None, ge=2048, le=32000)
    monthly_budget_usd: float | None = Field(default=None, ge=0, le=1000)
    max_run_cost_usd: float | None = Field(default=None, ge=0.01, le=100)
    min_market_cap: float | None = Field(default=None, ge=0)
    exclude_current_holdings: bool | None = None
    exclude_watchlist: bool | None = None
    require_positive_fcf: bool | None = None
    max_trailing_pe: float | None = Field(default=None, ge=1, le=1000)
    max_forward_pe: float | None = Field(default=None, ge=1, le=1000)
    max_price_to_sales: float | None = Field(default=None, ge=1, le=1000)
    filter_extreme_momentum: bool | None = None
    missing_data_policy: Literal["warn", "watch_only", "reject"] | None = None


OpportunityCategory = Literal["估值错杀", "行业趋势", "盈利改善", "事件驱动", "技术反转", "长期成长"]
OpportunityAction = Literal["关注", "深入研究", "等待确认"]


class OpportunityEvidence(StrictModel):
    type: Literal["financial", "news", "market"]
    content: str = Field(min_length=1)


class OpportunityAnalysis(StrictModel):
    """The stable item persisted in opportunity_history.result_json."""

    title: str = Field(min_length=1)
    ticker: str = Field(min_length=1, max_length=32)
    category: list[OpportunityCategory] = Field(min_length=1)
    summary: str = Field(min_length=1)
    why_now: list[str] = Field(min_length=1)
    evidence: list[OpportunityEvidence] = Field(min_length=1)
    catalysts: list[str]
    risks: list[str] = Field(min_length=1)
    valuation_view: str = Field(min_length=1)
    confidence: int = Field(ge=0, le=100)
    action: list[OpportunityAction] = Field(min_length=1)


class OpportunityBatch(StrictModel):
    market_condition: str = Field(min_length=1)
    opportunities: list[OpportunityAnalysis] = Field(min_length=1, max_length=12)
