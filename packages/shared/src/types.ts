export type MarketStatus = { is_open: boolean; checked_at: string }
export type DashboardStock = {
  ticker: string
  company_name?: string | null
  logo_url?: string | null
  price: number | null
  previous_close: number | null
  updated_at: string | null
  volume: number | null
  volume_ratio: number | null
  volume_label: string | null
}
export type Dashboard = { market: MarketStatus; stocks: DashboardStock[] }
export type IndexQuote = { symbol: string; name: string; price: number | null; previous_close: number | null; change_points: number | null; change_percent: number | null }
export type Indices = { indices: IndexQuote[]; market: MarketStatus }
export type Alert = { id: number; ticker: string; period: string; change_percent: number; triggered_at: string }
export type Report = { id: number; ticker: string | null; report_type: string; title: string; model: string; created_at: string; confidence?: '高' | '中' | '低' | null }
export type ReportDetail = Report & { content: string; sources: { title: string; url: string }[] }
export type NewsItem = { id: number; ticker: string; provider: string; title: string; translated_title: string | null; url: string; source: string | null; summary: string | null; symbols: string[]; news_type: string; scope: 'market' | 'company'; topic: string | null; importance_score: number | null; quality_score: number | null; sentiment_score: number | null; published_at: string | null; found_at: string; ai_summary: string | null; ai_summary_model: string | null; ai_summary_status: 'idle' | 'queued' | 'processing' | 'completed' | 'failed'; ai_summary_requested_at: string | null }
export type MarketNews = { items: NewsItem[]; total: number; generated_at: string; last_updated_at: string | null; sources: string[] }
export type WatchItem = { id: number; ticker: string; enabled: boolean; alert_enabled: boolean }

export type Position = {
  symbol: string
  total_quantity: number
  average_cost: number
  total_cost?: number | null
  currency: string
  current_price: number | null
  previous_close?: number | null
  daily_change_amount?: number | null
  daily_change_percent?: number | null
  market_value: number | null
  unrealized_pnl: number | null
  unrealized_pnl_percent: number | null
  total_pnl?: number | null
  total_return_pct?: number | null
  daily_pnl?: number | null
  daily_return_pct?: number | null
  holding_days?: number | null
  first_trade_at?: string | null
  price_source?: string | null
  price_as_of?: string | null
  price_is_report_fallback?: boolean
  price_available?: boolean
  project_price_available?: boolean
  quantity_source?: string | null
  average_cost_source?: string | null
  ibkr_conid?: number | null
  ibkr_market_price?: number | null
  ibkr_market_value?: number | null
  ibkr_unrealized_pnl?: number | null
  ibkr_fx_rate_to_base?: number | null
  ibkr_report_date?: string | null
  fx_rate?: number | null
  fx_rate_source?: string | null
  base_currency_market_value?: number | null
  base_currency_total_cost?: number | null
  base_currency_unrealized_pnl?: number | null
  authority_source?: string | null
  valuation_available: boolean
  portfolio_weight: number | null
}
export type PortfolioSummary = {
  portfolio_id: number
  base_currency: string
  position_count: number
  priced_count: number
  total_market_value: number
  total_cost: number
  total_unrealized_pnl: number
  total_unrealized_pnl_percent: number | null
  net_asset_value?: number | null
  invested_market_value?: number | null
  cash?: number | null
  latest_daily_return?: number | null
  time_weighted_return?: number | null
  latest_sync_at?: string | null
  account_data_source?: string | null
  has_unpriced_positions: boolean
  has_unconverted_positions: boolean
  fx_conversion_used: boolean
  positions: Position[]
}
export type CalendarSummary = { today: number; next_7_days: number; next_30_days: number; high_impact: number; portfolio_events: number; generated_at: string }
export type CalendarEvent = { id: number; symbol: string; event_type: string; event_date: string; event_time: string | null; title: string; description: string | null; impact_level: string; portfolio_relevance: boolean; watchlist_relevance: boolean; primary_source: string }
export type CalendarEvents = { items: CalendarEvent[]; total: number; next_cursor: number | null; start_date: string; end_date: string; generated_at: string }

