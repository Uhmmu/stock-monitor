import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { GlassCard, IOSPage, LoadingState, NavigationBar, SectionHeader, StateView, StatusPill } from '../components'
import './options.css'

type Json = Record<string, unknown>
type OptionRow = {
  symbol: string; name: string | null; sector: string | null; status: string | null; price: number | null; expiration: string | null; dte: number | null; atmIv: number | null; ivChange: number | null; pcVolume: number | null; pcOi: number | null; callVolume: number | null; putVolume: number | null; callOi: number | null; putOi: number | null; skew: number | null; activity: number | null; activityLevel: string | null; updatedAt: string | null; provider: string | null; quality: Json
}
type Sector = { sector: string; primary: OptionRow | null; secondary: OptionRow[] }
type Overview = { status: string | null; asOf: string | null; market: OptionRow[]; sectors: Sector[]; watchlist: OptionRow[]; sync: Json | null }
type Point = Json & { x?: string | number | null; y?: number | null; value?: number | null }
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

function row(value: unknown): OptionRow {
  const item = record(value)
  return {
    symbol: String(pick(item, ['symbol', 'ticker', 'underlying']) ?? ''), name: text(pick(item, ['name', 'company_name', 'display_name'])), sector: text(pick(item, ['sector', 'primary_sector'])), status: text(pick(item, ['status', 'data_status'])), price: num(pick(item, ['underlying_price', 'price', 'current_price'])), expiration: text(pick(item, ['nearest_expiration', 'expiration'])), dte: num(pick(item, ['dte', 'days_to_expiration'])), atmIv: num(pick(item, ['atm_iv', 'at_the_money_iv'])), ivChange: num(pick(item, ['iv_change', 'atm_iv_change'])), pcVolume: num(pick(item, ['put_call_volume_ratio', 'put_call_ratio_volume', 'pc_volume'])), pcOi: num(pick(item, ['put_call_oi_ratio', 'put_call_ratio_oi', 'pc_oi'])), callVolume: num(pick(item, ['call_volume', 'calls_volume'])), putVolume: num(pick(item, ['put_volume', 'puts_volume'])), callOi: num(pick(item, ['call_oi', 'calls_open_interest'])), putOi: num(pick(item, ['put_oi', 'puts_open_interest'])), skew: num(pick(item, ['downside_skew', 'skew'])), activity: num(pick(item, ['activity_score', 'score'])), activityLevel: text(pick(item, ['activity_level', 'activity'])), updatedAt: text(pick(item, ['updated_at', 'as_of', 'fetched_at'])), provider: text(pick(item, ['provider', 'source'])), quality: record(item.quality),
  }
}

function overview(value: unknown): Overview {
  const source = record(value)
  return {
    status: text(source.status), asOf: text(pick(source, ['as_of', 'updated_at'])), market: array(source.market).map(row).filter(item => item.symbol), watchlist: array(source.watchlist).map(row).filter(item => item.symbol),
    sectors: array(source.sectors).map(item => { const sector = record(item); const primary = sector.primary == null ? null : row(sector.primary); return { sector: String(pick(sector, ['sector', 'name', 'label']) ?? '未分类行业'), primary: primary?.symbol ? primary : null, secondary: array(sector.secondary).map(row).filter(item => item.symbol) } }).filter(item => item.primary || item.secondary.length),
    sync: source.sync == null ? null : record(source.sync),
  }
}

function detail(value: unknown): Detail {
  const source = record(value); const base = row(source.summary ?? source)
  const points = (key: string, fallback?: string) => array(source[key] ?? (fallback ? source[fallback] : undefined)).map(item => record(item) as Point)
  const chain = Array.isArray(source.chain) ? source.chain : Object.values(record(source.chain)).flatMap(value => array(value))
  return { ...base, expirations: array(source.expirations).map(item => typeof item === 'string' ? item : record(item)), chain: chain.map(item => record(item)), term: points('term_structure', 'expiration_structure'), oi: points('oi_distribution'), volume: points('volume_distribution'), history: points('history') }
}

function MobileOptionCard({ item, onOpen }: { item: OptionRow; onOpen: (symbol: string) => void }) {
  return <button className="mobile-option-card" type="button" onClick={() => onOpen(item.symbol)}><div className="mobile-option-head"><div><strong>{item.symbol}</strong><small>{item.name || '期权标的'}</small></div><StatusPill tone={statusTone(item.status)}>{status(item.status)}</StatusPill></div><div className="mobile-option-price"><b>{item.price == null ? '数据不足' : `$${item.price.toFixed(2)}`}</b><span>{item.expiration || '期限不可用'}{item.dte == null ? '' : ` · ${item.dte} 天`}</span></div><div className="mobile-option-grid"><div><span>ATM IV</span><b>{asPercent(item.atmIv)}</b></div><div><span>P/C 成交</span><b>{asRatio(item.pcVolume)}</b></div><div><span>活跃度</span><b>{item.activity == null ? '数据不足' : item.activity.toFixed(0)}</b></div><div><span>下行偏斜</span><b>{asPercent(item.skew)}</b></div></div><footer><span>{item.provider || '来源不可用'}</span><time>{item.updatedAt ? item.updatedAt.slice(0, 16).replace('T', ' ') : '时间不可用'}</time></footer></button>
}

