import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { Sheet } from './Sheet'
import './options.css'

type Json = Record<string, unknown>

export type OptionQuality = {
  level?: string | null
  score?: number | null
  coverage?: number | string | null
  warnings?: string[]
}

export type OptionRow = {
  symbol: string
  name: string | null
  asset_type: string | null
  sector: string | null
  industry: string | null
  user_group: string | null
  status: string | null
  underlying_price: number | null
  nearest_expiration: string | null
  dte: number | null
  atm_iv: number | null
  iv_change: number | null
  put_call_volume_ratio: number | null
  put_call_oi_ratio: number | null
  call_volume: number | null
  put_volume: number | null
  call_oi: number | null
  put_oi: number | null
  downside_skew: number | null
  activity_level: string | null
  activity_score: number | null
  quality: OptionQuality
  updated_at: string | null
  provider: string | null
}

export type OptionSector = { sector: string; primary: OptionRow | null; secondary: OptionRow[] }
export type OptionsOverview = {
  as_of: string | null
  status: string | null
  market: OptionRow[]
  sectors: OptionSector[]
  watchlist: OptionRow[]
  rankings: Record<string, OptionRow[]>
  sync: Json | null
}

export type OptionChainRow = Json & {
  strike?: number | null
  option_type?: string | null
  type?: string | null
  impliedVolatility?: number | null
  implied_volatility?: number | null
  openInterest?: number | null
  open_interest?: number | null
  volume?: number | null
  lastPrice?: number | null
  last_price?: number | null
}

export type OptionPoint = Json & { x?: string | number | null; y?: number | null; value?: number | null; label?: string | null }
export type OptionsDetail = OptionRow & {
  expirations: (string | Json)[]
  term_structure: OptionPoint[]
  oi_distribution: OptionPoint[]
  volume_distribution: OptionPoint[]
  chain: OptionChainRow[]
  history: OptionPoint[]
}

const asRecord = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {}
const asArray = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const pick = (record: Json, keys: string[]) => keys.map(key => record[key]).find(value => value !== undefined && value !== null)
const text = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value.trim() : value == null ? null : String(value)
const number = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : typeof value === 'string' && value.trim() && Number.isFinite(Number(value)) ? Number(value) : null

const quality = (value: unknown): OptionQuality => {
  const row = asRecord(value)
  return {
    level: text(pick(row, ['level', 'status'])),
    score: number(pick(row, ['score', 'quality_score'])),
    coverage: number(pick(row, ['coverage', 'coverage_percent'])) ?? text(pick(row, ['coverage', 'coverage_percent'])),
    warnings: asArray(row.warnings).map(item => text(item)).filter((item): item is string => !!item),
  }
}

export function normalizeOptionRow(value: unknown): OptionRow {
  const row = asRecord(value)
  return {
    symbol: String(pick(row, ['symbol', 'ticker', 'underlying']) ?? ''),
    name: text(pick(row, ['name', 'company_name', 'display_name'])),
    asset_type: text(pick(row, ['asset_type', 'instrument_type'])),
    sector: text(pick(row, ['sector', 'primary_sector'])),
    industry: text(pick(row, ['industry', 'primary_industry'])),
    user_group: text(pick(row, ['user_group', 'group_name'])),
    status: text(pick(row, ['status', 'data_status'])),
    underlying_price: number(pick(row, ['underlying_price', 'price', 'current_price'])),
    nearest_expiration: text(pick(row, ['nearest_expiration', 'expiration'])),
    dte: number(pick(row, ['dte', 'days_to_expiration'])),
    atm_iv: number(pick(row, ['atm_iv', 'at_the_money_iv'])),
    iv_change: number(pick(row, ['iv_change', 'atm_iv_change'])),
    put_call_volume_ratio: number(pick(row, ['put_call_volume_ratio', 'put_call_ratio_volume', 'pc_volume'])),
    put_call_oi_ratio: number(pick(row, ['put_call_oi_ratio', 'put_call_ratio_oi', 'pc_oi'])),
    call_volume: number(pick(row, ['call_volume', 'calls_volume'])),
    put_volume: number(pick(row, ['put_volume', 'puts_volume'])),
    call_oi: number(pick(row, ['call_oi', 'calls_open_interest'])),
    put_oi: number(pick(row, ['put_oi', 'puts_open_interest'])),
    downside_skew: number(pick(row, ['downside_skew', 'skew'])),
    activity_level: text(pick(row, ['activity_level', 'activity'])),
    activity_score: number(pick(row, ['activity_score', 'score'])),
    quality: quality(row.quality),
    updated_at: text(pick(row, ['updated_at', 'as_of', 'fetched_at'])),
    provider: text(pick(row, ['provider', 'source'])),
  }
}

