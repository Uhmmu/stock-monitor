import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { Sheet } from './Sheet'
import './industry-pulse.css'

export type IndustryView = 'overview' | 'ai-chain' | 'focus' | 'taxonomy'
export type PulseRange = '30' | '90' | '365'

type JsonRecord = Record<string, unknown>

export type PulseRow = {
  id: string
  name: string
  code: string | null
  pulse: number | null
  strength: number | null
  heat: number | null
  risk: number | null
  change5d: number | null
  mood: string | null
  confidence: number | string | null
  coverage: number | string | null
  breadth: number | null
  relativeStrength: number | null
  proxyMode: string | null
  proxyEtfs: string[]
  constituentCount: number
  rank: number | null
  sparkline: number[]
  parentId: string | null
  level: number | null
  children: PulseRow[]
  raw: JsonRecord
}

export type TaxonomyNode = PulseRow & { children: TaxonomyNode[] }

const VIEW_TABS: [IndustryView, string][] = [
  ['overview', '总览'],
  ['ai-chain', 'AI 产业链'],
  ['focus', '重点板块'],
  ['taxonomy', '全市场行业'],
]

const MOOD_LABELS: Record<string, string> = {
  strong: '强势', leadership: '领涨', heating_up: '升温', heating: '升温', constructive: '偏强',
  neutral: '中性', cooling: '降温', weakening: '转弱', risk_off: '风险规避', panic: '恐慌',
  overheated: '过热', early_reversal: '早期反转', reversal: '反转候选',
  derived: '子节点聚合', unavailable: '数据不足',
}

const BUCKET_LABELS: Record<string, string> = {
  leaders: '今日领涨', current_leaders: '今日领涨',
  fastest_heating: '升温最快', heating: '升温最快',
  relative_strength_breakout: '相对强度突破', rs_breakout: '相对强度突破',
  volume_abnormal: '成交异常', volume_shock: '成交异常',
  overheating: '过热观察', overheated: '过热观察',
  cooling: '领涨降温', cooling_leaders: '领涨降温',
  risk_off: '风险规避', panic: '风险规避',
  reversal_candidates: '早期反转候选', reversal: '早期反转候选', rotation: '轮动增强',
  breadth_expansion: '广度扩张', early_broadening: '早期扩散', narrow_leadership: '窄幅领涨', internal_confirmation: '内部确认',
}

const PROXY_LABELS: Record<string, string> = {
  DIRECT_ETF: '外部 ETF 确认',
  EQUITY_BASKET: '代表性股票篮子',
  HYBRID: '篮子 + 外部 ETF',
  DERIVED: '子节点聚合',
}

const THEME_BASKET_KEYS = ['healthcare_ai', 'financial_ai', 'consumer_ai', 'ai_platform', 'ai_platforms', 'enterprise_ai', 'data', 'cybersecurity', 'developer_ecosystem', 'robotics', 'autonomous_systems', 'defense_ai']

const asRecord = (value: unknown): JsonRecord => value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
const asArray = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const first = (...values: unknown[]) => values.find(value => value !== undefined && value !== null)
const asText = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value.trim() : value == null ? null : String(value)
const asNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value)
  return null
}
const pickArray = (value: unknown, keys: string[]): unknown[] => {
  const record = asRecord(value)
  for (const key of keys) {
    const candidate = record[key]
    if (Array.isArray(candidate)) return candidate
  }
  return []
}

const scoreValue = (raw: JsonRecord, keys: string[]) => asNumber(first(...keys.map(key => raw[key])))

const score = (value: number | null) => value == null ? null : Math.max(0, Math.min(100, value))

const nestedValue = (value: unknown, keys: string[]) => {
  const record = asRecord(value)
  return first(...keys.map(key => record[key]))
}

const scalarValue = (value: unknown, keys: string[]) => {
  const nested = nestedValue(value, keys)
  return nested === undefined ? value : nested
}

const proxyLabel = (value: string | null) => value == null ? '代理不足' : PROXY_LABELS[value.toUpperCase()] || value

const themeBasket = (row: PulseRow) => {
  const raw = row.raw
  if (first(raw.is_theme_basket, raw.theme_basket, raw.themeBasket) === true) return true
  const key = String(first(raw.node_key, raw.nodeKey, raw.code, row.code, raw.slug, '')).toLowerCase()
  return THEME_BASKET_KEYS.some(candidate => key.includes(candidate))
}

const rowId = (raw: JsonRecord, fallback: string) => String(first(raw.id, raw.node_id, raw.node_key, raw.key, raw.code, raw.symbol, fallback))

const rowName = (raw: JsonRecord, fallback: string) => String(first(raw.name_zh, raw.label_zh, raw.display_name_zh, raw.name, raw.label, raw.title, raw.node_name, fallback))

const rowChange = (raw: JsonRecord) => asNumber(first(raw.change_5d, raw.delta_5d, raw.pulse_change_5d, raw.change, raw.change_percent))

