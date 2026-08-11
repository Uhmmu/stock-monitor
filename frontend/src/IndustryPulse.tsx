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
  breadth_expansion: '广度扩张', narrow_leadership: '窄幅领涨', internal_confirmation: '内部确认',
}

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
    confidence: first(raw.confidence, raw.confidence_score, raw.data_confidence) as number | string | null ?? null,
    coverage: first(raw.coverage, raw.coverage_quality, raw.data_quality, raw.coverage_percent) as number | string | null ?? null,
    breadth: score(scoreValue(raw, ['breadth', 'breadth_score', 'breadth_percent'])),
    relativeStrength: score(scoreValue(raw, ['relative_strength', 'relative_strength_score', 'rs_score', 'rs'])),
    proxyMode: asText(first(raw.proxy_mode, raw.proxyMode)),
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
const tone = (value: number | null, inverse = false) => value == null ? 'neutral' : inverse ? value >= 70 ? 'negative' : value <= 35 ? 'positive' : 'neutral' : value >= 70 ? 'positive' : value <= 35 ? 'negative' : 'neutral'

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="industry-sparkline-empty">历史不足</span>
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${30 - ((value - min) / span) * 25}`).join(' ')
  return <svg className="industry-sparkline" viewBox="0 0 100 32" role="img" aria-label="板块脉冲历史趋势"><polyline points={points} fill="none" vectorEffect="non-scaling-stroke"/></svg>
}

function ScoreCell({ label, value, inverse = false }: { label: string; value: number | null; inverse?: boolean }) {
  return <div className={`industry-score-cell ${tone(value, inverse)}`}><span>{label}</span><strong>{scoreText(value)}</strong></div>
}

function PulseCard({ row, onSelect, compact = false }: { row: PulseRow; onSelect: (row: PulseRow) => void; compact?: boolean }) {
  return <button type="button" className={`industry-pulse-card${compact ? ' compact' : ''}`} onClick={() => onSelect(row)}>
    <div className="industry-pulse-card-head"><span><b>{row.name}</b>{row.code && <small>{row.code}</small>}</span><em>{row.rank != null ? `#${row.rank}` : moodText(row.mood)}</em></div>
    <div className="industry-pulse-value"><strong>{scoreText(row.pulse)}</strong><span>Pulse</span><small className={row.change5d == null ? '' : row.change5d >= 0 ? 'positive' : 'negative'}>{signedText(row.change5d)} · 5D</small></div>
    {!compact && <Sparkline values={row.sparkline}/>}
    <div className="industry-score-grid four"><ScoreCell label="Breadth" value={row.breadth}/><ScoreCell label="RS" value={row.relativeStrength}/><ScoreCell label="Heat" value={row.heat}/><ScoreCell label="Risk" value={row.risk} inverse/></div>
    <footer><span>{moodText(row.mood)}</span><span>{row.proxyMode || 'Proxy不足'} · {row.constituentCount} 只 · {confidenceText(row.confidence)}</span></footer>
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
  const hottest = [...rows].sort((a, b) => (b.heat ?? -1) - (a.heat ?? -1))[0]
  return <div className="industry-view-content">
    <div className="industry-summary-grid"><SummaryCard label="当前最强" row={strongest} note="当前排名"/><SummaryCard label="升温最快" row={heating} note="Pulse 变化"/><SummaryCard label="热度最高" row={hottest} note="Heat，不等于强度"/></div>
    <section className="industry-section"><div className="industry-section-heading"><div><p>MARKET PULSE</p><h3>一级行业</h3></div><small>{rows.length} 个板块 · 只读快照</small></div><div className="industry-card-grid">{rows.map(row => <PulseCard key={row.id} row={row} onSelect={onSelect}/>)}</div></section>
  </div>
}

