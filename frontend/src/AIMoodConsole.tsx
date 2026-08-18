import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { Sheet } from './Sheet'
import './ai-mood.css'

export type MoodRange = '7' | '20' | '60' | '90' | '180'
export type MoodSort = 'strongest' | 'improving' | 'deteriorating' | 'confidence' | 'divergent' | 'crowded'
export type MoodFilter = 'all' | MoodSort

export type JsonRecord = Record<string, unknown>

export type MoodEvidence = {
  stance: string | null
  category: string | null
  message: string | null
  value: string | number | null
  weight: string | number | null
  source: string | null
}

export type MoodDivergence = {
  type: string | null
  direction: string | null
  severity: string | number | null
  confidence: string | number | null
  duration_sessions: number | null
  first_seen: string | null
  last_seen: string | null
  evidence: MoodEvidence[]
  resolved: boolean | null
}

export type MoodTransition = {
  state: string | null
  from_state: string | null
  to_state: string | null
  date: string | null
  occurred_on: string | null
  message: string | null
}

export type MoodHistoryPoint = {
  date: string | null
  as_of: string | null
  mood_score: number | string | null
  state: string | null
  direction: string | null
  phase: string | null
  transition: MoodTransition | null
}

export type MoodRow = {
  scope_type: string
  scope_key: string
  name: string
  name_zh: string | null
  state: string | null
  candidate_state: string | null
  previous_state: string | null
  direction: string | null
  phase: string | null
  regime: string | null
  mood_score: number | string | null
  confidence: number | string | null
  quality: number | string | null
  coverage: number | string | null
  freshness_status: string | null
  agreement_score: number | string | null
  agreement_level: string | null
  state_started_on: string | null
  duration_sessions: number | null
  signals: JsonRecord
  evidence: MoodEvidence[]
  divergences: MoodDivergence[]
  transition: MoodTransition | null
  missing_sources: string[]
  stale_sources: string[]
  history: MoodHistoryPoint[]
  raw: JsonRecord
}

export type MoodReport = {
  market_mood: string | null
  sector_regime: string | null
  regime_changes: unknown[]
  ai_chain_mood: string | null
  key_divergences: unknown[]
  crowding_signals: unknown[]
  improving_sectors: unknown[]
  deteriorating_sectors: unknown[]
  limitations: string[]
  raw: JsonRecord
}

export type MoodOverview = {
  status: string | null
  as_of: string | null
  calculation_version: string | null
  market: MoodRow | null
  sectors: MoodRow[]
  industries: MoodRow[]
  ai_chain: MoodRow[]
  watchlist: MoodRow[]
  movers: Record<string, unknown[]>
  divergences: unknown[]
  transitions: unknown[]
  report: MoodReport
  limitations: string[]
  raw: JsonRecord
}

export type MoodDetail = {
  item: MoodRow | null
  history: MoodHistoryPoint[]
  status: string | null
  raw: JsonRecord
}

export const rangeOptions: Array<[MoodRange, string]> = [
  ['7', '7D'],
  ['20', '20D'],
  ['60', '60D'],
  ['90', '3M'],
  ['180', '6M'],
]

const STATE_LABELS: Record<string, string> = {
  strong: '强势',
  leadership: '领涨',
  heating: '升温',
  heating_up: '升温',
  constructive: '偏强',
  neutral: '中性',
  cooling: '降温',
  weakening: '转弱',
  weak: '偏弱',
  risk_on: '风险偏好',
  risk_off: '风险规避',
  panic: '恐慌',
  overheated: '过热',
  divergent: '分歧',
  early_reversal: '早期反转',
  reversal: '反转候选',
  unavailable: '数据不足',
  stale: '数据待更新',
  nascent: '萌芽',
  emerging: '形成',
  established: '成熟',
  mature: '成熟',
  transitioning: '过渡',
  transition: '过渡',
  crowded: '拥挤',
  early_improvement: '早期改善',
  accumulation: '积累',
  expansion: '扩散',
  distribution: '派发',
  deterioration: '恶化',
  breakdown: '破位',
  trending_up: '趋势向上',
  improving: '改善',
  trending_down: '趋势向下',
  stretched: '过度延伸',
  exhaustion: '耗竭',
  dormant: '休眠',
  green: '绿灯',
  yellow: '黄灯',
  red: '红灯',
  gray: '灰灯',
  grey: '灰灯',
  insufficient_data: '数据不足',
  insufficient_history: '历史不足',
  low_confidence: '低置信',
}

const DIRECTION_LABELS: Record<string, string> = {
  up: '改善',
  down: '走弱',
  flat: '平稳',
  bullish: '偏强',
  bearish: '偏弱',
  neutral: '中性',
  improving: '改善',
  improving_fast: '快速改善',
  deteriorating: '走弱',
  deteriorating_fast: '快速走弱',
  rising: '上行',
  falling: '下行',
  stable: '平稳',
}

const SCOPE_LABELS: Record<string, string> = {
  market: '市场',
  sector: '行业',
  industry: '行业',
  ai_chain: 'AI 产业链',
  watchlist: '自选股',
}

