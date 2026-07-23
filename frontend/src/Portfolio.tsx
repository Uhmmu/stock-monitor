import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import { Sheet } from './Sheet'
import { SecuritySearchAutocomplete, type SecuritySearchResult } from './SecuritySearchAutocomplete'

// ── 持仓模块类型 ──────────────────────────────────────────────
type PositionView = {
  symbol:string
  security_id:number|null
  total_quantity:number
  average_cost:number
  total_cost:number
  realized_pnl:number
  currency:string
  last_transaction_at:string|null
  price_available:boolean
  current_price:number|null
  price_source:string|null
  market_value:number|null
  unrealized_pnl:number|null
  unrealized_pnl_percent:number|null
  portfolio_weight:number|null
}
type PortfolioSummary = {
  portfolio_id:number
  base_currency:string
  position_count:number
  priced_count:number
  total_market_value:number
  total_cost:number
  total_unrealized_pnl:number
  total_unrealized_pnl_percent:number|null
  total_realized_pnl:number
  has_unpriced_positions:boolean
  positions:PositionView[]
}
type PriceLevelZone = {
  zone_type:string
  lower_price:number
  upper_price:number
  center_price:number
  strength:number
  confidence:number
  timeframe:string
  touch_count:number
  last_touched_at:string|null
  status:string
}
type ArrivalEstimate = {
  estimator:string
  target_zone_id:string
  probability_5d:number|null
  probability_10d:number|null
  probability_20d:number|null
  median_days:number|null
  lower_days:number|null
  upper_days:number|null
  confidence:number|null
  assumptions:string[]
  unavailable_reason:string|null
  direction:'support'|'resistance'
  target_zone:PriceLevelZone
}
type PositionTechnical = {
  symbol:string
  timeframe:string
  available:boolean
  status:string
  current_price:number|null
  trend_state:string
  trend_strength:number|null
  volatility_state:string
  atr:number|null
  support_zones:PriceLevelZone[]
  resistance_zones:PriceLevelZone[]
  analyzer_errors:{analyzer:string;error:string}[]
  market_data_source:string|null
  data_through:string|null
  calculated_at:string|null
  unavailable_reason:string|null
  arrival_estimates:ArrivalEstimate[]
  cost_basis_reference:{average_cost:number;vs_current_price:number|null}
}
type HealthSectorBucket = {sector:string;market_value:number;weight:number}
type PortfolioHealth = {
  portfolio_id:number
  total_market_value:number
  priced_count:number
  position_count:number
  has_unpriced_positions:boolean
  concentration:{
    available:boolean
    reason?:string
    hhi:number|null
    hhi_scaled?:number|null
    top_five_weight:number|null
    effective_holdings:number|null
    holdings_count?:number
  }
  sector_exposure:{
    available:boolean
    reason?:string
    buckets:HealthSectorBucket[]
    unclassified_weight?:number
  }
}
type TransactionRow = {
  id:number
  symbol:string
  transaction_type:string
  quantity:number
  price:number
  fees:number
  currency:string
  trade_date:string
  account:string|null
  note:string|null
  source:string
}

export const fmtMoney = (value:number|null, currency='USD') => value==null?'数据不足':`${currency==='USD'?'$':currency+' '}${value.toLocaleString('zh-CN',{maximumFractionDigits:2,minimumFractionDigits:2})}`
export const fmtPercent = (value:number|null) => value==null?'—':`${value>=0?'+':''}${value.toFixed(2)}%`
export const fmtNum = (value:number, digits=4) => value.toLocaleString('zh-CN',{maximumFractionDigits:digits})
const typeLabel:Record<string,string> = {buy:'买入',sell:'卖出',dividend:'股息',fee:'费用',deposit:'转入现金',withdrawal:'转出现金',split:'拆股',transfer_in:'转入',transfer_out:'转出'}
const trendLabel:Record<string,string> = {uptrend:'上升趋势',downtrend:'下降趋势',range:'区间震荡',unknown:'趋势不明'}
const volLabel:Record<string,string> = {expanding:'波动扩大',contracting:'波动收窄',normal:'波动正常',unknown:'数据不足'}

