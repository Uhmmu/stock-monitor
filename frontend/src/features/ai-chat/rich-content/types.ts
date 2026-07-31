import type { Citation } from '../api'

export type FreshnessStatus = 'fresh' | 'aging' | 'stale' | 'unknown'
export type Numeric = number | string

export type BlockFreshness = {
  as_of?: string | null
  retrieved_at?: string | null
  status: FreshnessStatus
  label?: string | null
}

export type RichBlockInteraction = {
  expandable?: boolean
  sortable?: boolean
  selectable?: boolean
  navigation_target?: string | null
}

export type RichBlock<T = Record<string, unknown>> = {
  block_id: string
  block_type: string
  block_version: number
  title?: string | null
  subtitle?: string | null
  data: T
  citation_keys: string[]
  source_ids: string[]
  freshness?: BlockFreshness | null
  warnings: string[]
  fallback_markdown: string
  interaction?: RichBlockInteraction | null
}

export type RichMarkdownPart = {
  type: 'markdown'
  part_id: string
  content: string
}

export type RichBlockPart = {
  type: 'block'
  part_id: string
  block: RichBlock
}

export type RichContentPart = RichMarkdownPart | RichBlockPart

export type RichContentDocument = {
  schema_version: number
  parts: RichContentPart[]
  fallback_markdown: string
  warnings: string[]
}

export type RichBlockProps<T = Record<string, unknown>> = {
  block: RichBlock<T>
  citations: Citation[]
  onCitation: (key: string) => void
}

export type TimeValuePoint = { x: string; value: Numeric | null }

export type StockQuoteData = {
  symbol: string
  company_name?: string | null
  price: Numeric
  currency: string
  change?: Numeric | null
  change_percent?: Numeric | null
  previous_close?: Numeric | null
  open?: Numeric | null
  day_high?: Numeric | null
  day_low?: Numeric | null
  market_status: 'pre_market' | 'open' | 'after_hours' | 'closed' | 'unknown'
  extended_price?: Numeric | null
  extended_change_percent?: Numeric | null
  sparkline: TimeValuePoint[]
  as_of: string
}

export type MetricItem = {
  key: string
  label: string
  value?: Numeric | null
  display_value: string
  unit?: string | null
  trend: 'positive' | 'negative' | 'neutral' | 'unknown'
  secondary_text?: string | null
  as_of?: string | null
}

export type MetricGridData = {
  symbol?: string | null
  columns: number
  metrics: MetricItem[]
}

export type ChartSeries = {
  key: string
  label: string
  unit?: string | null
  points: TimeValuePoint[]
}

export type MiniLineChartData = {
  title: string
  x_axis_type: 'date' | 'quarter' | 'year' | 'category'
  series: ChartSeries[]
  y_axis_unit?: string | null
  value_format?: string | null
  show_legend: boolean
  show_tooltip: boolean
}

export type ValuationRangeData = {
  symbol: string
  currency: string
  current_price?: Numeric | null
  bear_value?: Numeric | null
  base_value?: Numeric | null
  bull_value?: Numeric | null
  lower_bound?: Numeric | null
  upper_bound?: Numeric | null
  model_name?: string | null
  valuation_date?: string | null
  current_position_label?: string | null
}

export type ComparisonColumn = {
  key: string
  label: string
  value_type: 'text' | 'number' | 'currency' | 'percent' | 'date' | 'score'
  sortable: boolean
}

export type ComparisonRow = {
  row_id: string
  label: string
  symbol?: string | null
  values: Record<string, unknown>
}

export type ComparisonTableData = {
  columns: ComparisonColumn[]
  rows: ComparisonRow[]
  highlight_row_id?: string | null
  default_sort_key?: string | null
}

export type AllocationItem = {
  key: string
  label: string
  symbol?: string | null
  weight_percent: Numeric
  value?: Numeric | null
  currency?: string | null
  category?: string | null
}

export type PortfolioAllocationData = {
  portfolio_id?: number | string | null
  total_value?: Numeric | null
  currency?: string | null
  items: AllocationItem[]
  concentration_score?: Numeric | null
  largest_weight_percent?: Numeric | null
}

export type RiskItem = {
  risk_id: string
  title: string
  severity: 'low' | 'medium' | 'high' | 'critical' | 'unknown'
  status: 'not_triggered' | 'watching' | 'partially_triggered' | 'triggered' | 'unknown'
  summary: string
  evidence_summary?: string | null
  monitoring_condition?: string | null
  citation_keys: string[]
}

export type RiskPanelData = { symbol?: string | null; risks: RiskItem[] }

export type TimelineEvent = {
  event_id: string
  title: string
  event_type: string
  starts_at: string
  ends_at?: string | null
  symbol?: string | null
  importance: 'low' | 'medium' | 'high'
  status: 'upcoming' | 'ongoing' | 'completed' | 'cancelled' | 'unknown'
  summary?: string | null
  citation_keys: string[]
}

export type CatalystTimelineData = { events: TimelineEvent[]; timezone: string }

export type NewsSourceItem = {
  source_id: string
  title: string
  provider?: string | null
  published_at?: string | null
  url?: string | null
  authority?: string | null
}

export type NewsClusterData = {
  cluster_id: string
  headline: string
  symbol?: string | null
  event_date?: string | null
  summary: string
  source_count: number
  official_source_present: boolean
  sources: NewsSourceItem[]
  disagreement_summary?: string | null
}

export type SecFilingData = {
  filing_id: string
  symbol: string
  form_type: string
  filed_at: string
  report_period?: string | null
  title?: string | null
  summary?: string | null
  key_changes: string[]
  risk_changes: string[]
  official_url?: string | null
}

export type InvestmentDecisionData = {
  decision_id: string
  title: string
  symbols: string[]
  decision_type: string
  status: string
  action?: string | null
  thesis_summary?: string | null
  invalidation_conditions: string[]
  risks: string[]
  decision_date: string
  target_review_at?: string | null
  review_due: boolean
}

export type SourceListItem = {
  citation_key: string
  source_id: string
  title: string
  source_type: string
  origin: 'internal' | 'web' | 'deep_search' | 'unknown'
  provider?: string | null
  published_at?: string | null
  retrieved_at?: string | null
  url?: string | null
  authority?: string | null
}

export type SourceListData = { sources: SourceListItem[]; collapsed: boolean }