const SIGNAL_LABELS: Array<[string, string[]]> = [
  ['趋势', ['trend', 'trend_score']],
  ['广度', ['breadth', 'breadth_score']],
  ['相对强度', ['relative_strength', 'relativeStrength', 'rs', 'rs_score']],
  ['期权', ['options', 'options_score', 'options_signal']],
  ['新闻', ['news', 'news_score', 'news_signal']],
  ['风险定价', ['risk_pricing', 'riskPricing', 'risk', 'risk_score']],
]

const asRecord = (value: unknown): JsonRecord => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
)

const asArray = (value: unknown): unknown[] => Array.isArray(value) ? value : []

const asText = (value: unknown): string | null => {
  if (value == null) return null
  if (typeof value === 'string') return value.trim() || null
  return String(value)
}

const asNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return null
}

const first = (...values: unknown[]): unknown => values.find(value => value !== undefined && value !== null)

const firstText = (...values: unknown[]): string | null => asText(first(...values))

const firstNumber = (...values: unknown[]): number | string | null => {
  const value = first(...values)
  return value == null ? null : asNumber(value) ?? asText(value)
}

const asStringList = (value: unknown): string[] => asArray(value).map(asText).filter((item): item is string => Boolean(item))

const normalizeEvidence = (value: unknown): MoodEvidence => {
  if (value == null || typeof value !== 'object') return {
    stance: null, category: null, message: asText(value), value: null, weight: null, source: null,
  }
  const raw = asRecord(value)
  return {
    stance: firstText(raw.stance, raw.tone, raw.direction),
    category: firstText(raw.category, raw.signal, raw.type),
    message: firstText(raw.message, raw.summary, raw.text, raw.detail),
    value: firstNumber(raw.value, raw.score, raw.metric),
    weight: firstNumber(raw.weight),
    source: firstText(raw.source, raw.provider),
  }
}

const normalizeEvidenceList = (value: unknown): MoodEvidence[] => {
  if (Array.isArray(value)) return value.map(normalizeEvidence)
  const raw = asRecord(value)
  const grouped = ['supporting', 'contradicting', 'warnings'].flatMap(stance =>
    asArray(raw[stance]).map(item => normalizeEvidence(
      item && typeof item === 'object' ? { ...asRecord(item), stance } : { stance, message: item },
    )),
  )
  if (grouped.length) return grouped
  if (!Object.keys(raw).length) return []
  const metrics = asArray(raw.metrics).map(asText).filter(Boolean).join(' / ')
  return [normalizeEvidence({ ...raw, message: first(raw.message, metrics ? `${metrics} 信号出现分歧` : null) })]
}

const normalizeTransition = (value: unknown): MoodTransition | null => {
  if (!value || typeof value !== 'object') return null
  const raw = asRecord(value)
  return {
    state: firstText(raw.state, raw.label),
    from_state: firstText(raw.from_state, raw.from, raw.previous_state),
    to_state: firstText(raw.to_state, raw.to, raw.state),
    date: firstText(raw.date, raw.as_of, raw.observed_on),
    occurred_on: firstText(raw.occurred_on, raw.transition_date, raw.date),
    message: firstText(raw.message, raw.summary, raw.reason),
  }
}

const normalizeDivergence = (value: unknown): MoodDivergence => {
  const raw = asRecord(value)
  return {
    type: firstText(raw.type, raw.category, raw.kind),
    direction: firstText(raw.direction, raw.stance),
    severity: firstNumber(raw.severity, raw.level),
    confidence: firstNumber(raw.confidence),
    duration_sessions: asNumber(first(raw.duration_sessions, raw.duration, raw.sessions)),
    first_seen: firstText(raw.first_seen, raw.started_on, raw.firstSeen),
    last_seen: firstText(raw.last_seen, raw.ended_on, raw.lastSeen),
    evidence: normalizeEvidenceList(raw.evidence),
    resolved: typeof raw.resolved === 'boolean' ? raw.resolved : null,
  }
}

const normalizeHistoryPoint = (value: unknown): MoodHistoryPoint => {
  const raw = asRecord(value)
  return {
    date: firstText(raw.date, raw.as_of, raw.observed_on),
    as_of: firstText(raw.as_of, raw.date, raw.observed_on),
    mood_score: firstNumber(raw.mood_score, raw.score, raw.mood),
    state: firstText(raw.state, raw.candidate_state),
    direction: firstText(raw.direction, raw.trend),
    phase: firstText(raw.phase),
    transition: normalizeTransition(raw.transition),
  }
}

