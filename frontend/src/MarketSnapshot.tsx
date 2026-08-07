import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import { RealtimeQuoteCard } from './RealtimeMarketCard'
import { RealtimeBarSummary, RealtimeMarketEventList } from './RealtimeMarketEvents'
import { mergeRealtimeMarketEvents, useMarketEvents, useRealtimeQuotes } from './realtime'

export type PriceSnapshot = {
  id:number
  symbol:string
  exchange:string|null
  currency:string|null
  source_type:'price_snapshot'
  provider:string
  provider_symbol:string|null
  provider_role:string|null
  last_price:number
  open_price:number|null
  day_high:number|null
  day_low:number|null
  previous_close:number|null
  price_change:number|null
  price_change_percent:number|null
  day_volume:number|null
  average_volume_10d:number|null
  average_volume_20d:number|null
  relative_volume_20d:number|null
  relative_volume_basis:'full_day_average'|'same_time_average'|'unknown'|null
  market_timestamp:string|null
  trading_date:string|null
  market_session:'pre_market'|'regular'|'after_hours'|'closed'|'unknown'
  snapshot_market_session:string
  timestamp_source:'provider'|'derived'|'fetched_at_fallback'|null
  fetched_at:string|null
  persisted_at:string|null
  is_delayed:boolean|null
  delay_seconds:number|null
  is_stale:boolean
  age_seconds:number|null
  stale_after_seconds:number
  age_basis:string
}

export function priceRangePosition(snapshot:Pick<PriceSnapshot,'last_price'|'day_low'|'day_high'>):number|null {
  const {last_price:price,day_low:low,day_high:high}=snapshot
  if(low==null||high==null||!Number.isFinite(price)||!Number.isFinite(low)||!Number.isFinite(high)||high<=low)return null
  return Math.min(100,Math.max(0,(price-low)/(high-low)*100))
}

const sessionLabel:Record<PriceSnapshot['market_session'],string>={
  pre_market:'盘前',regular:'常规交易',after_hours:'盘后',closed:'已休市',unknown:'阶段未知',
}
const providerLabel:Record<string,string>={yfinance:'Yahoo Finance',yahoo:'Yahoo Finance',finnhub:'Finnhub',alpaca:'Alpaca',tiingo:'Tiingo'}
const number=(value:number|null,maximumFractionDigits=2)=>value==null?'--':value.toLocaleString('zh-CN',{maximumFractionDigits})
const money=(value:number|null,currency:string|null)=>value==null?'--':new Intl.NumberFormat('zh-CN',{style:'currency',currency:currency||'USD',maximumFractionDigits:2}).format(value)
const exactTime=(value:string|null)=>value?new Date(value).toLocaleString('zh-CN',{timeZoneName:'short'}):'--'
const age=(seconds:number|null)=>seconds==null?'新鲜度未知':seconds<60?`${seconds} 秒前`:seconds<3600?`${Math.floor(seconds/60)} 分钟前`:`${Math.floor(seconds/3600)} 小时前`