function emptyManualForm(today:string) {
  return {symbol:'',price:'',quantity:'',trade_date:today,fees:'0',currency:'USD',account:'',note:''}
}

export function PortfolioModule() {
  const client = useQueryClient()
  const today = new Date().toISOString().slice(0,10)
  const [subtab,setSubtab] = useState<'overview'|'positions'|'technical'|'health'|'transactions'>('overview')
  const [entryOpen,setEntryOpen] = useState(false)
  const [entrySecurity,setEntrySecurity] = useState<SecuritySearchResult|null>(null)
  const [entryForm,setEntryForm] = useState(emptyManualForm(today))
  const [detailSymbol,setDetailSymbol] = useState<string|null>(null)

  const summary = useQuery({queryKey:['portfolio-summary'],queryFn:()=>api<PortfolioSummary>('/portfolio/summary'),staleTime:30_000})
  const health = useQuery({queryKey:['portfolio-health'],queryFn:()=>api<PortfolioHealth>('/portfolio/health'),enabled:subtab==='health',staleTime:60_000})
  const transactions = useQuery({queryKey:['portfolio-transactions'],queryFn:()=>api<TransactionRow[]>('/portfolio/transactions'),enabled:subtab==='transactions'})
  const detail = useQuery({queryKey:['portfolio-technical',detailSymbol],queryFn:()=>api<PositionTechnical>(`/portfolio/positions/${detailSymbol}/technical`),enabled:!!detailSymbol})

  const resetEntry = () => {setEntryOpen(false);setEntrySecurity(null);setEntryForm(emptyManualForm(today))}
  const createEntry = useMutation({
    mutationFn:()=>post('/portfolio/positions',{
      symbol:entrySecurity?.display_symbol||entryForm.symbol.toUpperCase(),
      security_id:entrySecurity?.security_id||null,
      price:Number(entryForm.price),
      quantity:Number(entryForm.quantity),
      trade_date:entryForm.trade_date,
      fees:entryForm.fees===''?0:Number(entryForm.fees),
      currency:entryForm.currency,
      account:entryForm.account||null,
      note:entryForm.note||null,
    }),
    onSuccess:()=>{
      resetEntry()
      client.invalidateQueries({queryKey:['portfolio-summary']})
      client.invalidateQueries({queryKey:['portfolio-health']})
      client.invalidateQueries({queryKey:['portfolio-transactions']})
    },
  })
  const deleteTxn = useMutation({
    mutationFn:(id:number)=>api<unknown>(`/portfolio/transactions/${id}`,{method:'DELETE'}),
    onSuccess:()=>{
      client.invalidateQueries({queryKey:['portfolio-summary']})
      client.invalidateQueries({queryKey:['portfolio-health']})
      client.invalidateQueries({queryKey:['portfolio-transactions']})
    },
  })

  const s = summary.data
  const subtabs:[string,string][] = [['overview','总览'],['positions','持仓明细'],['technical','技术位置'],['health','组合健康'],['transactions','交易记录']]

  return <div className="portfolio-module">
    <div className="section-title">
      <div><p>HOLDINGS</p><h2>持仓</h2></div>
      <div className="section-actions"><button onClick={()=>setEntryOpen(true)}>＋ 手动添加持仓</button></div>
    </div>
    <div className="portfolio-subtabs">{subtabs.map(([key,label])=><button key={key} className={subtab===key?'active':''} onClick={()=>setSubtab(key as typeof subtab)}>{label}</button>)}</div>

    {subtab==='overview'&&<div className="portfolio-overview">
      {summary.isLoading&&<div className="empty">正在读取持仓数据…</div>}
      {!summary.isLoading&&s&&<>
        <div className="metric-card-row">
          <div className="metric-card"><span>持仓市值</span><strong>{fmtMoney(s.total_market_value,s.base_currency)}</strong>{s.has_unpriced_positions&&<small className="portfolio-gap-hint">部分持仓数据不足</small>}</div>
          <div className="metric-card"><span>浮动盈亏</span><strong className={((s.total_unrealized_pnl)||0)>=0?'positive':'negative'}>{fmtMoney(s.total_unrealized_pnl,s.base_currency)}</strong><small>{fmtPercent(s.total_unrealized_pnl_percent)}</small></div>
          <div className="metric-card"><span>已实现盈亏</span><strong className={s.total_realized_pnl>=0?'positive':'negative'}>{fmtMoney(s.total_realized_pnl,s.base_currency)}</strong></div>
          <div className="metric-card"><span>持仓数量</span><strong>{s.position_count}</strong><small>{s.priced_count} 个可估值</small></div>
        </div>
        <div className="table portfolio-table">
          <div className="table-head portfolio-row"><span>代码</span><span>数量</span><span>成本价</span><span>现价</span><span>市值</span><span>浮动盈亏</span><span>占比</span></div>
          {s.positions.map(p=><button key={p.symbol} className="table-row portfolio-row" onClick={()=>{setDetailSymbol(p.symbol);setSubtab('technical')}}>
            <span className="toggle">{p.symbol}</span>
            <span>{fmtNum(p.total_quantity)}</span>
            <span>{fmtMoney(p.average_cost,p.currency)}</span>
            <span>{p.price_available?fmtMoney(p.current_price,p.currency):'数据不足'}</span>
            <span>{p.price_available?fmtMoney(p.market_value,p.currency):'数据不足'}</span>
            <span className={(p.unrealized_pnl||0)>=0?'positive':'negative'}>{p.price_available?`${fmtMoney(p.unrealized_pnl,p.currency)} (${fmtPercent(p.unrealized_pnl_percent)})`:'数据不足'}</span>
            <span>{p.portfolio_weight==null?'—':`${p.portfolio_weight.toFixed(1)}%`}</span>
          </button>)}
          {!s.positions.length&&<div className="empty">还没有持仓，点击右上角添加第一笔买入记录。</div>}
        </div>
      </>}
    </div>}

    {subtab==='positions'&&<div className="portfolio-positions">
      {s?.positions.map(p=><article key={p.symbol} className="position-card">
        <header><b>{p.symbol}</b><span>{p.currency}</span></header>
        <div className="position-card-grid">
          <div><span>持仓数量</span><b>{fmtNum(p.total_quantity)}</b></div>
          <div><span>平均成本</span><b>{fmtMoney(p.average_cost,p.currency)}</b></div>
          <div><span>总成本</span><b>{fmtMoney(p.total_cost,p.currency)}</b></div>
          <div><span>已实现盈亏</span><b className={p.realized_pnl>=0?'positive':'negative'}>{fmtMoney(p.realized_pnl,p.currency)}</b></div>
          <div><span>最近交易</span><b>{p.last_transaction_at||'—'}</b></div>
          <div><span>数据来源</span><b>{p.price_available?(p.price_source==='snapshot'?'实时快照':p.price_source==='fmp'?'FMP 日线':'Yahoo 日线'):'数据不足'}</b></div>
        </div>
        <button className="position-detail-btn" onClick={()=>{setDetailSymbol(p.symbol);setSubtab('technical')}}>查看技术位置 →</button>
      </article>)}
      {!s?.positions.length&&<div className="empty">还没有持仓明细。</div>}
    </div>}

    {subtab==='technical'&&<div className="portfolio-technical">
      <div className="portfolio-technical-list">{s?.positions.map(p=><button key={p.symbol} className={detailSymbol===p.symbol?'active':''} onClick={()=>setDetailSymbol(p.symbol)}>
        <b>{p.symbol}</b><span>{p.price_available?fmtMoney(p.current_price,p.currency):'数据不足'}</span>
      </button>)}{!s?.positions.length&&<div className="empty">还没有持仓可供技术分析。</div>}</div>
      <div className="portfolio-technical-detail">
        {!detailSymbol&&<div className="empty">从左侧选择一个持仓查看技术位置。</div>}
        {detailSymbol&&detail.isLoading&&<div className="empty">正在读取技术位置…</div>}
        {detailSymbol&&detail.data&&<PositionTechnicalPanel data={detail.data}/>}
      </div>
    </div>}

    {subtab==='health'&&<div className="portfolio-health">
      {health.isLoading&&<div className="empty">正在计算组合健康…</div>}
      {health.data&&<>
        <div className="metric-card-row">
          <div className="metric-card"><span>集中度 HHI</span><strong>{health.data.concentration.available?health.data.concentration.hhi_scaled?.toFixed(0):'数据不足'}</strong><small>{health.data.concentration.available?'0-10000，越低越分散':health.data.concentration.reason}</small></div>
          <div className="metric-card"><span>前五大占比</span><strong>{health.data.concentration.available?`${health.data.concentration.top_five_weight?.toFixed(1)}%`:'数据不足'}</strong></div>
          <div className="metric-card"><span>有效持仓数</span><strong>{health.data.concentration.available?health.data.concentration.effective_holdings:'数据不足'}</strong><small>1/HHI，衡量真实分散度</small></div>
        </div>
        <div className="section-title"><div><p>SECTOR</p><h2>行业暴露</h2></div></div>
        {health.data.sector_exposure.available?<div className="table portfolio-sector-table">
          <div className="table-head portfolio-sector-row"><span>行业</span><span>市值</span><span>占比</span></div>
          {health.data.sector_exposure.buckets.map(b=><div key={b.sector} className="table-row portfolio-sector-row"><span>{b.sector}</span><span>{fmtMoney(b.market_value)}</span><span>{b.weight.toFixed(1)}%</span></div>)}
          {!!health.data.sector_exposure.unclassified_weight&&<div className="table-row portfolio-sector-row"><span>未分类</span><span>—</span><span>{health.data.sector_exposure.unclassified_weight.toFixed(1)}%</span></div>}
        </div>:<div className="empty">{health.data.sector_exposure.reason}</div>}
      </>}
    </div>}

    {subtab==='transactions'&&<div className="portfolio-transactions">
      <div className="table portfolio-txn-table">
        <div className="table-head portfolio-txn-row"><span>日期</span><span>代码</span><span>类型</span><span>数量</span><span>价格</span><span>手续费</span><span>账户</span><span></span></div>
        {transactions.data?.map(t=><div key={t.id} className="table-row portfolio-txn-row">
          <span>{t.trade_date}</span>
          <span>{t.symbol}</span>
          <span>{typeLabel[t.transaction_type]||t.transaction_type}</span>
          <span>{fmtNum(t.quantity)}</span>
          <span>{fmtMoney(t.price,t.currency)}</span>
          <span>{fmtMoney(t.fees,t.currency)}</span>
          <span>{t.account||'—'}</span>
          <button className="danger" onClick={()=>deleteTxn.mutate(t.id)}>删除</button>
        </div>)}
        {!transactions.isLoading&&!transactions.data?.length&&<div className="empty">还没有交易记录。</div>}
      </div>
    </div>}

    <Sheet open={entryOpen} onClose={resetEntry} title="手动添加持仓">
      <form className="portfolio-entry-form" onSubmit={e=>{e.preventDefault();createEntry.mutate()}}>
        <label><span>股票代码</span><SecuritySearchAutocomplete value={entrySecurity} onSelect={sec=>{setEntrySecurity(sec);if(sec)setEntryForm(f=>({...f,symbol:sec.display_symbol}))}} placeholder="搜索代码或公司名称"/></label>
        <div className="portfolio-entry-grid">
          <label><span>买入价格</span><input type="number" inputMode="decimal" min="0" step="any" required value={entryForm.price} onChange={e=>setEntryForm(f=>({...f,price:e.target.value}))} placeholder="0.00"/></label>
          <label><span>数量</span><input type="number" inputMode="decimal" min="0" step="any" required value={entryForm.quantity} onChange={e=>setEntryForm(f=>({...f,quantity:e.target.value}))} placeholder="0"/></label>
          <label><span>买入日期</span><input type="date" required value={entryForm.trade_date} onChange={e=>setEntryForm(f=>({...f,trade_date:e.target.value}))}/></label>
          <label><span>手续费</span><input type="number" inputMode="decimal" min="0" step="any" value={entryForm.fees} onChange={e=>setEntryForm(f=>({...f,fees:e.target.value}))} placeholder="0"/></label>
          <label><span>币种</span><select value={entryForm.currency} onChange={e=>setEntryForm(f=>({...f,currency:e.target.value}))}>{['USD','HKD','CNY','EUR','JPY','GBP','CAD','AUD'].map(c=><option key={c} value={c}>{c}</option>)}</select></label>
          <label><span>账户</span><input value={entryForm.account} onChange={e=>setEntryForm(f=>({...f,account:e.target.value}))} placeholder="可选"/></label>
        </div>
        <label className="portfolio-entry-note"><span>备注</span><input value={entryForm.note} onChange={e=>setEntryForm(f=>({...f,note:e.target.value}))} placeholder="可选"/></label>
        {createEntry.error&&<p className="error">{createEntry.error.message}</p>}
        <div className="portfolio-entry-actions"><button disabled={createEntry.isPending||!entryForm.symbol}>{createEntry.isPending?'保存中…':'保存持仓'}</button></div>
      </form>
    </Sheet>
  </div>
}