/** Normalize backend rows without deriving or calculating mood data on the client. */
export function normalizeMoodRow(value: unknown): MoodRow {
  const raw = asRecord(value)
  const signalValue = first(raw.signals, raw.signal_values, raw.signalScores)
  const signals = { ...asRecord(signalValue) }
  if (Array.isArray(signalValue)) {
    signalValue.forEach(item => {
      const signal = asRecord(item)
      const key = firstText(signal.key, signal.metric, signal.name, signal.label)
      const category = firstText(signal.category)
      const value = first(signal.normalized_score, signal.value, signal.score, signal.state, signal.status, signal.label) ?? null
      if (key) signals[key] = value
      if (category && signals[category] === undefined) signals[category] = value
    })
  }
  const history = asArray(first(raw.history, raw.history_points, raw.timeline)).map(normalizeHistoryPoint)
  return {
    scope_type: firstText(raw.scope_type, raw.scope, raw.type) || 'unknown',
    scope_key: firstText(raw.scope_key, raw.key, raw.id, raw.symbol) || '',
    name: firstText(raw.name, raw.name_zh, raw.title, raw.scope_key, raw.key) || '未命名对象',
    name_zh: firstText(raw.name_zh, raw.nameZh, raw.display_name),
    state: firstText(raw.state, raw.current_state),
    candidate_state: firstText(raw.candidate_state, raw.candidate),
    previous_state: firstText(raw.previous_state, raw.prior_state),
    direction: firstText(raw.direction, raw.trend),
    phase: firstText(raw.phase),
    regime: firstText(raw.regime),
    mood_score: firstNumber(raw.mood_score, raw.score, raw.mood),
    confidence: firstNumber(raw.confidence),
    quality: firstNumber(raw.quality),
    coverage: firstNumber(raw.coverage),
    freshness_status: firstText(raw.freshness_status, raw.freshness, raw.data_status),
    agreement_score: firstNumber(raw.agreement_score, raw.agreement),
    agreement_level: firstText(raw.agreement_level, raw.consensus),
    state_started_on: firstText(raw.state_started_on, raw.started_on),
    duration_sessions: asNumber(first(raw.duration_sessions, raw.duration, raw.sessions)),
    signals,
    evidence: normalizeEvidenceList(raw.evidence),
    divergences: asArray(first(raw.divergences, raw.divergence))
      .filter(value => asRecord(value).active !== false || asRecord(value).resolved === true)
      .map(normalizeDivergence),
    transition: normalizeTransition(raw.transition),
    missing_sources: asStringList(first(raw.missing_sources, raw.missingSources)),
    stale_sources: asStringList(first(raw.stale_sources, raw.staleSources)),
    history,
    raw,
  }
}

const normalizeObjectList = (value: unknown): unknown[] => asArray(value)

export function normalizeMoodReport(value: unknown): MoodReport {
  const raw = asRecord(value)
  const report = asRecord(first(raw.report, raw.data, raw))
  return {
    market_mood: firstText(report.market_mood, report.marketMood, report.market),
    sector_regime: firstText(report.sector_regime, report.sectorRegime, report.sector),
    regime_changes: normalizeObjectList(first(report.regime_changes, report.regimeChanges)),
    ai_chain_mood: firstText(report.ai_chain_mood, report.aiChainMood, report.ai_chain),
    key_divergences: normalizeObjectList(first(report.key_divergences, report.keyDivergences, report.divergences)),
    crowding_signals: normalizeObjectList(first(report.crowding_signals, report.crowdingSignals, report.crowding)),
    improving_sectors: normalizeObjectList(first(report.improving_sectors, report.improvingSectors)),
    deteriorating_sectors: normalizeObjectList(first(report.deteriorating_sectors, report.deterioratingSectors)),
    limitations: asStringList(report.limitations),
    raw,
  }
}

export function normalizeOverview(value: unknown): MoodOverview {
  const raw = asRecord(value)
  const rows = (...keys: string[]) => keys.flatMap(key => asArray(raw[key])).map(normalizeMoodRow)
  const moversRaw = asRecord(raw.movers)
  const movers = Object.fromEntries(Object.entries(moversRaw).map(([key, items]) => [key, asArray(items)])) as Record<string, unknown[]>
  const moverDivergences = [...(movers.new_divergence || []), ...(movers.resolved_divergence || [])]
  return {
    status: firstText(raw.status),
    as_of: firstText(raw.as_of, raw.asOf, raw.calculated_at),
    calculation_version: firstText(raw.calculation_version, raw.calculationVersion, raw.version),
    market: first(raw.market, raw.market_mood) ? normalizeMoodRow(first(raw.market, raw.market_mood)) : null,
    sectors: [...rows('sectors'), ...rows('industries')],
    industries: rows('industries'),
    ai_chain: rows('ai_chain', 'aiChain'),
    watchlist: rows('watchlist', 'watch_list'),
    movers,
    divergences: [...normalizeObjectList(raw.divergences), ...moverDivergences],
    transitions: [...normalizeObjectList(raw.transitions), ...moverDivergences],
    report: normalizeMoodReport(raw.report),
    limitations: [...asStringList(raw.limitations), ...normalizeMoodReport(raw.report).limitations],
    raw,
  }
}

export function normalizeDetail(value: unknown): MoodDetail {
  const raw = asRecord(value)
  const itemValue = first(raw.item, raw.row, raw.mood, raw)
  const item = itemValue && typeof itemValue === 'object' ? normalizeMoodRow(itemValue) : null
  const history = asArray(first(raw.history, item?.raw.history, item?.raw.timeline)).map(normalizeHistoryPoint)
  return {
    item,
    history: history.length ? history : item?.history || [],
    status: firstText(raw.status),
    raw,
  }
}

