import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AreaSeries, ColorType, LineSeries, createChart, type IChartApi, type Time } from 'lightweight-charts'
import { api, post } from './api'
import './quant-backtests.css'

export type QuantInterval = '1h' | '4h' | '1d'
export type QuantSplitMode = 'full' | '60_20_20'

export type QuantStrategyDefinition = {
  key: string
  version: string
  label: string
  description: string
  parameters?: Record<string, unknown>
}

export type QuantInstrumentDefinition = {
  id: number
  display_label: string
  provider_symbol?: string
  kind?: string
  venue?: string
}

export type QuantDefinitions = {
  strategies: QuantStrategyDefinition[]
  instruments: QuantInstrumentDefinition[]
  intervals: QuantInterval[]
  feature_set: Record<string, unknown> | null
  defaults: Record<string, unknown>
  limits: Record<string, number>
}

export type QuantBacktestForm = {
  strategy_key: string
  instrument_ids?: string[]
  /** Compatibility alias for callers that still construct a singleton form. */
  instrument_id?: string
  interval: QuantInterval
  start_date: string
  end_date: string
  target_exposure: string
  initial_capital: string
  leverage: string
  taker_fee_bps: string
  spread_bps: string
  slippage_bps: string
  split_mode: QuantSplitMode
}

export type QuantBacktestRun = {
  id: number
  status: string
  strategy_key?: string | null
  strategy_version?: string | null
  instrument_ids?: number[]
  instrument_id?: number | null
  interval?: string | null
  start_at?: string | null
  end_at?: string | null
  created_at?: string | null
  completed_at?: string | null
  metrics?: Record<string, unknown> | null
  config?: Record<string, unknown> | null
  parameters?: Record<string, unknown> | null
  warnings?: string[]
  manifest_hash?: string | null
  feature_hash?: string | null
  data_hash?: string | null
  code_version?: string | null
  seed?: number | null
  split_mode?: string | null
  initial_capital?: number | string | null
  error?: string | null
  failure_reason?: string | null
}

export type QuantRunList = { items: QuantBacktestRun[]; total: number }
export type QuantEquityPoint = {
  time: string | number
  equity: number | null
  nav?: number | null
  drawdown?: number | null
  exposure?: number | null
  cash?: number | null
}
export type QuantTrade = {
  id?: number | string
  time?: string | null
  instrument_id?: number | null
  side?: string | null
  quantity?: number | null
  price?: number | null
  fee?: number | null
  spread?: number | null
  slippage?: number | null
  funding?: number | null
  reason?: string | null
}

type QueryEnvelope = Record<string, unknown> | null | undefined

const ACTIVE_STATUSES = new Set(['pending', 'running', 'cancel_requested'])
const TERMINAL_STATUSES = new Set(['completed', 'completed_with_warnings', 'failed', 'cancelled', 'canceled'])
const DEFAULT_INTERVALS: QuantInterval[] = ['1h', '4h', '1d']
const FALLBACK_STRATEGIES: QuantStrategyDefinition[] = [
  { key: 'dual-ma-trend-v1', version: 'v1', label: '双均线趋势', description: '使用已保存的技术特征生成目标仓位。' },
  { key: 'rsi-mean-reversion-v1', version: 'v1', label: 'RSI 均值回归', description: '在边界和回归条件满足时调整目标仓位。' },
]

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function firstValue(record: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) if (record[key] !== undefined && record[key] !== null) return record[key]
  return undefined
}

