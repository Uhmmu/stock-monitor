import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { GlassCard, IOSPage, LoadingState, NavigationBar, SectionHeader, StateView, StatusPill } from '../components'
import './options.css'

type Json = Record<string, unknown>
type OptionsState = Json & { activity?: unknown; bias?: unknown; risk_pricing?: unknown; positioning?: unknown; historical_regime?: unknown }
type OptionRow = {
  symbol: string; name: string | null; sector: string | null; status: string | null; price: number | null; expiration: string | null; dte: number | null; atmIv: number | null; ivChange: number | null; pcVolume: number | null; pcOi: number | null; callVolume: number | null; putVolume: number | null; callOi: number | null; putOi: number | null; skew: number | null; activity: number | null; totalVolume: number | null; volume20dAverage: number | null; nearTermIv: number | null; activityLevel: string | null; optionsBias: string | null; biasStatus: string | null; optionsState: OptionsState | null; historicalComparison: Json | null; updatedAt: string | null; provider: string | null; quality: Json
}
type Sector = { sector: string; primary: OptionRow | null; secondary: OptionRow[] }
type Overview = { status: string | null; asOf: string | null; market: OptionRow[]; sectors: Sector[]; watchlist: OptionRow[]; sync: Json | null }
type Point = Json & { x?: string | number | null; y?: number | null; value?: number | null; date?: string | null; time?: string | number | null; comparison?: Json | null; anomaly_direction?: string | null; trend_direction?: string | null }
type Detail = OptionRow & { expirations: (string | Json)[]; chain: Json[]; term: Point[]; oi: Point[]; volume: Point[]; history: Point[] }

const record = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {}
const array = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const pick = (row: Json, keys: string[]) => keys.map(key => row[key]).find(value => value != null)
const text = (value: unknown) => typeof value === 'string' && value.trim() ? value.trim() : value == null ? null : String(value)
const num = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : typeof value === 'string' && value.trim() && Number.isFinite(Number(value)) ? Number(value) : null
const asPercent = (value: number | null) => value == null ? '数据不足' : `${(Math.abs(value) <= 2 ? value * 100 : value).toFixed(1)}%`
const asRatio = (value: number | null) => value == null ? '数据不足' : `${value.toFixed(2)}×`
const asCompact = (value: number | null) => value == null ? '数据不足' : Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
const status = (value: string | null) => ({ OK: '已更新', READY: '已更新', PARTIAL: '部分覆盖', DEGRADED: '部分可用', NO_OPTIONS: '无可用期权', NO_DATA: '数据不足', STALE: '缓存较旧', STALE_DATA: '缓存较旧', ERROR: '读取失败', PROVIDER_ERROR: '数据源错误', NO_VALID_EXPIRATION: '无有效到期日', INSUFFICIENT_LIQUIDITY: '流动性不足', INSUFFICIENT_HISTORY: '历史数据不足', INSUFFICIENT_HISTORY_DATA: '历史数据不足' } as Record<string, string>)[String(value || '').toUpperCase()] || value || '状态未知'
const statusTone = (value: string | null): 'positive' | 'warning' | 'negative' | 'neutral' => ['OK', 'READY'].includes(String(value || '').toUpperCase()) ? 'positive' : ['NO_OPTIONS', 'NO_DATA', 'ERROR', 'PROVIDER_ERROR'].includes(String(value || '').toUpperCase()) ? 'negative' : ['PARTIAL', 'DEGRADED', 'STALE', 'STALE_DATA', 'NO_VALID_EXPIRATION', 'INSUFFICIENT_LIQUIDITY', 'INSUFFICIENT_HISTORY', 'INSUFFICIENT_HISTORY_DATA'].includes(String(value || '').toUpperCase()) ? 'warning' : 'neutral'
const stateLabels: Record<string, string> = { low: '低', normal: '正常', elevated: '偏高', high: '高', extreme: '极高', insufficient_history: '历史不足', insufficient_history_data: '历史不足', insufficient_data: '数据不足', ready: '可用', partial: '部分可用', positive: '偏正', negative: '偏负', neutral: '中性', mixed: '混合', call_heavy: 'Call 偏重', put_heavy: 'Put 偏重', balanced: '相对平衡' }
const stateText = (value: unknown): string => { if (value && typeof value === 'object' && !Array.isArray(value)) { const item = record(value); return stateText(pick(item, ['status', 'label', 'value', 'state']) ?? pick(record(item.raw_metrics), ['status', 'label'])) } const raw = text(value); return raw ? (stateLabels[raw.toLowerCase()] || raw.replace(/_/g, ' ')) : 'N/A' }