export function stateLabel(value: string | null | undefined): string {
  if (!value) return '数据不足'
  return STATE_LABELS[value.toLowerCase()] || value.replaceAll('_', ' ')
}

export function directionLabel(value: string | null | undefined): string {
  if (!value) return '平稳'
  return DIRECTION_LABELS[value.toLowerCase()] || value.replaceAll('_', ' ')
}

export function scopeLabel(value: string | null | undefined): string {
  if (!value) return '对象'
  return SCOPE_LABELS[value.toLowerCase()] || value
}

export function formatMoodValue(value: number | string | null | undefined, suffix = ''): string {
  if (value == null || value === '') return '数据不足'
  const numeric = asNumber(value)
  if (numeric == null) return `${value}${suffix}`
  return `${Number.isInteger(numeric) ? numeric : numeric.toFixed(1)}${suffix}`
}

export function formatPercentValue(value: number | string | null | undefined): string {
  if (value == null || value === '') return '数据不足'
  const numeric = asNumber(value)
  if (numeric == null) return String(value)
  const percent = numeric >= 0 && numeric <= 1 ? numeric * 100 : numeric
  return `${Number.isInteger(percent) ? percent : percent.toFixed(1)}%`
}

const scoreForSort = (row: MoodRow) => asNumber(row.mood_score) ?? -Infinity
const confidenceForSort = (row: MoodRow) => asNumber(row.confidence) ?? -Infinity
const includesAny = (value: string | null, needles: string[]) => Boolean(value && needles.some(needle => value.toLowerCase().includes(needle)))

export function sortMoodRows(rows: MoodRow[], sort: MoodSort): MoodRow[] {
  const copy = [...rows]
  if (sort === 'confidence') return copy.sort((a, b) => confidenceForSort(b) - confidenceForSort(a))
  if (sort === 'improving') return copy.sort((a, b) => Number(includesAny(b.direction, ['up', 'improv', 'rising', 'heating'])) - Number(includesAny(a.direction, ['up', 'improv', 'rising', 'heating'])) || scoreForSort(b) - scoreForSort(a))
  if (sort === 'deteriorating') return copy.sort((a, b) => Number(includesAny(b.direction, ['down', 'deterior', 'falling', 'cooling', 'weak'])) - Number(includesAny(a.direction, ['down', 'deterior', 'falling', 'cooling', 'weak'])) || scoreForSort(a) - scoreForSort(b))
  if (sort === 'divergent') return copy.sort((a, b) => b.divergences.length - a.divergences.length || confidenceForSort(b) - confidenceForSort(a))
  if (sort === 'crowded') return copy.sort((a, b) => Number(includesAny(b.state, ['crowd', 'overheat'])) - Number(includesAny(a.state, ['crowd', 'overheat'])) || scoreForSort(b) - scoreForSort(a))
  return copy.sort((a, b) => scoreForSort(b) - scoreForSort(a))
}

export function filterMoodRows(rows: MoodRow[], filter: MoodFilter): MoodRow[] {
  if (filter === 'all' || filter === 'strongest' || filter === 'confidence') return rows
  if (filter === 'divergent') return rows.filter(row => row.divergences.length > 0 || includesAny(row.state, ['diverg']))
  if (filter === 'crowded') return rows.filter(row => includesAny(row.state, ['crowd', 'overheat']) || row.divergences.some(item => includesAny(item.type, ['crowd', 'overheat'])))
  if (filter === 'improving') return rows.filter(row => includesAny(row.direction, ['up', 'improv', 'rising', 'heating']))
  if (filter === 'deteriorating') return rows.filter(row => includesAny(row.direction, ['down', 'deterior', 'falling', 'cooling', 'weak']))
  return rows
}

const textValue = (value: unknown): string | null => {
  if (value == null) return null
  if (typeof value === 'object') {
    const raw = asRecord(value)
    return firstText(raw.label, raw.name, raw.message, raw.summary, raw.text, raw.status, raw.value, raw.score)
  }
  return asText(value)
}

const objectLabel = (value: unknown): string => textValue(value) || '待确认'

export function divergenceText(value: unknown): string {
  const raw = asRecord(value)
  const left = firstText(raw.left, raw.left_name, raw.source_a, raw.a)
  const right = firstText(raw.right, raw.right_name, raw.source_b, raw.b)
  const type = firstText(raw.type, raw.category, raw.kind)
  const message = firstText(raw.message, raw.summary, raw.reason)
  if (message) return message
  if (left && right) return `${left} 与 ${right} 出现${type ? `「${type}」` : '信号'}分歧。`
  if (type) return `${type} 分歧仍在观察。`
  return objectLabel(value)
}

export function evidenceGroups(evidence: MoodEvidence[]): Array<[string, MoodEvidence[]]> {
  const grouped = new Map<string, MoodEvidence[]>()
  evidence.forEach(item => {
    const key = item.category || '其他证据'
    grouped.set(key, [...(grouped.get(key) || []), item])
  })
  return [...grouped.entries()]
}