function numberOrNull(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stringOrEmpty(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function normalizeStrategy(value: unknown, index: number): QuantStrategyDefinition | null {
  if (typeof value === 'string') return { key: value, version: 'v1', label: value, description: '' }
  const record = asRecord(value)
  if (!record) return null
  const key = stringOrEmpty(firstValue(record, ['key', 'strategy_key', 'id', 'slug', 'name']))
  if (!key) return null
  return {
    key,
    version: stringOrEmpty(firstValue(record, ['version', 'strategy_version'])) || 'v1',
    label: stringOrEmpty(firstValue(record, ['label', 'display_name', 'name', 'title'])) || `策略 ${index + 1}`,
    description: stringOrEmpty(firstValue(record, ['description', 'description_zh', 'summary'])),
    parameters: asRecord(firstValue(record, ['parameters', 'parameter_schema', 'defaults'])) ?? undefined,
  }
}

function normalizeInstrument(value: unknown): QuantInstrumentDefinition | null {
  const id = numberOrNull(typeof value === 'number' || typeof value === 'string' ? value : asRecord(value)?.id)
  if (id === null || id <= 0) return null
  if (typeof value === 'number' || typeof value === 'string') return { id, display_label: `永续合约 #${id}` }
  const record = asRecord(value) ?? {}
  const label = stringOrEmpty(firstValue(record, ['display_label', 'label', 'display_name', 'symbol', 'provider_symbol'])) || `永续合约 #${id}`
  return {
    id,
    display_label: label,
    provider_symbol: stringOrEmpty(record.provider_symbol) || undefined,
    kind: stringOrEmpty(firstValue(record, ['kind', 'instrument_kind'])) || undefined,
    venue: stringOrEmpty(record.venue) || undefined,
  }
}

/** Convert the backend definitions envelope into the small form contract the page needs. */
export function normalizeQuantDefinitions(value: unknown): QuantDefinitions {
  const record = asRecord(value) ?? {}
  const strategies = asArray(firstValue(record, ['strategies', 'strategy_definitions']))
    .map(normalizeStrategy).filter((item): item is QuantStrategyDefinition => item !== null)
  const instrumentValues = asArray(firstValue(record, ['instruments', 'instrument_definitions', 'instrument_ids']))
  const allInstruments = instrumentValues.map(normalizeInstrument).filter((item): item is QuantInstrumentDefinition => item !== null)
  const perpetual = allInstruments.filter(item => !item.kind || /perpetual|future/i.test(item.kind))
  const intervalValues = asArray(record.intervals).filter((item): item is QuantInterval => DEFAULT_INTERVALS.includes(item as QuantInterval))
  const defaults = asRecord(record.defaults) ?? {}
  const limits = Object.fromEntries(Object.entries(asRecord(record.limits) ?? {}).flatMap(([key, value]) => {
    const parsed = numberOrNull(value)
    return parsed === null ? [] : [[key, parsed]]
  }))
  return {
    strategies: strategies.length ? strategies : FALLBACK_STRATEGIES,
    instruments: perpetual.length ? perpetual : allInstruments,
    intervals: intervalValues.length ? intervalValues : DEFAULT_INTERVALS,
    feature_set: asRecord(record.feature_set),
    defaults,
    limits,
  }
}

export function isBacktestPollingStatus(status: string | null | undefined): boolean {
  return status != null && ACTIVE_STATUSES.has(status)
}

export function isBacktestTerminalStatus(status: string | null | undefined): boolean {
  return status != null && TERMINAL_STATUSES.has(status)
}

export function backtestStatusLabel(status: string | null | undefined): string {
  return ({
    pending: '排队中', running: '运行中', cancel_requested: '正在取消', completed: '已完成',
    completed_with_warnings: '完成但有警告', failed: '失败', cancelled: '已取消', canceled: '已取消',
  } as Record<string, string>)[status || ''] || status || '未知状态'
}

export function validateQuantBacktestForm(form: QuantBacktestForm): string[] {
  const errors: string[] = []
  const instrumentIds = form.instrument_ids?.length ? form.instrument_ids : form.instrument_id ? [form.instrument_id] : []
  const number = (value: string, label: string, minimum: number, maximum?: number) => {
    if (value.trim() === '') { errors.push(`${label}不能为空`); return }
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < minimum || (maximum !== undefined && parsed > maximum)) {
      errors.push(`${label}范围无效`)
    }
  }
  if (!form.strategy_key) errors.push('请选择策略')
  if (instrumentIds.length < 1 || instrumentIds.length > 3 || instrumentIds.some(value => !/^[1-9]\d*$/.test(value))) errors.push('请选择 1–3 个永续合约')
  if (!DEFAULT_INTERVALS.includes(form.interval)) errors.push('周期无效')
  if (!form.start_date || !form.end_date) errors.push('请选择回测区间')
  else {
    const startMs = Date.parse(`${form.start_date}T00:00:00Z`)
    const endMs = Date.parse(`${form.end_date}T00:00:00Z`)
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) errors.push('日期无效')
    else if (startMs >= endMs) errors.push('开始日期必须早于结束日期')
    else if (endMs - startMs > 365 * 86_400_000) errors.push('回测区间不能超过 365 天')
  }
  number(form.target_exposure, '目标仓位', 0.25, 1)
  number(form.initial_capital, '初始资金', 1000, 1_000_000)
  number(form.leverage, '杠杆', 1, 3)
  number(form.taker_fee_bps, 'Taker 费率', 0, 100)
  number(form.spread_bps, '价差', 0, 100)
  number(form.slippage_bps, '滑点', 0, 200)
  if (!['full', '60_20_20'].includes(form.split_mode)) errors.push('数据分段无效')
  return errors
}

export function normalizeRunList(value: unknown): QuantRunList {
  const record = asRecord(value)
  const rows = asArray(record ? firstValue(record, ['items', 'runs', 'backtests']) : value)
  const items = rows.map(normalizeRun).filter((item): item is QuantBacktestRun => item !== null)
  const total = numberOrNull(record && firstValue(record, ['total', 'count'])) ?? items.length
  return { items, total }
}