export function normalizeOptionRow(value: unknown): OptionRow {
  const item = record(value)
  return {
    symbol: String(pick(item, ['symbol', 'ticker', 'underlying']) ?? ''), name: text(pick(item, ['name', 'company_name', 'display_name'])), sector: text(pick(item, ['sector', 'primary_sector'])), status: text(pick(item, ['status', 'data_status'])), price: num(pick(item, ['underlying_price', 'price', 'current_price'])), expiration: text(pick(item, ['nearest_expiration', 'expiration'])), dte: num(pick(item, ['dte', 'days_to_expiration'])), atmIv: num(pick(item, ['atm_iv', 'at_the_money_iv'])), ivChange: num(pick(item, ['iv_change', 'atm_iv_change'])), pcVolume: num(pick(item, ['put_call_volume_ratio', 'put_call_ratio_volume', 'pc_volume'])), pcOi: num(pick(item, ['put_call_oi_ratio', 'put_call_ratio_oi', 'pc_oi'])), callVolume: num(pick(item, ['call_volume', 'calls_volume'])), putVolume: num(pick(item, ['put_volume', 'puts_volume'])), callOi: num(pick(item, ['call_oi', 'calls_open_interest'])), putOi: num(pick(item, ['put_oi', 'puts_open_interest'])), skew: num(pick(item, ['downside_skew', 'skew'])), activity: num(pick(item, ['activity_score', 'score'])), totalVolume: num(pick(item, ['total_volume', 'volume'])), volume20dAverage: num(pick(item, ['volume_20d_average', 'average_20d', 'avg_20d_volume'])), nearTermIv: num(pick(item, ['near_term_iv', 'front_iv', 'short_term_iv'])), activityLevel: text(pick(item, ['activity_level', 'activity'])), optionsBias: text(pick(item, ['options_bias', 'bias'])), biasStatus: text(pick(item, ['bias_status'])), optionsState: (() => { const state = pick(item, ['options_state', 'option_state', 'state']); return state && typeof state === 'object' && !Array.isArray(state) ? record(state) as OptionsState : null })(), historicalComparison: (() => { const comparison = pick(item, ['historical_comparison', 'history_comparison', 'comparisons']); return comparison && typeof comparison === 'object' && !Array.isArray(comparison) ? record(comparison) : null })(), updatedAt: text(pick(item, ['updated_at', 'as_of', 'fetched_at'])), provider: text(pick(item, ['provider', 'source'])), quality: record(item.quality),
  }
}

const row = normalizeOptionRow

function overview(value: unknown): Overview {
  const source = record(value)
  return {
    status: text(source.status), asOf: text(pick(source, ['as_of', 'updated_at'])), market: array(source.market).map(row).filter(item => item.symbol), watchlist: array(source.watchlist).map(row).filter(item => item.symbol),
    sectors: array(source.sectors).map(item => { const sector = record(item); const primary = sector.primary == null ? null : row(sector.primary); return { sector: String(pick(sector, ['sector', 'name', 'label']) ?? '未分类行业'), primary: primary?.symbol ? primary : null, secondary: array(sector.secondary).map(row).filter(item => item.symbol) } }).filter(item => item.primary || item.secondary.length),
    sync: source.sync == null ? null : record(source.sync),
  }
}