export function historyPoints(row: MoodRow | null, history: MoodHistoryPoint[] = []): MoodHistoryPoint[] {
  const points = history.length ? history : row?.history || []
  return points.filter(point => point.date || point.as_of || point.mood_score != null)
}

function toneForState(value: string | null): string {
  if (includesAny(value, ['risk_off', 'panic', 'weak', 'deterior', 'breakdown', 'distribution', 'trending_down', 'falling', 'cooling'])) return 'negative'
  if (includesAny(value, ['risk_on', 'strong', 'lead', 'expansion', 'accumulation', 'trending_up', 'improv', 'rising', 'heating', 'constructive'])) return 'positive'
  if (includesAny(value, ['diverg', 'crowd', 'overheat', 'stale'])) return 'caution'
  return 'neutral'
}

function DataStatus({ row }: { row: MoodRow | null }) {
  if (!row) return <span className="ai-mood-pill neutral">数据不足</span>
  const stale = row.freshness_status && includesAny(row.freshness_status, ['stale', 'old', 'expired'])
  return <span className={`ai-mood-pill ${stale ? 'caution' : toneForState(row.state)}`}>{stale ? '数据待更新' : stateLabel(row.state)}</span>
}

export function MoodLoadingState() {
  return <section className="ai-mood-state" aria-label="正在加载 AI 市场情绪" aria-busy="true"><span className="ai-mood-spinner" /><strong>正在整理市场情绪</strong><small>等待最新状态与证据。</small></section>
}

export function MoodErrorState({ message = '市场情绪暂时无法读取，请稍后重试。' }: { message?: string }) {
  return <section className="ai-mood-state error" role="alert"><strong>读取失败</strong><small>{message}</small></section>
}

export function MoodEmptyState({ message = '当前范围暂无可用情绪数据。' }: { message?: string }) {
  return <section className="ai-mood-state empty"><strong>暂无情绪快照</strong><small>{message}</small></section>
}

function OverviewMetric({ label, value, detail }: { label: string; value: string; detail?: string | null }) {
  return <div className="ai-mood-metric"><dt>{label}</dt><dd>{value}</dd>{detail && <small>{detail}</small>}</div>
}

export function MarketMoodCard({ row }: { row: MoodRow | null }) {
  if (!row) return <article className="ai-mood-market-card ai-mood-muted-card"><p className="ai-mood-eyebrow">MARKET MOOD</p><h2>市场状态暂缺</h2><p>当前范围没有足够来源形成确定结论。</p></article>
  return <article className="ai-mood-market-card">
    <div className="ai-mood-card-heading"><div><p className="ai-mood-eyebrow">MARKET MOOD</p><h2>{row.name_zh || row.name}</h2><p>{row.regime || row.phase || '状态快照'}</p></div><DataStatus row={row} /></div>
    <dl className="ai-mood-metric-grid">
      <OverviewMetric label="情绪分数" value={formatMoodValue(row.mood_score)} />
      <OverviewMetric label="置信度" value={formatPercentValue(row.confidence)} />
      <OverviewMetric label="共识" value={row.agreement_level || formatPercentValue(row.agreement_score)} />
      <OverviewMetric label="阶段" value={row.phase ? stateLabel(row.phase) : '数据不足'} detail={row.direction ? directionLabel(row.direction) : null} />
    </dl>
    <SignalStrip row={row} />
  </article>
}

export function SignalStrip({ row }: { row: MoodRow | null }) {
  return <div className="ai-mood-signal-strip" aria-label="情绪信号条">
    {SIGNAL_LABELS.map(([label, keys]) => {
      const value = row ? first(
        ...keys.map(key => row.signals[key]),
        ...Object.entries(row.signals)
          .filter(([key]) => keys.some(candidate => key.toLowerCase() === candidate.toLowerCase() || key.toLowerCase().includes(candidate.toLowerCase())))
          .map(([, candidate]) => candidate),
      ) : null
      const text = textValue(value) || (value != null ? formatPercentValue(value as number | string) : '数据不足')
      return <div className="ai-mood-signal" key={label}><span>{label}</span><strong>{text}</strong></div>
    })}
  </div>
}

function boardRowKey(row: MoodRow) {
  return `${row.scope_type}:${row.scope_key || row.name}`
}

export function MoodBoard({ rows, onSelect, title = '行业与产业链', emptyMessage = '暂无行业情绪。' }: { rows: MoodRow[]; onSelect?: (row: MoodRow) => void; title?: string; emptyMessage?: string }) {
  if (!rows.length) return <section className="ai-mood-board"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">BOARD</p><h2>{title}</h2></div></div><MoodEmptyState message={emptyMessage} /></section>
  return <section className="ai-mood-board"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">BOARD</p><h2>{title}</h2></div><small>{rows.length} 个对象</small></div><div className="ai-mood-board-grid">
    {rows.map(row => <button className="ai-mood-row-card" type="button" key={boardRowKey(row)} onClick={() => onSelect?.(row)}>
      <span className="ai-mood-row-main"><strong>{row.name_zh || row.name}</strong><small>{scopeLabel(row.scope_type)} · {row.direction ? directionLabel(row.direction) : '暂无方向'}</small></span>
      <span className="ai-mood-row-state"><DataStatus row={row} /><b>{formatMoodValue(row.mood_score)}</b><small>置信 {formatPercentValue(row.confidence)}</small></span>
    </button>)}
  </div></section>
}