function normalizeRun(value: unknown): QuantBacktestRun | null {
  const envelope = asRecord(value)
  const record = asRecord(envelope?.run) || asRecord(envelope?.backtest) || envelope
  if (!record) return null
  const id = numberOrNull(firstValue(record, ['id', 'run_id']))
  if (id === null) return null
  const manifest = asRecord(record.manifest)
  const config = asRecord(record.config)
  const instrumentIds = asArray(firstValue(record, ['instrument_ids', 'instruments']) ?? firstValue(manifest || {}, ['instrument_ids', 'instruments']) ?? firstValue(config || {}, ['instrument_ids', 'instruments'])).map(item => numberOrNull(typeof item === 'object' ? asRecord(item)?.id : item)).filter((item): item is number => item !== null)
  const instrumentId = numberOrNull(record.instrument_id)
  const strategy = asRecord(firstValue(record, ['strategy', 'strategy_definition']))
  return {
    id,
    status: stringOrEmpty(record.status),
    strategy_key: stringOrEmpty(firstValue(record, ['strategy_key', 'strategy'])) || stringOrEmpty(strategy && firstValue(strategy, ['strategy_key', 'key', 'name'])) || null,
    strategy_version: stringOrEmpty(record.strategy_version) || stringOrEmpty(strategy?.version) || null,
    instrument_ids: instrumentIds.length ? instrumentIds : instrumentId === null ? [] : [instrumentId],
    instrument_id: instrumentId,
    interval: stringOrEmpty(record.interval) || null,
    start_at: stringOrEmpty(firstValue(record, ['start_at', 'start_date', 'window_start'])) || null,
    end_at: stringOrEmpty(firstValue(record, ['end_at', 'end_date', 'window_end'])) || null,
    created_at: stringOrEmpty(record.created_at) || null,
    completed_at: stringOrEmpty(record.completed_at) || null,
    metrics: asRecord(record.metrics),
    config: asRecord(record.config),
    parameters: asRecord(record.parameters),
    warnings: asArray(record.warnings).map(stringOrEmpty).filter(Boolean),
    manifest_hash: stringOrEmpty(firstValue(record, ['manifest_hash', 'result_hash'])) || null,
    feature_hash: stringOrEmpty(record.feature_hash) || null,
    data_hash: stringOrEmpty(record.data_hash) || null,
    code_version: stringOrEmpty(firstValue(record, ['code_version', 'code_hash'])) || null,
    seed: numberOrNull(record.seed),
    initial_capital: firstValue(record, ['initial_capital', 'capital']) as number | string | null | undefined,
    split_mode: stringOrEmpty(firstValue(record, ['split_mode']) ?? firstValue(config || {}, ['split_mode'])) || null,
    error: stringOrEmpty(firstValue(record, ['error', 'failure_reason', 'error_message'])) || null,
    failure_reason: stringOrEmpty(record.failure_reason) || null,
  }
}

export function normalizeEquityPoints(value: unknown): QuantEquityPoint[] {
  const record = asRecord(value)
  const rows = asArray(record ? firstValue(record, ['items', 'points', 'equity']) : value)
  return rows.flatMap(row => {
    const item = asRecord(row)
    if (!item) return []
    const time = firstValue(item, ['time', 'timestamp', 'at', 'observed_at'])
    if (typeof time !== 'string' && typeof time !== 'number') return []
    const equity = numberOrNull(firstValue(item, ['equity', 'nav', 'value']))
    return [{
      time,
      equity,
      nav: numberOrNull(item.nav),
      drawdown: numberOrNull(item.drawdown),
      exposure: numberOrNull(firstValue(item, ['exposure', 'gross_exposure'])),
      cash: numberOrNull(item.cash),
    }]
  })
}

export function normalizeTrades(value: unknown): QuantTrade[] {
  const record = asRecord(value)
  const rows = asArray(record ? firstValue(record, ['items', 'trades']) : value)
  return rows.flatMap(row => {
    const item = asRecord(row)
    if (!item) return []
    return [{
      id: typeof item.id === 'number' || typeof item.id === 'string' ? item.id : undefined,
      time: stringOrEmpty(firstValue(item, ['time', 'timestamp', 'filled_at', 'fill_time'])) || null,
      instrument_id: numberOrNull(item.instrument_id),
      side: stringOrEmpty(item.side) || null,
      quantity: numberOrNull(firstValue(item, ['quantity', 'qty'])),
      price: numberOrNull(item.price),
      fee: numberOrNull(item.fee),
      spread: numberOrNull(item.spread),
      slippage: numberOrNull(item.slippage),
      funding: numberOrNull(item.funding),
      reason: stringOrEmpty(item.reason) || null,
    }]
  })
}

export function compareRunSelection(ids: number[], candidate: number): number[] {
  if (ids.includes(candidate)) return ids.filter(id => id !== candidate)
  return ids.length >= 4 ? ids : [...ids, candidate]
}

export function backtestActionPath(id: number, action: 'cancel' | 'rerun'): string {
  return `/crypto/quant/backtests/${id}/${action}`
}

export function compareRunsPath(ids: number[]): string {
  return `/crypto/quant/backtests/compare?run_ids=${ids.join(',')}`
}