const rowSparkline = (raw: JsonRecord) => {
  const source = first(raw.sparkline, raw.pulse_history, raw.history, raw.trend)
  if (Array.isArray(source)) {
    return source.map(item => typeof item === 'object' ? scoreValue(asRecord(item), ['pulse', 'pulse_score', 'score', 'value', 'close']) : asNumber(item)).filter((item): item is number => item != null)
  }
  return []
}

export function normalizePulseRow(value: unknown, index = 0): PulseRow {
  const raw = asRecord(value)
  const children = pickArray(raw, ['children', 'nodes', 'items']).map((item, childIndex) => normalizePulseRow(item, childIndex))
  return {
    id: rowId(raw, `node-${index}`),
    name: rowName(raw, `未命名板块 ${index + 1}`),
    code: asText(first(raw.code, raw.symbol, raw.slug)),
    pulse: score(scoreValue(raw, ['pulse', 'pulse_score', 'score', 'sector_pulse'])),
    strength: score(scoreValue(raw, ['strength', 'strength_score', 'trend_score'])),
    heat: score(scoreValue(raw, ['heat', 'heat_score', 'temperature'])),
    risk: score(scoreValue(raw, ['risk', 'risk_score'])),
    change5d: rowChange(raw),
    mood: asText(first(raw.mood, raw.regime, raw.status, raw.direction)),
    confidence: scalarValue(first(raw.confidence, raw.confidence_score, raw.data_confidence), ['confidence', 'score', 'value', 'level']) as number | string | null ?? null,
    coverage: scalarValue(first(raw.coverage, raw.coverage_quality, raw.data_quality, raw.coverage_percent), ['quality', 'coverage', 'value', 'percent', 'level']) as number | string | null ?? null,
    breadth: score(scoreValue(raw, ['breadth', 'breadth_score', 'breadth_percent'])),
    relativeStrength: score(scoreValue(raw, ['relative_strength', 'relative_strength_score', 'rs_score', 'rs'])),
    proxyMode: asText(first(raw.proxy_mode, raw.proxyMode)),
    proxyEtfs: asArray(first(raw.proxy_etfs, raw.etfs)).map(item => asText(typeof item === 'object' ? first(asRecord(item).ticker, asRecord(item).symbol) : item)).filter((item): item is string => item != null),
    constituentCount: asNumber(first(raw.constituent_count, raw.valid_constituents)) ?? 0,
    rank: asNumber(first(raw.rank, raw.position)),
    sparkline: rowSparkline(raw),
    parentId: asText(first(raw.parent_id, raw.parent, raw.parent_key)),
    level: asNumber(first(raw.level, raw.depth)),
    children,
    raw,
  }
}

export function responseRows(value: unknown, keys = ['sectors', 'nodes', 'items', 'rows', 'results']): PulseRow[] {
  const rows = Array.isArray(value) ? value : pickArray(value, keys)
  return rows.map((item, index) => normalizePulseRow(item, index))
}

export function buildTaxonomyTree(value: unknown): TaxonomyNode[] {
  const rows = responseRows(value, ['nodes', 'taxonomy', 'items', 'sectors'])
  const byId = new Map<string, TaxonomyNode>()
  const roots: TaxonomyNode[] = []
  rows.forEach(row => byId.set(row.id, { ...row, children: [] }))
  rows.forEach(row => {
    const node = byId.get(row.id)!
    if (row.parentId && byId.has(row.parentId)) byId.get(row.parentId)!.children.push(node)
    else roots.push(node)
  })
  if (!roots.length && rows.length) return rows.map(row => ({ ...row, children: row.children as TaxonomyNode[] }))
  return roots
}

export function extractFocusBuckets(value: unknown): { key: string; label: string; rows: PulseRow[] }[] {
  const record = asRecord(value)
  const source = asRecord(first(record.buckets, record.signals, record.focus, record.categories))
  const entries = Object.entries(source)
  if (entries.length) return entries.map(([key, rows]) => ({ key, label: BUCKET_LABELS[key] || key, rows: responseRows(rows) })).filter(item => item.rows.length)
  return Object.entries(record)
    .filter(([key, rows]) => key in BUCKET_LABELS && Array.isArray(rows))
    .map(([key, rows]) => ({ key, label: BUCKET_LABELS[key], rows: responseRows(rows) }))
    .filter(item => item.rows.length)
}

export const scoreText = (value: number | null) => value == null ? '数据不足' : value.toFixed(0)

export const signedText = (value: number | null) => value == null ? '数据不足' : `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`

export function confidenceText(value: number | string | null): string {
  if (value == null || value === '') return '置信度不足'
  if (typeof value === 'number') return `${Math.round((value <= 1 ? value * 100 : value))}%`
  const labels: Record<string, string> = { high: '高', medium: '中', low: '低', HIGH: '高', MEDIUM: '中', LOW: '低' }
  return labels[value] || value
}