export function HistoryChart({ row, history = [] }: { row: MoodRow | null; history?: MoodHistoryPoint[] }) {
  const points = historyPoints(row, history)
  if (points.length < 2) return <div className="ai-mood-history-empty">历史不足，暂不能形成趋势线。</div>
  const values = points.map(point => asNumber(point.mood_score)).filter((value): value is number => value != null)
  if (values.length < 2) return <div className="ai-mood-history-empty">历史分数不足，暂不能形成趋势线。</div>
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const width = 520
  const height = 150
  const plotted = points.map((point, index) => {
    const score = asNumber(point.mood_score)
    if (score == null) return null
    const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width
    const y = height - ((score - min) / span) * (height - 26) - 12
    return { point, x, y }
  }).filter((value): value is { point: MoodHistoryPoint; x: number; y: number } => value != null)
  const path = plotted.map((item, index) => `${index ? 'L' : 'M'} ${item.x.toFixed(2)} ${item.y.toFixed(2)}`).join(' ')
  return <div className="ai-mood-history-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="情绪分数历史趋势"><title>情绪分数历史趋势</title><path className="ai-mood-chart-axis" d={`M 0 ${height - 12} H ${width}`} /><path className="ai-mood-chart-line" d={path} />{plotted.map(({ point, x, y }, index) => <circle className={`ai-mood-chart-point ${toneForState(point.state)}`} key={`${point.date || point.as_of || index}-${index}`} cx={x} cy={y} r="4"><title>{`${point.date || point.as_of || '日期未知'} · ${formatMoodValue(point.mood_score)} · ${stateLabel(point.state)}`}</title></circle>)}</svg><div className="ai-mood-history-labels"><span>{points[0].date || points[0].as_of || '起点'}</span><span>{points.at(-1)?.date || points.at(-1)?.as_of || '最新'}</span></div></div>
}

function EvidenceList({ evidence }: { evidence: MoodEvidence[] }) {
  const groups = evidenceGroups(evidence)
  if (!groups.length) return <p className="ai-mood-muted">暂无结构化证据。</p>
  return <div className="ai-mood-evidence-groups">{groups.map(([group, items]) => <div className="ai-mood-evidence-group" key={group}><h4>{group}</h4>{items.map((item, index) => <div className="ai-mood-evidence" key={`${group}-${index}`}><span className={`ai-mood-evidence-dot ${toneForState(item.stance)}`} /><p>{item.message || '证据内容暂缺'}<small>{[item.source, item.value != null ? `值 ${item.value}` : null].filter(Boolean).join(' · ')}</small></p></div>)}</div>)}</div>
}

function DivergenceList({ divergences }: { divergences: MoodDivergence[] }) {
  if (!divergences.length) return <p className="ai-mood-muted">当前没有记录中的分歧。</p>
  return <div className="ai-mood-divergences">{divergences.map((item, index) => <article className="ai-mood-divergence" key={`${item.type || 'divergence'}-${index}`}><div><strong>{item.type || '信号分歧'}</strong><span>{item.resolved ? '已解决' : item.direction ? directionLabel(item.direction) : '观察中'}</span></div><p>{item.evidence[0]?.message || '多来源信号方向尚未一致。'}</p><small>{item.duration_sessions == null ? '持续时长未知' : `持续 ${item.duration_sessions} 个交易时段`} · 置信 {formatPercentValue(item.confidence)}</small></article>)}</div>
}

export function MoodDetailContent({ detail, onAskAI }: { detail: MoodDetail; onAskAI?: (scopeKey: string, row: MoodRow) => void }) {
  const row = detail.item
  if (!row) return <MoodEmptyState message="这个对象的详细情绪快照暂不可用。" />
  return <div className="ai-mood-detail-content">
    <div className="ai-mood-detail-hero"><div><p className="ai-mood-eyebrow">{scopeLabel(row.scope_type)}</p><h2>{row.name_zh || row.name}</h2><p>{row.scope_key || '标识暂缺'}</p></div><div className="ai-mood-detail-hero-side"><DataStatus row={row} />{onAskAI && row.scope_key && <button className="ai-mood-quiet-button" type="button" onClick={() => onAskAI(row.scope_key, row)}>问 AI</button>}</div></div>
    <dl className="ai-mood-detail-metrics"><OverviewMetric label="当前状态" value={stateLabel(row.state)} detail={row.candidate_state ? `候选：${stateLabel(row.candidate_state)}` : null} /><OverviewMetric label="前一状态" value={stateLabel(row.previous_state)} /><OverviewMetric label="状态持续" value={row.duration_sessions == null ? '数据不足' : `${row.duration_sessions} 个时段`} /><OverviewMetric label="数据新鲜度" value={row.freshness_status ? stateLabel(row.freshness_status) : '数据不足'} /></dl>
    <SignalStrip row={row} />
    <div className="ai-mood-detail-section"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">HISTORY</p><h3>状态轨迹</h3></div></div><HistoryChart row={row} history={detail.history} /></div>
    <div className="ai-mood-detail-section"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">EVIDENCE</p><h3>结构化证据</h3></div></div><EvidenceList evidence={row.evidence} /></div>
    <div className="ai-mood-detail-section"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">DIVERGENCES</p><h3>分歧记录</h3></div></div><DivergenceList divergences={row.divergences} /></div>
    {(row.missing_sources.length || row.stale_sources.length) ? <p className="ai-mood-detail-limitation">{row.missing_sources.length ? `缺失来源：${row.missing_sources.join('、')}` : ''}{row.missing_sources.length && row.stale_sources.length ? ' · ' : ''}{row.stale_sources.length ? `待更新来源：${row.stale_sources.join('、')}` : ''}</p> : null}
  </div>
}

