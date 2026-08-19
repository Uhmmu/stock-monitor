from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


FreshnessStatus = Literal["fresh", "aging", "stale", "unknown"]
BlockType = Literal[
    "stock_quote",
    "metric_grid",
    "mini_line_chart",
    "valuation_range",
    "valuation_summary",
    "comparison_table",
    "portfolio_allocation",
    "risk_panel",
    "catalyst_timeline",
    "news_cluster",
    "sec_filing",
    "investment_decision",
    "source_list",
]


class BlockFreshness(StrictModel):
    as_of: datetime | None = None
    retrieved_at: datetime | None = None
    status: FreshnessStatus = "unknown"
    label: str | None = Field(None, max_length=160)


class BlockInteractionConfig(StrictModel):
    expandable: bool = False
    sortable: bool = False
    selectable: bool = False
    navigation_target: str | None = Field(None, max_length=500)


class TimeValuePoint(StrictModel):
    x: str = Field(min_length=1, max_length=80)
    value: Decimal | None = None


class StockQuoteData(StrictModel):
    symbol: str = Field(min_length=1, max_length=32)
    company_name: str | None = Field(None, max_length=256)
    price: Decimal
    currency: str = Field("—", min_length=1, max_length=12)
    change: Decimal | None = None
    change_percent: Decimal | None = None
    previous_close: Decimal | None = None
    open: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    market_status: Literal[
        "pre_market", "open", "after_hours", "closed", "unknown"
    ] = "unknown"
    extended_price: Decimal | None = None
    extended_change_percent: Decimal | None = None
    sparkline: list[TimeValuePoint] = Field(default_factory=list, max_length=120)
    as_of: datetime


class MetricItem(StrictModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:\-]+$")
    label: str = Field(min_length=1, max_length=120)
    value: Decimal | str | int | None = None
    display_value: str = Field(max_length=120)
    unit: str | None = Field(None, max_length=32)
    trend: Literal["positive", "negative", "neutral", "unknown"] = "unknown"
    secondary_text: str | None = Field(None, max_length=240)
    as_of: datetime | None = None


class MetricGridData(StrictModel):
    symbol: str | None = Field(None, max_length=32)
    columns: int = Field(2, ge=1, le=4)
    metrics: list[MetricItem] = Field(min_length=1, max_length=16)


class ChartSeries(StrictModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:\-]+$")
    label: str = Field(min_length=1, max_length=120)
    unit: str | None = Field(None, max_length=32)
    points: list[TimeValuePoint] = Field(min_length=1, max_length=500)


class MiniLineChartData(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    x_axis_type: Literal["date", "quarter", "year", "category"]
    series: list[ChartSeries] = Field(min_length=1, max_length=5)
    y_axis_unit: str | None = Field(None, max_length=32)
    value_format: str | None = Field(None, max_length=32)
    show_legend: bool = True
    show_tooltip: bool = True


class ValuationRangeData(StrictModel):
    symbol: str = Field(min_length=1, max_length=32)
    currency: str = Field("—", min_length=1, max_length=12)
    current_price: Decimal | None = None
    bear_value: Decimal | None = None
    base_value: Decimal | None = None
    bull_value: Decimal | None = None
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    model_name: str | None = Field(None, max_length=160)
    valuation_date: datetime | date | None = None
    current_position_label: str | None = Field(None, max_length=160)

    @model_validator(mode="after")
    def require_range_value(self):
        if all(
            value is None
            for value in (
                self.bear_value,
                self.base_value,
                self.bull_value,
                self.lower_bound,
                self.upper_bound,
            )
        ):
            raise ValueError("valuation range requires at least one scenario value")
        return self


class ValuationMethodItem(StrictModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:\-]+$")
    label: str = Field(min_length=1, max_length=120)
    weight_percent: Decimal | None = None
    verdict: str | None = Field(None, max_length=32)
    stars: int | None = Field(None, ge=0, le=5)
    fair_value: Decimal | None = None
    scenario_low: Decimal | None = None
    scenario_high: Decimal | None = None
    metric_value: Decimal | None = None
    metric_unit: str | None = Field(None, max_length=16)
    peer_median: Decimal | None = None
    comparison: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=200)