export function normalizeOptionsDetail(value: unknown): Detail {
  const source = record(value); const base = row(source.summary ?? source)
  const points = (key: string, fallback?: string) => array(source[key] ?? (fallback ? source[fallback] : undefined)).map(item => { const point = record(item); return { ...point, date: text(pick(point, ['date', 'time', 'trading_date', 'x'])), x: pick(point, ['x', 'date', 'time', 'trading_date']) as string | number | null | undefined, y: num(pick(point, ['y', 'value', 'metric_value'])), value: num(pick(point, ['value', 'y', 'metric_value'])), comparison: point.comparison != null ? record(point.comparison) : point.historical_comparison != null ? record(point.historical_comparison) : null, anomaly_direction: text(pick(point, ['anomaly_direction', 'activity_anomaly_direction', 'anomaly'])), trend_direction: text(pick(point, ['trend_direction', 'trend'])) } })
  const chain = Array.isArray(source.chain) ? source.chain : Object.values(record(source.chain)).flatMap(value => array(value))
  return { ...base, expirations: array(source.expirations).map(item => typeof item === 'string' ? item : record(item)), chain: chain.map(item => record(item)), term: points('term_structure', 'expiration_structure'), oi: points('oi_distribution'), volume: points('volume_distribution'), history: points('history') }
}

const detail = normalizeOptionsDetail

const metricValue = (key: string, value: number | null) => value == null ? 'N/A' : key === 'atmIv' || key === 'skew' ? asPercent(value) : key === 'pcVolume' || key === 'pcOi' ? asRatio(value) : asCompact(value)
const signed = (key: string, value: number | null) => value == null ? 'N/A' : `${value >= 0 ? '+' : '-'}${metricValue(key, Math.abs(value))}`
const historyMetric = (key: string) => key === 'average_20d' ? 'activity' : key === 'put_call_volume_ratio' || key === 'pcVolume' ? 'put_call' : key === 'put_call_oi_ratio' || key === 'pcOi' ? 'put_call_oi' : key === 'atm_iv' || key === 'atmIv' ? 'iv' : key === 'downside_skew' || key === 'skew' ? 'skew' : key === 'total_volume' ? 'total_volume' : 'activity'
const comparisonFor = (item: OptionRow, key: string, current: number | null) => {
  const root = item.historicalComparison || {}
  const metricKey = historyMetric(key)
  const source = record(root[key] || {})
  const changes = record(record(root.changes)[metricKey])
  const averages = record(record(root.averages)[metricKey])
  const fallback = record(pick(root, [key, metricKey]))
  const candidate = Object.keys(source).length ? source : fallback
  const latest = num(pick(candidate, ['current', 'latest', 'value'])) ?? current
  const average7 = num(averages['7']); const average20 = num(averages['20'])
  return { current: latest, previous: num(pick(candidate, ['previous', 'previous_value', 'value_1d'])) ?? (latest != null && num(changes['1']) != null ? latest - num(changes['1'])! : null), change1d: num(pick(candidate, ['change_1d', 'delta_1d'])) ?? num(changes['1']), change7d: num(pick(candidate, ['change_7d', 'delta_7d'])) ?? (latest != null && average7 != null ? latest - average7 : null), change20d: num(pick(candidate, ['change_20d', 'delta_20d'])) ?? num(changes['20']) ?? (latest != null && average20 != null ? latest - average20 : null) }
}

function MobileStateGrid({ item }: { item: OptionRow }) {
  const entries = [['activity', '活跃度', item.optionsState?.activity ?? item.activityLevel], ['bias', '偏向', item.optionsState?.bias ?? item.optionsBias ?? item.biasStatus], ['risk_pricing', '风险定价', item.optionsState?.risk_pricing], ['positioning', '持仓结构', item.optionsState?.positioning], ['historical_regime', '历史状态', item.optionsState?.historical_regime]] as const
  return <div className="mobile-option-state-grid">{entries.map(([key, label, value]) => <div key={key}><span>{label}</span><b>{stateText(value)}</b></div>)}</div>
}

