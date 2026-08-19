import {
  isNumber,
  isRecord,
  isString,
  recordArray,
  stringArray,
} from './validation'

type Validator = (value: unknown) => boolean

const numeric = (value: unknown) =>
  isNumber(value)
  || (isString(value, 80) && value.trim() !== '' && Number.isFinite(Number(value)))

const optionalNumeric = (value: unknown) => value == null || numeric(value)
const requiredRecords = (value: unknown, max: number): value is Record<string, unknown>[] =>
  recordArray(value, max) && value.length > 0
const optionalString = (value: unknown, max = 2_000) => value == null || isString(value, max)
const identifier = (value: unknown, max = 128) => isString(value, max) && value.length > 0
const oneOf = (value: unknown, choices: readonly string[]) =>
  typeof value === 'string' && choices.includes(value)

function validPoints(value: unknown, max = 500): boolean {
  return Array.isArray(value)
    && value.length <= max
    && value.every(point => (
      isRecord(point)
      && identifier(point.x, 80)
      && (point.value == null || numeric(point.value))
    ))
}

const stockQuote: Validator = value => {
  if (!isRecord(value)) return false
  return (
    identifier(value.symbol, 32)
    && numeric(value.price)
    && identifier(value.currency, 12)
    && isString(value.as_of, 80)
    && oneOf(value.market_status, ['pre_market', 'open', 'after_hours', 'closed', 'unknown'])
    && optionalNumeric(value.change)
    && optionalNumeric(value.change_percent)
    && optionalNumeric(value.previous_close)
    && Array.isArray(value.sparkline)
    && validPoints(value.sparkline, 120)
  )
}

const metricGrid: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.metrics, 16)) return false
  return value.metrics.every(metric => (
    identifier(metric.key, 64)
    && identifier(metric.label, 120)
    && isString(metric.display_value, 120)
    && optionalString(metric.secondary_text, 240)
    && oneOf(metric.trend, ['positive', 'negative', 'neutral', 'unknown'])
  ))
}

const miniLineChart: Validator = value => {
  if (!isRecord(value) || !identifier(value.title, 200) || !requiredRecords(value.series, 5)) return false
  return value.series.every(series => (
    identifier(series.key, 64)
    && identifier(series.label, 120)
    && validPoints(series.points, 500)
    && Array.isArray(series.points)
    && series.points.length > 0
  ))
}

const valuationRange: Validator = value => {
  if (!isRecord(value) || !identifier(value.symbol, 32)) return false
  const values = [
    value.bear_value,
    value.base_value,
    value.bull_value,
    value.lower_bound,
    value.upper_bound,
  ]
  return (
    values.some(numeric)
    && values.every(optionalNumeric)
    && optionalNumeric(value.current_price)
  )
}

const valuationMethod = (value: unknown): value is Record<string, unknown> => (
  isRecord(value)
  && identifier(value.key, 64)
  && identifier(value.label, 120)
  && optionalNumeric(value.weight_percent)
  && optionalString(value.verdict, 32)
  && (value.stars == null || (Number.isInteger(value.stars) && Number(value.stars) >= 0 && Number(value.stars) <= 5))
  && optionalNumeric(value.fair_value)
  && optionalNumeric(value.scenario_low)
  && optionalNumeric(value.scenario_high)
  && optionalNumeric(value.metric_value)
  && optionalString(value.metric_unit, 16)
  && optionalNumeric(value.peer_median)
  && optionalString(value.comparison, 80)
  && optionalString(value.note, 200)
)

const valuationSummary: Validator = value => {
  if (!isRecord(value) || !identifier(value.symbol, 32)) return false
  if (!Array.isArray(value.methods) || value.methods.length > 3) return false
  if (!value.methods.every(valuationMethod)) return false
  return (
    optionalNumeric(value.current_price)
    && optionalNumeric(value.consensus_value)
    && optionalString(value.consensus_label, 64)
    && optionalNumeric(value.consensus_position_percent)
    && (value.model_conflict == null || typeof value.model_conflict === 'boolean')
    && optionalString(value.valuation_date, 80)
  )
}