class ValuationSummaryData(StrictModel):
    symbol: str = Field(min_length=1, max_length=32)
    currency: str = Field("—", min_length=1, max_length=12)
    current_price: Decimal | None = None
    methods: list[ValuationMethodItem] = Field(default_factory=list, max_length=3)
    consensus_value: Decimal | None = None
    consensus_label: str | None = Field(None, max_length=64)
    consensus_position_percent: Decimal | None = None
    model_conflict: bool | None = None
    valuation_date: datetime | date | None = None

    @model_validator(mode="after")
    def require_value(self):
        if not self.methods and self.consensus_value is None:
            raise ValueError("valuation summary requires methods or a consensus value")
        return self


class ComparisonColumn(StrictModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:\-]+$")
    label: str = Field(min_length=1, max_length=120)
    value_type: Literal["text", "number", "currency", "percent", "date", "score"]
    sortable: bool = True


class ComparisonRow(StrictModel):
    row_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=160)
    symbol: str | None = Field(None, max_length=32)
    values: dict[str, Any]


class ComparisonTableData(StrictModel):
    columns: list[ComparisonColumn] = Field(min_length=1, max_length=12)
    rows: list[ComparisonRow] = Field(min_length=1, max_length=100)
    highlight_row_id: str | None = Field(None, max_length=128)
    default_sort_key: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def values_match_columns(self):
        keys = {column.key for column in self.columns}
        if len(keys) != len(self.columns):
            raise ValueError("comparison column keys must be unique")
        for row in self.rows:
            row.values = {key: value for key, value in row.values.items() if key in keys}
        if self.default_sort_key and self.default_sort_key not in keys:
            raise ValueError("default sort key is not a registered column")
        return self


class AllocationItem(StrictModel):
    key: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=160)
    symbol: str | None = Field(None, max_length=32)
    weight_percent: Decimal = Field(ge=0)
    value: Decimal | None = None
    currency: str | None = Field(None, max_length=12)
    category: str | None = Field(None, max_length=120)


class PortfolioAllocationData(StrictModel):
    portfolio_id: int | str | None = None
    total_value: Decimal | None = None
    currency: str | None = Field(None, max_length=12)
    items: list[AllocationItem] = Field(min_length=1, max_length=11)
    concentration_score: Decimal | None = None
    largest_weight_percent: Decimal | None = None


class RiskItem(StrictModel):
    risk_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    severity: Literal["low", "medium", "high", "critical", "unknown"] = "unknown"
    status: Literal[
        "not_triggered", "watching", "partially_triggered", "triggered", "unknown"
    ] = "unknown"
    summary: str = Field(min_length=1, max_length=2000)
    evidence_summary: str | None = Field(None, max_length=3000)
    monitoring_condition: str | None = Field(None, max_length=1000)
    citation_keys: list[str] = Field(default_factory=list, max_length=20)


class RiskPanelData(StrictModel):
    symbol: str | None = Field(None, max_length=32)
    risks: list[RiskItem] = Field(min_length=1, max_length=8)


class TimelineEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=240)
    event_type: str = Field(min_length=1, max_length=80)
    starts_at: datetime
    ends_at: datetime | None = None
    symbol: str | None = Field(None, max_length=32)
    importance: Literal["low", "medium", "high"] = "medium"
    status: Literal["upcoming", "ongoing", "completed", "cancelled", "unknown"] = "upcoming"
    summary: str | None = Field(None, max_length=1200)
    citation_keys: list[str] = Field(default_factory=list, max_length=20)


class CatalystTimelineData(StrictModel):
    events: list[TimelineEvent] = Field(min_length=1, max_length=30)
    timezone: str = Field("Asia/Shanghai", min_length=1, max_length=64)


class NewsSourceItem(StrictModel):
    source_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=400)
    provider: str | None = Field(None, max_length=100)
    published_at: datetime | None = None
    url: str | None = Field(None, max_length=2000)
    authority: str | None = Field(None, max_length=80)


class NewsClusterData(StrictModel):
    cluster_id: str = Field(min_length=1, max_length=128)
    headline: str = Field(min_length=1, max_length=400)
    symbol: str | None = Field(None, max_length=32)
    event_date: datetime | None = None
    summary: str = Field(min_length=1, max_length=4000)
    source_count: int = Field(ge=1)
    official_source_present: bool = False
    sources: list[NewsSourceItem] = Field(min_length=1, max_length=10)
    disagreement_summary: str | None = Field(None, max_length=2000)