function ReportList({ title, values }: { title: string; values: unknown[] }) {
  return <section className="ai-mood-report-section"><div className="ai-mood-section-heading"><h3>{title}</h3><small>{values.length ? `${values.length} 条` : '暂无'}</small></div>{values.length ? <ul>{values.map((value, index) => <li key={`${title}-${index}`}>{title === '关键分歧' ? divergenceText(value) : objectLabel(value)}</li>)}</ul> : <p className="ai-mood-muted">当前没有记录。</p>}</section>
}

export function MoodReportContent({ report }: { report: MoodReport }) {
  return <div className="ai-mood-report-content"><div className="ai-mood-report-head"><div><p className="ai-mood-eyebrow">AI MOOD REPORT</p><h2>市场情绪摘要</h2></div><p>基于已存快照与确定性规则生成，不触发新的模型请求。</p></div><div className="ai-mood-report-highlights"><OverviewMetric label="市场情绪" value={report.market_mood ? stateLabel(report.market_mood) : '数据不足'} /><OverviewMetric label="行业状态" value={report.sector_regime ? stateLabel(report.sector_regime) : '数据不足'} /><OverviewMetric label="AI 链情绪" value={report.ai_chain_mood ? stateLabel(report.ai_chain_mood) : '数据不足'} /></div><div className="ai-mood-report-grid"><ReportList title="关键分歧" values={report.key_divergences} /><ReportList title="拥挤信号" values={report.crowding_signals} /><ReportList title="改善行业" values={report.improving_sectors} /><ReportList title="走弱行业" values={report.deteriorating_sectors} /><ReportList title="状态变化" values={report.regime_changes} /></div>{report.limitations.length > 0 && <div className="ai-mood-report-limitations"><strong>解读边界</strong>{report.limitations.map(item => <span key={item}>{item}</span>)}</div>}</div>
}

export function MoodReportSection({ range = '20', enabled = true }: { range?: MoodRange; enabled?: boolean }) {
  const query = useQuery({
    queryKey: ['mood', 'report', range],
    queryFn: () => api<unknown>(`/mood/report?range=${range}`),
    enabled,
    staleTime: 60_000,
    retry: 1,
  })
  if (!enabled) return <MoodEmptyState message="登录后可查看市场情绪报告。" />
  if (query.isLoading) return <MoodLoadingState />
  if (query.isError) return <MoodErrorState message="情绪报告暂时无法读取。" />
  if (!query.data) return <MoodEmptyState />
  return <MoodReportContent report={normalizeMoodReport(query.data)} />
}

function MoverList({ title, values, onSelect }: { title: string; values: unknown[]; onSelect: (row: MoodRow) => void }) {
  const rows = values.map(value => normalizeMoodRow(value)).filter(row => row.scope_key || row.name)
  return <div className="ai-mood-mover"><h3>{title}</h3>{rows.length ? rows.slice(0, 5).map(row => <button type="button" key={boardRowKey(row)} onClick={() => onSelect(row)}><span>{row.name_zh || row.name}</span><DataStatus row={row} /></button>) : <p className="ai-mood-muted">暂无记录</p>}</div>
}