const rowArray = (value: unknown) => asArray(value).map(normalizeOptionRow).filter(row => row.symbol)

export function normalizeOptionsOverview(value: unknown): OptionsOverview {
  const source = asRecord(value)
  const rawSectors = asArray(source.sectors)
  const sectors = rawSectors.map(item => {
    const row = asRecord(item)
    const primary = row.primary == null ? null : normalizeOptionRow(row.primary)
    return {
      sector: String(pick(row, ['sector', 'name', 'label']) ?? '未分类行业'),
      primary: primary?.symbol ? primary : null,
      secondary: rowArray(row.secondary),
    }
  }).filter(item => item.primary || item.secondary.length)
  const rankingsSource = asRecord(source.rankings)
  return {
    as_of: text(pick(source, ['as_of', 'updated_at'])),
    status: text(source.status),
    market: rowArray(source.market),
    sectors,
    watchlist: rowArray(source.watchlist),
    rankings: Object.fromEntries(Object.entries(rankingsSource).map(([key, rows]) => [key, rowArray(rows)])),
    sync: source.sync == null ? null : asRecord(source.sync),
  }
}

export function normalizeOptionsDetail(value: unknown): OptionsDetail {
  const source = asRecord(value)
  const base = normalizeOptionRow(source.summary ?? source)
  const points = (key: string, fallback?: string) => asArray(source[key] ?? (fallback ? source[fallback] : undefined)).map(item => asRecord(item) as OptionPoint)
  const chain = Array.isArray(source.chain) ? source.chain : Object.values(asRecord(source.chain)).flatMap(value => asArray(value))
  return {
    ...base,
    expirations: asArray(source.expirations).map(item => typeof item === 'string' ? item : asRecord(item)),
    term_structure: points('term_structure', 'expiration_structure'),
    oi_distribution: points('oi_distribution'),
    volume_distribution: points('volume_distribution'),
    chain: chain.map(item => asRecord(item) as OptionChainRow),
    history: points('history'),
  }
}

export const statusLabel = (status: string | null | undefined) => ({
  OK: '已更新', READY: '已更新', PARTIAL: '部分覆盖', DEGRADED: '部分可用', NO_OPTIONS: '无可用期权', NO_DATA: '数据不足', STALE: '缓存较旧', STALE_DATA: '缓存较旧', ERROR: '读取失败', PROVIDER_ERROR: '数据源错误', NO_VALID_EXPIRATION: '无有效到期日', INSUFFICIENT_LIQUIDITY: '流动性不足', INSUFFICIENT_HISTORY: '历史数据不足', INSUFFICIENT_HISTORY_DATA: '历史数据不足',
} as Record<string, string>)[String(status || '').toUpperCase()] || (status || '状态未知')

