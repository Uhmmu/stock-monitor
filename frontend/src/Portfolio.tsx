import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import { Sheet } from './Sheet'
import { SecuritySearchAutocomplete, securityPayload, type SecuritySearchResult } from './SecuritySearchAutocomplete'
import { PortfolioRiskAnalysis } from './PortfolioAnalysis'
import { ScenarioAnalysisView, StressTestView } from './PortfolioScenarios'
import { MonteCarloView } from './PortfolioMonteCarlo'
import { PortfolioOptimizationView } from './PortfolioOptimization'
import { PortfolioAnalysisHistory } from './PortfolioAnalysisHistory'

// ── 持仓模块类型 ──────────────────────────────────────────────
type PositionView = {
  symbol:string
  security_id:number|null
  total_quantity:number
  average_cost:number
  total_cost:number
  currency:string
  last_transaction_at:string|null
  price_available:boolean
  current_price:number|null
  price_source:string|null
  market_value:number|null
  unrealized_pnl:number|null
  unrealized_pnl_percent:number|null
  fx_rate:number|null
  fx_rate_source:string|null
  base_currency_market_value:number|null
  base_currency_total_cost:number|null
  base_currency_unrealized_pnl:number|null
  valuation_available:boolean
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
  has_unpriced_positions:boolean
  has_unconverted_positions:boolean
  fx_conversion_used:boolean
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
  currency:string
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
type HealthCoverage = {
  covered_weight:number
  uncovered_weight:number
  covered_market_value:number
  uncovered_market_value:number
  covered_symbols:string[]
  uncovered_symbols:string[]
  excluded_symbols:string[]
  freshness:'fresh'|'mixed'|'stale'|'unavailable'
  confidence:number
  status:'sufficient'|'partial'|'insufficient'
  basis:string
}
type HealthContributor = {symbol:string;score:number;weight:number;contribution:number}
type HealthSubscore = {score:number|null;coverage_weight:number}
type HealthFinding = {
  id:string
  category:string
  severity:'positive'|'info'|'warning'|'high'
  title:string
  message:string
  evidence:Record<string,unknown>
  affected_symbols:string[]
  affected_weight:number
  priority:number
}
type PortfolioHealth = {
  portfolio_id:number
  as_of:string
  base_currency:string
  total_market_value:number
  invested_market_value:number
  cash_value:number
  cash_weight:number
  cash_tracked:boolean
  priced_count:number
  position_count:number
  has_unpriced_positions:boolean
  health:{score:number|null;grade:string;confidence:number;included_components:string[];excluded_components:string[]}
  fundamental_quality:{
    score:number|null;grade:string;coverage_weight:number;covered_market_value:number;uncovered_market_value:number
    subscores:Record<string,HealthSubscore>
    top_positive_contributors:HealthContributor[]
    top_negative_contributors:HealthContributor[]
  }
  valuation_risk:{
    score:number|null;raw_weighted_valuation_risk:number|null;confidence_adjusted_valuation_risk:number|null
    grade:string;coverage_weight:number;average_confidence:number;undervalued_weight:number;fairly_valued_weight:number
    overvalued_weight:number;high_risk_weight:number;low_confidence_valuation_weight:number
  }
  sec_risk:{
    score:number|null;grade:string;coverage_weight:number
    flag_exposures:{flag:string;label:string;severity:string;weight:number;affected_symbols:string[]}[]
    affected_positions:{symbol:string;weight:number;risk_score:number;flags:string[]}[]
  }
  concentration:{
    available:boolean
    reason?:string
    risk_score:number|null
    grade?:string
    largest_position_weight:number|null
    top_two_weight:number|null
    top_three_weight:number|null
    hhi:number|null
    hhi_scaled?:number|null
    top_five_weight:number|null
    effective_holdings:number|null
    effective_position_count:number|null
    holdings_count?:number
    sector_weights:HealthSectorBucket[]
    industry_weights:{industry:string;market_value:number;weight:number}[]
    country_weights:{country:string;market_value:number;weight:number}[]
    currency_weights:{currency:string;market_value:number;weight:number}[]
  }
  coverage:{price:HealthCoverage;fundamental:HealthCoverage;valuation:HealthCoverage;sec:HealthCoverage}
  findings:HealthFinding[]
  sector_exposure:{
    available:boolean
    reason?:string
    buckets:HealthSectorBucket[]
    unclassified_weight?:number
  }
}
type StrategyProfile = {
  strategy_type:string
  investment_horizon:string
  risk_tolerance:string
  max_single_position:number
  max_theme_exposure:number
  valuation_preference:string
  minimum_quality_score:number
  preferred_regions:string[]
  preferred_market_caps:string[]
  updated_at:string
}
type StrategyChoice = {value:string;label:string}
type StrategyProfileResponse = {
  profile:StrategyProfile
  presets:Record<string,Omit<StrategyProfile,'updated_at'>>
  choices:Record<string,StrategyChoice[]>
}
type PersonalizedInterpretation = {
  strategy_type:string
  strategy_label:string
  evaluated_at:string
  items:{id:string;dimension:string;status:'aligned'|'caution'|'unavailable';title:string;message:string;evidence:Record<string,unknown>}[]
  overall_summary:string
  recommendations:{id:string;title:string;reason:string;priority:number}[]
  unavailable_dimensions:string[]
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
type PortfolioBenchmark = {
  start_date:string|null
  portfolio_return_percent:number|null
  configured:boolean
  benchmarks:{symbol:string;name:string;start_price:number|null;start_price_date:string|null;latest_price:number|null;latest_price_date:string|null;return_percent:number|null;relative_return_percent:number|null;status:'available'|'unavailable';message:string|null}[]
  source:string
  as_of:string
}

export const fmtMoney = (value:number|null, currency='USD') => value==null?'数据不足':`${currency==='USD'?'$':currency+' '}${value.toLocaleString('zh-CN',{maximumFractionDigits:2,minimumFractionDigits:2})}`
export const fmtPercent = (value:number|null) => value==null?'—':`${value>=0?'+':''}${value.toFixed(2)}%`
export const fmtNum = (value:number, digits=4) => value.toLocaleString('zh-CN',{maximumFractionDigits:digits})
export const fmtHealthScore = (value:number|null) => value==null?'数据不足':Math.round(value).toString()
const typeLabel:Record<string,string> = {buy:'买入',sell:'卖出',dividend:'股息',fee:'费用',deposit:'转入现金',withdrawal:'转出现金',split:'拆股',transfer_in:'转入',transfer_out:'转出'}
const trendLabel:Record<string,string> = {uptrend:'上升趋势',downtrend:'下降趋势',range:'区间震荡',unknown:'趋势不明'}
const volLabel:Record<string,string> = {expanding:'波动扩大',contracting:'波动收窄',normal:'波动正常',unknown:'数据不足'}
type PortfolioTab = 'overview'|'positions'|'technical'|'health'|'stress'|'scenario'|'monte-carlo'|'optimization'|'history'

function emptyManualForm(today:string) {
  return {symbol:'',price:'',quantity:'',trade_date:today,fees:'0',currency:'USD',account:'',note:''}
}

export function PortfolioModule() {
  const client = useQueryClient()
  const today = new Date().toISOString().slice(0,10)
  const [subtab,setSubtab] = useState<PortfolioTab>('overview')
  const [entryOpen,setEntryOpen] = useState(false)
  const [entrySecurity,setEntrySecurity] = useState<SecuritySearchResult|null>(null)
  const [entryForm,setEntryForm] = useState(emptyManualForm(today))
  const [detailSymbol,setDetailSymbol] = useState<string|null>(null)
  const [strategyOpen,setStrategyOpen] = useState(false)

  const summary = useQuery({queryKey:['portfolio-summary'],queryFn:()=>api<PortfolioSummary>('/portfolio/summary'),staleTime:30_000})
  const strategy = useQuery({queryKey:['portfolio-strategy-profile'],queryFn:()=>api<StrategyProfileResponse>('/portfolio/strategy-profile'),staleTime:60_000})
  const benchmark = useQuery({queryKey:['portfolio-benchmark'],queryFn:()=>api<PortfolioBenchmark>('/portfolio/benchmark'),enabled:subtab==='overview',staleTime:15*60_000,refetchInterval:15*60_000})
  const health = useQuery({queryKey:['portfolio-health'],queryFn:()=>api<PortfolioHealth>('/portfolio/health'),enabled:subtab==='health',staleTime:60_000})
  const interpretation = useQuery({queryKey:['portfolio-interpretation'],queryFn:()=>api<PersonalizedInterpretation>('/portfolio/interpretation'),enabled:subtab==='health',staleTime:60_000})
  const transactions = useQuery({queryKey:['portfolio-transactions'],queryFn:()=>api<TransactionRow[]>('/portfolio/transactions'),enabled:subtab==='history'})
  const detail = useQuery({queryKey:['portfolio-technical',detailSymbol],queryFn:()=>api<PositionTechnical>(`/portfolio/positions/${detailSymbol}/technical`),enabled:!!detailSymbol})

  const resetEntry = () => {setEntryOpen(false);setEntrySecurity(null);setEntryForm(emptyManualForm(today))}
  const createEntry = useMutation({
    mutationFn:()=>post('/portfolio/positions',{
      symbol:entrySecurity?.display_symbol||entryForm.symbol.toUpperCase(),
      ...(entrySecurity?securityPayload(entrySecurity):{security_id:null}),
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
  const saveStrategy = useMutation({
    scope:{id:'portfolio-strategy-profile'},
    mutationFn:(changes:Partial<StrategyProfile>)=>api<StrategyProfileResponse>('/portfolio/strategy-profile',{method:'PUT',body:JSON.stringify(changes)}),
    onMutate:async changes=>{
      await client.cancelQueries({queryKey:['portfolio-strategy-profile']})
      const previous=client.getQueryData<StrategyProfileResponse>(['portfolio-strategy-profile'])
      if(previous) client.setQueryData<StrategyProfileResponse>(['portfolio-strategy-profile'],{
        ...previous,profile:{...previous.profile,...changes,updated_at:new Date().toISOString()},
      })
      return {previous}
    },
    onError:(_error,_changes,context)=>{
      if(context?.previous) client.setQueryData(['portfolio-strategy-profile'],context.previous)
    },
    onSuccess:data=>{
      client.setQueryData(['portfolio-strategy-profile'],data)
      client.invalidateQueries({queryKey:['portfolio-interpretation']})
    },
  })
  const resetStrategy = useMutation({
    mutationFn:()=>post<StrategyProfileResponse>('/portfolio/strategy-profile/reset',{}),
    onSuccess:data=>{
      client.setQueryData(['portfolio-strategy-profile'],data)
      client.invalidateQueries({queryKey:['portfolio-interpretation']})
    },
  })
  const saveBenchmark = useMutation({
    mutationFn:(payload:{start_date:string;portfolio_return_percent:number})=>api<PortfolioBenchmark>('/portfolio/benchmark',{method:'PUT',body:JSON.stringify(payload)}),
    onSuccess:data=>client.setQueryData(['portfolio-benchmark'],data),
  })

  const s = summary.data
  const subtabs:[PortfolioTab,string][] = [['overview','持仓概览'],['health','风险体检'],['stress','压力测试'],['scenario','情景分析'],['monte-carlo','蒙特卡洛'],['optimization','组合优化'],['history','历史记录']]
  const openTab = (key:PortfolioTab) => {
    if(key==='technical'&&!detailSymbol&&s?.positions[0]) setDetailSymbol(s.positions[0].symbol)
    setSubtab(key)
  }
  const openTechnical = (symbol:string) => {
    setDetailSymbol(symbol)
    setSubtab('technical')
  }
  const technicalContent = <div className="portfolio-technical">
    <div className="portfolio-technical-list">{s?.positions.map(p=><button key={p.symbol} className={detailSymbol===p.symbol?'active':''} onClick={()=>setDetailSymbol(p.symbol)}>
      <b>{p.symbol}</b><span>{p.price_available?fmtMoney(p.current_price,p.currency):'数据不足'}</span>
    </button>)}{!s?.positions.length&&<div className="empty">还没有持仓可供技术分析。</div>}</div>
    <div className="portfolio-technical-detail">
      {!detailSymbol&&<div className="empty">选择一个持仓查看技术位置。</div>}
      {detailSymbol&&detail.isLoading&&<div className="empty">正在读取技术位置…</div>}
      {detailSymbol&&detail.data&&<PositionTechnicalPanel data={detail.data}/>}
    </div>
  </div>
  const healthContent = <PortfolioHealthView health={health.data} loading={health.isLoading} currency={s?.base_currency||'USD'} interpretation={interpretation.data} interpretationLoading={interpretation.isLoading}/>
  const strategyLabel = strategy.data?.choices.strategy_type?.find(row=>row.value===strategy.data?.profile.strategy_type)?.label||'质量成长'

  return <div className="portfolio-module">
    <div className="section-title">
      <div><p>HOLDINGS</p><h2>持仓</h2></div>
      <div className="section-actions"><button onClick={()=>setEntryOpen(true)}>＋ 手动添加持仓</button></div>
    </div>
    <button className="portfolio-strategy-entry" onClick={()=>setStrategyOpen(true)}>
      <span className="portfolio-strategy-icon" aria-hidden="true">◎</span>
      <span><b>组合策略</b><small>设置投资风格与风险偏好</small></span>
      <strong>{strategy.isLoading?'载入中':strategyLabel}</strong><i aria-hidden="true">›</i>
    </button>
    <div className="portfolio-subtabs">{subtabs.map(([key,label])=><button key={key} className={subtab===key?'active':''} onClick={()=>openTab(key)}>{label}</button>)}</div>

    {subtab==='overview'&&<div className="portfolio-overview">
      {summary.isLoading&&<div className="empty">正在读取持仓数据…</div>}
      {!summary.isLoading&&s&&<>
        <div className="metric-card-row portfolio-metrics">
          <div className="metric-card portfolio-value-card"><span>折算后持仓市值</span><strong>{fmtMoney(s.total_market_value,s.base_currency)}</strong><small>{s.fx_conversion_used?`已按 Yahoo 汇率折算为 ${s.base_currency}`:`以 ${s.base_currency} 计价`}</small>{(s.has_unpriced_positions||s.has_unconverted_positions)&&<small className="portfolio-gap-hint">部分持仓暂未计入汇总</small>}</div>
          <div className="metric-card portfolio-pnl-card"><span>浮动盈亏</span><strong className={((s.total_unrealized_pnl)||0)>=0?'positive':'negative'}>{fmtMoney(s.total_unrealized_pnl,s.base_currency)}</strong><small>{fmtPercent(s.total_unrealized_pnl_percent)}</small></div>
          <div className="metric-card portfolio-count-card"><span>持仓数量</span><strong>{s.position_count}</strong><small>{s.priced_count} 个已折算</small></div>
        </div>
        <PortfolioBenchmarkSection data={benchmark.data} loading={benchmark.isLoading} saving={saveBenchmark.isPending} error={saveBenchmark.error} onSave={payload=>saveBenchmark.mutate(payload)}/>
        <div className="table portfolio-table">
          <div className="table-head portfolio-row"><span>代码</span><span>数量</span><span>成本价</span><span>现价</span><span>市值</span><span>浮动盈亏</span><span>占比</span></div>
          {s.positions.map(p=><button key={p.symbol} className="table-row portfolio-row" onClick={()=>openTechnical(p.symbol)}>
            <span className="toggle">{p.symbol}</span>
            <span data-label="数量">{fmtNum(p.total_quantity)}</span>
            <span data-label="成本价">{fmtMoney(p.average_cost,p.currency)}</span>
            <span data-label="现价">{p.price_available?fmtMoney(p.current_price,p.currency):'数据不足'}</span>
            <span data-label="本币市值">{p.price_available?fmtMoney(p.market_value,p.currency):'数据不足'}</span>
            <span data-label="浮动盈亏" className={(p.unrealized_pnl||0)>=0?'positive':'negative'}>{p.price_available?`${fmtMoney(p.unrealized_pnl,p.currency)} (${fmtPercent(p.unrealized_pnl_percent)})`:'数据不足'}</span>
            <span data-label={`${s.base_currency} 占比`}>{p.portfolio_weight==null?'—':`${p.portfolio_weight.toFixed(1)}%`}</span>
          </button>)}
          {!s.positions.length&&<div className="empty">还没有持仓，点击右上角添加第一笔买入记录。</div>}
        </div>
      </>}
    </div>}

    {subtab==='positions'&&<div className="portfolio-positions">
      {s?.positions.map(p=><article key={p.symbol} className="position-card">
        <div className="position-card-header"><b>{p.symbol}</b><span>{p.currency}</span></div>
        <div className="position-card-grid">
          <div><span>持仓数量</span><b>{fmtNum(p.total_quantity)}</b></div>
          <div><span>平均成本</span><b>{fmtMoney(p.average_cost,p.currency)}</b></div>
          <div><span>总成本</span><b>{fmtMoney(p.total_cost,p.currency)}</b></div>
          <div><span>当前价格</span><b>{p.price_available?fmtMoney(p.current_price,p.currency):'数据不足'}</b></div>
          <div><span>最近交易</span><b>{p.last_transaction_at||'—'}</b></div>
          <div><span>数据来源</span><b>{p.price_available?(p.price_source==='snapshot'?'实时快照':p.price_source==='fmp'?'FMP 日线':'Yahoo 日线'):'数据不足'}</b></div>
        </div>
        <button className="position-detail-btn" onClick={()=>openTechnical(p.symbol)}>查看技术位置 →</button>
      </article>)}
      {!s?.positions.length&&<div className="empty">还没有持仓明细。</div>}
    </div>}

    {subtab==='technical'&&technicalContent}

    {subtab==='health'&&s&&<PortfolioRiskAnalysis portfolioId={s.portfolio_id} currency={s.base_currency} healthContent={healthContent}/>}

    {subtab==='stress'&&s&&<StressTestView portfolioId={s.portfolio_id}/>}
    {subtab==='scenario'&&s&&<ScenarioAnalysisView portfolioId={s.portfolio_id}/>}
    {subtab==='monte-carlo'&&s&&<MonteCarloView portfolioId={s.portfolio_id}/>}
    {subtab==='optimization'&&s&&<PortfolioOptimizationView portfolioId={s.portfolio_id} symbols={s.positions.map(row=>row.symbol)}/>}

    {subtab==='history'&&<div className="portfolio-transactions">
      <PortfolioAnalysisHistory/>
      <div className="portfolio-health-heading"><div><small>TRANSACTIONS</small><h3>交易记录</h3></div></div>
      <div className="table portfolio-txn-table">
        <div className="table-head portfolio-txn-row"><span>日期</span><span>代码</span><span>类型</span><span>数量</span><span>价格</span><span>手续费</span><span>账户</span><span></span></div>
        {transactions.data?.map(t=><div key={t.id} className="table-row portfolio-txn-row">
          <span className="txn-date" data-label="日期">{t.trade_date}</span>
          <span className="txn-symbol" data-label="代码">{t.symbol}</span>
          <span className="txn-type" data-label="类型">{typeLabel[t.transaction_type]||t.transaction_type}</span>
          <span data-label="数量">{fmtNum(t.quantity)}</span>
          <span data-label="价格">{fmtMoney(t.price,t.currency)}</span>
          <span data-label="手续费">{fmtMoney(t.fees,t.currency)}</span>
          <span data-label="账户">{t.account||'—'}</span>
          <button className="danger" onClick={()=>deleteTxn.mutate(t.id)}>删除</button>
        </div>)}
        {!transactions.isLoading&&!transactions.data?.length&&<div className="empty">还没有交易记录。</div>}
      </div>
    </div>}

    <Sheet open={entryOpen} onClose={resetEntry} title="手动添加持仓">
      <form className="portfolio-entry-form" onSubmit={e=>{e.preventDefault();createEntry.mutate()}}>
        <label><span>股票代码</span><SecuritySearchAutocomplete value={entrySecurity} onSelect={sec=>{setEntrySecurity(sec);if(sec)setEntryForm(f=>({...f,symbol:sec.display_symbol,currency:['USD','HKD','CNY','EUR','JPY','GBP','CAD','AUD'].includes(sec.currency||'')?sec.currency!:f.currency}))}} placeholder="搜索代码或公司名称"/></label>
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
    <Sheet open={strategyOpen} onClose={()=>setStrategyOpen(false)} title="组合策略">
      <StrategySettings
        data={strategy.data}
        loading={strategy.isLoading}
        saving={saveStrategy.isPending||resetStrategy.isPending}
        error={saveStrategy.error||resetStrategy.error}
        onSave={changes=>saveStrategy.mutate(changes)}
        onReset={()=>resetStrategy.mutate()}
      />
    </Sheet>
  </div>
}

function PortfolioBenchmarkSection({data,loading,saving,error,onSave}:{
  data:PortfolioBenchmark|undefined;loading:boolean;saving:boolean;error:Error|null
  onSave:(payload:{start_date:string;portfolio_return_percent:number})=>void
}) {
  const today = new Date().toISOString().slice(0,10)
  const [startDate,setStartDate] = useState('')
  const [portfolioReturn,setPortfolioReturn] = useState('')
  useEffect(()=>{
    if(data){setStartDate(data.start_date||'');setPortfolioReturn(data.portfolio_return_percent==null?'':String(data.portfolio_return_percent))}
  },[data?.start_date,data?.portfolio_return_percent])
  const canSave = !!startDate && portfolioReturn.trim()!=='' && Number.isFinite(Number(portfolioReturn))
  return <section className="portfolio-benchmark" aria-label="组合基准对比">
    <div className="portfolio-benchmark-heading"><div><small>PERFORMANCE BASELINE</small><h3>组合与大盘对比</h3></div><span>{data?.configured?'自动同步指数收盘价':'设置后开始比较'}</span></div>
    <p>输入你的入市日与组合至今累计涨跌幅，系统会持续对照 SPY、QQQ、VT；相对收益为你的组合涨跌幅减去对应基准。</p>
    <form className="portfolio-benchmark-form" onSubmit={event=>{event.preventDefault();if(canSave)onSave({start_date:startDate,portfolio_return_percent:Number(portfolioReturn)})}}>
      <label><span>入市日期</span><input type="date" required max={today} value={startDate} onChange={event=>setStartDate(event.target.value)}/></label>
      <label><span>组合累计涨跌幅</span><div className="benchmark-percent-input"><input type="number" required inputMode="decimal" step="any" min="-100" value={portfolioReturn} onChange={event=>setPortfolioReturn(event.target.value)} placeholder="例如 18.5"/><b>%</b></div></label>
      <button disabled={!canSave||saving}>{saving?'正在更新…':data?.configured?'更新基准':'开始比较'}</button>
    </form>
    {error&&<p className="error">保存失败：{error.message}</p>}
    {loading&&<div className="benchmark-empty">正在读取市场基准…</div>}
    {!loading&&data?.configured&&<>
      <div className="benchmark-grid">
        {data.benchmarks.map(row=><article className={row.status==='available'?'':'unavailable'} key={row.symbol}>
          <div><b>{row.symbol}</b><span>{row.name}</span></div>
          {row.status==='available'?<>
            <dl><div><dt>基准涨跌</dt><dd className={(row.return_percent||0)>=0?'positive':'negative'}>{fmtPercent(row.return_percent)}</dd></div><div><dt>相对表现</dt><dd className={(row.relative_return_percent||0)>=0?'positive':'negative'}>{fmtPercent(row.relative_return_percent)}</dd></div></dl>
            <small>{row.start_price_date} 收盘 {fmtMoney(row.start_price)} → {row.latest_price_date} 收盘 {fmtMoney(row.latest_price)}</small>
          </>:<p>{row.message||'数据不足'}</p>}
        </article>)}
      </div>
      <footer>来源：{data.source}。价格基准不含股息再投资；非交易日自动采用其后第一个交易日的收盘价。</footer>
    </>}
  </section>
}

type EditableStrategyField = 'strategy_type'|'investment_horizon'|'risk_tolerance'|'max_single_position'|'max_theme_exposure'|'valuation_preference'|'minimum_quality_score'|'preferred_regions'|'preferred_market_caps'

function StrategySettings({data,loading,saving,error,onSave,onReset}:{
  data:StrategyProfileResponse|undefined
  loading:boolean
  saving:boolean
  error:Error|null
  onSave:(changes:Partial<StrategyProfile>)=>void
  onReset:()=>void
}) {
  const [activeField,setActiveField] = useState<EditableStrategyField|null>(null)
  if(loading||!data) return <div className="empty">正在载入组合策略…</div>
  const {profile,choices}=data
  const labelFor = (field:string,value:string) => choices[field]?.find(row=>row.value===value)?.label||value
  const rows:{field:EditableStrategyField;label:string;value:string}[] = [
    {field:'strategy_type',label:'投资策略',value:labelFor('strategy_type',profile.strategy_type)},
    {field:'risk_tolerance',label:'风险承受能力',value:labelFor('risk_tolerance',profile.risk_tolerance)},
    {field:'investment_horizon',label:'投资期限',value:labelFor('investment_horizon',profile.investment_horizon)},
    {field:'max_single_position',label:'单一持仓上限',value:`${profile.max_single_position.toFixed(0)}%`},
    {field:'max_theme_exposure',label:'主题暴露上限',value:`${profile.max_theme_exposure.toFixed(0)}%`},
    {field:'valuation_preference',label:'估值偏好',value:labelFor('valuation_preference',profile.valuation_preference)},
    {field:'minimum_quality_score',label:'基本面质量门槛',value:`${profile.minimum_quality_score.toFixed(0)} 分`},
    {field:'preferred_regions',label:'偏好区域',value:profile.preferred_regions.map(value=>labelFor('preferred_regions',value)).join('、')},
    {field:'preferred_market_caps',label:'偏好市值规模',value:profile.preferred_market_caps.map(value=>labelFor('preferred_market_caps',value)).join('、')},
  ]
  const singleChoiceFields = new Set<EditableStrategyField>(['strategy_type','risk_tolerance','investment_horizon','valuation_preference'])
  const multiChoiceFields = new Set<EditableStrategyField>(['preferred_regions','preferred_market_caps'])
  const numberOptions = (field:EditableStrategyField) => {
    const start = field==='minimum_quality_score'?0:field==='max_theme_exposure'?10:5
    return Array.from({length:(100-start)/5+1},(_,index)=>start+index*5)
  }
  const chooseSingle = (field:EditableStrategyField,value:string) => {
    if(field==='strategy_type') onSave(data.presets[value]||{strategy_type:value})
    else onSave({[field]:value})
    setActiveField(null)
  }
  const toggleMulti = (field:'preferred_regions'|'preferred_market_caps',value:string) => {
    const current = profile[field]
    if(field==='preferred_regions'&&value==='global') return onSave({[field]:['global']})
    const withoutGlobal = current.filter(item=>item!=='global')
    const next = withoutGlobal.includes(value)?withoutGlobal.filter(item=>item!==value):[...withoutGlobal,value]
    if(next.length) onSave({[field]:next})
  }
  return <div className="strategy-settings">
    <p className="strategy-settings-intro">策略只改变组合健康结果的解读方式，不会修改任何客观评分。</p>
    <div className="strategy-settings-group">
      {rows.map(row=><div className={`strategy-setting ${activeField===row.field?'expanded':''}`} key={row.field}>
        <button type="button" aria-expanded={activeField===row.field} onClick={()=>setActiveField(current=>current===row.field?null:row.field)}>
          <span>{row.label}</span><strong>{row.value}</strong><i aria-hidden="true">›</i>
        </button>
        {activeField===row.field&&<div className="strategy-selector">
          {singleChoiceFields.has(row.field)&&choices[row.field]?.map(option=><button type="button" className={(profile[row.field] as string)===option.value?'selected':''} key={option.value} onClick={()=>chooseSingle(row.field,option.value)}><span>{option.label}</span><b aria-hidden="true">✓</b></button>)}
          {multiChoiceFields.has(row.field)&&choices[row.field]?.map(option=>{const selected=(profile[row.field] as string[]).includes(option.value);return <button type="button" className={selected?'selected':''} key={option.value} onClick={()=>toggleMulti(row.field as 'preferred_regions'|'preferred_market_caps',option.value)}><span>{option.label}</span><b aria-hidden="true">✓</b></button>})}
          {!singleChoiceFields.has(row.field)&&!multiChoiceFields.has(row.field)&&numberOptions(row.field).map(value=>{const selected=profile[row.field]===value;return <button type="button" className={selected?'selected':''} key={value} onClick={()=>{onSave({[row.field]:value});setActiveField(null)}}><span>{value}{row.field==='minimum_quality_score'?' 分':'%'}</span><b aria-hidden="true">✓</b></button>})}
        </div>}
      </div>)}
    </div>
    <button className="strategy-reset" type="button" disabled={saving} onClick={onReset}>恢复此策略的默认值</button>
    <div className="strategy-save-status" role="status">{saving?'正在自动保存…':error?`保存失败：${error.message}`:`已自动保存 · ${new Date(profile.updated_at).toLocaleString('zh-CN')}`}</div>
  </div>
}

function PersonalizedInterpretationSection({data,loading}:{data:PersonalizedInterpretation|undefined;loading:boolean}) {
  return <section className="health-section personalized-interpretation">
    <div className="portfolio-health-heading"><div><small>策略画像</small><h3>个性化解读</h3></div><span>{data?`基于${data.strategy_label}`:'载入中'}</span></div>
    {loading&&<div className="empty">正在结合你的组合策略生成解读…</div>}
    {!loading&&!data&&<p className="health-quiet">个性化解读暂不可用，客观健康评分不受影响。</p>}
    {data&&<>
      <div className="personalized-items">{data.items.map(item=><article className={`personalized-${item.status}`} key={item.id}>
        <span aria-hidden="true">{item.status==='aligned'?'✓':item.status==='caution'?'!':'—'}</span>
        <div><h4>{item.title}</h4><p>{item.message}</p></div>
      </article>)}</div>
      <div className="personalized-summary"><span>总体结论</span><p>{data.overall_summary}</p></div>
      <div className="personalized-recommendations"><h4>组合方向建议</h4>{data.recommendations.map(row=><article key={row.id}><b>{row.title}</b><p>{row.reason}</p></article>)}</div>
      {data.unavailable_dimensions.includes('market_cap')&&<small className="personalized-gap">市值规模暴露尚未进入客观健康分析，本次不据此形成结论。</small>}
    </>}
  </section>
}

function PortfolioHealthView({health,loading,currency,interpretation,interpretationLoading}:{health:PortfolioHealth|undefined;loading:boolean;currency:string;interpretation:PersonalizedInterpretation|undefined;interpretationLoading:boolean}) {
  if(loading) return <div className="empty">正在计算组合健康…</div>
  if(!health) return <div className="empty">组合健康数据暂不可用。</div>
  const scoreClass = (value:number|null,risk=false) => value==null?'muted':risk?(value>60?'risk-high':value>40?'risk-mid':'risk-low'):(value>=80?'score-high':value>=60?'score-mid':'score-low')
  const subscoreLabels:Record<string,string> = {profitability:'盈利能力',growth:'成长质量',cashflow_quality:'现金流质量',balance_sheet_health:'资产负债',capital_efficiency:'资本效率'}
  const coverageLabels:[keyof PortfolioHealth['coverage'],string][] = [['price','价格'],['fundamental','基本面'],['valuation','估值'],['sec','SEC']]
  const freshnessLabel:Record<HealthCoverage['freshness'],string> = {fresh:'数据新鲜',mixed:'部分过期',stale:'数据已过期',unavailable:'暂无数据'}
  const findings = health.findings.slice(0,6)
  return <div className="portfolio-health">
    <div className="portfolio-health-summary">
      <div className="health-score-main">
        <span>组合健康评分</span><strong>{fmtHealthScore(health.health.score)}</strong>
        <b>{health.health.grade}</b><small>综合可信度 {(health.health.confidence*100).toFixed(0)}%</small>
      </div>
      <div className="health-score-item"><span>基本面质量</span><strong className={scoreClass(health.fundamental_quality.score)}>{fmtHealthScore(health.fundamental_quality.score)}</strong><small>{health.fundamental_quality.grade}</small></div>
      <div className="health-score-item"><span>估值风险</span><strong className={scoreClass(health.valuation_risk.score,true)}>{fmtHealthScore(health.valuation_risk.score)}</strong><small>{health.valuation_risk.grade}</small></div>
      <div className="health-score-item"><span>集中度风险</span><strong className={scoreClass(health.concentration.risk_score,true)}>{fmtHealthScore(health.concentration.risk_score)}</strong><small>{health.concentration.grade||'数据不足'}</small></div>
      <div className="health-score-item"><span>SEC 风险</span><strong className={scoreClass(health.sec_risk.score,true)}>{fmtHealthScore(health.sec_risk.score)}</strong><small>{health.sec_risk.grade}</small></div>
    </div>

    <PersonalizedInterpretationSection data={interpretation} loading={interpretationLoading}/>

    <section className="health-section">
      <div className="portfolio-health-heading"><div><small>质量分析</small><h3>基本面质量加权</h3></div><span>覆盖 {health.fundamental_quality.coverage_weight.toFixed(0)}%</span></div>
      <div className="health-dimension-list">
        {Object.entries(health.fundamental_quality.subscores).map(([key,item])=><div className="health-dimension" key={key}>
          <div><b>{subscoreLabels[key]||key}</b><span>覆盖 {item.coverage_weight.toFixed(0)}%</span><strong>{fmtHealthScore(item.score)}</strong></div>
          <i aria-hidden="true"><span style={{width:`${Math.min(100,item.score||0)}%`}}/></i>
        </div>)}
      </div>
      {(health.fundamental_quality.top_positive_contributors.length>0||health.fundamental_quality.top_negative_contributors.length>0)&&<div className="health-contributors">
        <div><span>主要正向贡献</span>{health.fundamental_quality.top_positive_contributors.map(row=><p key={row.symbol}><b>{row.symbol}</b><small>权重 {row.weight.toFixed(1)}%</small><strong>+{row.contribution.toFixed(1)}</strong></p>)}</div>
        <div><span>主要负向贡献</span>{health.fundamental_quality.top_negative_contributors.map(row=><p key={row.symbol}><b>{row.symbol}</b><small>权重 {row.weight.toFixed(1)}%</small><strong>{row.contribution.toFixed(1)}</strong></p>)}</div>
      </div>}
    </section>

    <section className="health-section">
      <div className="portfolio-health-heading"><div><small>估值分析</small><h3>估值风险加权</h3></div><span>可信度 {(health.valuation_risk.average_confidence*100).toFixed(0)}%</span></div>
      <div className="health-stat-line">
        <div><span>组合估值风险</span><strong className={scoreClass(health.valuation_risk.score,true)}>{fmtHealthScore(health.valuation_risk.score)}</strong></div>
        <div><span>估值覆盖率</span><strong>{health.valuation_risk.coverage_weight.toFixed(0)}%</strong></div>
        <div><span>置信度调整后</span><strong>{fmtHealthScore(health.valuation_risk.confidence_adjusted_valuation_risk)}</strong></div>
      </div>
      <div className="health-exposure-grid">
        <div><span>低估仓位</span><strong>{health.valuation_risk.undervalued_weight.toFixed(1)}%</strong></div>
        <div><span>合理估值</span><strong>{health.valuation_risk.fairly_valued_weight.toFixed(1)}%</strong></div>
        <div><span>高估仓位</span><strong>{health.valuation_risk.overvalued_weight.toFixed(1)}%</strong></div>
        <div><span>高风险仓位</span><strong>{health.valuation_risk.high_risk_weight.toFixed(1)}%</strong></div>
        <div><span>低可信仓位</span><strong>{health.valuation_risk.low_confidence_valuation_weight.toFixed(1)}%</strong></div>
      </div>
    </section>

    <section className="health-section">
      <div className="portfolio-health-heading"><div><small>监管披露</small><h3>SEC 风险暴露</h3></div><span>覆盖 {health.sec_risk.coverage_weight.toFixed(0)}%</span></div>
      {health.sec_risk.flag_exposures.length?<div className="health-sec-list">{health.sec_risk.flag_exposures.map(row=><div key={row.flag} className={`sec-${row.severity}`}>
        <div><b>{row.label}</b><span>{row.affected_symbols.join('、')}</span></div><strong>{row.weight.toFixed(1)}%</strong>
      </div>)}</div>:<p className="health-quiet">当前已覆盖持仓中未发现近两年的结构化 SEC 风险事件。</p>}
    </section>

    <section className="health-section">
      <div className="portfolio-health-heading"><div><small>配置结构</small><h3>集中度与配置</h3></div><span>已折算为 {currency}</span></div>
      {health.concentration.available?<>
        <div className="health-stat-line health-concentration-stats">
          <div><span>最大单一持仓</span><strong>{health.concentration.largest_position_weight?.toFixed(1)}%</strong></div>
          <div><span>前三大持仓</span><strong>{health.concentration.top_three_weight?.toFixed(1)}%</strong></div>
          <div><span>前五大持仓</span><strong>{health.concentration.top_five_weight?.toFixed(1)}%</strong></div>
          <div><span>有效持仓数</span><strong>{health.concentration.effective_position_count?.toFixed(1)}</strong></div>
          <div><span>HHI</span><strong>{health.concentration.hhi_scaled?.toFixed(0)}</strong></div>
        </div>
        <div className="portfolio-sector-list">
          {health.concentration.sector_weights.map(b=><div className={`portfolio-sector-item ${b.sector==='未分类'?'muted':''}`} key={b.sector}>
            <div><b>{b.sector}</b><span>{fmtMoney(b.market_value,currency)}</span><strong>{b.weight.toFixed(1)}%</strong></div>
            <i aria-hidden="true"><span style={{width:`${Math.min(100,b.weight)}%`}}/></i>
          </div>)}
        </div>
      </>:<div className="empty">{health.concentration.reason}</div>}
    </section>

    <section className="health-section">
      <div className="portfolio-health-heading"><div><small>规则结论</small><h3>规则化总结</h3></div><span>基于当前持仓</span></div>
      {findings.length?<div className="health-findings">{findings.map(row=><article key={row.id} className={`finding-${row.severity}`}>
        <span>{row.severity==='high'?'高关注':row.severity==='warning'?'需留意':row.severity==='positive'?'积极':'提示'}</span>
        <div><h4>{row.title}</h4><p>{row.message}</p>{row.affected_symbols.length>0&&<small>{row.affected_symbols.join('、')}</small>}</div>
      </article>)}</div>:<p className="health-quiet">当前没有需要突出显示的规则化结论。</p>}
    </section>

    <div className="health-coverage" aria-label="数据覆盖率">
      {coverageLabels.map(([key,label])=>{const item=health.coverage[key];return <div key={key} className={`coverage-${item.status}`}><span>{label}</span><strong>{item.covered_weight.toFixed(0)}%</strong><small>{freshnessLabel[item.freshness]}</small></div>})}
    </div>
    <p className="health-disclaimer">仅审视当前持仓结构与已有分析数据，不评价历史交易表现，也不构成投资建议。</p>
  </div>
}

function PositionTechnicalPanel({data}:{data:PositionTechnical}) {
  if (!data.available) {
    return <div className="empty">{data.unavailable_reason||'技术分析暂不可用。'}</div>
  }
  return <article className="position-technical-panel">
    <div className="position-technical-header">
      <h3>{data.symbol}</h3>
      <strong>{fmtMoney(data.current_price,data.currency)}</strong>
    </div>
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
            <span>{fmtMoney(z.lower_price,data.currency)}–{fmtMoney(z.upper_price,data.currency)}</span>
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
          <b>{est.direction==='resistance'?'上方阻力':'下方支撑'} {fmtMoney(est.target_zone.center_price,data.currency)}</b>
          {est.median_days!=null?<p>预计 {est.median_days} 个交易日左右到达（{est.lower_days}–{est.upper_days} 日区间），仅为概率估算。</p>:<p>{est.unavailable_reason}</p>}
          {est.probability_5d!=null&&<small>5日概率 {Math.round(est.probability_5d*100)}% · 10日 {est.probability_10d!=null?Math.round(est.probability_10d*100):'—'}% · 20日 {est.probability_20d!=null?Math.round(est.probability_20d*100):'—'}%</small>}
        </div>)}
      </section>
    </div>
    {data.analyzer_errors.length>0&&<footer className="portfolio-analyzer-errors">部分分析器暂不可用：{data.analyzer_errors.map(e=>e.analyzer).join('、')}</footer>}
    <footer>来源：{data.market_data_source||'—'} · 数据截至 {data.data_through||'—'}</footer>
  </article>
}