const comparisonTable: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.columns, 12) || !requiredRecords(value.rows, 100)) return false
  const keys = new Set<string>()
  for (const column of value.columns) {
    if (!identifier(column.key, 64) || !identifier(column.label, 120) || keys.has(column.key as string)) return false
    keys.add(column.key as string)
  }
  return value.rows.every(row => (
    identifier(row.row_id, 128)
    && identifier(row.label, 160)
    && isRecord(row.values)
  ))
}

const portfolioAllocation: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.items, 11)) return false
  return value.items.every(item => (
    identifier(item.key, 128)
    && identifier(item.label, 160)
    && numeric(item.weight_percent)
    && Number(item.weight_percent) >= 0
    && optionalNumeric(item.value)
  ))
}

const riskPanel: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.risks, 8)) return false
  return value.risks.every(risk => (
    identifier(risk.risk_id, 128)
    && identifier(risk.title, 200)
    && identifier(risk.summary, 2_000)
    && oneOf(risk.severity, ['low', 'medium', 'high', 'critical', 'unknown'])
    && oneOf(risk.status, ['not_triggered', 'watching', 'partially_triggered', 'triggered', 'unknown'])
    && stringArray(risk.citation_keys ?? [], 20, 16)
  ))
}

const catalystTimeline: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.events, 30) || !identifier(value.timezone, 64)) return false
  return value.events.every(event => (
    identifier(event.event_id, 128)
    && identifier(event.title, 240)
    && identifier(event.event_type, 80)
    && isString(event.starts_at, 80)
    && oneOf(event.importance, ['low', 'medium', 'high'])
    && oneOf(event.status, ['upcoming', 'ongoing', 'completed', 'cancelled', 'unknown'])
    && stringArray(event.citation_keys ?? [], 20, 16)
  ))
}

const newsCluster: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.sources, 10)) return false
  return (
    identifier(value.cluster_id, 128)
    && identifier(value.headline, 400)
    && identifier(value.summary, 4_000)
    && Number.isInteger(value.source_count)
    && Number(value.source_count) >= 1
    && value.sources.every(source => (
      identifier(source.source_id, 256)
      && identifier(source.title, 400)
      && optionalString(source.url, 2_000)
    ))
  )
}

const secFiling: Validator = value => (
  isRecord(value)
  && identifier(value.filing_id, 128)
  && identifier(value.symbol, 32)
  && identifier(value.form_type, 32)
  && isString(value.filed_at, 80)
  && stringArray(value.key_changes ?? [], 20, 1_000)
  && stringArray(value.risk_changes ?? [], 20, 1_000)
)

const investmentDecision: Validator = value => (
  isRecord(value)
  && identifier(value.decision_id, 128)
  && identifier(value.title, 240)
  && identifier(value.decision_type, 64)
  && identifier(value.status, 32)
  && isString(value.decision_date, 80)
  && stringArray(value.symbols ?? [], 20, 32)
  && stringArray(value.invalidation_conditions ?? [], 30, 1_000)
  && stringArray(value.risks ?? [], 30, 1_000)
)

const sourceList: Validator = value => {
  if (!isRecord(value) || !requiredRecords(value.sources, 100)) return false
  return value.sources.every(source => (
    isString(source.citation_key, 16)
    && /^S\d+$/.test(source.citation_key)
    && identifier(source.source_id, 256)
    && identifier(source.title, 400)
    && identifier(source.source_type, 64)
    && oneOf(source.origin, ['internal', 'web', 'deep_search', 'unknown'])
    && optionalString(source.url, 2_000)
  ))
}

export const blockDataValidators: Record<string, Validator> = {
  stock_quote: stockQuote,
  metric_grid: metricGrid,
  mini_line_chart: miniLineChart,
  valuation_range: valuationRange,
  valuation_summary: valuationSummary,
  comparison_table: comparisonTable,
  portfolio_allocation: portfolioAllocation,
  risk_panel: riskPanel,
  catalyst_timeline: catalystTimeline,
  news_cluster: newsCluster,
  sec_filing: secFiling,
  investment_decision: investmentDecision,
  source_list: sourceList,
}