export function formatQuantNumber(value: unknown, digits = 2): string {
  const parsed = numberOrNull(value)
  return parsed === null ? '数据不足' : parsed.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

export function formatQuantTime(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function utcBoundary(value: string, end = false): string {
  return `${value}T${end ? '23:59:59.999' : '00:00:00.000'}Z`
}

function initialForm(definitions: QuantDefinitions): QuantBacktestForm {
  const today = new Date()
  const start = new Date(today.getTime() - 365 * 86_400_000)
  const date = (value: Date) => value.toISOString().slice(0, 10)
  const defaults = definitions.defaults
  const defaultNumber = (key: string, fallback: string) => numberOrNull(defaults[key]) == null ? fallback : String(defaults[key])
  return {
    strategy_key: definitions.strategies[0]?.key || '',
    instrument_ids: definitions.instruments.slice(0, 3).map(instrument => String(instrument.id)),
    interval: DEFAULT_INTERVALS.includes(defaults.interval as QuantInterval) ? defaults.interval as QuantInterval : definitions.intervals[0] || '1d',
    start_date: date(start), end_date: date(today),
    target_exposure: defaultNumber('target_exposure', '1'), initial_capital: defaultNumber('initial_capital', '10000'),
    leverage: defaultNumber('leverage', '1'), taker_fee_bps: defaultNumber('taker_fee_bps', '4'),
    spread_bps: defaultNumber('spread_bps', '2'), slippage_bps: defaultNumber('slippage_bps', '2'), split_mode: 'full',
  }
}

function metricValue(metrics: Record<string, unknown> | null | undefined, keys: string[]): unknown {
  if (!metrics) return null
  return firstValue(metrics, keys)
}

function runConfigValue(run: QuantBacktestRun, keys: string[]): unknown {
  return firstValue(run.config || {}, keys) ?? firstValue(run.parameters || {}, keys) ?? (keys.includes('initial_capital') ? run.initial_capital : undefined)
}

function QuantChart({ points }: { points: QuantEquityPoint[] }) {
  const hostRef = (node: HTMLDivElement | null) => {
    if (!node || points.length < 2) return
    let chart: IChartApi | null = null
    let observer: ResizeObserver | null = null
    try {
      const computed = getComputedStyle(node)
      const textColor = computed.color
      const accent = computed.getPropertyValue('--accent').trim() || '#397bd8'
      chart = createChart(node, {
        width: Math.max(node.clientWidth, 1), height: 260,
        layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor, fontFamily: 'inherit', fontSize: 11 },
        grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(120,120,128,0.12)' } },
        rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      })
      const toTime = (value: string | number): Time => {
        if (typeof value === 'number') return (value > 2_000_000_000 ? Math.round(value / 1000) : value) as Time
        const parsed = Date.parse(value)
        return (Number.isFinite(parsed) ? Math.round(parsed / 1000) : value) as Time
      }
      const equity = chart.addSeries(AreaSeries, { lineColor: accent, topColor: 'rgba(57,123,216,.22)', bottomColor: 'rgba(57,123,216,.02)', lineWidth: 2, priceLineVisible: false, title: '净值' })
      const drawdown = chart.addSeries(LineSeries, { color: '#d97706', lineWidth: 1, lineStyle: 2, priceScaleId: 'drawdown', priceLineVisible: false, lastValueVisible: false, title: '回撤' })
      chart.priceScale('drawdown').applyOptions({ scaleMargins: { top: .72, bottom: .04 }, borderVisible: false })
      equity.setData(points.filter(item => item.equity != null).map(item => ({ time: toTime(item.time), value: item.equity! })))
      drawdown.setData(points.filter(item => item.drawdown != null).map(item => ({ time: toTime(item.time), value: item.drawdown! })))
      chart.timeScale().fitContent()
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(entries => { const width = entries[0]?.contentRect.width; if (width) chart?.applyOptions({ width }) })
        observer.observe(node)
      }
    } catch (error) {
      console.error('Quant chart render failed', error)
    }
    return () => { observer?.disconnect(); chart?.remove() }
  }
  if (points.length < 2) return <div className="quant-chart-empty">净值数据不足，系统不会用直线填补缺失区间。</div>
  return <div className="quant-equity-chart" ref={hostRef} role="img" aria-label="回测净值与回撤图" />
}

function statusClass(status: string): string {
  return isBacktestPollingStatus(status) ? 'active' : status === 'failed' ? 'failed' : status === 'completed_with_warnings' ? 'warning' : 'done'
}