export function coverageText(value: number | string | null): string {
  if (value == null || value === '') return '覆盖不足'
  if (typeof value === 'number') return value <= 1 ? `${Math.round(value * 100)}%` : `${Math.round(value)}%`
  const labels: Record<string, string> = { high: '高覆盖', medium: '中覆盖', low: '低覆盖', HIGH: '高覆盖', MEDIUM: '中覆盖', LOW: '低覆盖' }
  return labels[value] || value
}

const moodText = (value: string | null) => value == null ? '状态不足' : MOOD_LABELS[value] || MOOD_LABELS[value.toLowerCase()] || value
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="industry-sparkline-empty">历史不足</span>
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${30 - ((value - min) / span) * 25}`).join(' ')
  return <svg className="industry-sparkline" viewBox="0 0 100 32" role="img" aria-label="板块脉冲历史趋势"><polyline points={points} fill="none" vectorEffect="non-scaling-stroke"/></svg>
}

function PulseCard({ row, onSelect, compact = false }: { row: PulseRow; onSelect: (row: PulseRow) => void; compact?: boolean }) {
  return <button type="button" className={`industry-pulse-card${compact ? ' compact' : ''}`} onClick={() => onSelect(row)}>
    <div className="industry-pulse-card-head"><span><b>{row.name}</b>{row.code && <small>{row.code}</small>}{themeBasket(row) && <small className="industry-theme-badge">Theme Basket</small>}</span><em>{row.rank != null ? `#${row.rank}` : moodText(row.mood)}</em></div>
    <div className="industry-pulse-value"><strong>{scoreText(row.pulse)}</strong><span>Pulse</span><small className={row.change5d == null ? '' : row.change5d >= 0 ? 'positive' : 'negative'}>{signedText(row.change5d)} · 5D</small></div>
    {!compact && <Sparkline values={row.sparkline}/>}
    <div className="industry-proxy-chips">{row.proxyEtfs.length ? row.proxyEtfs.map(ticker => <span key={ticker}>{ticker}</span>) : <span>{proxyLabel(row.proxyMode)}</span>}</div>
    <footer><span>{moodText(row.mood)}</span><span>{coverageText(row.coverage)} · {confidenceText(row.confidence)}</span></footer>
  </button>
}

function SummaryCard({ label, row, note }: { label: string; row?: PulseRow; note: string }) {
  return <div className="industry-summary-card"><span>{label}</span><strong>{row?.name || '数据不足'}</strong><small>{row ? `${scoreText(row.pulse)} Pulse · ${note}` : '等待已保存快照'}</small></div>
}

function OverviewView({ data, loading, error, onSelect }: { data: unknown; loading: boolean; error: boolean; onSelect: (row: PulseRow) => void }) {
  if (loading) return <LoadingState text="正在读取行业脉冲快照…" />
  if (error) return <ErrorState text="行业脉冲暂时无法读取；后台同步成功后会继续保留上一份快照。" />
  const rows = responseRows(data)
  if (!rows.length) return <EmptyState text="暂无行业脉冲快照。" />
  const strongest = [...rows].sort((a, b) => (b.pulse ?? -1) - (a.pulse ?? -1))[0]
  const heating = [...rows].sort((a, b) => (b.change5d ?? -Infinity) - (a.change5d ?? -Infinity))[0]
  const cooling = [...rows].sort((a, b) => (a.change5d ?? Infinity) - (b.change5d ?? Infinity))[0]
  return <div className="industry-view-content">
    <div className="industry-summary-grid"><SummaryCard label="当前最强" row={strongest} note="ETF 映射趋势"/><SummaryCard label="升温最快" row={heating} note="5 日趋势变化"/><SummaryCard label="降温最快" row={cooling} note="5 日趋势变化"/></div>
    <section className="industry-section"><div className="industry-section-heading"><div><p>MARKET TREND</p><h3>板块趋势总览</h3></div><small>{rows.length} 个板块 · ETF 映射快照</small></div><div className="industry-card-grid">{rows.map(row => <PulseCard key={row.id} row={row} onSelect={onSelect}/>)}</div></section>
  </div>
}

function chainGroups(value: unknown): { key: string; label: string; rows: PulseRow[] }[] {
  const record = asRecord(value)
  const source = first(record.groups, record.layers, record.sections, record.nodes)
  if (Array.isArray(source)) {
    const grouped = source.map((group, index) => {
      const item = asRecord(group)
      return { key: String(first(item.node_key, item.key, item.slug, item.id, index)), label: String(first(item.name_zh, item.label_zh, item.name, item.label, `产业链 ${index + 1}`)), rows: responseRows(item) }
    }).filter(group => group.rows.length)
    if (grouped.length) return grouped
  }
  const object = asRecord(source)
  return Object.entries(object).map(([key, rows]) => ({ key, label: MOOD_LABELS[key] || key, rows: responseRows(rows) })).filter(group => group.rows.length)
}