const metricLabels: Record<string, string> = {
  activity: '活跃度', activity_score: '活跃度', atm_iv: 'ATM IV', iv: 'ATM IV', iv_change: 'IV 变化',
  put_call_volume_ratio: 'Put / Call 成交量', put_call_oi_ratio: 'Put / Call 持仓量', downside_skew: '下行偏斜',
}
const rankFields: Record<string, keyof OptionRow> = {
  activity: 'activity_score', activity_score: 'activity_score', atm_iv: 'atm_iv', iv: 'atm_iv', iv_change: 'iv_change',
  put_call_volume: 'put_call_volume_ratio', put_call_volume_ratio: 'put_call_volume_ratio', put_call_oi: 'put_call_oi_ratio', put_call_oi_ratio: 'put_call_oi_ratio', call_activity: 'call_volume', put_activity: 'put_volume', downside_skew: 'downside_skew',
}

export const rankingLabel = (key: string) => metricLabels[key] || key

export function sortOptionRows(rows: OptionRow[], ranking: string): OptionRow[] {
  const field = rankFields[ranking]
  if (!field) return rows
  return [...rows].sort((a, b) => (number(b[field]) ?? -Infinity) - (number(a[field]) ?? -Infinity))
}

const percent = (value: number | null, digits = 1) => value == null ? '数据不足' : `${(value * (Math.abs(value) <= 2 ? 100 : 1)).toFixed(digits)}%`
const ratio = (value: number | null) => value == null ? '数据不足' : `${value.toFixed(2)}×`
const compact = (value: number | null) => value == null ? '数据不足' : Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
const price = (value: number | null) => value == null ? '数据不足' : `$${value.toFixed(2)}`
const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '时间不可用'

function QualityBadge({ row }: { row: OptionRow }) {
  const level = row.status || row.quality.level
  return <span className={`options-quality ${String(level || '').toLowerCase()}`}>{statusLabel(level)}</span>
}

function Metric({ label, value, tone = '' }: { label: string; value: React.ReactNode; tone?: string }) {
  return <div className={`options-metric ${tone}`}><span>{label}</span><b>{value}</b></div>
}

function OptionCard({ row, onOpen, compact: isCompact = false }: { row: OptionRow; onOpen: (symbol: string) => void; compact?: boolean }) {
  const unavailable = ['NO_OPTIONS', 'NO_DATA', 'ERROR'].includes(String(row.status || '').toUpperCase())
  return <button type="button" className={`options-card${isCompact ? ' compact' : ''}${unavailable ? ' unavailable' : ''}`} onClick={() => row.symbol && onOpen(row.symbol)} disabled={!row.symbol}>
    <div className="options-card-head"><div><strong>{row.symbol || '未命名标的'}</strong><small>{row.name || row.asset_type || '期权标的'}</small></div><QualityBadge row={row}/></div>
    <div className="options-card-price"><b>{price(row.underlying_price)}</b><span>{row.nearest_expiration || '期限不可用'}{row.dte != null ? ` · ${row.dte} 天` : ''}</span></div>
    <div className="options-card-metrics"><Metric label="ATM IV" value={percent(row.atm_iv)}/><Metric label="P/C 成交" value={ratio(row.put_call_volume_ratio)}/><Metric label="活跃度" value={row.activity_score == null ? '数据不足' : `${row.activity_score.toFixed(0)} / 100`}/><Metric label="下行偏斜" value={percent(row.downside_skew)}/></div>
    <footer><span>{row.provider || '来源不可用'}</span><time>{date(row.updated_at)}</time></footer>
  </button>
}

function EmptyState({ title, message, retry }: { title: string; message: string; retry?: () => void }) {
  return <div className="options-state" role={retry ? 'alert' : undefined}><strong>{title}</strong><p>{message}</p>{retry && <button type="button" onClick={retry}>重新加载</button>}</div>
}