function PositionTechnicalPanel({data}:{data:PositionTechnical}) {
  if (!data.available) {
    return <div className="empty">{data.unavailable_reason||'技术分析暂不可用。'}</div>
  }
  return <article className="position-technical-panel">
    <header>
      <h3>{data.symbol}</h3>
      <strong>{data.current_price!=null?`$${data.current_price.toFixed(2)}`:'数据不足'}</strong>
    </header>
    <div className="technical-metrics">
      <div><span>趋势</span><b className={`trend-${data.trend_state}`}>{trendLabel[data.trend_state]||data.trend_state}</b></div>
      <div><span>波动状态</span><b>{volLabel[data.volatility_state]||data.volatility_state}</b></div>
      <div><span>ATR</span><b>{data.atr!=null?data.atr.toFixed(2):'—'}</b></div>
      <div><span>成本价对比现价</span><b className={(data.cost_basis_reference.vs_current_price||0)>=0?'positive':'negative'}>{fmtPercent(data.cost_basis_reference.vs_current_price)}</b></div>
    </div>
    <div className="technical-columns">
      <section>
        <h3>支撑与阻力区域</h3>
        <div className="zone-table">
          {[...data.support_zones,...data.resistance_zones].map(z=><div key={`${z.zone_type}-${z.center_price}`}>
            <b className={z.zone_type==='support'?'positive':'negative'}>{z.zone_type==='support'?'支撑':'阻力'}</b>
            <span>${z.lower_price.toFixed(2)}–{z.upper_price.toFixed(2)}</span>
            <span>{Math.round(z.strength*100)} 分</span>
            <span>{z.touch_count} 次触及</span>
          </div>)}
          {!data.support_zones.length&&!data.resistance_zones.length&&<p>暂无已确认的支撑或阻力区域。</p>}
        </div>
      </section>
      <section>
        <h3>到达时间估算</h3>
        {data.arrival_estimates.length===0&&<p>数据不足，暂无到达时间估算。</p>}
        {data.arrival_estimates.map(est=><div key={est.target_zone_id} className="arrival-estimate">
          <b>{est.direction==='resistance'?'上方阻力':'下方支撑'} ${est.target_zone.center_price.toFixed(2)}</b>
          {est.median_days!=null?<p>预计 {est.median_days} 个交易日左右到达（{est.lower_days}–{est.upper_days} 日区间），仅为概率估算。</p>:<p>{est.unavailable_reason}</p>}
          {est.probability_5d!=null&&<small>5日概率 {Math.round(est.probability_5d*100)}% · 10日 {est.probability_10d!=null?Math.round(est.probability_10d*100):'—'}% · 20日 {est.probability_20d!=null?Math.round(est.probability_20d*100):'—'}%</small>}
        </div>)}
      </section>
    </div>
    {data.analyzer_errors.length>0&&<footer className="portfolio-analyzer-errors">部分分析器暂不可用：{data.analyzer_errors.map(e=>e.analyzer).join('、')}</footer>}
    <footer>来源：{data.market_data_source||'—'} · 数据截至 {data.data_through||'—'}</footer>
  </article>
}