export function MarketSnapshotContent({snapshot}:{snapshot:PriceSnapshot}) {
  const position=priceRangePosition(snapshot)
  const tone=snapshot.price_change_percent==null?'neutral':snapshot.price_change_percent>0?'positive':snapshot.price_change_percent<0?'negative':'neutral'
  const sign=snapshot.price_change!=null&&snapshot.price_change>0?'+':''
  const delay=snapshot.is_delayed
    ? `可能延迟${snapshot.delay_seconds!=null?`约 ${Math.ceil(snapshot.delay_seconds/60)} 分钟`:''}`
    : snapshot.is_delayed===false?'未标记延迟':'延迟状态未知'
  return <article className={`market-snapshot-card${snapshot.is_stale?' stale':''}`}>
    {snapshot.is_stale&&<div className="market-snapshot-warning">数据可能已过期；这是数据库中最新保存的快照，并非实时请求。</div>}
    <header>
      <div><p>{snapshot.symbol} · 最新已入库价格</p><strong>{money(snapshot.last_price,snapshot.currency)}</strong></div>
      <div className={tone}><b>{snapshot.price_change==null?'--':`${sign}${money(snapshot.price_change,snapshot.currency)}`}</b><span>{snapshot.price_change_percent==null?'--':`${snapshot.price_change_percent>0?'+':''}${snapshot.price_change_percent.toFixed(2)}%`}</span></div>
      <em>{sessionLabel[snapshot.market_session]}</em>
    </header>
    <section className="market-day-range" aria-label="当日价格区间">
      <div><span>当日最低</span><b>{money(snapshot.day_low,snapshot.currency)}</b><span>当日最高</span><b>{money(snapshot.day_high,snapshot.currency)}</b></div>
      <div className={`market-day-range-track${position==null?' unavailable':''}`}>
        {position!=null&&<i style={{left:`${position}%`}} aria-label={`当前价格位于当日区间 ${position.toFixed(0)}%`}/>}
      </div>
      <small>{position==null?'价格区间数据不足':`当前 ${money(snapshot.last_price,snapshot.currency)}`}</small>
    </section>
    <dl className="market-snapshot-metrics">
      <div><dt>开盘价</dt><dd>{money(snapshot.open_price,snapshot.currency)}</dd></div>
      <div><dt>前收盘价</dt><dd>{money(snapshot.previous_close,snapshot.currency)}</dd></div>
      <div><dt>当日最高</dt><dd>{money(snapshot.day_high,snapshot.currency)}</dd></div>
      <div><dt>当日最低</dt><dd>{money(snapshot.day_low,snapshot.currency)}</dd></div>
      <div><dt>当日成交量</dt><dd>{number(snapshot.day_volume,0)}</dd></div>
      <div><dt>20 日平均量</dt><dd>{number(snapshot.average_volume_20d,0)}</dd></div>
      <div><dt>相对成交量</dt><dd>{snapshot.relative_volume_20d==null?'--':`${snapshot.relative_volume_20d.toFixed(2)}×`}</dd><small>{snapshot.relative_volume_basis==='full_day_average'?'对比完整交易日均量，盘中值天然偏低':snapshot.relative_volume_basis==='same_time_average'?'对比历史同时间累计量':'比较口径未知'}</small></div>
    </dl>
    <footer>
      <div><span>行情时点</span><b>{exactTime(snapshot.market_timestamp)}</b><small>{snapshot.timestamp_source==='fetched_at_fallback'?'供应商未返回可靠时点；未伪装为供应商时间':`交易日 ${snapshot.trading_date||'--'}`}</small></div>
      <div><span>数据提供方</span><b>{providerLabel[snapshot.provider]||snapshot.provider}</b><small>{snapshot.provider_role==='market_data_aggregator'?'市场数据聚合商':'数据源性质未知'}</small></div>
      <div><span>获取 / 入库</span><b>{exactTime(snapshot.fetched_at)}</b><small>入库 {exactTime(snapshot.persisted_at)}</small></div>
      <div><span>数据状态</span><b>{delay}</b><small>{age(snapshot.age_seconds)} · 阈值 {Math.round(snapshot.stale_after_seconds/60)} 分钟</small></div>
    </footer>
  </article>
}

export function MarketSnapshotState({state}:{state:'loading'|'error'|'empty'}) {
  const message=state==='loading'
    ? '正在读取已入库市场快照…'
    : state==='error'
      ? '市场快照读取失败或尚未入库；后台行情同步成功后会自动显示。'
      : '暂无已入库市场快照。'
  return <div className={`market-snapshot-state${state==='error'?' error':''}`}>{message}</div>
}

export function MarketSnapshot({symbol}:{symbol:string}) {
  const realtime=useRealtimeQuotes([symbol])
  const eventHistory=useMarketEvents([symbol])
  const events=mergeRealtimeMarketEvents(realtime.events,eventHistory.data||[])
  const latestBar=realtime.bars[symbol.toUpperCase()]
  const result=useQuery({
    queryKey:['price-snapshot',symbol],
    queryFn:()=>api<PriceSnapshot>(`/stocks/${encodeURIComponent(symbol)}/price-snapshot/latest`),
    enabled:!!symbol,
    staleTime:30_000,
  })
  return <div className="market-snapshot-stack">
    <RealtimeQuoteCard symbol={symbol} quote={realtime.quotes[symbol.toUpperCase()]} streamStatus={realtime.streamStatus} lastUpdateAt={realtime.lastUpdateAt}/>
    <RealtimeBarSummary bar={latestBar}/>
    <RealtimeMarketEventList events={events} />
    {result.isLoading&&<MarketSnapshotState state="loading"/>}
    {result.isError&&<MarketSnapshotState state="error"/>}
    {!result.isLoading&&!result.isError&&!result.data&&<MarketSnapshotState state="empty"/>}
    {result.data&&<MarketSnapshotContent snapshot={result.data}/>}
  </div>
}