export function QuantBacktests({ enabled = true }: { enabled?: boolean }) {
  const queryClient = useQueryClient()
  const definitionsQuery = useQuery({ queryKey: ['crypto-quant-definitions'], queryFn: () => api<unknown>('/crypto/quant/definitions'), staleTime: 5 * 60_000, enabled })
  const definitions = useMemo(() => normalizeQuantDefinitions(definitionsQuery.data), [definitionsQuery.data])
  const [form, setForm] = useState<QuantBacktestForm>(() => initialForm(normalizeQuantDefinitions(undefined)))
  const [formReady, setFormReady] = useState(false)
  const [formErrors, setFormErrors] = useState<string[]>([])
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [selectedCompare, setSelectedCompare] = useState<number[]>([])
  const [tradePage, setTradePage] = useState(0)

  // Apply backend defaults once, without overwriting edits after the first response.
  useEffect(() => {
    if (!formReady && definitionsQuery.data) { setForm(initialForm(definitions)); setFormReady(true) }
  }, [definitions, definitionsQuery.data, formReady])
  const runsQuery = useQuery({
    queryKey: ['crypto-quant-backtests'],
    queryFn: () => api<unknown>('/crypto/quant/backtests?limit=30'),
    staleTime: 10_000,
    enabled,
    refetchInterval: query => normalizeRunList(query.state.data).items.some(item => isBacktestPollingStatus(item.status)) ? 8000 : false,
  })
  const runs = useMemo(() => normalizeRunList(runsQuery.data), [runsQuery.data])
  const statusQuery = useQuery({
    queryKey: ['crypto-quant-status'],
    queryFn: () => api<unknown>('/crypto/quant/status'),
    staleTime: 30_000,
    enabled,
    refetchInterval: runs.items.some(item => isBacktestPollingStatus(item.status)) ? 8000 : false,
  })
  const featureQuery = useQuery({ queryKey: ['crypto-quant-features'], queryFn: () => api<unknown>('/crypto/quant/features'), staleTime: 60_000, enabled })
  const selectedRun = runs.items.find(item => item.id === selectedRunId) || null
  const detailQuery = useQuery({ queryKey: ['crypto-quant-backtest', selectedRunId], queryFn: () => api<unknown>(`/crypto/quant/backtests/${selectedRunId}`), enabled: enabled && selectedRunId !== null, staleTime: 15_000,
    refetchInterval: query => { const item = normalizeRun(query.state.data); return item && isBacktestPollingStatus(item.status) ? 8000 : false } })
  const detail = useMemo(() => normalizeRun(detailQuery.data) || selectedRun, [detailQuery.data, selectedRun])
  const equityQuery = useQuery({ queryKey: ['crypto-quant-equity', selectedRunId], queryFn: () => api<unknown>(`/crypto/quant/backtests/${selectedRunId}/equity`), enabled: enabled && selectedRunId !== null && Boolean(detail && !isBacktestPollingStatus(detail.status)), staleTime: 30_000 })
  const tradesQuery = useQuery({ queryKey: ['crypto-quant-trades', selectedRunId, tradePage], queryFn: () => api<unknown>(`/crypto/quant/backtests/${selectedRunId}/trades?limit=25&offset=${tradePage * 25}`), enabled: enabled && selectedRunId !== null && Boolean(detail && !isBacktestPollingStatus(detail.status)), staleTime: 30_000 })
  const compareQuery = useQuery({ queryKey: ['crypto-quant-compare', selectedCompare], queryFn: () => api<unknown>(compareRunsPath(selectedCompare)), enabled: enabled && selectedCompare.length >= 2, staleTime: 30_000 })
  const createMutation = useMutation({ mutationFn: () => {
    const selectedInstrumentIds = form.instrument_ids?.length ? form.instrument_ids : form.instrument_id ? [form.instrument_id] : []
    const values = {
      strategy_key: form.strategy_key, instrument_ids: selectedInstrumentIds.map(Number), interval: form.interval,
      start_at: utcBoundary(form.start_date), end_at: utcBoundary(form.end_date, true), target_exposure: Number(form.target_exposure),
      initial_capital: Number(form.initial_capital), leverage: Number(form.leverage), taker_fee_bps: Number(form.taker_fee_bps),
      spread_bps: Number(form.spread_bps), slippage_bps: Number(form.slippage_bps), split_mode: form.split_mode,
    }
    return post<unknown>('/crypto/quant/backtests', values)
  }, onSuccess: data => {
    const run = normalizeRun(data)
    if (run) setSelectedRunId(run.id)
    queryClient.invalidateQueries({ queryKey: ['crypto-quant-backtests'] })
    queryClient.invalidateQueries({ queryKey: ['crypto-quant-status'] })
  } })
  const actionMutation = useMutation({ mutationFn: ({ id, action }: { id: number; action: 'cancel' | 'rerun' }) => post<unknown>(backtestActionPath(id, action), {}), onSuccess: data => {
    const run = normalizeRun(data); if (run) setSelectedRunId(run.id)
    queryClient.invalidateQueries({ queryKey: ['crypto-quant-backtests'] }); queryClient.invalidateQueries({ queryKey: ['crypto-quant-status'] }); queryClient.invalidateQueries({ queryKey: ['crypto-quant-backtest', selectedRunId] })
  } })

  const update = <K extends keyof QuantBacktestForm>(key: K, value: QuantBacktestForm[K]) => setForm(current => ({ ...current, [key]: value }))
  const toggleInstrument = (value: string) => setForm(current => {
    const selected = current.instrument_ids?.length ? current.instrument_ids : current.instrument_id ? [current.instrument_id] : []
    const next = selected.includes(value) ? selected.filter(item => item !== value) : selected.length >= 3 ? selected : [...selected, value]
    return { ...current, instrument_ids: next, instrument_id: next[0] }
  })
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const errors = validateQuantBacktestForm(form)
    setFormErrors(errors)
    if (!errors.length && enabled) createMutation.mutate()
  }
  const selectedMetrics = detail?.metrics
  const equity = normalizeEquityPoints(equityQuery.data)
  const trades = normalizeTrades(tradesQuery.data)
  const featureRecord = asRecord(featureQuery.data)
  const featureMeta = asRecord(featureRecord && firstValue(featureRecord, ['feature_set'])) || featureRecord
  const statusRecord = asRecord(statusQuery.data)
  const setCompare = (id: number) => setSelectedCompare(current => compareRunSelection(current, id))

  return <div className="quant-backtests-page">
    <section className="quant-hero">
      <div><p className="crypto-eyebrow">QUANT RESEARCH · GOAL 4</p><h2>量化回测</h2><p>只读取已保存的加密市场与特征数据，重放可复现的中频策略。回测不是预测、交易信号或实时行情。</p></div>
      <div className="quant-status-card"><span>运行队列</span><b>{!statusRecord ? '读取中…' : statusRecord.enabled === false ? '已暂停' : numberOrNull(statusRecord.active_runs) ? `${numberOrNull(statusRecord.active_runs)} 个运行中` : stringOrEmpty(firstValue(statusRecord, ['queue_status', 'status', 'label'])) || '可用'}</b><small>{runs.total} 条已保存运行</small></div>
    </section>

    <section className="quant-card quant-config" aria-label="回测配置">
      <header><div><p className="crypto-eyebrow">IMMUTABLE INPUTS</p><h3>创建一次回测</h3></div><span className="quant-muted">不会调用供应商接口</span></header>
      <form onSubmit={submit} noValidate>
        <div className="quant-form-grid">
          <label><span>策略</span><select value={form.strategy_key} onChange={event => update('strategy_key', event.target.value)}><option value="">选择策略</option>{definitions.strategies.slice(0, 2).map(strategy => <option key={`${strategy.key}-${strategy.version}`} value={strategy.key}>{strategy.label} · {strategy.version}</option>)}</select></label>
          <fieldset className="quant-instrument-picker"><legend>永续合约（最多 3 个）</legend>{definitions.instruments.slice(0, 3).map(instrument => <label key={instrument.id}><input type="checkbox" checked={form.instrument_ids?.includes(String(instrument.id)) ?? false} onChange={() => toggleInstrument(String(instrument.id))} /><span>{instrument.display_label}</span></label>)}{!definitions.instruments.length && <small>等待定义同步</small>}</fieldset>
          <label><span>周期</span><select value={form.interval} onChange={event => update('interval', event.target.value as QuantInterval)}>{definitions.intervals.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <label><span>开始日期</span><input type="date" value={form.start_date} onChange={event => update('start_date', event.target.value)} /></label>
          <label><span>结束日期</span><input type="date" value={form.end_date} onChange={event => update('end_date', event.target.value)} /></label>
          <label><span>目标仓位幅度（0.25 至 1）</span><input type="number" inputMode="decimal" min="0.25" max="1" step="0.01" value={form.target_exposure} onChange={event => update('target_exposure', event.target.value)} /></label>
          <label><span>初始资金（USD）</span><input type="number" inputMode="decimal" min="1000" max="1000000" step="any" value={form.initial_capital} onChange={event => update('initial_capital', event.target.value)} /></label>
          <label><span>杠杆（1 至 3 倍）</span><input type="number" inputMode="decimal" min="1" max="3" step="0.1" value={form.leverage} onChange={event => update('leverage', event.target.value)} /></label>
          <label><span>Taker 费率（bps）</span><input type="number" inputMode="decimal" min="0" max="100" step="0.1" value={form.taker_fee_bps} onChange={event => update('taker_fee_bps', event.target.value)} /></label>
          <label><span>价差（bps）</span><input type="number" inputMode="decimal" min="0" max="100" step="0.1" value={form.spread_bps} onChange={event => update('spread_bps', event.target.value)} /></label>
          <label><span>滑点（bps）</span><input type="number" inputMode="decimal" min="0" max="200" step="0.1" value={form.slippage_bps} onChange={event => update('slippage_bps', event.target.value)} /></label>
          <label><span>数据分段</span><select value={form.split_mode} onChange={event => update('split_mode', event.target.value as QuantSplitMode)}><option value="full">全区间</option><option value="60_20_20">60 / 20 / 20（训练 / 验证 / 测试）</option></select></label>
        </div>
        {form.strategy_key && <p className="quant-description">{definitions.strategies.find(item => item.key === form.strategy_key)?.description || '该策略由服务端固定实现。'}</p>}
        {formErrors.map(error => <p className="quant-error" role="alert" key={error}>{error}</p>)}
        {createMutation.error && <p className="quant-error" role="alert">创建失败：{createMutation.error.message}</p>}
        <button className="quant-primary-button" type="submit" disabled={!enabled || createMutation.isPending || definitions.instruments.length === 0}>{createMutation.isPending ? '正在排队…' : '开始回测'}</button>
      </form>
      {definitionsQuery.error && <p className="quant-error" role="alert">定义暂时无法读取：{definitionsQuery.error.message}</p>}
    </section>

    <section className="quant-card quant-assumptions" aria-label="回测假设与数据状态">
      <header><div><p className="crypto-eyebrow">PROVENANCE</p><h3>假设、特征与限制</h3></div></header>
      <div className="quant-info-grid"><div><span>特征集</span><b>{stringOrEmpty(featureMeta && firstValue(featureMeta, ['version', 'feature_set_version', 'status'])) || '数据不足'}</b></div><div><span>特征点</span><b>{formatQuantNumber(featureRecord && firstValue(featureRecord, ['count', 'value_count']), 0)}</b></div><div><span>数据状态</span><b>{stringOrEmpty(featureRecord && firstValue(featureRecord, ['status', 'data_status'])) || '读取中…'}</b></div></div>
      <ul><li>策略只看决策时点以前的已持久化特征，成交按下一根 bar 的因果规则模拟。</li><li>费用、价差、滑点与资金费用按表单配置计入；缺失数据和非适用字段保持为空。</li><li>结果包含 manifest、数据、特征与代码哈希；回测结果不代表未来表现。</li></ul>
      {definitions.feature_set && <p className="quant-muted">特征版本：{stringOrEmpty(firstValue(definitions.feature_set, ['version', 'feature_set_version'])) || '已登记'} · {stringOrEmpty(firstValue(definitions.feature_set, ['hash', 'definition_hash', 'config_hash'])) || '哈希待返回'}</p>}
      {featureQuery.error && <p className="quant-error" role="alert">特征状态暂时无法读取：{featureQuery.error.message}</p>}
      {asArray(featureRecord && firstValue(featureRecord, ['warnings', 'omissions'])).map((warning, index) => <p className="quant-error" role="status" key={`${String(warning)}-${index}`}>{stringOrEmpty(warning)}</p>)}
    </section>

    <section className="quant-card quant-history" aria-label="回测历史">
      <header><div><p className="crypto-eyebrow">RUN HISTORY</p><h3>运行历史</h3></div><small>勾选 2–4 条进行比较</small></header>
      {runsQuery.isLoading && <p className="quant-muted">正在读取运行历史…</p>}
      {runsQuery.error && <p className="quant-error" role="alert">运行历史暂时无法读取：{runsQuery.error.message}</p>}
      {!runsQuery.isLoading && !runs.items.length && <p className="quant-empty">还没有回测运行。</p>}
      <div className="quant-run-list">{runs.items.map(run => <article className={selectedRunId === run.id ? 'selected' : ''} key={run.id}>
        <label className="quant-compare-check"><input type="checkbox" checked={selectedCompare.includes(run.id)} onChange={() => setCompare(run.id)} disabled={!isBacktestTerminalStatus(run.status)} aria-label={`选择运行 ${run.id} 比较`} /><span>比较</span></label>
        <button className="quant-run-main" onClick={() => { setSelectedRunId(run.id); setTradePage(0) }} aria-pressed={selectedRunId === run.id}><b>#{run.id} · {run.strategy_key || '策略未知'}</b><span>{run.instrument_ids?.join(', ') || run.instrument_id || '标的未知'} · {run.interval || '周期未知'}</span><small>{formatQuantTime(run.created_at)} · <i className={`quant-status ${statusClass(run.status)}`}>{backtestStatusLabel(run.status)}</i></small></button>
        <div className="quant-run-actions">{isBacktestPollingStatus(run.status) && <button onClick={() => actionMutation.mutate({ id: run.id, action: 'cancel' })} disabled={actionMutation.isPending}>取消</button>}{isBacktestTerminalStatus(run.status) && <button onClick={() => actionMutation.mutate({ id: run.id, action: 'rerun' })} disabled={actionMutation.isPending}>重新运行</button>}</div>
      </article>)}</div>
      {actionMutation.error && <p className="quant-error" role="alert">操作失败：{actionMutation.error.message}</p>}
      {selectedCompare.length >= 2 && <div className="quant-compare-panel"><header><h4>运行比较</h4><small>{selectedCompare.length} 条</small></header>{compareQuery.isLoading && <p className="quant-muted">正在读取比较结果…</p>}{compareQuery.error && <p className="quant-error" role="alert">比较暂时不可用：{compareQuery.error.message}</p>}{!compareQuery.isLoading && !compareQuery.error && <CompareResult data={compareQuery.data}/>}</div>}
    </section>

    {selectedRunId !== null && <section className="quant-card quant-result" aria-label="回测结果">
      <header><div><p className="crypto-eyebrow">BACKTEST RESULT · #{selectedRunId}</p><h3>{detail?.strategy_key || '回测详情'}</h3></div>{detail && <span className={`quant-status ${statusClass(detail.status)}`}>{backtestStatusLabel(detail.status)}</span>}</header>
      {detailQuery.isLoading && <p className="quant-muted">正在读取回测详情…</p>}
      {detailQuery.error && <p className="quant-error" role="alert">详情暂时无法读取：{detailQuery.error.message}</p>}
      {detail?.error && <p className="quant-error" role="alert">{detail.error}</p>}
      {detail && <><dl className="quant-metrics"><div><dt>总收益率</dt><dd>{formatPercent(metricValue(selectedMetrics, ['total_return', 'return_pct', 'cumulative_return']))}</dd></div><div><dt>年化收益</dt><dd>{formatPercent(metricValue(selectedMetrics, ['annualized_return', 'cagr']))}</dd></div><div><dt>最大回撤</dt><dd>{formatPercent(metricValue(selectedMetrics, ['max_drawdown', 'drawdown']))}</dd></div><div><dt>夏普比率</dt><dd>{formatQuantNumber(metricValue(selectedMetrics, ['sharpe_ratio', 'annualized_sharpe', 'sharpe']), 2)}</dd></div><div><dt>成交次数</dt><dd>{formatQuantNumber(metricValue(selectedMetrics, ['trade_count', 'trades', 'fills']), 0)}</dd></div><div><dt>总费用</dt><dd>{formatQuantNumber(metricValue(selectedMetrics, ['total_fees', 'fees', 'costs']), 2)}</dd></div></dl>
        <div className="quant-manifest"><span>Manifest <b>{detail.manifest_hash || '数据不足'}</b></span><span>数据 <b>{detail.data_hash || '数据不足'}</b></span><span>特征 <b>{detail.feature_hash || '数据不足'}</b></span><span>代码 <b>{detail.code_version || '数据不足'}</b></span></div>
        <div className="quant-result-assumptions"><span>资金 {formatQuantNumber(runConfigValue(detail, ['initial_capital', 'capital']), 2)}</span><span>杠杆 {formatQuantNumber(runConfigValue(detail, ['leverage']), 2)}×</span><span>Taker {formatQuantNumber(runConfigValue(detail, ['taker_fee_bps', 'fee_bps']), 2)} bps</span><span>价差 {formatQuantNumber(runConfigValue(detail, ['spread_bps', 'full_spread_bps']), 2)} bps</span><span>滑点 {formatQuantNumber(runConfigValue(detail, ['slippage_bps']), 2)} bps</span><span>分段 {detail.split_mode === '60_20_20' ? '60 / 20 / 20' : '全区间'}</span></div>
        <SegmentSummary metrics={selectedMetrics} />
        {!!detail.warnings?.length && <div className="quant-warning-list">{detail.warnings.map(warning => <p key={warning}>{warning}</p>)}</div>}
        {!isBacktestPollingStatus(detail.status) && <><QuantChart points={equity}/><div className="quant-trades"><header><h4>模拟成交</h4><small>{tradePage * 25 + 1}–{tradePage * 25 + trades.length}</small></header>{tradesQuery.isLoading && <p className="quant-muted">正在读取成交记录…</p>}{tradesQuery.error && <p className="quant-error" role="alert">成交记录暂时无法读取。</p>}{trades.length > 0 && <div className="quant-trade-table"><div className="quant-trade-head"><span>时间</span><span>方向</span><span>数量</span><span>价格</span><span>费用</span><span>原因</span></div>{trades.map((trade, index) => <div className="quant-trade-row" key={String(trade.id ?? `${trade.time}-${index}`)}><span>{formatQuantTime(trade.time)}</span><span>{trade.side || '—'}</span><span>{formatQuantNumber(trade.quantity, 4)}</span><span>{formatQuantNumber(trade.price, 4)}</span><span>{formatQuantNumber(trade.fee, 4)}</span><span>{trade.reason || '—'}</span></div>)}</div>}{!tradesQuery.isLoading && !trades.length && <p className="quant-empty">暂无模拟成交。</p>}<div className="quant-pagination"><button onClick={() => setTradePage(page => Math.max(0, page - 1))} disabled={tradePage === 0}>上一页</button><span>第 {tradePage + 1} 页</span><button onClick={() => setTradePage(page => page + 1)} disabled={trades.length < 25}>下一页</button></div></div></>}
      </>}
    </section>}
  </div>
}