export function AIMoodConsole({ enabled = true, onAskAI }: { enabled?: boolean; onAskAI?: (scopeKey: string, row: MoodRow) => void }) {
  const [range, setRange] = useState<MoodRange>('20')
  const [board, setBoard] = useState<'sectors' | 'industries' | 'ai_chain' | 'watchlist'>('sectors')
  const [filter, setFilter] = useState<MoodFilter>('all')
  const [sort, setSort] = useState<MoodSort>('strongest')
  const [selected, setSelected] = useState<MoodRow | null>(null)
  const overviewQuery = useQuery({
    queryKey: ['mood', 'overview', range],
    queryFn: () => api<unknown>(`/mood/overview?range=${range}`),
    enabled,
    staleTime: 60_000,
    retry: 1,
  })
  const overview = useMemo(() => overviewQuery.data ? normalizeOverview(overviewQuery.data) : null, [overviewQuery.data])
  const detailQuery = useQuery({
    queryKey: ['mood', 'detail', selected?.scope_type, selected?.scope_key, range],
    queryFn: () => api<unknown>(`/mood/${encodeURIComponent(selected!.scope_type)}/${encodeURIComponent(selected!.scope_key)}?range=${range}`),
    enabled: enabled && Boolean(selected?.scope_type && selected?.scope_key),
    staleTime: 60_000,
    retry: 1,
  })
  const boardRows = useMemo(() => {
    if (!overview) return []
    const rows = board === 'sectors' ? overview.sectors : board === 'industries' ? overview.industries : board === 'ai_chain' ? overview.ai_chain : overview.watchlist
    return sortMoodRows(filterMoodRows(rows, filter), sort)
  }, [board, filter, overview, sort])
  const detail = detailQuery.data ? normalizeDetail(detailQuery.data) : selected ? { item: selected, history: selected.history, status: null, raw: selected.raw } : null
  if (!enabled) return <MoodEmptyState message="登录后可查看 AI 市场情绪。" />
  if (overviewQuery.isLoading) return <MoodLoadingState />
  if (overviewQuery.isError) return <MoodErrorState />
  if (!overview) return <MoodEmptyState />
  const partial = overview.status !== 'ready' || !overview.market || (!overview.sectors.length && !overview.industries.length)
  return <section className="ai-mood-console" aria-label="AI 市场情绪控制台"><div className="ai-mood-console-head"><div><p className="ai-mood-eyebrow">AI MOOD CONSOLE</p><h1>市场情绪控制台</h1><p>状态、证据、分歧和变化轨迹集中呈现。</p></div><div className="ai-mood-head-actions"><label><span>观察范围</span><select value={range} onChange={event => setRange(event.target.value as MoodRange)}>{rangeOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><small>{overview.as_of ? `截至 ${overview.as_of}` : '更新时间暂缺'}{overview.calculation_version ? ` · ${overview.calculation_version}` : ''}</small></div></div>{partial && <div className="ai-mood-notice" role="status">部分数据可用{overview.limitations.length ? ` · ${overview.limitations[0]}` : ' · 当前快照覆盖有限'}</div>}<MarketMoodCard row={overview.market} /><div className="ai-mood-board-controls"><div className="ai-mood-tabs" role="tablist" aria-label="情绪对象"><button type="button" className={board === 'sectors' ? 'active' : ''} onClick={() => setBoard('sectors')}>行业</button><button type="button" className={board === 'ai_chain' ? 'active' : ''} onClick={() => setBoard('ai_chain')}>AI 链</button><button type="button" className={board === 'watchlist' ? 'active' : ''} onClick={() => setBoard('watchlist')}>自选股</button></div><div className="ai-mood-filter-row"><label><span>筛选</span><select value={filter} onChange={event => setFilter(event.target.value as MoodFilter)}><option value="all">全部</option><option value="improving">改善</option><option value="deteriorating">走弱</option><option value="confidence">高置信</option><option value="divergent">分歧</option><option value="crowded">拥挤</option></select></label><label><span>排序</span><select value={sort} onChange={event => setSort(event.target.value as MoodSort)}><option value="strongest">最强</option><option value="improving">改善</option><option value="deteriorating">走弱</option><option value="confidence">置信度</option><option value="divergent">分歧</option><option value="crowded">拥挤</option></select></label></div></div><MoodBoard rows={boardRows} onSelect={setSelected} title={board === 'sectors' ? '行业情绪' : board === 'ai_chain' ? 'AI 产业链情绪' : '自选股情绪'} />{(overview.divergences.length || overview.transitions.length) > 0 && <section className="ai-mood-analysis"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">ANALYSIS</p><h2>分歧与变化</h2></div></div><div className="ai-mood-analysis-grid">{overview.divergences.slice(0, 6).map((item, index) => <article key={`divergence-${index}`}><span>分歧</span><p>{divergenceText(item)}</p></article>)}{overview.transitions.slice(0, 6).map((item, index) => <article key={`transition-${index}`}><span>变化</span><p>{objectLabel(item)}</p></article>)}</div></section>}<section className="ai-mood-movers"><div className="ai-mood-section-heading"><div><p className="ai-mood-eyebrow">MOVERS</p><h2>近期变化</h2></div></div><div className="ai-mood-mover-grid"><MoverList title="改善" values={overview.movers.improving || overview.movers.improvers || []} onSelect={setSelected} /><MoverList title="走弱" values={overview.movers.deteriorating || []} onSelect={setSelected} /><MoverList title="新领涨" values={overview.movers.new_leadership || []} onSelect={setSelected} /><MoverList title="新拥挤" values={overview.movers.new_crowded || []} onSelect={setSelected} /></div></section><Sheet open={Boolean(selected)} onClose={() => setSelected(null)} title={selected ? `${selected.name_zh || selected.name} · 情绪详情` : undefined} size="wide">{detailQuery.isLoading ? <MoodLoadingState /> : detailQuery.isError ? <MoodErrorState message="详情暂时无法读取。" /> : detail ? <MoodDetailContent detail={detail} onAskAI={onAskAI} /> : <MoodEmptyState />}</Sheet></section>
}

export default AIMoodConsole

export type MoodReportSectionProps = { range?: MoodRange; enabled?: boolean }