const FLOW_PHASES = [
  { key: 'upstream', label: '上游 · 能源与算力', note: '电力、半导体与关键硬件', categories: ['ai.power', 'ai.compute'] },
  { key: 'infrastructure', label: '中游 · 基础设施', note: '服务器、网络、数据中心与云', categories: ['ai.infrastructure'] },
  { key: 'platforms', label: '平台层 · 软件与数据', note: '平台、数据、安全与开发生态', categories: ['ai.software_and_data'] },
  { key: 'downstream', label: '下游 · AI 应用', note: '行业落地与终端应用', categories: ['ai.applications'] },
] as const

export function chainFlow(value: unknown) {
  const groups = chainGroups(value)
  return FLOW_PHASES.map(phase => ({
    ...phase,
    rows: groups.filter(group => phase.categories.some(category => group.key === category || group.key.startsWith(`${category}.`))).flatMap(group => group.rows),
  })).filter(phase => phase.rows.length)
}

function FlowNodeCard({ row, onSelect }: { row: PulseRow; onSelect: (row: PulseRow) => void }) {
  return <button type="button" className="industry-flow-node" onClick={() => onSelect(row)}>
    <div><span><b>{row.name}</b><small>{row.constituentCount ? `${row.constituentCount} 只成分` : '成分数据不足'}</small></span><em>{moodText(row.mood)}</em></div>
    <div className="industry-flow-trend"><strong>{scoreText(row.pulse)}</strong><span>趋势强度</span><small className={row.change5d == null ? '' : row.change5d >= 0 ? 'positive' : 'negative'}>{signedText(row.change5d)} · 5D</small></div>
    <div className="industry-proxy-chips">{row.proxyEtfs.length ? row.proxyEtfs.map(ticker => <span key={ticker}>{ticker}</span>) : <span>{proxyLabel(row.proxyMode)}</span>}</div>
    <footer><span>{confidenceText(row.confidence)}置信</span><span>{coverageText(row.coverage)}</span></footer>
  </button>
}

function AIChainView({ data, loading, error, onSelect }: { data: unknown; loading: boolean; error: boolean; onSelect: (row: PulseRow) => void }) {
  if (loading) return <LoadingState text="正在读取 AI 产业链快照…" />
  if (error) return <ErrorState text="AI 产业链快照暂时无法读取。" />
  const groups = chainGroups(data)
  const phases = chainFlow(data)
  const record = asRecord(data)
  const concentrationRaw = first(record.concentration, record.chain_concentration, record.breadth_summary)
  const concentration = asRecord(concentrationRaw)
  const ratioScore = (value: unknown) => {
    const number = asNumber(value)
    return number === null ? null : number <= 1 ? number * 100 : number
  }
  const concentrationScore = ratioScore(first(concentrationRaw, concentration.score, concentration.value, concentration.breadth_score))
  const chainBreadth = ratioScore(first(record.breadth, concentration.breadth, concentration.coverage))
  const propagation = asText(first(record.propagation_status, record.propagation, record.summary, record.narrative))
  const propagationText = propagation ? ({ broadening: '沿产业链扩散', BROADENING: '沿产业链扩散', mixed: '局部扩散', STABLE: '局部扩散', narrowing: '尚未形成扩散', CONCENTRATING: '扩散范围收窄' }[propagation] || propagation) : null
  const propagationFrontier = asText(record.propagation_frontier)
  const availableGroups = asNumber(record.available_groups)
  const totalGroups = asNumber(record.total_groups)
  const coverage = asRecord(record.coverage)
  const confidence = asRecord(coverage.confidence)
  const breadthSummary = asRecord(record.breadth_summary)
  const strongNodes = asNumber(breadthSummary.strong_nodes) ?? 0
  const eligibleNodes = asNumber(breadthSummary.eligible_nodes) ?? 0
  const concentrationValue = asText(concentration.status) === 'NO_STRONG_NODES' ? '暂无强势链条' : concentrationScore == null ? '数据不足' : `${concentrationScore.toFixed(0)}%`
  if (!groups.length) return <EmptyState text="暂无 AI 产业链快照。" />
  const chainRows = groups.flatMap(group => group.rows)
  const syntheticCoverageRaw = first(record.synthetic_coverage, record.synthetic_node_coverage, coverage.synthetic, coverage.synthetic_nodes, concentration.synthetic_coverage)
  const syntheticCoverage = asRecord(syntheticCoverageRaw)
  const syntheticTotal = asNumber(first(syntheticCoverage.total_nodes, syntheticCoverage.total, coverage.synthetic_total_nodes, record.synthetic_total_nodes, record.total_synthetic_nodes, coverage.synthetic_nodes)) ?? chainRows.length
  const syntheticAvailable = asNumber(first(syntheticCoverage.available_nodes, syntheticCoverage.valid_nodes, syntheticCoverage.calculable_nodes, coverage.synthetic_available_nodes, record.synthetic_available_nodes, record.available_synthetic_nodes)) ?? chainRows.filter(row => row.pulse != null && row.constituentCount >= 5).length
  const syntheticQuality = scalarValue(first(syntheticCoverage.quality, syntheticCoverage.coverage, syntheticCoverage.effective_data_coverage, syntheticCoverage.effective_weight_coverage, syntheticCoverageRaw, coverage.synthetic_coverage, record.synthetic_coverage_quality), ['quality', 'coverage', 'value', 'effective_weight_coverage'])
  const syntheticConfidenceRaw = first(syntheticCoverage.confidence, record.synthetic_confidence, coverage.synthetic_confidence)
  const syntheticConfidence = asRecord(syntheticConfidenceRaw)
  const confidenceTextValue = Object.keys(syntheticConfidence).length ? `${asNumber(syntheticConfidence.high) ?? 0}/${asNumber(syntheticConfidence.medium) ?? 0}/${asNumber(syntheticConfidence.low) ?? 0}` : confidenceText(syntheticConfidenceRaw as number | string | null)
  return <div className="industry-view-content">
    <section className="industry-chain-banner"><div><p>AI TRADE STRUCTURE</p><h3>AI 产业链状态</h3><p>主要覆盖口径是每个 AI 节点的代表性股票篮子；外部 ETF 仅作市场确认，不替代篮子数据。</p></div><div className="industry-chain-facts"><span><b>{concentrationValue}</b><small>{asText(first(concentration.label_zh, concentration.label)) || '链条集中度'}</small></span><span><b>{scoreText(chainBreadth)}</b><small>链条广度 · {strongNodes}/{eligibleNodes}</small></span></div></section>
    <div className="industry-coverage-grid"><span><b>{syntheticAvailable}/{syntheticTotal}</b><small>代表性股票篮子覆盖</small></span><span><b>{coverageText(syntheticQuality as number | string | null)}</b><small>有效篮子数据</small></span><span><b>{confidenceTextValue}</b><small>篮子置信度 · 高 / 中 / 低</small></span><span><b>{asNumber(coverage.direct_etf_nodes) ?? 0}</b><small>外部 ETF 确认</small></span><span><b>{strongNodes}/{eligibleNodes}</b><small>节点广度分子 / 分母</small></span></div>
    <p className="industry-signal-note"><b>覆盖口径</b>代表性股票篮子是 AI 产业链的主要数据层；链条广度使用 {strongNodes}/{eligibleNodes} 个 eligible 节点。{propagationText ? ` ${propagationText}${propagationFrontier ? ` · 当前前沿：${propagationFrontier}` : ''}` : ''}</p>
    <div className="industry-flow" aria-label="AI 产业链上游到下游流程图">{phases.map((phase, index) => <section className="industry-flow-stage" key={phase.key}>
      <header><span>{index + 1}</span><div><h3>{phase.label}</h3><p>{phase.note}</p></div>{index < phases.length - 1 && <i aria-hidden="true">→</i>}</header>
      <div className="industry-flow-waterfall">{phase.rows.map(row => <FlowNodeCard key={row.id} row={row} onSelect={onSelect}/>)}</div>
    </section>)}</div>
  </div>
}