function MobileSparkline({ points, label }: { points: Point[]; label: string }) {
  const values = points.map(point => num(point.y ?? point.value ?? pick(point, ['atm_iv', 'iv', 'open_interest', 'oi', 'volume', 'activity_score']) ?? (typeof point.x === 'number' ? point.x : null))).filter((value): value is number => value != null)
  if (!values.length) return <div className="mobile-option-chart-empty">{label}：数据不足</div>
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const pointsText = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${100 - ((value - min) / span) * 86 - 7}`).join(' ')
  return <figure className="mobile-option-chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={label}><polyline points={pointsText}/></svg><figcaption>{label}<b>{values.at(-1)?.toFixed(2)}</b></figcaption></figure>
}

function OptionsDetailPage({ symbol, back }: { symbol: string; back: () => void }) {
  const [expiration, setExpiration] = useState('')
  const [chainType, setChainType] = useState<'call' | 'put'>('call')
  const query = useQuery({ queryKey: ['ios-options-detail', symbol, expiration], queryFn: () => api<unknown>(`/options/symbols/${encodeURIComponent(symbol)}${expiration ? `?expiration=${encodeURIComponent(expiration)}` : ''}`), enabled: !!symbol, staleTime: 60_000 })
  const data = query.data ? detail(query.data) : null
  const expirationValue = (item: string | Json) => typeof item === 'string' ? item : text(pick(item, ['expiration', 'date', 'value'])) || ''
  return <><NavigationBar title={`${symbol} 期权`} eyebrow="OPTIONS DETAIL" back={back}/><IOSPage className="options-mobile-page detail-page"><div className="mobile-options-heading"><div><span>OPTIONS DETAIL</span><h1>{symbol}</h1><p>{data?.name || '标的名称暂缺'} · {data?.sector || '行业数据不足'}</p></div>{data && <StatusPill tone={statusTone(data.status)}>{status(data.status)}</StatusPill>}</div>{query.isLoading && <LoadingState rows={7}/>} {query.isError && <StateView title="期权详情暂不可用" message="已保存的摘要和链暂时无法读取。" retry={() => { void query.refetch() }}/>} {data && <><GlassCard className="mobile-options-summary"><div className="mobile-options-detail-grid"><div><span>标的价格</span><b>{data.price == null ? '数据不足' : `$${data.price.toFixed(2)}`}</b></div><div><span>ATM IV</span><b>{asPercent(data.atmIv)}</b></div><div><span>P/C 成交量</span><b>{asRatio(data.pcVolume)}</b></div><div><span>P/C 持仓量</span><b>{asRatio(data.pcOi)}</b></div><div><span>总成交量</span><b>{asCompact((data.callVolume || 0) + (data.putVolume || 0) || null)}</b></div><div><span>活跃度</span><b>{data.activity == null ? '数据不足' : data.activity.toFixed(0)}</b></div></div></GlassCard><SectionHeader title="期限结构" caption="选择已保存到期日"/><div className="mobile-option-expirations">{data.expirations.slice(0, 10).map(item => <button type="button" className={expirationValue(item) === expiration ? 'active' : ''} key={expirationValue(item)} onClick={() => setExpiration(expirationValue(item))}>{expirationValue(item) || '数据不足'}</button>)}{!data.expirations.length && <span>期限数据不足</span>}</div><SectionHeader title="合约链" caption="只读已保存合约，不构成交易终端" action={<div className="mobile-option-toggle"><button type="button" className={chainType === 'call' ? 'active' : ''} onClick={() => setChainType('call')}>Calls</button><button type="button" className={chainType === 'put' ? 'active' : ''} onClick={() => setChainType('put')}>Puts</button></div>}/><div className="mobile-option-chain">{data.chain.filter(item => { const type = String(pick(item, ['option_type', 'type']) || '').toLowerCase(); return type ? type.includes(chainType) || (chainType === 'call' ? ['c', 'calls'].includes(type) : ['p', 'puts'].includes(type)) : true }).slice(0, 40).map((item, index) => <div key={String(pick(item, ['contractSymbol', 'contract_symbol']) || index)}><b>{num(pick(item, ['strike']))?.toFixed(2) || '—'}</b><span>IV {asPercent(num(pick(item, ['impliedVolatility', 'implied_volatility'])))}</span><span>量 {asCompact(num(item.volume))}</span><span>OI {asCompact(num(pick(item, ['openInterest', 'open_interest'])))}</span><strong>{item.lastPrice == null ? '—' : `$${Number(item.lastPrice).toFixed(2)}`}</strong></div>)}{!data.chain.length && <div className="mobile-option-chart-empty">合约数据不足</div>}</div><div className="mobile-option-charts"><MobileSparkline label="ATM IV / 期限" points={data.term}/><MobileSparkline label="持仓量分布" points={data.oi}/><MobileSparkline label="成交量分布" points={data.volume}/><MobileSparkline label="历史快照" points={data.history}/></div><p className="mobile-options-note">期权活跃度描述成交与持仓活动，不代表涨跌概率或交易建议。缺失指标保持“数据不足”。</p></>}</IOSPage></>
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