function formatPercent(value: unknown): string {
  const parsed = numberOrNull(value)
  if (parsed === null) return '数据不足'
  return `${(Math.abs(parsed) <= 2 ? parsed * 100 : parsed).toFixed(2)}%`
}

function CompareResult({ data }: { data: unknown }) {
  const record = asRecord(data)
  const rows = asArray(record ? firstValue(record, ['items', 'runs', 'results']) : data)
  if (!rows.length) return <p className="quant-empty">比较结果不足。</p>
  return <div className="quant-compare-table">{rows.map((value, index) => { const item = asRecord(value) ?? {}; const metrics = asRecord(item.metrics) ?? item; const id = firstValue(item, ['id', 'run_id']) ?? index + 1; return <article key={String(id)}><b>#{String(id)}</b><span>收益 {formatPercent(firstValue(metrics, ['total_return', 'return_pct', 'cumulative_return']))}</span><span>回撤 {formatPercent(firstValue(metrics, ['max_drawdown', 'drawdown']))}</span><span>夏普 {formatQuantNumber(firstValue(metrics, ['sharpe_ratio', 'sharpe']), 2)}</span></article> })}</div>
}

function SegmentSummary({ metrics }: { metrics: Record<string, unknown> | null | undefined }) {
  const segments = asRecord(metrics && metrics.segments)
  if (!segments || !Object.keys(segments).length) return null
  return <div className="quant-segments" aria-label="训练验证测试分段结果">{Object.entries(segments).map(([name, value]) => { const row = asRecord(value) || {}; return <span key={name}><b>{name}</b><small>收益 {formatPercent(firstValue(row, ['return', 'total_return']))} · 回撤 {formatPercent(firstValue(row, ['max_drawdown', 'drawdown']))}</small></span> })}</div>
}

export default QuantBacktests
export const QuantBacktestsPage = QuantBacktests