function MobileComparison({ item }: { item: OptionRow }) {
  const entries = [['activity', '活跃度', item.activity ?? item.totalVolume], ['atmIv', 'ATM IV', item.atmIv], ['pcVolume', 'P/C 成交', item.pcVolume], ['skew', '下行偏斜', item.skew]] as const
  const hasAny = entries.some(([key, , current]) => { const comparison = comparisonFor(item, key, current); return comparison.current != null || comparison.previous != null || comparison.change1d != null || comparison.change7d != null || comparison.change20d != null })
  if (!hasAny) return <div className="mobile-option-comparison-empty">历史对比：历史不足</div>
  return <div className="mobile-option-comparison" aria-label="当前与历史变化">{entries.map(([key, label, current]) => { const comparison = comparisonFor(item, key, current); if (comparison.current == null && comparison.previous == null && comparison.change1d == null && comparison.change7d == null && comparison.change20d == null) return null; return <div key={key}><span>{label}</span><b>{metricValue(key, comparison.current)}</b><small>1D {signed(key, comparison.change1d)} · 7D {signed(key, comparison.change7d)} · 20D {signed(key, comparison.change20d)}</small></div> })}</div>
}

function MobileOptionCard({ item, onOpen }: { item: OptionRow; onOpen: (symbol: string) => void }) {
  return <button className="mobile-option-card" type="button" onClick={() => onOpen(item.symbol)}><div className="mobile-option-head"><div><strong>{item.symbol}</strong><small>{item.name || '期权标的'}</small></div><StatusPill tone={statusTone(item.status)}>{status(item.status)}</StatusPill></div><div className="mobile-option-price"><b>{item.price == null ? '数据不足' : `$${item.price.toFixed(2)}`}</b><span>{item.expiration || '期限不可用'}{item.dte == null ? '' : ` · ${item.dte} 天`}</span></div><div className="mobile-option-grid"><div><span>ATM IV</span><b>{asPercent(item.atmIv)}</b></div><div><span>P/C 成交</span><b>{asRatio(item.pcVolume)}</b></div><div><span>活跃度</span><b>{item.activity == null ? '数据不足' : item.activity.toFixed(0)}</b></div><div><span>下行偏斜</span><b>{asPercent(item.skew)}</b></div></div><MobileStateGrid item={item}/><MobileComparison item={item}/><footer><span>{item.provider || '来源不可用'}</span><time>{item.updatedAt ? item.updatedAt.slice(0, 16).replace('T', ' ') : '时间不可用'}</time></footer></button>
}