class SecFilingData(StrictModel):
    filing_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=32)
    form_type: str = Field(min_length=1, max_length=32)
    filed_at: datetime
    report_period: datetime | date | None = None
    title: str | None = Field(None, max_length=300)
    summary: str | None = Field(None, max_length=3000)
    key_changes: list[str] = Field(default_factory=list, max_length=20)
    risk_changes: list[str] = Field(default_factory=list, max_length=20)
    official_url: str | None = Field(None, max_length=2000)


class InvestmentDecisionData(StrictModel):
    decision_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=240)
    symbols: list[str] = Field(default_factory=list, max_length=20)
    decision_type: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    action: str | None = Field(None, max_length=4000)
    thesis_summary: str | None = Field(None, max_length=3000)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=30)
    decision_date: datetime | date
    target_review_at: datetime | None = None
    review_due: bool = False


class SourceListItem(StrictModel):
    citation_key: str = Field(min_length=2, max_length=16, pattern=r"^S\d+$")
    source_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=400)
    source_type: str = Field(min_length=1, max_length=64)
    origin: Literal["internal", "web", "deep_search", "unknown"] = "unknown"
    provider: str | None = Field(None, max_length=100)
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    url: str | None = Field(None, max_length=2000)
    authority: str | None = Field(None, max_length=100)


class SourceListData(StrictModel):
    sources: list[SourceListItem] = Field(min_length=1, max_length=100)
    collapsed: bool = True


BLOCK_DATA_MODELS: dict[str, type[StrictModel]] = {
    "stock_quote": StockQuoteData,
    "metric_grid": MetricGridData,
    "mini_line_chart": MiniLineChartData,
    "valuation_range": ValuationRangeData,
    "valuation_summary": ValuationSummaryData,
    "comparison_table": ComparisonTableData,
    "portfolio_allocation": PortfolioAllocationData,
    "risk_panel": RiskPanelData,
    "catalyst_timeline": CatalystTimelineData,
    "news_cluster": NewsClusterData,
    "sec_filing": SecFilingData,
    "investment_decision": InvestmentDecisionData,
    "source_list": SourceListData,
}


class RichBlock(StrictModel):
    block_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.:\-]*$"
    )
    block_type: str = Field(min_length=1, max_length=64)
    block_version: int = Field(ge=1, le=100)
    title: str | None = Field(None, max_length=240)
    subtitle: str | None = Field(None, max_length=400)
    data: dict[str, Any]
    citation_keys: list[str] = Field(default_factory=list, max_length=100)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    freshness: BlockFreshness | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
    fallback_markdown: str = Field(min_length=1, max_length=30000)
    interaction: BlockInteractionConfig | None = None


class MarkdownPart(StrictModel):
    type: Literal["markdown"] = "markdown"
    part_id: str = Field(min_length=1, max_length=128)
    content: str = Field(max_length=100000)


class RichBlockPart(StrictModel):
    type: Literal["block"] = "block"
    part_id: str = Field(min_length=1, max_length=128)
    block: RichBlock


RichContentPart = Annotated[
    MarkdownPart | RichBlockPart, Field(discriminator="type")
]


class RichContentDocument(StrictModel):
    schema_version: int = Field(1, ge=1, le=100)
    parts: list[RichContentPart] = Field(default_factory=list, max_length=41)
    fallback_markdown: str = Field(max_length=100000)
    warnings: list[str] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def unique_ids(self):
        part_ids = [part.part_id for part in self.parts]
        block_ids = [
            part.block.block_id
            for part in self.parts
            if isinstance(part, RichBlockPart)
        ]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("part_id values must be unique")
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("block_id values must be unique")
        return self


class RichBlockCandidate(StrictModel):
    block_id: str
    block_type: str
    block_version: int
    tool_name: str
    tool_call_id: str
    relevance_hint: str | None = Field(None, max_length=300)
    recommended_position: Literal["early", "after_related_text", "late"] = (
        "after_related_text"
    )
    block: RichBlock


class RichBlockDefinition(StrictModel):
    block_type: str
    version: int
    data_schema: dict[str, Any]


class CompositionResult(StrictModel):
    document: RichContentDocument
    used_citation_keys: list[str] = Field(default_factory=list)
    candidate_block_count: int = 0
    used_block_count: int = 0
    invalid_placeholder_count: int = 0
    duplicate_placeholder_count: int = 0
    auto_inserted_count: int = 0
    duration_ms: int = 0