function Sparkline({ points, label }: { points: OptionPoint[]; label: string }) {
  const values = points.map(point => number(point.y ?? point.value ?? pick(point, ['atm_iv', 'iv', 'open_interest', 'oi', 'volume', 'activity_score']) ?? (typeof point.x === 'number' ? point.x : null))).filter((item): item is number => item != null)
  if (!values.length) return <div className="options-chart-empty">{label}：数据不足</div>
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const coords = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${100 - ((value - min) / span) * 86 - 7}`).join(' ')
  return <figure className="options-chart"><svg viewBox="0 0 100 100" role="img" aria-label={label} preserveAspectRatio="none"><polyline points={coords}/></svg><figcaption><span>{label}</span><b>{values.at(-1)?.toFixed(2)}</b></figcaption></figure>
}

function DetailMetricGrid({ data }: { data: OptionsDetail }) {
  return <div className="options-detail-metrics"><Metric label="标的价格" value={price(data.underlying_price)}/><Metric label="ATM IV" value={percent(data.atm_iv)}/><Metric label="P/C 成交量" value={ratio(data.put_call_volume_ratio)}/><Metric label="P/C 持仓量" value={ratio(data.put_call_oi_ratio)}/><Metric label="总成交量" value={compact((data.call_volume || 0) + (data.put_volume || 0) || null)}/><Metric label="活跃度" value={data.activity_score == null ? '数据不足' : `${data.activity_score.toFixed(0)} / 100`}/></div>
}

function ChainTable({ rows, type }: { rows: OptionChainRow[]; type: 'call' | 'put' }) {
  const matches = rows.filter(row => {
    const optionType = String(row.option_type ?? row.type ?? '').toLowerCase()
    return optionType ? optionType.includes(type) || (type === 'call' ? ['c', 'calls'].includes(optionType) : ['p', 'puts'].includes(optionType)) : true
  }).slice(0, 80)
  if (!matches.length) return <div className="options-chart-empty">{type === 'call' ? 'Call' : 'Put'} 合约数据不足。</div>
  const value = (row: OptionChainRow, keys: string[]) => number(pick(row, keys))
  return <div className="options-chain-wrap"><table className="options-chain"><thead><tr><th>行权价</th><th>IV</th><th>成交量</th><th>持仓量</th><th>最新价</th></tr></thead><tbody>{matches.map((row, index) => <tr key={`${String(row.contractSymbol || row.contract_symbol || index)}`}><td>{value(row, ['strike'])?.toFixed(2) || '数据不足'}</td><td>{percent(value(row, ['impliedVolatility', 'implied_volatility']))}</td><td>{compact(value(row, ['volume']))}</td><td>{compact(value(row, ['openInterest', 'open_interest']))}</td><td>{price(value(row, ['lastPrice', 'last_price']))}</td></tr>)}</tbody></table></div>
}

function OptionsDetailSheet({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const [expiration, setExpiration] = useState('')
  const [chainType, setChainType] = useState<'call' | 'put'>('call')
  const detail = useQuery({ queryKey: ['options-detail', symbol, expiration], queryFn: () => api<unknown>(`/options/symbols/${encodeURIComponent(symbol || '')}${expiration ? `?expiration=${encodeURIComponent(expiration)}` : ''}`), enabled: !!symbol, staleTime: 60_000 })
  const data = detail.data ? normalizeOptionsDetail(detail.data) : null
  const expirations = data?.expirations || []
  const expValue = (item: string | Json) => typeof item === 'string' ? item : text(pick(item, ['expiration', 'date', 'value'])) || ''
  return <Sheet open={!!symbol} onClose={onClose} title={symbol ? `${symbol} · 期权研究` : '期权研究'} size="wide">
    {detail.isLoading && <EmptyState title="正在读取期权详情" message="仅加载已保存的摘要、链和历史快照。"/>}
    {detail.isError && <EmptyState title="期权详情暂不可用" message="上游没有返回有效数据，稍后可以重试。" retry={() => { void detail.refetch() }}/>}
    {data && <article className="options-detail">
      <header className="options-detail-heading"><div><p className="options-eyebrow">OPTIONS DETAIL</p><h2>{data.symbol}</h2><p>{data.name || '标的名称暂缺'} · {data.sector || '行业数据不足'} · {data.provider || '来源不可用'}</p></div><QualityBadge row={data}/></header>
      <DetailMetricGrid data={data}/>
      <section className="options-detail-section"><div className="options-section-title"><div><h3>期限结构</h3><small>选择已保存的到期日查看链</small></div><select aria-label="选择期权到期日" value={expiration || expValue(expirations[0] || '')} onChange={event => setExpiration(event.target.value)}><option value="">最近期限</option>{expirations.map(item => <option value={expValue(item)} key={expValue(item)}>{expValue(item)}</option>)}</select></div><div className="options-expiration-strip">{expirations.slice(0, 8).map(item => <button type="button" className={expValue(item) === expiration ? 'active' : ''} key={expValue(item)} onClick={() => setExpiration(expValue(item))}>{expValue(item) || '数据不足'}</button>)}{!expirations.length && <span>期限数据不足</span>}</div></section>
      <section className="options-detail-section"><div className="options-section-title"><div><h3>Call / Put 链</h3><small>仅展示已保存的前 80 条合约，非交易终端</small></div><div className="options-toggle"><button type="button" className={chainType === 'call' ? 'active' : ''} onClick={() => setChainType('call')}>Calls</button><button type="button" className={chainType === 'put' ? 'active' : ''} onClick={() => setChainType('put')}>Puts</button></div></div><ChainTable rows={data.chain} type={chainType}/></section>
      <div className="options-chart-grid"><Sparkline label="ATM IV / 期限结构" points={data.term_structure}/><Sparkline label="持仓量分布" points={data.oi_distribution}/><Sparkline label="成交量分布" points={data.volume_distribution}/><Sparkline label="历史快照" points={data.history}/></div>
      <p className="options-detail-note">期权活跃度描述成交与持仓活动，不代表涨跌概率或交易建议。缺失指标保持“数据不足”。</p>
    </article>}
  </Sheet>
}

const sectionRows = (sector: OptionSector) => [sector.primary, ...sector.secondary].filter((row): row is OptionRow => !!row)

export function OptionsPage({ enabled = true }: { enabled?: boolean }) {
  const [ranking, setRanking] = useState('activity')
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const overview = useQuery({ queryKey: ['options-overview', ranking], queryFn: () => api<unknown>(`/options/overview?ranking=${encodeURIComponent(ranking)}`), staleTime: 60_000, refetchInterval: 5 * 60_000, enabled })
  const data = overview.data ? normalizeOptionsOverview(overview.data) : null
  const market = data ? sortOptionRows(data.market, ranking) : []
  const sectors = data ? data.sectors.map(sector => ({ ...sector, rows: sortOptionRows(sectionRows(sector), ranking) })) : []
  const watchlist = data ? sortOptionRows(data.watchlist, ranking) : []
  const groupedWatchlist = useMemo(() => watchlist.reduce<Record<string, OptionRow[]>>((groups, row) => { const key = row.sector || '未分类行业'; (groups[key] ||= []).push(row); return groups }, {}), [watchlist])
  return <div className="options-page">
    <section className="options-hero"><div><p className="options-eyebrow">OPTIONS RESEARCH · 期权研究</p><h2>看见市场在为哪些风险付费</h2><p>用已保存的 ETF 与自选股期权指标观察期限、波动率、成交和持仓。这里只呈现证据，不给出交易建议。</p></div><div className="options-hero-meta"><span>快照时间</span><b>{data?.as_of ? date(data.as_of) : '等待同步'}</b><small>{data?.sync ? text(pick(data.sync, ['status_label', 'status'])) || '同步状态未知' : '来源状态未知'}</small></div></section>
    <div className="options-toolbar" role="toolbar" aria-label="期权排序"><label>排序<select value={ranking} onChange={event => setRanking(event.target.value)}><option value="activity">活跃度最高</option><option value="iv">ATM IV 最高</option><option value="iv_change">IV 变化</option><option value="put_call_volume">Put / Call 成交量</option><option value="put_call_oi">Put / Call 持仓量</option><option value="call_activity">Call 成交量</option><option value="put_activity">Put 成交量</option><option value="downside_skew">下行偏斜</option></select></label><span>{data ? `${market.length + watchlist.length} 个已覆盖标的` : '数据同步中'}</span></div>
    {overview.isLoading && <EmptyState title="正在读取期权研究" message="正在读取市场、行业和自选股的已保存摘要。"/>}
    {!enabled && <EmptyState title="演示预览未加载期权数据" message="连接账户后读取已保存的市场、行业和自选股期权摘要。"/>}
    {overview.isError && <EmptyState title="期权研究暂不可用" message="期权概览接口没有返回有效数据，请稍后重试。" retry={() => { void overview.refetch() }}/>}
    {data && <>
      {data.status && !['OK', 'READY'].includes(data.status.toUpperCase()) && <div className="options-status-banner"><strong>{statusLabel(data.status)}</strong><span>{data.status.toUpperCase() === 'NO_OPTIONS' ? '当前覆盖范围没有可用期权链，系统不会用股票行情替代。' : '当前快照存在覆盖或数据质量限制，已有内容仍会保留。'}</span></div>}
      <section className="options-section"><div className="options-section-title"><div><p className="options-eyebrow">MARKET OPTIONS</p><h3>市场 ETF</h3></div><small>SPY · QQQ · IWM</small></div><div className="options-card-grid market">{market.map(row => <OptionCard key={row.symbol} row={row} onOpen={setSelectedSymbol}/>)}{!market.length && <EmptyState title={statusLabel(data.status)} message="市场 ETF 期权摘要暂不可用。"/>}</div></section>
      <section className="options-section"><div className="options-section-title"><div><p className="options-eyebrow">SECTOR OPTIONS</p><h3>一级行业代理</h3></div><small>Primary 与 secondary 分开展示</small></div><div className="options-sector-grid">{sectors.map(sector => <article className="options-sector" key={sector.sector}><header><div><h4>{sector.sector}</h4><small>{sector.primary?.symbol || 'Primary 数据不足'}</small></div><QualityBadge row={sector.primary || sector.rows[0] || normalizeOptionRow({ status: 'NO_DATA' })}/></header><div className="options-sector-primary">{sector.primary ? <OptionCard row={sector.primary} onOpen={setSelectedSymbol} compact/> : <span>Primary ETF 数据不足</span>}</div>{sector.rows.filter(row => row.symbol !== sector.primary?.symbol).length > 0 && <div className="options-secondary-list">{sector.rows.filter(row => row.symbol !== sector.primary?.symbol).map(row => <button type="button" key={row.symbol} onClick={() => setSelectedSymbol(row.symbol)}><b>{row.symbol}</b><span>{row.name || 'secondary proxy'}</span><em>{percent(row.atm_iv)}</em></button>)}</div>}</article>)}{!sectors.length && <EmptyState title="行业覆盖不足" message="当前没有可用的一级行业期权代理。"/>}</div></section>
      <section className="options-section"><div className="options-section-title"><div><p className="options-eyebrow">WATCHLIST OPTIONS</p><h3>自选股期权</h3></div><small>{watchlist.length ? `${watchlist.length} 只已覆盖` : '只展示当前自选股'}</small></div>{Object.entries(groupedWatchlist).map(([sector, rows]) => <div className="options-watch-group" key={sector}><h4>{sector}</h4><div className="options-card-grid">{rows.map(row => <OptionCard key={row.symbol} row={row} onOpen={setSelectedSymbol}/>)}</div></div>)}{!watchlist.length && <EmptyState title="暂无自选股期权" message="当前自选股可能没有可用期权链，或仍在等待首次同步。"/>}</section>
    </>}
    <OptionsDetailSheet symbol={selectedSymbol} onClose={() => setSelectedSymbol(null)}/>
  </div>
}

export { OptionsPage as Options }
export { EmptyState as OptionsEmptyState }