function MobileSparkline({ points, label }: { points: Point[]; label: string }) {
  const values = points.map(point => num(point.y ?? point.value ?? pick(point, ['atm_iv', 'iv', 'open_interest', 'oi', 'volume', 'activity_score']) ?? (typeof point.x === 'number' ? point.x : null))).filter((value): value is number => value != null)
  if (!values.length) return <div className="mobile-option-chart-empty">{label}：数据不足</div>
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const pointsText = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${100 - ((value - min) / span) * 86 - 7}`).join(' ')
  return <figure className="mobile-option-chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={label}><polyline points={pointsText}/></svg><figcaption>{label}<b>{values.at(-1)?.toFixed(2)}</b></figcaption></figure>
}

type MobileChartSeries = { key: string; label: string; aliases?: string[] }
const pointDate = (point: Point) => {
  const raw = point.date ?? point.time ?? point.x
  if (typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10)
  if (typeof raw === 'number' && Number.isFinite(raw)) return new Date((raw < 2_000_000_000 ? raw * 1000 : raw)).toISOString().slice(0, 10)
  const parsed = raw == null ? NaN : Date.parse(String(raw)); return Number.isFinite(parsed) ? new Date(parsed).toISOString().slice(0, 10) : null
}
const pointValue = (point: Point, series: MobileChartSeries) => { const source = record(point.comparison); const metric = historyMetric(series.key); return num(pick(point, [series.key, ...(series.aliases || [])])) ?? num(pick(source, [series.key, ...(series.aliases || [])])) ?? (series.key === 'average_20d' ? num(pick(record(record(source.averages)[metric]), ['20'])) : null) ?? (series.key === 'value' ? num(point.value ?? point.y) : null) }
const dailyPoints = (points: Point[], series: MobileChartSeries) => {
  const values = new Map<string, { date: string; value: number; point: Point }>()
  points.forEach(point => { const date = pointDate(point); const value = pointValue(point, series); if (date && value != null) values.set(date, { date, value, point }) })
  return [...values.values()].sort((a, b) => a.date.localeCompare(b.date))
}
const chartText = (series: MobileChartSeries, value: number | null) => value == null ? 'N/A' : series.key.includes('iv') || series.key.includes('skew') ? asPercent(value) : series.key.includes('ratio') ? asRatio(value) : asCompact(value)
const pointComparison = (point: Point, series: MobileChartSeries, current?: number | null) => {
  const source = record(point.comparison); const metric = historyMetric(series.key); const changes = record(record(source.changes)[metric]); const averages = record(record(source.averages)[metric]); const statistics = record(record(source.statistics)[metric]); const selected = record(statistics[String(num(pick(statistics, ['selected_window'])) || 20)]); const anomalies = record(record(source.metric_anomalies)[metric]); const change1d = num(changes['1']);
  return { previous: num(pick(source, ['previous', 'previous_value'])) ?? (current != null && change1d != null ? current - change1d : null), average: num(averages['20']) ?? num(averages['7']), percentile: num(selected.percentile), zscore: num(selected.zscore), anomaly: text(pick(anomalies, ['direction', 'status'])) }
}
const anomalyDirection = (point: Point, series: MobileChartSeries) => { const value = String(pointComparison(point, series).anomaly || point.anomaly_direction || '').toLowerCase(); return ['up', 'rise', 'increase', 'positive', '↑'].includes(value) ? '↑' : ['down', 'fall', 'decrease', 'negative', '↓'].includes(value) ? '↓' : null }

function MobileDailyChart({ title, points, primary, secondary }: { title: string; points: Point[]; primary: MobileChartSeries; secondary?: MobileChartSeries }) {
  const primaryPoints = dailyPoints(points, primary)
  const secondaryPoints = secondary ? dailyPoints(points, secondary) : []
  const values = primaryPoints.map(item => item.value).concat(secondaryPoints.map(item => item.value))
  const min = values.length ? Math.min(...values) : 0; const max = values.length ? Math.max(...values) : 1; const span = max - min || 1
  const x = (index: number, length: number) => 8 + (index / Math.max(length - 1, 1)) * 84
  const y = (value: number) => 86 - ((value - min) / span) * 67
  const labels = primaryPoints.length ? [primaryPoints[0], primaryPoints[Math.floor((primaryPoints.length - 1) / 2)], primaryPoints.at(-1)].filter((item, index, array): item is typeof primaryPoints[number] => !!item && array.findIndex(candidate => candidate?.date === item.date) === index) : []
  return <figure className="mobile-option-daily-chart" aria-label={title}><div className="mobile-option-daily-head"><strong>{title}</strong><small>{primary.label}{secondary ? ` · ${secondary.label}` : ''}</small></div>{!primaryPoints.length ? <div className="mobile-option-chart-empty">{title}：历史不足</div> : <><svg viewBox="0 0 100 112" role="img" aria-label={`${title}每日历史`}><line x1="8" y1="87" x2="92" y2="87" className="mobile-option-axis"/><polyline points={primaryPoints.map((item, index) => `${x(index, primaryPoints.length)},${y(item.value)}`).join(' ')} className="mobile-option-daily-line primary"/>{secondary && secondaryPoints.length > 0 && <polyline points={secondaryPoints.map((item, index) => `${x(index, secondaryPoints.length)},${y(item.value)}`).join(' ')} className="mobile-option-daily-line secondary"/>}{primaryPoints.map((item, index) => { const marker = anomalyDirection(item.point, primary); const comparison = pointComparison(item.point, primary, item.value); return <g key={item.date}><title>{`${item.date} ${primary.label} ${chartText(primary, item.value)}${marker ? ` 异常方向 ${marker}` : ''}${comparison.previous != null ? ` 上一日 ${chartText(primary, comparison.previous)}` : ''}${comparison.average != null ? ` 滚动均值 ${chartText(primary, comparison.average)}` : ''}${comparison.percentile != null ? ` 分位 ${comparison.percentile.toFixed(0)}%` : ''}${comparison.zscore != null ? ` Z ${comparison.zscore.toFixed(2)}` : ''}`}</title><circle cx={x(index, primaryPoints.length)} cy={y(item.value)} r="1.9" className="mobile-option-daily-point"/><text x={x(index, primaryPoints.length)} y={marker ? y(item.value) - 5 : y(item.value) - 3} className={marker ? 'mobile-option-anomaly' : 'mobile-option-trend-placeholder'}>{marker || ''}</text></g> })}{labels.map(item => <text key={`label-${item.date}`} x={x(primaryPoints.findIndex(candidate => candidate.date === item.date), primaryPoints.length)} y="103" textAnchor="middle" className="mobile-option-date-label">{item.date.slice(5)}</text>)}</svg><div className="mobile-option-daily-summary" role="status"><span>{primaryPoints.at(-1)?.date}</span><b>{chartText(primary, primaryPoints.at(-1)?.value ?? null)}</b>{anomalyDirection(primaryPoints.at(-1)!.point, primary) && <small>异常 {anomalyDirection(primaryPoints.at(-1)!.point, primary)}</small>}</div></>}</figure>
}

function OptionsDetailPage({ symbol, back }: { symbol: string; back: () => void }) {
  const [expiration, setExpiration] = useState('')
  const [chainType, setChainType] = useState<'call' | 'put'>('call')
  const query = useQuery({ queryKey: ['ios-options-detail', symbol, expiration], queryFn: () => api<unknown>(`/options/symbols/${encodeURIComponent(symbol)}${expiration ? `?expiration=${encodeURIComponent(expiration)}` : ''}`), enabled: !!symbol, staleTime: 60_000 })
  const data = query.data ? detail(query.data) : null
  const expirationValue = (item: string | Json) => typeof item === 'string' ? item : text(pick(item, ['expiration', 'date', 'value'])) || ''
  return <><NavigationBar title={`${symbol} 期权`} eyebrow="OPTIONS DETAIL" back={back}/><IOSPage className="options-mobile-page detail-page"><div className="mobile-options-heading"><div><span>OPTIONS DETAIL</span><h1>{symbol}</h1><p>{data?.name || '标的名称暂缺'} · {data?.sector || '行业数据不足'}</p></div>{data && <StatusPill tone={statusTone(data.status)}>{status(data.status)}</StatusPill>}</div>{query.isLoading && <LoadingState rows={7}/>} {query.isError && <StateView title="期权详情暂不可用" message="已保存的摘要和链暂时无法读取。" retry={() => { void query.refetch() }}/>} {data && <><GlassCard className="mobile-options-summary"><div className="mobile-options-detail-grid"><div><span>标的价格</span><b>{data.price == null ? '数据不足' : `$${data.price.toFixed(2)}`}</b></div><div><span>ATM IV</span><b>{asPercent(data.atmIv)}</b></div><div><span>P/C 成交量</span><b>{asRatio(data.pcVolume)}</b></div><div><span>P/C 持仓量</span><b>{asRatio(data.pcOi)}</b></div><div><span>总成交量</span><b>{asCompact(data.totalVolume ?? ((data.callVolume || 0) + (data.putVolume || 0) || null))}</b></div><div><span>活跃度</span><b>{data.activity == null ? '数据不足' : data.activity.toFixed(0)}</b></div></div><MobileStateGrid item={data}/><MobileComparison item={data}/></GlassCard><SectionHeader title="期限结构" caption="选择已保存到期日"/><div className="mobile-option-expirations">{data.expirations.slice(0, 10).map(item => <button type="button" className={expirationValue(item) === expiration ? 'active' : ''} key={expirationValue(item)} onClick={() => setExpiration(expirationValue(item))}>{expirationValue(item) || '数据不足'}</button>)}{!data.expirations.length && <span>期限数据不足</span>}</div><SectionHeader title="合约链" caption="只读已保存合约，不构成交易终端" action={<div className="mobile-option-toggle"><button type="button" className={chainType === 'call' ? 'active' : ''} onClick={() => setChainType('call')}>Calls</button><button type="button" className={chainType === 'put' ? 'active' : ''} onClick={() => setChainType('put')}>Puts</button></div>}/><div className="mobile-option-chain">{data.chain.filter(item => { const type = String(pick(item, ['option_type', 'type']) || '').toLowerCase(); return type ? type.includes(chainType) || (chainType === 'call' ? ['c', 'calls'].includes(type) : ['p', 'puts'].includes(type)) : true }).slice(0, 40).map((item, index) => <div key={String(pick(item, ['contractSymbol', 'contract_symbol']) || index)}><b>{num(pick(item, ['strike']))?.toFixed(2) || '—'}</b><span>IV {asPercent(num(pick(item, ['impliedVolatility', 'implied_volatility'])))}</span><span>量 {asCompact(num(item.volume))}</span><span>OI {asCompact(num(pick(item, ['openInterest', 'open_interest'])))}</span><strong>{num(pick(item, ['lastPrice', 'last_price'])) == null ? '—' : `$${num(pick(item, ['lastPrice', 'last_price']))!.toFixed(2)}`}</strong></div>)}{!data.chain.length && <div className="mobile-option-chart-empty">合约数据不足</div>}</div><SectionHeader title="每日历史" caption="日期、异常方向与滚动上下文"/><div className="mobile-option-daily-charts"><MobileDailyChart title="成交活动" points={data.history} primary={{ key: 'total_volume', aliases: ['volume', 'activity_score'], label: '总成交量' }} secondary={{ key: 'average_20d', aliases: ['avg_20d', 'volume_20d_average'], label: '20D 均值' }}/><MobileDailyChart title="成交量与持仓量结构" points={data.history} primary={{ key: 'put_call_volume_ratio', aliases: ['pc_volume'], label: 'P/C 成交量' }} secondary={{ key: 'put_call_oi_ratio', aliases: ['pc_oi'], label: 'P/C 持仓量' }}/><MobileDailyChart title="ATM 波动率" points={data.history} primary={{ key: 'atm_iv', aliases: ['iv'], label: 'ATM IV' }} secondary={{ key: 'near_term_iv', aliases: ['front_iv', 'short_term_iv'], label: '近月 IV' }}/><MobileDailyChart title="下行偏斜" points={data.history} primary={{ key: 'downside_skew', aliases: ['skew'], label: '下行偏斜' }}/></div><div className="mobile-option-charts mobile-option-distribution-charts"><MobileSparkline label="ATM IV / 期限" points={data.term}/><MobileSparkline label="持仓量分布" points={data.oi}/><MobileSparkline label="成交量分布" points={data.volume}/></div><p className="mobile-options-note">期权活跃度描述成交与持仓活动，不代表涨跌概率或交易建议。缺失指标保持“数据不足”。</p></>}</IOSPage></>
}

function OptionsOverviewPage({ back, openDetail }: { back?: () => void; openDetail?: (symbol: string) => void }) {
  const overviewQuery = useQuery({ queryKey: ['ios-options-overview'], queryFn: () => api<unknown>('/options/overview?ranking=activity'), staleTime: 60_000, refetchInterval: 5 * 60_000 })
  const data = overviewQuery.data ? overview(overviewQuery.data) : null
  const [segment, setSegment] = useState<'market' | 'sector' | 'watchlist'>('market')
  const groups = useMemo(() => data?.watchlist.reduce<Record<string, OptionRow[]>>((result, item) => { const key = item.sector || '未分类行业'; (result[key] ||= []).push(item); return result }, {}) || {}, [data?.watchlist])
  const open = (item: OptionRow) => item.symbol && openDetail?.(item.symbol)
  return <><NavigationBar title="期权研究" eyebrow="OPTIONS" back={back}/><IOSPage className="options-mobile-page"><section className="mobile-options-hero"><span>OPTIONS RESEARCH</span><h1>期权在为哪些风险定价</h1><p>用 ETF 和自选股的已保存指标观察波动率、期限、成交和持仓。信息用于研究，不构成交易建议。</p><small>{data?.asOf ? `快照 ${data.asOf.slice(0, 16).replace('T', ' ')}` : '等待同步'}</small></section>{overviewQuery.isLoading && <LoadingState rows={8}/>} {overviewQuery.isError && <StateView title="期权研究暂不可用" message="概览接口没有返回有效数据。" retry={() => { void overviewQuery.refetch() }}/>} {data && <>{data.status && <div className="mobile-options-status"><StatusPill tone={statusTone(data.status)}>{status(data.status)}</StatusPill><span>{String(data.status).toUpperCase() === 'NO_OPTIONS' ? '当前覆盖范围没有可用期权链，系统不会用行情替代。' : '已有字段会保留，缺失指标显示数据不足。'}</span></div>}<div className="segmented-control options-mobile-segments"><button type="button" className={segment === 'market' ? 'active' : ''} onClick={() => setSegment('market')}>市场</button><button type="button" className={segment === 'sector' ? 'active' : ''} onClick={() => setSegment('sector')}>行业</button><button type="button" className={segment === 'watchlist' ? 'active' : ''} onClick={() => setSegment('watchlist')}>自选股</button></div>{segment === 'market' && <><SectionHeader title="市场 ETF" caption="SPY · QQQ · IWM"/><div className="mobile-options-list">{data.market.map(item => <MobileOptionCard item={item} onOpen={symbol => open(row({ symbol }))} key={item.symbol}/>) }{!data.market.length && <StateView title={status(data.status)} message="市场 ETF 期权摘要暂不可用。"/>}</div></>}{segment === 'sector' && <><SectionHeader title="一级行业代理" caption="Primary 与 secondary 分开展示"/><div className="mobile-options-sector-list">{data.sectors.map(item => <GlassCard key={item.sector}><div className="mobile-options-sector-head"><div><strong>{item.sector}</strong><small>{item.primary?.symbol || 'Primary 数据不足'}</small></div>{item.primary && <StatusPill tone={statusTone(item.primary.status)}>{status(item.primary.status)}</StatusPill>}</div>{item.primary && <MobileOptionCard item={item.primary} onOpen={symbol => open(row({ symbol }))}/>} {!item.primary && <p className="mobile-options-muted">Primary ETF 数据不足</p>}{item.secondary.map(secondary => <button className="mobile-options-secondary" type="button" key={secondary.symbol} onClick={() => open(secondary)}><b>{secondary.symbol}</b><span>{secondary.name || 'secondary proxy'}</span><em>{asPercent(secondary.atmIv)}</em></button>)}</GlassCard>)}{!data.sectors.length && <StateView title="行业覆盖不足" message="当前没有可用的一级行业期权代理。"/>}</div></>}{segment === 'watchlist' && <><SectionHeader title="自选股期权" caption={data.watchlist.length ? `${data.watchlist.length} 只已覆盖` : '只展示当前自选股'}/>{Object.entries(groups).map(([name, items]) => <section className="mobile-options-watch-group" key={name}><h3>{name}</h3><div className="mobile-options-list">{items.map(item => <MobileOptionCard item={item} onOpen={symbol => open(row({ symbol }))} key={item.symbol}/>)}</div></section>)}{!data.watchlist.length && <StateView title="暂无自选股期权" message="自选股可能没有可用期权链，或仍在等待首次同步。"/>}</>}</>}</IOSPage></>
}

export const normalizeOptionsOverview = overview
export const optionStatusLabel = status

export function OptionsPage({ back, openDetail, symbol = '' }: { back?: () => void; openDetail?: (symbol: string) => void; symbol?: string }) {
  return symbol ? <OptionsDetailPage symbol={symbol} back={back || (() => undefined)}/> : <OptionsOverviewPage back={back} openDetail={openDetail}/>
}