function chainGroups(value: unknown): { key: string; label: string; rows: PulseRow[] }[] {
  const record = asRecord(value)
  const source = first(record.groups, record.layers, record.sections, record.nodes)
  if (Array.isArray(source)) {
    const grouped = source.map((group, index) => {
      const item = asRecord(group)
      return { key: String(first(item.id, item.key, item.slug, index)), label: String(first(item.name_zh, item.label_zh, item.name, item.label, `产业链 ${index + 1}`)), rows: responseRows(item) }
    }).filter(group => group.rows.length)
    if (grouped.length) return grouped
  }
  const object = asRecord(source)
  return Object.entries(object).map(([key, rows]) => ({ key, label: MOOD_LABELS[key] || key, rows: responseRows(rows) })).filter(group => group.rows.length)
}

function AIChainView({ data, loading, error, onSelect }: { data: unknown; loading: boolean; error: boolean; onSelect: (row: PulseRow) => void }) {
  if (loading) return <LoadingState text="正在读取 AI 产业链快照…" />
  if (error) return <ErrorState text="AI 产业链快照暂时无法读取。" />
  const groups = chainGroups(data)
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
  return <div className="industry-view-content">
    <section className="industry-chain-banner"><div><p>AI TRADE STRUCTURE</p><h3>AI 产业链状态</h3><p>以下为板块行为与节点扩散信号，不是新闻情绪，也不是资金流入/流出记录。</p></div><div className="industry-chain-facts"><span><b>{concentrationValue}</b><small>{asText(first(concentration.label_zh, concentration.label)) || '链条集中度'}</small></span><span><b>{scoreText(chainBreadth)}</b><small>链条广度 · {strongNodes}/{eligibleNodes}</small></span></div></section>
    <div className="industry-coverage-grid"><span><b>{asNumber(coverage.calculable_nodes) ?? availableGroups ?? 0}/{asNumber(coverage.total_nodes) ?? totalGroups ?? 0}</b><small>可计算节点</small></span><span><b>{asNumber(coverage.direct_etf_nodes) ?? 0}</b><small>ETF</small></span><span><b>{asNumber(coverage.hybrid_nodes) ?? 0}</b><small>Hybrid</small></span><span><b>{asNumber(coverage.equity_basket_nodes) ?? 0}</b><small>Basket</small></span><span><b>{asNumber(confidence.high) ?? 0}/{asNumber(confidence.medium) ?? 0}/{asNumber(confidence.low) ?? 0}</b><small>高 / 中 / 低置信度</small></span></div>
    <p className="industry-signal-note"><b>覆盖口径</b>ETF、股票篮子与 Hybrid 分开统计；链条广度使用 {strongNodes}/{eligibleNodes} 个 eligible 节点。{propagationText ? ` ${propagationText}${propagationFrontier ? ` · 当前前沿：${propagationFrontier}` : ''}` : ''}</p>
    <div className="industry-chain-grid">{groups.map(group => <section className="industry-chain-group" key={group.key}><div className="industry-section-heading"><div><p>CHAIN NODE</p><h3>{group.label}</h3></div><small>{group.rows.length} 个节点</small></div><div className="industry-chain-nodes">{group.rows.map(row => <PulseCard key={row.id} row={row} onSelect={onSelect} compact/>)}</div></section>)}</div>
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
  return <div className="industry-view-content"><p className="industry-signal-note"><b>信号口径</b>这些分组由价格、趋势、相对强度、成交量和波动变化推导；不代表真实资金流向，也不是买入或卖出建议。</p><div className="industry-focus-grid">{buckets.map(bucket => <section className="industry-focus-bucket" key={bucket.key}><div className="industry-section-heading"><div><p>FOCUS SIGNAL</p><h3>{bucket.label}</h3></div><small>{bucket.rows.length} 个</small></div><div className="industry-focus-list">{bucket.rows.slice(0, 8).map(row => <FocusNote key={row.id} row={row} onSelect={onSelect}/>)}</div></section>)}</div></div>
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

type DetailData = { node: PulseRow; history: { date: string; value: number }[]; etfs: JsonRecord[]; constituents: JsonRecord[]; breadth: JsonRecord; proxyMode: string | null; summary: string | null; relative: JsonRecord }

function detailData(value: unknown, fallback: PulseRow): DetailData {
  const record = asRecord(value)
  const rawNode = first(record.node, record.detail, record.item, value)
  const node = normalizePulseRow(rawNode, 0)
  const historyRows = pickArray(record, ['history', 'pulse_history', 'snapshots', 'series'])
  const history = historyRows.map(item => {
    const row = asRecord(item)
    return { date: String(first(row.date, row.trading_date, row.as_of, row.observation_date, '')), value: scoreValue(row, ['pulse', 'pulse_score', 'score', 'value']) ?? NaN }
  }).filter(item => item.date && Number.isFinite(item.value))
  const etfs = pickArray(record, ['etfs', 'proxies', 'instruments', 'proxy_etfs']).map(asRecord).filter(item => Object.keys(item).length)
  const constituents = pickArray(record, ['constituents', 'basket_members']).map(asRecord).filter(item => Object.keys(item).length)
  const breadth = asRecord(record.breadth)
  const relative = asRecord(first(record.relative_strength, record.relative, record.benchmark_comparison))
  return { node: node.id === 'node-0' && fallback.id !== 'node-0' ? fallback : node, history, etfs, constituents, breadth, proxyMode: asText(first(record.proxy_mode, node.proxyMode)), summary: asText(first(record.ai_summary, record.summary, record.narrative)), relative }
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
  return <div className="industry-constituent-table"><div className="industry-constituent-head"><span>股票</span><span>角色 / 来源</span><span>权重</span><span>5D / 20D</span><span>RS / MA20</span><span>成交量</span></div>{rows.map((row, index) => {
    const weight = asNumber(row.weight); const r5 = asNumber(row.return_5d); const r20 = asNumber(row.return_20d); const rs = asNumber(row.rs_20d); const volume = asNumber(row.relative_volume)
    return <div className="industry-constituent-row" key={`${String(first(row.ticker, index))}-${index}`}><b>{String(first(row.ticker, '—'))}</b><span>{String(first(row.role, '—'))}<small>{String(first(row.classification_source, '—'))}</small></span><span>{weight == null ? '—' : `${(weight * 100).toFixed(1)}%`}</span><span>{signedText(r5)}<small>{signedText(r20)}</small></span><span>{rs == null ? '—' : signedText(rs)}<small>{row.above_ma20 === true ? 'MA20 上方' : row.above_ma20 === false ? 'MA20 下方' : 'MA20不足'}</small></span><span>{volume == null ? '—' : `${volume.toFixed(2)}x`}</span></div>
  })}</div>
}

function NodeDetail({ selected, range, onRange, onClose }: { selected: PulseRow | null; range: PulseRange; onRange: (range: PulseRange) => void; onClose: () => void }) {
  const detail = useQuery({ queryKey: ['industry-pulse', 'node', selected?.id, range], queryFn: () => api<unknown>(`/industry-pulse/nodes/${encodeURIComponent(selected!.id)}?range=${range}`), enabled: selected !== null, staleTime: 5 * 60_000 })
  const data = selected && detail.data ? detailData(detail.data, selected) : selected ? { node: selected, history: [], etfs: [], constituents: [], breadth: {}, proxyMode: selected.proxyMode, summary: null, relative: {} } : null
  const relativeBenchmarks = data ? [...new Set(['SPY', 'QQQ', ...Object.keys(data.relative)])] : ['SPY', 'QQQ']
  return <Sheet open={selected !== null} onClose={onClose} title={selected?.name || '行业板块详情'} size="wide">
    {!selected ? null : detail.isLoading ? <LoadingState text="正在读取板块详情…"/> : detail.isError ? <ErrorState text="板块详情暂时无法读取。"/> : data && <article className="industry-node-detail">
      <div className="industry-node-heading"><div><p>NODE DETAIL · CACHED SNAPSHOT</p><h2>{data.node.name}</h2><p>{data.node.code || '行业节点'} · 只读数据；页面不会触发 AI 或外部行情请求。</p></div><div className="industry-node-facts"><span><b>{coverageText(data.node.coverage)}</b><small>覆盖</small></span><span><b>{confidenceText(data.node.confidence)}</b><small>置信度</small></span></div></div>
      <div className="industry-detail-score-grid"><ScoreCell label="Pulse" value={data.node.pulse}/><ScoreCell label="Strength" value={data.node.strength ?? data.node.pulse}/><ScoreCell label="Heat" value={data.node.heat}/><ScoreCell label="Risk" value={data.node.risk} inverse/></div>
      <div className="industry-detail-facts"><div><span>状态</span><b>{moodText(data.node.mood)}</b></div><div><span>Proxy</span><b>{data.proxyMode || '数据不足'}</b></div><div><span>Breadth</span><b>{scoreText(data.node.breadth)}</b></div><div><span>成分股</span><b>{data.constituents.length}</b></div></div>
      <div className="industry-breadth-grid">{[['MA20', 'above_ma20'], ['MA50', 'above_ma50'], ['5D 正收益', 'positive_5d'], ['20D 正收益', 'positive_20d'], ['RS 改善', 'improving_rs'], ['量能扩张', 'expanding_volume']].map(([label, key]) => <span key={key}><b>{asNumber(data.breadth[`${key}_count`]) ?? 0} / {asNumber(data.breadth[`${key}_eligible`]) ?? 0}</b><small>{label}</small></span>)}</div>
      <div className="industry-detail-toolbar"><div role="tablist" aria-label="历史范围">{(['30', '90', '365'] as PulseRange[]).map(value => <button type="button" role="tab" aria-selected={range === value} className={range === value ? 'active' : ''} onClick={() => onRange(value)} key={value}>{value}D</button>)}</div><small>按已保存的 Pulse 快照计算</small></div>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>PULSE HISTORY</p><h3>历史状态与趋势</h3></div><small>{data.history.length} 个有效点</small></div><HistoryChart points={data.history}/></section>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>BENCHMARK COMPARISON</p><h3>相对强度</h3></div><small>SPY / QQQ / 一级板块基准</small></div><div className="industry-relative-grid">{relativeBenchmarks.map(label => {
        const item = asRecord(first(data.relative[label], data.relative[label.toLowerCase()]))
        const value = asNumber(first(item.rs_20d, item.value, data.relative[label], data.relative[label.toLowerCase()]))
        return <div key={label}><span>{label}</span><b>{value === null ? '数据不足' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`}</b><small>相对回报 / 走势由后端快照提供</small></div>
      })}</div></section>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>ETF PROXIES</p><h3>ETF 行情代理</h3></div><small>Role / Purity / Data status</small></div><ProxyTable rows={data.etfs}/></section>
      <section className="industry-detail-section"><div className="industry-section-heading"><div><p>SYNTHETIC EQUITY BASKET</p><h3>代表股票与内部状态</h3></div><small>分类来源仅用于审核；Pulse 使用已启用成员</small></div><ConstituentTable rows={data.constituents}/></section>
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
    <div className="industry-page-heading"><div><p className="eyebrow">INDUSTRY / SECTOR PULSE</p><h2>行业板块检测</h2><p>用已保存的行业分类、ETF 代理和确定性指标，观察板块强弱、变化速度与 AI 产业链扩散。</p></div><span className="industry-readonly-badge">只读快照{generatedAt ? ` · ${generatedAt}` : ''}</span></div>
    <div className="industry-view-tabs" role="tablist" aria-label="行业板块视图">{VIEW_TABS.map(([key, label]) => <button type="button" role="tab" aria-selected={view === key} className={view === key ? 'active' : ''} onClick={() => setView(key)} key={key}>{label}</button>)}</div>
    {view === 'overview' && <OverviewView data={overview.data} loading={overview.isLoading} error={overview.isError} onSelect={showDetail}/>}
    {view === 'ai-chain' && <AIChainView data={aiChain.data} loading={aiChain.isLoading} error={aiChain.isError} onSelect={showDetail}/>}
    {view === 'focus' && <FocusView data={focus.data} loading={focus.isLoading} error={focus.isError} onSelect={showDetail}/>}
    {view === 'taxonomy' && <TaxonomyView data={taxonomy.data} loading={taxonomy.isLoading} error={taxonomy.isError} onSelect={showDetail}/>}
    <NodeDetail selected={selected} range={range} onRange={setRange} onClose={() => setSelected(null)}/>
  </div>
}