function FocusNote({ row, onSelect }: { row: PulseRow; onSelect: (row: PulseRow) => void }) {
  return <button type="button" className="industry-focus-note" onClick={() => onSelect(row)}>
    <span><b>{row.name}</b>{row.rank != null && <small>#{row.rank}</small>}</span>
    <strong>{scoreText(row.pulse)}<small> Pulse</small></strong>
    <footer><span className={row.change5d == null ? '' : row.change5d >= 0 ? 'positive' : 'negative'}>{signedText(row.change5d)} · 5D</span><span>{moodText(row.mood)}</span></footer>
  </button>
}

function FocusView({ data, loading, error, onSelect }: { data: unknown; loading: boolean; error: boolean; onSelect: (row: PulseRow) => void }) {
  if (loading) return <LoadingState text="正在读取重点板块信号…" />
  if (error) return <ErrorState text="重点板块信号暂时无法读取。" />
  const buckets = extractFocusBuckets(data)
  if (!buckets.length) return <EmptyState text="暂无重点板块信号。" />
  return <div className="industry-view-content"><p className="industry-signal-note"><b>信号口径</b>这些分组由价格、趋势、相对强度、成交量和波动变化推导；不代表真实资金流向，也不构成投资建议。</p><div className="industry-focus-grid">{buckets.map(bucket => <section className="industry-focus-bucket" key={bucket.key}><div className="industry-section-heading"><div><p>FOCUS SIGNAL</p><h3>{bucket.label}</h3></div><small>{bucket.rows.length} 个</small></div><div className="industry-focus-list">{bucket.rows.slice(0, 8).map(row => <FocusNote key={row.id} row={row} onSelect={onSelect}/>)}</div></section>)}</div></div>
}

function TaxonomyTree({ nodes, onSelect }: { nodes: TaxonomyNode[]; onSelect: (row: PulseRow) => void }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(nodes.slice(0, 1).map(node => node.id)))
  const toggle = (id: string) => setOpen(current => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const render = (node: TaxonomyNode, level: number): React.ReactNode => {
    const expanded = open.has(node.id)
    return <li role="treeitem" aria-level={level} aria-expanded={node.children.length ? expanded : undefined} key={node.id}>
      <div className="industry-tree-row"><button type="button" className="industry-tree-toggle" onClick={() => node.children.length ? toggle(node.id) : onSelect(node)} aria-label={`${node.children.length ? expanded ? '收起' : '展开' : '查看'} ${node.name}`}>{node.children.length ? expanded ? '⌄' : '›' : '·'}</button><button type="button" className="industry-tree-label" onClick={() => onSelect(node)}><span><b>{node.name}</b>{node.code && <small>{node.code}</small>}</span><span>{scoreText(node.pulse)}<small> Pulse</small></span></button></div>
      {node.children.length > 0 && expanded && <ul role="group">{node.children.map(child => render(child, level + 1))}</ul>}
    </li>
  }
  return <ul className="industry-taxonomy-tree" role="tree" aria-label="全市场行业分类树">{nodes.map(node => render(node, 1))}</ul>
}

function TaxonomyView({ data, loading, error, onSelect }: { data: unknown; loading: boolean; error: boolean; onSelect: (row: PulseRow) => void }) {
  if (loading) return <LoadingState text="正在读取全市场行业分类…" />
  if (error) return <ErrorState text="行业分类快照暂时无法读取。" />
  const nodes = buildTaxonomyTree(data)
  if (!nodes.length) return <EmptyState text="暂无行业分类快照。" />
  return <div className="industry-view-content"><section className="industry-section"><div className="industry-section-heading"><div><p>BASE INDUSTRY TAXONOMY</p><h3>全市场三层分类</h3></div><small>公司业务身份与主题暴露分开</small></div><TaxonomyTree nodes={nodes} onSelect={onSelect}/></section></div>
}

type DetailData = {
  node: PulseRow
  history: { date: string; value: number }[]
  etfs: JsonRecord[]
  constituents: JsonRecord[]
  basket: JsonRecord
  proxyMode: string | null
  summary: string | null
}

function detailData(value: unknown, fallback: PulseRow): DetailData {
  const record = asRecord(value)
  const metrics = asRecord(record.metrics)
  const rawNode = first(record.node, record.detail, record.item, value)
  const node = normalizePulseRow(rawNode, 0)
  const historyRows = pickArray(record, ['history', 'pulse_history', 'snapshots', 'series'])
  const history = historyRows.map(item => {
    const row = asRecord(item)
    return { date: String(first(row.date, row.trading_date, row.as_of, row.observation_date, '')), value: scoreValue(row, ['pulse', 'pulse_score', 'score', 'value']) ?? NaN }
  }).filter(item => item.date && Number.isFinite(item.value))
  const basketSignal = asRecord(metrics.basket_signal)
  const basketBase = asRecord(first(record.synthetic_etf, record.synthetic_basket, record.representative_basket, record.basket, metrics.synthetic_etf, metrics.synthetic_basket, metrics.basket, basketSignal.basket))
  const basket: JsonRecord = { ...basketBase, metric: first(basketBase.metric, basketSignal.metric, asRecord(metrics.synthetic).metric) }
  const etfs = pickArray(record, ['etfs', 'proxies', 'instruments', 'proxy_etfs']).map(asRecord).filter(item => Object.keys(item).length)
  const directConstituents = pickArray(record, ['constituents', 'basket_members']).map(asRecord).filter(item => Object.keys(item).length)
  const constituents = directConstituents.length ? directConstituents : pickArray(basket, ['members', 'constituents']).map(asRecord).filter(item => Object.keys(item).length)
  return { node: node.id === 'node-0' && fallback.id !== 'node-0' ? fallback : node, history, etfs, constituents, basket, proxyMode: asText(first(record.proxy_mode, node.proxyMode)), summary: asText(first(record.ai_summary, record.summary, record.narrative)) }
}

function HistoryChart({ points }: { points: { date: string; value: number }[] }) {
  if (points.length < 2) return <div className="industry-chart-empty">该范围内历史脉冲不足，系统不会用直线填补缺失日期。</div>
  const min = Math.min(...points.map(point => point.value)); const max = Math.max(...points.map(point => point.value)); const span = max - min || 1
  const coords = points.map((point, index) => `${(index / Math.max(points.length - 1, 1)) * 100},${140 - ((point.value - min) / span) * 120}`).join(' ')
  return <div className="industry-history-chart"><svg viewBox="0 0 100 150" preserveAspectRatio="none" role="img" aria-label="行业脉冲历史趋势"><line x1="0" x2="100" y1="80" y2="80" className="industry-chart-zero"/><polyline points={coords} className="industry-chart-line"/></svg><div><span>{points[0].date}</span><span>{points[points.length - 1].date}</span></div></div>
}

function ProxyTable({ rows }: { rows: JsonRecord[] }) {
  if (!rows.length) return <div className="industry-chart-empty">暂无可靠 ETF 代理；请以覆盖质量与数据状态为准。</div>
  return <div className="industry-proxy-table"><div className="industry-proxy-head"><span>ETF</span><span>角色</span><span>Purity</span><span>状态</span></div>{rows.map((row, index) => <div className="industry-proxy-row" key={`${String(first(row.ticker, row.symbol, row.code, index))}-${index}`}><b>{String(first(row.ticker, row.symbol, row.code, '—'))}</b><span>{String(first(row.role, row.proxy_role, row.instrument_role, '数据不足'))}</span><span>{String(first(row.purity, row.theme_purity, row.exposure_weight, '数据不足'))}</span><span>{String(first(row.health_status, row.status, row.data_quality, row.coverage_quality, '数据不足'))}</span></div>)}</div>
}

function ConstituentTable({ rows }: { rows: JsonRecord[] }) {
  if (!rows.length) return <div className="industry-chart-empty">当前节点没有达到分类与覆盖门槛的股票篮子。</div>
  return <div className="industry-constituent-table"><div className="industry-constituent-head"><span>股票</span><span>产业链角色</span><span>权重</span><span>数据状态</span></div>{rows.map((row, index) => {
    const weight = asNumber(row.weight)
    return <div className="industry-constituent-row" key={`${String(first(row.ticker, index))}-${index}`}><b>{String(first(row.ticker, '—'))}</b><span>{String(first(row.role, '—'))}<small>{String(first(row.sub_role, row.classification_source, '—'))}</small></span><span>{weight == null ? '—' : `${(weight * 100).toFixed(1)}%`}</span><span>{String(first(row.health_status, row.validation_status, '数据不足'))}</span></div>
  })}</div>
}

function NodeDetail({ selected, range, onRange, onClose }: { selected: PulseRow | null; range: PulseRange; onRange: (range: PulseRange) => void; onClose: () => void }) {
  const detail = useQuery({ queryKey: ['industry-pulse', 'node', selected?.id, range], queryFn: () => api<unknown>(`/industry-pulse/nodes/${encodeURIComponent(selected!.id)}?range=${range}`), enabled: selected !== null, staleTime: 5 * 60_000 })
  const data = selected && detail.data ? detailData(detail.data, selected) : selected ? { node: selected, history: [], etfs: [], constituents: [], basket: {}, proxyMode: selected.proxyMode, summary: null } : null
  const basket = data?.basket || {}
  const configuredConstituents = data ? asNumber(first(basket.target_constituents, basket.configured_constituents, basket.constituent_count, asArray(basket.members).length, data.node.raw.target_constituents, data.constituents.length)) : null
  const validConstituents = data ? asNumber(first(basket.valid_constituents, basket.valid_count, basket.available_constituents, data.node.raw.valid_constituents, data.node.constituentCount, data.constituents.length)) : null
  const basketQuality = data ? scalarValue(first(basket.effective_data_coverage, basket.effective_weight_coverage, basket.coverage_quality, basket.coverage, data.node.raw.synthetic_coverage, data.node.coverage), ['quality', 'coverage', 'value', 'effective_weight_coverage']) : null
  const basketConfidence = data ? scalarValue(first(basket.coverage_confidence, basket.synthetic_confidence, basket.confidence, data.node.raw.synthetic_confidence, data.node.confidence), ['confidence', 'value', 'score']) as number | string | null : null
  const basketHistory = data ? asNumber(first(basket.history_days, basket.synthetic_points, basket.history_length, data.node.raw.synthetic_history_days)) : null
  return <Sheet open={selected !== null} onClose={onClose} title={selected?.name || '行业板块详情'} size="wide">
    {!selected ? null : detail.isLoading ? <LoadingState text="正在读取板块详情…"/> : detail.isError ? <ErrorState text="板块详情暂时无法读取。"/> : data && <article className="industry-node-detail">
      <div className="industry-node-heading"><div><p>NODE DETAIL · CACHED SNAPSHOT</p><h2>{data.node.name}</h2><p>{data.node.code || '行业节点'} · 只读数据；页面不会触发 AI 或外部行情请求。</p>{themeBasket(data.node) && <span className="industry-theme-label">Theme Basket · 主题篮子</span>}</div><div className="industry-node-facts"><span><b>{configuredConstituents == null || validConstituents == null ? '数据不足' : `${validConstituents} / ${configuredConstituents}`}</b><small>篮子覆盖</small></span><span><b>{confidenceText(basketConfidence)}</b><small>篮子置信度</small></span></div></div>
      <div className="industry-detail-facts"><div><span>趋势强度</span><b>{scoreText(data.node.pulse)}</b></div><div><span>5 日变化</span><b>{signedText(data.node.change5d)}</b></div><div><span>当前方向</span><b>{moodText(data.node.mood)}</b></div><div><span>映射方式</span><b>{proxyLabel(data.proxyMode)}</b><small>{basketQuality == null ? '覆盖不足' : `${coverageText(basketQuality as number | string | null)} · ${basketHistory == null ? '历史不足' : `${basketHistory} 日历史`}`}</small></div></div>
      <div className="industry-detail-toolbar"><div role="tablist" aria-label="历史范围">{(['30', '90', '365'] as PulseRange[]).map(value => <button type="button" role="tab" aria-selected={range === value} className={range === value ? 'active' : ''} onClick={() => onRange(value)} key={value}>{value}D</button>)}</div><small>按已保存的 Pulse 快照计算</small></div>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>PULSE HISTORY</p><h3>历史状态与趋势</h3></div><small>{data.history.length} 个有效点</small></div><HistoryChart points={data.history}/></section>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>EXTERNAL CONFIRMATION</p><h3>外部 ETF 确认</h3></div><small>不替代代表性股票篮子</small></div><ProxyTable rows={data.etfs}/></section>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>REPRESENTATIVE STOCK BASKET</p><h3>代表性股票篮子</h3></div><small>{themeBasket(data.node) ? 'Theme Basket · 主题篮子' : '分类来源仅用于审核'}；Pulse 使用已启用成员</small></div><ConstituentTable rows={data.constituents}/></section>
      {data.summary && <section className="industry-detail-note"><b>缓存摘要</b><p>{data.summary}</p><small>摘要只解释已保存的确定性结果，不参与 Pulse 计算。</small></section>}
    </article>}
  </Sheet>
}

export function LoadingState({ text }: { text: string }) {
  return <div className="industry-state" aria-busy="true"><span className="industry-state-spinner"/><p>{text}</p></div>
}

export function ErrorState({ text }: { text: string }) {
  return <div className="industry-state industry-state-error" role="alert"><b>数据暂不可用</b><p>{text}</p></div>
}

export function EmptyState({ text }: { text: string }) {
  return <div className="industry-state"><b>暂无可展示数据</b><p>{text}</p></div>
}

export function IndustryPulse({ enabled = true }: { enabled?: boolean }) {
  const [view, setView] = useState<IndustryView>('overview')
  const [selected, setSelected] = useState<PulseRow | null>(null)
  const [range, setRange] = useState<PulseRange>('90')
  const overview = useQuery({ queryKey: ['industry-pulse', 'overview'], queryFn: () => api<unknown>('/industry-pulse/overview'), staleTime: 5 * 60_000, enabled })
  const aiChain = useQuery({ queryKey: ['industry-pulse', 'ai-chain'], queryFn: () => api<unknown>('/industry-pulse/ai-chain'), staleTime: 5 * 60_000, enabled: enabled && view === 'ai-chain' })
  const focus = useQuery({ queryKey: ['industry-pulse', 'focus'], queryFn: () => api<unknown>('/industry-pulse/focus'), staleTime: 5 * 60_000, enabled: enabled && view === 'focus' })
  const taxonomy = useQuery({ queryKey: ['industry-pulse', 'taxonomy'], queryFn: () => api<unknown>('/industry-pulse/taxonomy'), staleTime: 10 * 60_000, enabled: enabled && view === 'taxonomy' })
  const generatedAt = useMemo(() => {
    const value = asText(first(asRecord(overview.data).generated_at, asRecord(overview.data).as_of, asRecord(overview.data).updated_at))
    if (!value) return null
    const parsed = new Date(value)
    return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString('zh-CN') : '时间不足'
  }, [overview.data])
  const showDetail = (row: PulseRow) => { setRange('90'); setSelected(row) }
  return <div className="industry-pulse-page">
    <div className="industry-page-heading"><div><p className="eyebrow">INDUSTRY / SECTOR PULSE</p><h2>行业板块检测</h2><p>用已保存的代表性股票篮子、外部 ETF 确认和确定性指标，观察板块强弱、变化速度与 AI 产业链扩散。</p></div><span className="industry-readonly-badge">只读快照{generatedAt ? ` · ${generatedAt}` : ''}</span></div>
    <div className="industry-view-tabs" role="tablist" aria-label="行业板块视图">{VIEW_TABS.map(([key, label]) => <button type="button" role="tab" aria-selected={view === key} className={view === key ? 'active' : ''} onClick={() => setView(key)} key={key}>{label}</button>)}</div>
    {view === 'overview' && <OverviewView data={overview.data} loading={overview.isLoading} error={overview.isError} onSelect={showDetail}/>}
    {view === 'ai-chain' && <AIChainView data={aiChain.data} loading={aiChain.isLoading} error={aiChain.isError} onSelect={showDetail}/>}
    {view === 'focus' && <FocusView data={focus.data} loading={focus.isLoading} error={focus.isError} onSelect={showDetail}/>}
    {view === 'taxonomy' && <TaxonomyView data={taxonomy.data} loading={taxonomy.isLoading} error={taxonomy.isError} onSelect={showDetail}/>}
    <NodeDetail selected={selected} range={range} onRange={setRange} onClose={() => setSelected(null)}/>
  </div>
}