export type DiscoveryCandidate = {
  id: number
  raw_ticker: string
  normalized_ticker: string | null
  company_name: string
  display_status: string
  priority: string
  discovery_reason: string | null
  portfolio_fit: string | null
  why_now: string | null
  confidence: number | null
  investment_thesis: string[]
  major_risks: string[]
  groups: { id: string; name: string }[]
}
export type DiscoveryResult = {
  id: number
  status: string
  analysis_date: string | null
  groups: { id: string; name: string; summary: string; candidates: DiscoveryCandidate[] }[]
  raw_candidates: DiscoveryCandidate[]
  filtered_candidates: DiscoveryCandidate[]
  counts: { raw: number; accepted: number; watch_only: number; rejected: number }
  limitations: string[]
}
export type LatestDiscovery = { result: DiscoveryResult | null; using_previous_result: boolean; api_key_configured: boolean; monthly_spend_usd: number; monthly_budget_usd: number }

export type FundamentalMetric = { label: string; value: number | null; source: 'yahoo' | 'finnhub' | null }
export type Fundamentals = { ticker: string; metrics: FundamentalMetric[]; rating: { period: string | null; strongBuy: number; buy: number; hold: number; sell: number; strongSell: number } | null; as_of: string; source_support: { yahoo: boolean; finnhub: boolean } }
export type ValuationMetric = { key: string; label: string; value: number | null; unit: string; status: string; display?: string | null; peer_median: number | null; peer_count: number; peer_delta_percent: number | null; comparison: string | null; explanation: string; recommended_range: string; note: string | null }
export type ValuationSnapshot = { ticker: string; company: string; classification: { sector: string | null; industry: string | null; label: string; focus: string }; valuation: ValuationMetric[]; growth: ValuationMetric[]; health: ValuationMetric[]; dcf_scenarios: { bear: number | null; base: number | null; bull: number | null; current: number | null }; reverse_dcf: { implied_fcf_growth: number | null; unit: string }; consensus: { value: number | null; current: number | null }; model_signals: { key: string; label: string; verdict: string; stars: number; detail: string }[]; model_conflict: boolean; ai_opinion: string; ai_model: string | null; snapshot_date: string; generated_at: string | null }
export type FinancialStatement = { fiscal_year: number; fiscal_period: string; period_end: string; currency: string | null; income_statement: Record<string, number | null>; balance_sheet: Record<string, number | null>; cash_flow: Record<string, number | null>; source: string; synced_at: string }
export type SecEvent = { id: number; form: string; item_code: string; item_label: string; priority: string; text: string | null; summary_zh: string | null; summary_model: string | null; summary_status: string; filing_date: string | null; filing_url: string }
export type SecFinancial = { fiscal_year: number; fiscal_period: string; form: string; period_end: string | null; currency: string | null; revenue: number | null; net_income: number | null; operating_income: number | null; gross_profit: number | null; eps_diluted: number | null; cash_and_equivalents: number | null; total_debt: number | null; operating_cash_flow: number | null }
export type SecInsider = { id: number; insider_name: string; insider_title: string | null; transaction_date: string | null; transaction_code: string | null; shares: number | null; price: number | null; value: number | null; shares_owned_after: number | null; flag: string | null; filing_url: string }
export type SecHolding = { id: number; manager_name: string; shares: number | null; value_usd: number | null; put_call: string | null; share_change: number | null; is_new: boolean; filing_date: string | null }
export type SecHoldings = { report_period: string | null; prev_period: string | null; holdings: SecHolding[] }

export type WebAccessMode = 'off' | 'search' | 'deep_minimal' | 'deep_low' | 'deep_medium' | 'deep_high' | 'deep_xhigh'
export type AIConfig = { enabled: boolean; streaming: boolean; default_model: string; max_message_chars: number; models: { id: string; label: string; family: string; is_default: boolean; available: boolean }[]; web_search: { enabled: boolean; configured: boolean; default_mode: WebAccessMode; available_modes: WebAccessMode[]; deep_modes: Record<string, { label: string; estimated_base_cost_usd: number; confirmation_required: boolean; enabled: boolean }> } }
export type Conversation = { id: number; title: string; status: string; model: string | null; web_access_mode: WebAccessMode; message_count: number; last_message_preview: string | null; updated_at: string; last_message_at: string | null }
export type ConversationPage = { items: Conversation[]; page: number; limit: number; total: number; has_more: boolean }
export type AICitation = { key: string; title: string; url: string | null; provider: string | null; published_at: string | null }
export type AIMessage = { id: number | string; conversation_id: number; role: 'user' | 'assistant'; status: string; content: string; model: string | null; citations: AICitation[]; error_message_safe: string | null; created_at: string }
export type MessagePage = { items: AIMessage[]; page: number; limit: number; total: number; has_more: boolean }
