import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AreaSeries, ColorType, LineSeries, createChart, type IChartApi, type Time } from 'lightweight-charts'
import { api, post } from './api'
import { Sheet } from './Sheet'
import { SecuritySearchAutocomplete, securityPayload, type SecuritySearchResult } from './SecuritySearchAutocomplete'
import { PortfolioRiskAnalysis } from './PortfolioAnalysis'
import { ScenarioAnalysisView, StressTestView } from './PortfolioScenarios'
import { MonteCarloView } from './PortfolioMonteCarlo'
import { PortfolioOptimizationView } from './PortfolioOptimization'
import { chartThemeTokens, getResolvedTheme, subscribeTheme, type ThemeMode } from './theme'
import { PortfolioAnalysisHistory } from './PortfolioAnalysisHistory'
import { RealtimeQuoteCard } from './RealtimeMarketCard'
import { RealtimeMarketEventList } from './RealtimeMarketEvents'
import { mergeRealtimeMarketEvents, useMarketEvents, useRealtimeQuotes, type RealtimeQuote } from './realtime'

// ── 持仓模块类型 ──────────────────────────────────────────────
export type PositionView = {
  symbol:string
  security_id:number|null
  total_quantity:number
  average_cost:number
  total_cost:number
  currency:string
  last_transaction_at:string|null
  price_available:boolean
  current_price:number|null
  previous_close?:number|null
  price_source:string|null
  market_value:number|null
  unrealized_pnl:number|null
  unrealized_pnl_percent:number|null
  daily_change_amount?:number|null
  daily_change_percent?:number|null
  price_as_of?:string|null
  fx_rate:number|null
  fx_rate_source:string|null
  base_currency_market_value:number|null
  base_currency_total_cost:number|null
  base_currency_unrealized_pnl:number|null
  base_currency_realized_pnl:number|null
  base_currency_dividend_income:number|null
  base_currency_fees:number|null
  base_currency_taxes:number|null
  base_currency_total_pnl:number|null
  valuation_available:boolean
  portfolio_weight:number|null
  authority_source?:string
  realized_pnl:number
  dividend_income:number
  fees:number
  taxes:number
  fees_and_taxes:number
  total_pnl:number
  total_return_pct:number|null
  holding_days:number|null
  first_trade_at:string|null
  data_completeness:string
}
export type PortfolioSummary = {
  portfolio_id:number
  base_currency:string
  position_count:number
  priced_count:number
  total_market_value:number
  total_cost:number
  total_unrealized_pnl:number
  total_unrealized_pnl_percent:number|null
  net_asset_value:number|null
  invested_market_value:number
  cash:number
  net_contributions:number|null
  investment_pnl:number|null
  simple_cumulative_return:number|null
  latest_daily_return:number|null
  month_return:number|null
  year_return:number|null
  time_weighted_return:number|null
  realized_pnl:number
  dividend_income:number
  fees:number
  taxes:number
  max_drawdown:number|null
  latest_sync_at:string|null
  account_data_source:string
  market_price_source:string
  data_completeness:number
  has_unpriced_positions:boolean
  has_unconverted_positions:boolean
  fx_conversion_used:boolean
  positions:PositionView[]
}

export type LivePositionView = PositionView & {
  live_quote: RealtimeQuote|null
  live_is_realtime:boolean
  live_price:number|null
  live_market_value:number|null
  live_unrealized_pnl:number|null
  live_unrealized_pnl_percent:number|null
  live_daily_pnl:number|null
  live_daily_pnl_percent:number|null
  live_base_currency_market_value:number|null
  live_base_currency_unrealized_pnl:number|null
  live_base_currency_daily_pnl:number|null
  live_portfolio_weight:number|null
}

export type LivePortfolioView = Omit<PortfolioSummary,'positions'> & {
  positions:LivePositionView[]
  live_quote_count:number
  live_daily_pnl:number|null
  live_daily_pnl_percent:number|null
  live_last_quote_at:string|null
}

const finiteNumber = (value:unknown):value is number => typeof value==='number' && Number.isFinite(value)

/**
 * Revalue only the fields supported by a fresh server-normalized quote. FX is
 * never guessed: a live local-currency price can update a position card while
 * base-currency totals continue to use the last converted value when its FX
 * rate is unavailable.
 */
export function deriveLivePortfolio(summary:PortfolioSummary|undefined, quotes:Record<string,RealtimeQuote>):LivePortfolioView|undefined {
  if(!summary) return undefined
  const rows=summary.positions.map((position):LivePositionView=>{
    const quote=quotes[position.symbol.toUpperCase()]||null
    const freshPrice=quote&&quote.is_stale!==true&&finiteNumber(quote.price)?quote.price:null
    const livePriceAvailable=freshPrice!=null
    const livePrice=freshPrice??position.current_price
    const liveMarketValue=freshPrice!=null?freshPrice*position.total_quantity:position.market_value
    const liveUnrealized=freshPrice!=null?freshPrice*position.total_quantity-position.total_cost:position.unrealized_pnl
    const previousClose=quote&&quote.is_stale!==true&&finiteNumber(quote.previous_close)&&quote.previous_close>0?quote.previous_close:null
    const liveDailyPnl=freshPrice!=null&&previousClose!=null?((freshPrice-previousClose)*position.total_quantity):null
    const liveDailyPercent=livePriceAvailable
      ? (finiteNumber(quote!.change_percent)?quote!.change_percent:(previousClose!=null?(freshPrice!-previousClose)/previousClose*100:null))
      : (position.daily_change_percent??null)
    const fx=finiteNumber(position.fx_rate)?position.fx_rate:null
    const liveBaseMarketValue=freshPrice!=null&&liveMarketValue!=null&&fx!=null?liveMarketValue*fx:position.base_currency_market_value
    const liveBaseUnrealized=freshPrice!=null&&liveUnrealized!=null&&fx!=null?liveUnrealized*fx:position.base_currency_unrealized_pnl
    const liveBaseDailyPnl=liveDailyPnl!=null&&fx!=null?liveDailyPnl*fx:null
    return {
      ...position,
      live_quote:quote,
      live_is_realtime:livePriceAvailable&&quote!.is_delayed!==true,
      live_price:livePrice,
      live_market_value:liveMarketValue,
      live_unrealized_pnl:liveUnrealized,
      live_unrealized_pnl_percent:liveUnrealized!=null&&position.total_cost>0?liveUnrealized/position.total_cost*100:position.unrealized_pnl_percent,
      live_daily_pnl:liveDailyPnl,
      live_daily_pnl_percent:liveDailyPercent,
      live_base_currency_market_value:liveBaseMarketValue,
      live_base_currency_unrealized_pnl:liveBaseUnrealized,
      live_base_currency_daily_pnl:liveBaseDailyPnl,
      live_portfolio_weight:position.portfolio_weight,
    }
  })
  const valued=rows.map(row=>row.live_base_currency_market_value).filter(finiteNumber)
  const unrealized=rows.map(row=>row.live_base_currency_unrealized_pnl).filter(finiteNumber)
  const daily=rows.map(row=>row.live_base_currency_daily_pnl).filter(finiteNumber)
  const dailyBase=rows.map(row=>{
    const quote=row.live_quote
    if(!quote||quote.is_stale===true||!finiteNumber(quote.price)||!finiteNumber(quote.previous_close)||quote.previous_close<=0||!finiteNumber(row.fx_rate)) return null
    return quote.previous_close*row.total_quantity*row.fx_rate
  }).filter(finiteNumber)
  const totalMarketValue=valued.length?valued.reduce((sum,value)=>sum+value,0):summary.total_market_value
  const totalUnrealized=unrealized.length?unrealized.reduce((sum,value)=>sum+value,0):summary.total_unrealized_pnl
  const totalDailyPnl=daily.length?daily.reduce((sum,value)=>sum+value,0):null
  const totalDailyPnlPercent=totalDailyPnl!=null&&dailyBase.length&&dailyBase.reduce((sum,value)=>sum+value,0)>0
    ? totalDailyPnl/dailyBase.reduce((sum,value)=>sum+value,0)*100
    : null
  const netAssetValue=finiteNumber(summary.cash)&&valued.length?totalMarketValue+summary.cash:summary.net_asset_value
  const investmentPnl=netAssetValue!=null&&summary.net_contributions!=null?netAssetValue-summary.net_contributions:summary.investment_pnl
  const simpleReturn=investmentPnl!=null&&summary.net_contributions!=null&&summary.net_contributions>0?investmentPnl/summary.net_contributions:summary.simple_cumulative_return
  const weightedTotal=totalMarketValue>0?totalMarketValue:null
  for(const row of rows) row.live_portfolio_weight=row.live_base_currency_market_value!=null&&weightedTotal!=null?row.live_base_currency_market_value/weightedTotal*100:row.portfolio_weight
  const latest=rows.map(row=>row.live_quote?.timestamp||row.live_quote?.received_at||null).filter((value):value is string=>!!value).sort().at(-1)||null
  return {
    ...summary,
    positions:rows,
    total_market_value:totalMarketValue,
    invested_market_value:totalMarketValue,
    total_unrealized_pnl:totalUnrealized,
    total_unrealized_pnl_percent:summary.total_cost>0?totalUnrealized/summary.total_cost*100:summary.total_unrealized_pnl_percent,
    net_asset_value:netAssetValue,
    investment_pnl:investmentPnl,
    simple_cumulative_return:simpleReturn,
    live_quote_count:rows.filter(row=>row.live_quote&&finiteNumber(row.live_quote.price)&&row.live_quote.is_stale!==true).length,
    live_daily_pnl:totalDailyPnl,
    live_daily_pnl_percent:totalDailyPnlPercent,
    live_last_quote_at:latest,
  }
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
export type PortfolioHealth = {
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
  account_analytics:{fact_type:string;historical_performance_is_not_forecast:boolean;time_weighted_return:number|null;max_drawdown:number|null;realized_pnl:number|null;unrealized_pnl:number|null;dividend_income:number|null;fees_and_taxes:number;cash_weight:number;largest_positive_contributor:{symbol:string;total_pnl:number}|null;largest_negative_contributor:{symbol:string;total_pnl:number}|null;data_completeness:number;source:string}
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
export type PersonalizedInterpretation = {
  strategy_type:string
  strategy_label:string
  evaluated_at:string
  items:{id:string;dimension:string;status:'aligned'|'caution'|'unavailable';title:string;message:string;evidence:Record<string,unknown>}[]
  overall_summary:string
  recommendations:{id:string;title:string;reason:string;priority:number}[]
  unavailable_dimensions:string[]
}
type TransactionRow = {
  event_id:string
  symbol:string|null
  event_type:string
  occurred_at:string|null
  quantity:number|null
  price:number|null
  commission:number
  tax:number
  gross_amount:number|null
  realized_pnl:number|null
  currency:string
  account:string|null
  note:string|null
  source_type:string
  authority_source:string
  authority_status:string
  is_authoritative:boolean
  is_editable:boolean
}
type PerformancePoint = {date:string;nav:number|null;net_contributions:number|null;investment_value:number|null;daily_return:number|null;cumulative_return:number|null;cash_flow_adjusted_index?:number|null;drawdown:number|null;benchmark_return:number|null;data_completeness:number}
type PerformanceSeries = {items:PerformancePoint[];source:string|null;calculation_method:string;data_completeness:number;warnings:string[];latest_sync_at:string|null}
type AttributionItem = {
  symbol:string
  total_pnl:number|null
  base_currency_total_pnl?:number|null
  realized_pnl:number
  unrealized_pnl:number
  dividends:number
  fees:number
  taxes:number
  fx_pnl:number
  valuation_available?:boolean
  position_status?:'open'|'closed'|string|null
  status?:'open'|'closed'|string|null
}
type ReturnAttribution = {items:AttributionItem[];base_currency?:string;source:string|null;warnings:string[];latest_sync_at?:string|null;coverage?:{ranked_count?:number;unconverted_symbols?:string[]}}
type PositionLedgerDetail = {
  summary:PositionView
  performance_curve:{date:string;market_value:number|null;cumulative_investment:number|null;cumulative_pnl:number|null;return_pct:number|null;data_completeness:number}[]
  timeline:TransactionRow[]
  open_lots:{lot_id:string;opened_at:string|null;quantity:number|null;cost_basis:number|null;cost_per_share:number|null;unrealized_pnl:number|null;status:string;matching_method:string;source_type:string}[]
  completed_trades:{id:number;opened_at:string|null;closed_at:string|null;quantity:number|null;average_entry_price:number|null;average_exit_price:number|null;gross_pnl:number|null;commissions:number|null;taxes:number|null;net_pnl:number|null;return_pct:number|null;holding_days:number|null;matching_method:string;source_type:string;warnings:string[]}[]
  data_sources:{account_facts:string;market_prices:string;derived:string}
  latest_sync_at:string|null
}
type CompletedTrade = PositionLedgerDetail['completed_trades'][number]&{symbol:string|null;account:string|null;is_authoritative:boolean}
type OpenLot = PositionLedgerDetail['open_lots'][number]&{symbol:string|null;account:string|null;currency:string;is_authoritative:boolean}
type PortfolioBenchmark = {
  start_date:string|null
  portfolio_return_percent:number|null
  configured:boolean
  portfolio_return_source:'ibkr_flex'|'manual'|'unavailable'
  benchmarks:{symbol:string;name:string;start_price:number|null;start_price_date:string|null;latest_price:number|null;latest_price_date:string|null;return_percent:number|null;relative_return_percent:number|null;status:'available'|'unavailable';message:string|null}[]
  source:string
  as_of:string
}

export const fmtMoney = (value:number|null, currency='USD') => value==null?'数据不足':`${currency==='USD'?'$':currency+' '}${value.toLocaleString('zh-CN',{maximumFractionDigits:2,minimumFractionDigits:2})}`
export const fmtPercent = (value:number|null) => value==null?'—':`${value>=0?'+':''}${value.toFixed(2)}%`
const fmtRatio = (value:number|null) => value==null?'—':fmtPercent(value*100)
export const fmtNum = (value:number, digits=4) => value.toLocaleString('zh-CN',{maximumFractionDigits:digits})
export const fmtHealthScore = (value:number|null) => value==null?'数据不足':Math.round(value).toString()
const typeLabel:Record<string,string> = {buy:'买入',sell:'卖出',dividend:'股息',fee:'费用',commission:'手续费',withholding_tax:'预扣税',broker_fee:'券商费用',margin_interest:'融资利息',interest_income:'利息收入',fx_conversion:'外汇转换',deposit:'转入现金',withdrawal:'转出现金',split:'拆股',transfer_in:'转入',transfer_out:'转出'}
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
  const [positionSheetSymbol,setPositionSheetSymbol] = useState<string|null>(null)
  const [strategyOpen,setStrategyOpen] = useState(false)
  const [performanceRange,setPerformanceRange] = useState('1Y')
  const [historyType,setHistoryType] = useState('all')
  const [historyView,setHistoryView] = useState<'activity'|'completed'|'lots'>('activity')

  const summary = useQuery({queryKey:['portfolio-summary'],queryFn:()=>api<PortfolioSummary>('/portfolio/summary'),staleTime:20_000,refetchInterval:30_000,refetchIntervalInBackground:true})
  const realtime = useRealtimeQuotes(summary.data?.positions.map(row=>row.symbol)||[])
  const eventHistory = useMarketEvents(summary.data?.positions.map(row=>row.symbol)||[])
  const strategy = useQuery({queryKey:['portfolio-strategy-profile'],queryFn:()=>api<StrategyProfileResponse>('/portfolio/strategy-profile'),staleTime:60_000})
  const benchmark = useQuery({queryKey:['portfolio-benchmark'],queryFn:()=>api<PortfolioBenchmark>('/portfolio/benchmark'),enabled:subtab==='overview',staleTime:15*60_000,refetchInterval:15*60_000})
  const performance = useQuery({queryKey:['portfolio-performance',performanceRange],queryFn:()=>api<PerformanceSeries>(`/portfolio/performance?range=${performanceRange}`),enabled:subtab==='overview',staleTime:30_000})
  const attribution = useQuery({queryKey:['portfolio-attribution'],queryFn:()=>api<ReturnAttribution>('/portfolio/attribution'),enabled:subtab==='overview',staleTime:30_000})
  const health = useQuery({queryKey:['portfolio-health'],queryFn:()=>api<PortfolioHealth>('/portfolio/health'),enabled:subtab==='health',staleTime:60_000})
  const interpretation = useQuery({queryKey:['portfolio-interpretation'],queryFn:()=>api<PersonalizedInterpretation>('/portfolio/interpretation'),enabled:subtab==='health',staleTime:60_000})
  const transactions = useQuery({queryKey:['portfolio-transactions',historyType],queryFn:()=>api<TransactionRow[]>(`/portfolio/transactions${historyType==='all'?'':`?event_type=${historyType}`}`),enabled:subtab==='history'&&historyView==='activity'})
  const completedTrades = useQuery({queryKey:['portfolio-completed-trades'],queryFn:()=>api<CompletedTrade[]>('/portfolio/completed-trades'),enabled:subtab==='history'&&historyView==='completed'})
  const openLots = useQuery({queryKey:['portfolio-open-lots'],queryFn:()=>api<OpenLot[]>('/portfolio/open-lots'),enabled:subtab==='history'&&historyView==='lots'})
  const detail = useQuery({queryKey:['portfolio-technical',detailSymbol],queryFn:()=>api<PositionTechnical>(`/portfolio/positions/${detailSymbol}/technical`),enabled:!!detailSymbol})
  const ledgerDetail = useQuery({queryKey:['portfolio-position-ledger',detailSymbol],queryFn:()=>api<PositionLedgerDetail>(`/portfolio/positions/${detailSymbol}`),enabled:!!detailSymbol})

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
  const live = useMemo(()=>deriveLivePortfolio(s,realtime.quotes),[s,realtime.quotes])
  const displayPositions = live?.positions||[]
  const liveEvents = mergeRealtimeMarketEvents(realtime.events,eventHistory.data||[])
  const subtabs:[PortfolioTab,string][] = [['overview','组合中心'],['health','风险体检'],['stress','压力测试'],['scenario','情景分析'],['monte-carlo','蒙特卡洛'],['optimization','组合优化'],['history','交易历史']]
  const openTab = (key:PortfolioTab) => {
    if(key==='technical'&&!detailSymbol&&live?.positions[0]) setDetailSymbol(live.positions[0].symbol)
    setSubtab(key)
  }
  const openTechnical = (symbol:string) => {
    setDetailSymbol(symbol)
    setSubtab('technical')
  }
  const technicalContent = <div className="portfolio-position-center">
    {detailSymbol&&ledgerDetail.isLoading&&<div className="empty">正在读取账户持仓事实…</div>}
    {detailSymbol&&ledgerDetail.data&&<PositionAccountPanel data={ledgerDetail.data}/>}
    <div className="portfolio-technical">
    <div className="portfolio-technical-list">{live?.positions.map(p=><button key={p.symbol} className={detailSymbol===p.symbol?'active':''} onClick={()=>setDetailSymbol(p.symbol)}>
      <b>{p.symbol}</b><span>{p.live_price!=null?fmtMoney(p.live_price,p.currency):'数据不足'}</span>
    </button>)}{!live?.positions.length&&<div className="empty">还没有持仓可供技术分析。</div>}</div>
    <div className="portfolio-technical-detail">
      {!detailSymbol&&<div className="empty">选择一个持仓查看技术位置。</div>}
      {detailSymbol&&detail.isLoading&&<div className="empty">正在读取技术位置…</div>}
      {detailSymbol&&detail.data&&<PositionTechnicalPanel data={detail.data}/>}
    </div>
    </div>
  </div>
  const healthContent = <PortfolioHealthView health={health.data} loading={health.isLoading} currency={s?.base_currency||'USD'} interpretation={interpretation.data} interpretationLoading={interpretation.isLoading}/>
  const strategyLabel = strategy.data?.choices.strategy_type?.find(row=>row.value===strategy.data?.profile.strategy_type)?.label||'质量成长'
  const positionSheet = live?.positions.find(row=>row.symbol===positionSheetSymbol)
  const openPosition = (symbol:string) => {
    if(window.matchMedia('(max-width: 700px)').matches) setPositionSheetSymbol(symbol)
    else openTechnical(symbol)
  }

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
        <section className="portfolio-account-source"><span>账户数据：{s.account_data_source==='ibkr_flex'?'IBKR':'手动账本'}</span><span>市场价格：{live?.live_quote_count?`实时行情 · ${live.live_quote_count}/${s.positions.length}`:'项目行情系统'}</span><span>最近同步：{s.latest_sync_at?new Date(s.latest_sync_at).toLocaleString('zh-CN'):'尚未同步'}</span></section>
        <div className="metric-card-row portfolio-metrics ledger-metrics">
          <div className="metric-card portfolio-value-card"><span>组合净值</span><strong>{fmtMoney(live?.net_asset_value??s.net_asset_value,s.base_currency)}</strong><small>持仓 {fmtMoney(live?.invested_market_value??s.invested_market_value,s.base_currency)} · 现金 {fmtMoney(s.cash,s.base_currency)}</small>{(s.has_unpriced_positions||s.has_unconverted_positions)&&<small className="portfolio-gap-hint">部分持仓暂未计入汇总</small>}</div>
          <div className="metric-card"><span>累计投资盈亏</span><strong className={(live?.investment_pnl||0)>=0?'positive':'negative'}>{fmtMoney(live?.investment_pnl??s.investment_pnl,s.base_currency)}</strong><small>账户净值 {fmtMoney(live?.net_asset_value??s.net_asset_value,s.base_currency)} − 累计净入金 {fmtMoney(s.net_contributions,s.base_currency)}<br/>简单累计收益率 {fmtRatio(live?.simple_cumulative_return??s.simple_cumulative_return)}</small></div>
          <div className="metric-card"><span>时间加权收益率</span><strong className={(s.time_weighted_return||0)>=0?'positive':'negative'}>{fmtRatio(s.time_weighted_return)}</strong><small>今日 {fmtRatio(s.latest_daily_return)} · 本月 {fmtRatio(s.month_return)} · 年内 {fmtRatio(s.year_return)}</small></div>
          <div className="metric-card"><span>实时日内盈亏</span><strong className={(live?.live_daily_pnl||0)>=0?'positive':'negative'}>{fmtMoney(live?.live_daily_pnl??null,s.base_currency)}</strong><small>{live?.live_daily_pnl_percent==null?'需要新鲜前收与汇率数据':`日内 ${fmtPercent(live.live_daily_pnl_percent)}`} · 仅统计可实时重算持仓</small></div>
          <div className="metric-card"><span>盈亏构成</span><strong>{fmtMoney(s.realized_pnl+(live?.total_unrealized_pnl??s.total_unrealized_pnl)+s.dividend_income-s.fees-s.taxes,s.base_currency)}</strong><small>已实现 {fmtMoney(s.realized_pnl,s.base_currency)} · 未实现 {fmtMoney(live?.total_unrealized_pnl??s.total_unrealized_pnl,s.base_currency)}</small></div>
          <div className="metric-card"><span>股息与费用</span><strong>{fmtMoney(s.dividend_income-s.fees-s.taxes,s.base_currency)}</strong><small>股息 {fmtMoney(s.dividend_income,s.base_currency)} · 费用税费 {fmtMoney(s.fees+s.taxes,s.base_currency)}</small></div>
          <div className="metric-card"><span>最大回撤</span><strong className="negative">{fmtRatio(s.max_drawdown)}</strong><small>现金流调整后账户曲线</small></div>
        </div>
        <MobilePerformanceOverview summary={live||s} benchmark={benchmark.data}/>
        <RealtimeMarketEventList events={liveEvents} title="组合盘中事件" subtitle="持仓的突破、VWAP、放量与指标事件" compact/>
        <PortfolioPerformanceChart data={performance.data} loading={performance.isLoading} error={performance.isError} range={performanceRange} onRange={setPerformanceRange} currency={s.base_currency}/>
        <ReturnAttributionPreview data={attribution.data} positions={live?.positions||s.positions} currency={s.base_currency} loading={attribution.isLoading}/>
        <PortfolioBenchmarkSection data={benchmark.data} loading={benchmark.isLoading} saving={saveBenchmark.isPending} error={saveBenchmark.error} onSave={payload=>saveBenchmark.mutate(payload)}/>
        <div className="table portfolio-table">
          <div className="table-head portfolio-row"><span>证券</span><span>市值</span><span>权重</span><span>平均成本</span><span>未实现盈亏</span><span>总收益</span><span>来源</span></div>
          {displayPositions.map(p=><button key={p.symbol} className="table-row portfolio-row" onClick={()=>openPosition(p.symbol)}>
            <span className="toggle">{p.symbol}</span>
            <span data-label="本币市值">{p.live_price!=null?fmtMoney(p.live_market_value,p.currency):p.price_available?fmtMoney(p.market_value,p.currency):'数据不足'}</span>
            <span data-label={`${s.base_currency} 占比`}>{p.live_portfolio_weight==null?p.portfolio_weight==null?'—':`${p.portfolio_weight.toFixed(1)}%`:`${p.live_portfolio_weight.toFixed(1)}%`}</span>
            <span data-label="平均成本">{fmtMoney(p.average_cost,p.currency)}<small>{fmtNum(p.total_quantity)} 股</small></span>
            <span data-label="浮动盈亏" className={((p.live_unrealized_pnl??p.unrealized_pnl)||0)>=0?'positive':'negative'}>{p.live_price!=null?`${fmtMoney(p.live_unrealized_pnl,p.currency)} (${fmtPercent(p.live_unrealized_pnl_percent)})`:p.price_available?`${fmtMoney(p.unrealized_pnl,p.currency)} (${fmtPercent(p.unrealized_pnl_percent)})`:'数据不足'}{(p.live_daily_pnl_percent??p.daily_change_percent)!=null&&<small className={((p.live_daily_pnl_percent??p.daily_change_percent)||0)>=0?'positive':'negative'}>今日 {fmtPercent(p.live_daily_pnl_percent??p.daily_change_percent??null)}</small>}</span>
            <span data-label="总收益" className={(p.total_pnl||0)>=0?'positive':'negative'}>{fmtMoney(p.total_pnl,p.currency)} ({fmtPercent(p.total_return_pct)})</span>
            <span data-label="账户来源">{p.authority_source==='ibkr_flex'?'IBKR':'手动'}<small>{p.data_completeness==='complete'?'完整':'部分数据'}</small></span>
          </button>)}
          {!displayPositions.length&&<div className="empty">还没有持仓，点击右上角添加第一笔买入记录。</div>}
        </div>
      </>}
    </div>}

    {subtab==='positions'&&<div className="portfolio-positions">
      {displayPositions.map(p=><article key={p.symbol} className="position-card">
        <div className="position-card-header"><b>{p.symbol}</b><span>{p.currency}</span></div>
        <div className="position-card-grid">
          <div><span>持仓数量</span><b>{fmtNum(p.total_quantity)}</b></div>
          <div><span>平均成本</span><b>{fmtMoney(p.average_cost,p.currency)}</b></div>
          <div><span>总成本</span><b>{fmtMoney(p.total_cost,p.currency)}</b></div>
          <div><span>当前价格</span><b>{p.live_price!=null?fmtMoney(p.live_price,p.currency):p.price_available?fmtMoney(p.current_price,p.currency):'数据不足'}</b></div>
          <div><span>最近交易</span><b>{p.last_transaction_at||'—'}</b></div>
          <div><span>数据来源</span><b>{p.live_is_realtime?'实时行情':p.price_available?(p.price_source==='snapshot'?'已入库快照':p.price_source==='fmp'?'FMP 日线':'Yahoo 日线'):'数据不足'}</b></div>
        </div>
        <RealtimeQuoteCard symbol={p.symbol} quote={realtime.quotes[p.symbol.toUpperCase()]} streamStatus={realtime.streamStatus} lastUpdateAt={realtime.lastUpdateAt} compact/>
        <button className="position-detail-btn" onClick={()=>openTechnical(p.symbol)}>查看技术位置 →</button>
      </article>)}
      {!displayPositions.length&&<div className="empty">还没有持仓明细。</div>}
    </div>}

    {subtab==='technical'&&technicalContent}

    {subtab==='health'&&s&&<PortfolioRiskAnalysis portfolioId={s.portfolio_id} currency={s.base_currency} healthContent={healthContent}/>}

    {subtab==='stress'&&s&&<StressTestView portfolioId={s.portfolio_id}/>}
    {subtab==='scenario'&&s&&<ScenarioAnalysisView portfolioId={s.portfolio_id}/>}
    {subtab==='monte-carlo'&&s&&<MonteCarloView portfolioId={s.portfolio_id}/>}
    {subtab==='optimization'&&s&&<PortfolioOptimizationView portfolioId={s.portfolio_id} symbols={s.positions.map(row=>row.symbol)}/>}

    {subtab==='history'&&<div className="portfolio-transactions">
      <PortfolioAnalysisHistory/>
      <div className="portfolio-health-heading"><div><small>UNIFIED LEDGER</small><h3>全局交易历史</h3></div><span>成交是投资事实；IBKR 记录只读</span></div>
      <div className="position-ledger-tabs global-ledger-tabs">{([['activity','成交与现金活动'],['completed','完整交易闭环'],['lots','当前开放批次']] as const).map(([key,label])=><button key={key} className={historyView===key?'active':''} onClick={()=>setHistoryView(key)}>{label}</button>)}</div>
      {historyView==='activity'&&<><div className="ledger-filters">{[['all','全部活动'],['buy','买入'],['sell','卖出'],['dividend','股息'],['deposit','入金'],['withdrawal','出金'],['commission','手续费'],['withholding_tax','税费']] .map(([key,label])=><button key={key} className={historyType===key?'active':''} onClick={()=>setHistoryType(key)}>{label}</button>)}</div>
      <div className="table portfolio-txn-table">
        <div className="table-head portfolio-txn-row"><span>时间</span><span>代码</span><span>事件</span><span>数量</span><span>价格</span><span>费用 / 税</span><span>来源</span><span></span></div>
        {transactions.data?.map(t=><div key={t.event_id} className="table-row portfolio-txn-row">
          <span className="txn-date" data-label="时间">{t.occurred_at?new Date(t.occurred_at).toLocaleString('zh-CN'):'—'}</span>
          <span className="txn-symbol" data-label="代码">{t.symbol||'账户'}</span>
          <span className="txn-type" data-label="事件">{typeLabel[t.event_type]||t.event_type}</span>
          <span data-label="数量">{t.quantity==null?'—':fmtNum(t.quantity)}</span>
          <span data-label="价格">{fmtMoney(t.price,t.currency)}</span>
          <span data-label="费用 / 税">{fmtMoney(t.commission+t.tax,t.currency)}</span>
          <span data-label="来源">{t.authority_source==='ibkr_flex'?'IBKR · 只读':'手动账本'}</span>
          {t.is_editable?<button className="danger" onClick={()=>deleteTxn.mutate(Number(t.event_id.split(':')[1]))}>删除</button>:<small className="ledger-readonly">券商事实</small>}
        </div>)}
        {!transactions.isLoading&&!transactions.data?.length&&<div className="empty">还没有交易记录。</div>}
      </div></>}
      {historyView==='completed'&&<div className="position-ledger-list global-ledger-list">{completedTrades.data?.map(row=><article key={row.id}><b>{row.symbol||'—'}</b><span>{row.opened_at?new Date(row.opened_at).toLocaleDateString('zh-CN'):'—'} → {row.closed_at?new Date(row.closed_at).toLocaleDateString('zh-CN'):'—'}</span><span>{fmtNum(row.quantity||0)} 股 · 持有 {row.holding_days??'—'} 天</span><span>{fmtMoney(row.average_entry_price)} → {fmtMoney(row.average_exit_price)}</span><strong className={(row.net_pnl||0)>=0?'positive':'negative'}>{fmtMoney(row.net_pnl)} · {fmtRatio(row.return_pct)}</strong></article>)}{!completedTrades.isLoading&&!completedTrades.data?.length&&<div className="empty">暂无已完成交易闭环。</div>}</div>}
      {historyView==='lots'&&<div className="position-ledger-list global-ledger-list">{openLots.data?.map(row=><article key={row.lot_id}><b>{row.symbol||'—'}</b><span>{row.opened_at?String(row.opened_at):'日期不足'}</span><span>{fmtNum(row.quantity||0)} 股</span><span>成本 {fmtMoney(row.cost_basis,row.currency)}</span><strong>{row.source_type==='ibkr_flex'?'IBKR 批次':'手动批次'}</strong></article>)}{!openLots.isLoading&&!openLots.data?.length&&<div className="empty">暂无开放成本批次。</div>}</div>}
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
    <Sheet open={positionSheet!==undefined} onClose={()=>setPositionSheetSymbol(null)} title={positionSheet?`${positionSheet.symbol} 持仓详情`:'持仓详情'}>
      {positionSheet&&<MobilePositionDetail position={positionSheet} baseCurrency={s?.base_currency||positionSheet.currency} realtime={realtime.quotes[positionSheet.symbol.toUpperCase()]} streamStatus={realtime.streamStatus} lastUpdateAt={realtime.lastUpdateAt} onTechnical={()=>{setPositionSheetSymbol(null);openTechnical(positionSheet.symbol)}}/>}
    </Sheet>
  </div>
}

function MobilePerformanceOverview({summary,benchmark}:{summary:PortfolioSummary;benchmark:PortfolioBenchmark|undefined}) {
  return <section className="mobile-performance-overview" aria-label="持仓与指数表现">
    <header><div><small>PERFORMANCE AT A GLANCE</small><h3>持仓与指数表现</h3></div><span>{summary.latest_sync_at?`IBKR ${new Date(summary.latest_sync_at).toLocaleDateString('zh-CN')}`:'等待 IBKR 同步'}</span></header>
    <div className="mobile-return-strip">
      <div><span>今日</span><strong className={(summary.latest_daily_return||0)>=0?'positive':'negative'}>{fmtRatio(summary.latest_daily_return)}</strong></div>
      <div><span>本月</span><strong className={(summary.month_return||0)>=0?'positive':'negative'}>{fmtRatio(summary.month_return)}</strong></div>
      <div><span>年内</span><strong className={(summary.year_return||0)>=0?'positive':'negative'}>{fmtRatio(summary.year_return)}</strong></div>
      <div><span>累计</span><strong className={(summary.time_weighted_return||0)>=0?'positive':'negative'}>{fmtRatio(summary.time_weighted_return)}</strong></div>
    </div>
    <div className="mobile-benchmark-grid">
      {(benchmark?.benchmarks||[]).map(row=><article key={row.symbol} className={row.status==='available'?'':'unavailable'}>
        <div><b>{row.symbol}</b><span>{row.name}</span></div>
        {row.status==='available'?<><strong className={(row.return_percent||0)>=0?'positive':'negative'}>{fmtPercent(row.return_percent)}</strong><small className={(row.relative_return_percent||0)>=0?'positive':'negative'}>相对 {fmtPercent(row.relative_return_percent)}</small></>:<small>数据不足</small>}
      </article>)}
      {!benchmark?.configured&&<p>在下方设置入市日期与累计涨跌幅后，这里会同步显示 SPY、QQQ、DIA 及相对表现。</p>}
    </div>
  </section>
}

function MobilePositionDetail({position,baseCurrency,realtime,streamStatus,lastUpdateAt,onTechnical}:{position:LivePositionView;baseCurrency:string;realtime?:import('./realtime').RealtimeQuote;streamStatus:import('./realtime').RealtimeStreamStatus;lastUpdateAt:string|null;onTechnical:()=>void}) {
  const fields = [
    ['当前价格',position.live_price!=null?fmtMoney(position.live_price,position.currency):position.price_available?fmtMoney(position.current_price,position.currency):'数据不足'],
    ['持仓数量',`${fmtNum(position.total_quantity)} 股`],
    ['本币市值',position.live_price!=null?fmtMoney(position.live_market_value,position.currency):position.price_available?fmtMoney(position.market_value,position.currency):'数据不足'],
    [`${baseCurrency} 市值`,fmtMoney(position.live_base_currency_market_value,baseCurrency)],
    ['组合权重',position.live_portfolio_weight==null?'—':`${position.live_portfolio_weight.toFixed(1)}%`],
    ['平均成本',fmtMoney(position.average_cost,position.currency)],
    ['浮动盈亏',position.live_price!=null?`${fmtMoney(position.live_unrealized_pnl,position.currency)} · ${fmtPercent(position.live_unrealized_pnl_percent)}`:position.price_available?`${fmtMoney(position.unrealized_pnl,position.currency)} · ${fmtPercent(position.unrealized_pnl_percent)}`:'数据不足'],
    ['今日涨跌',fmtPercent(position.live_daily_pnl_percent??position.daily_change_percent??null)],
    ['总收益',`${fmtMoney(position.total_pnl,position.currency)} · ${fmtPercent(position.total_return_pct)}`],
    ['账户来源',position.authority_source==='ibkr_flex'?'IBKR 权威持仓':'手动账本'],
  ]
  return <article className="mobile-position-detail">
    <header><div><small>{position.currency} · {position.authority_source==='ibkr_flex'?'IBKR SYNCED':'MANUAL'}</small><h2>{position.symbol}</h2></div><strong className={((position.live_unrealized_pnl??position.unrealized_pnl)||0)>=0?'positive':'negative'}>{fmtPercent(position.live_unrealized_pnl_percent??position.unrealized_pnl_percent)}</strong></header>
    <div>{fields.map(([label,value])=><section key={label}><span>{label}</span><b>{value}</b></section>)}</div>
    <RealtimeQuoteCard symbol={position.symbol} quote={realtime} streamStatus={streamStatus} lastUpdateAt={lastUpdateAt} compact/>
    <p>数量与成本取自最近成功同步的 IBKR 持仓事实；行情由项目价格快照自动更新，无需在 IBKR 页面手动刷新持仓列表。</p>
    <button onClick={onTechnical}>查看技术位置与账户时间线 <span>→</span></button>
  </article>
}

export function chartPoints(values:(number|null)[],width=720,height=190) {
  const present=values.filter((value):value is number=>value!=null)
  if(present.length<2)return ''
  const min=Math.min(...present),max=Math.max(...present),span=max-min||1
  return values.map((value,index)=>value==null?'':`${(index/Math.max(1,values.length-1)*width).toFixed(1)},${(height-(value-min)/span*height).toFixed(1)}`).filter(Boolean).join(' ')
}

function chartPointsDomain(values:(number|null)[],min:number,max:number,width=720,height=190) {
  if(!Number.isFinite(min)||!Number.isFinite(max))return ''
  const span=max-min||1
  return values.map((value,index)=>value==null?'':`${(index/Math.max(1,values.length-1)*width).toFixed(1)},${(height-(value-min)/span*height).toFixed(1)}`).filter(Boolean).join(' ')
}

function chartTheme() {
  return chartThemeTokens()
}

function observeChart(host:HTMLDivElement,chart:IChartApi) {
  const observer=new ResizeObserver(entries=>chart.applyOptions({width:entries[0].contentRect.width}))
  observer.observe(host)
  return observer
}

export function cashFlowAdjustedGrowth(point:PerformancePoint) {
  if(point.cash_flow_adjusted_index!=null)return point.cash_flow_adjusted_index-100
  return point.cumulative_return==null?null:point.cumulative_return*100
}

type PerformanceChartMode = 'return'|'assets_raw'|'assets_adjusted'

function PerformanceChartCanvas({points,mode,currency}:{points:PerformancePoint[];mode:PerformanceChartMode;currency:string}) {
  const mainRef=useRef<HTMLDivElement>(null)
  const drawdownRef=useRef<HTMLDivElement>(null)
  const [themeMode,setThemeMode]=useState<ThemeMode>(()=>getResolvedTheme())
  useEffect(()=>subscribeTheme(setThemeMode),[])
  useEffect(()=>{
    if(!mainRef.current||points.length<2)return
    const theme=chartTheme()
    const common={
      width:mainRef.current.clientWidth,
      layout:{background:{type:ColorType.Solid as const,color:'transparent'},textColor:theme.text,fontFamily:'inherit',fontSize:11},
      grid:{vertLines:{color:theme.grid},horzLines:{color:theme.grid}},
      rightPriceScale:{visible:true,borderVisible:true,borderColor:theme.border,minimumWidth:72},
      timeScale:{visible:true,borderVisible:true,borderColor:theme.border,timeVisible:false,secondsVisible:false,rightOffset:1,fixLeftEdge:true,fixRightEdge:true},
      crosshair:{vertLine:{labelVisible:true},horzLine:{labelVisible:true}},
      localization:{locale:'zh-CN'},
    }
    const chart=createChart(mainRef.current,{...common,height:286})
    if(mode==='return'||mode==='assets_adjusted'){
      const isReturn=mode==='return'
      const values=points.map(row=>({time:row.date as Time,value:isReturn?(row.cumulative_return==null?null:row.cumulative_return*100):cashFlowAdjustedGrowth(row)})).filter((row):row is {time:Time;value:number}=>row.value!=null)
      const series=chart.addSeries(AreaSeries,{lineColor:theme.accent,lineWidth:2,topColor:theme.accentSoft,bottomColor:theme.accentFaint,priceFormat:{type:'percent',precision:2,minMove:.01},title:''})
      const zero=chart.addSeries(LineSeries,{color:theme.zeroLine,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,title:''})
      series.setData(values)
      zero.setData(points.map(row=>({time:row.date as Time,value:0})))
    }else{
      const nav=chart.addSeries(AreaSeries,{lineColor:theme.accent,lineWidth:2,topColor:theme.accentSoft,bottomColor:theme.accentFaint,priceFormat:{type:'custom',formatter:(value:number)=>new Intl.NumberFormat('zh-CN',{style:'currency',currency,notation:'compact',maximumFractionDigits:1}).format(value)},title:''})
      const contributions=chart.addSeries(LineSeries,{color:theme.textStrong,lineWidth:2,lineStyle:2,priceFormat:{type:'custom',formatter:(value:number)=>new Intl.NumberFormat('zh-CN',{style:'currency',currency,notation:'compact',maximumFractionDigits:1}).format(value)},title:''})
      nav.setData(points.filter(row=>row.nav!=null).map(row=>({time:row.date as Time,value:row.nav!})))
      contributions.setData(points.filter(row=>row.net_contributions!=null).map(row=>({time:row.date as Time,value:row.net_contributions!})))
    }
    chart.timeScale().fitContent()
    const mainObserver=observeChart(mainRef.current,chart)

    let drawdownChart:IChartApi|null=null
    let drawdownObserver:ResizeObserver|null=null
    if(mode==='return'&&drawdownRef.current){
      drawdownChart=createChart(drawdownRef.current,{...common,height:145,rightPriceScale:{...common.rightPriceScale,minimumWidth:72,scaleMargins:{top:.12,bottom:.12}}})
      const underwater=drawdownChart.addSeries(AreaSeries,{lineColor:theme.down,lineWidth:2,topColor:theme.downSoft,bottomColor:theme.downFill,invertFilledArea:true,priceFormat:{type:'percent',precision:2,minMove:.01},title:''})
      const zero=drawdownChart.addSeries(LineSeries,{color:theme.zeroLine,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false})
      underwater.setData(points.filter(row=>row.drawdown!=null).map(row=>({time:row.date as Time,value:row.drawdown!*100})))
      zero.setData(points.map(row=>({time:row.date as Time,value:0})))
      drawdownChart.timeScale().fitContent()
      drawdownObserver=observeChart(drawdownRef.current,drawdownChart)
    }
    return()=>{mainObserver.disconnect();drawdownObserver?.disconnect();chart.remove();drawdownChart?.remove()}
  },[points,mode,currency,themeMode])
  const isPercent=mode!=='assets_raw'
  return <div className="performance-chart-stack">
    <div className="performance-axis-title">{mode==='return'?'累计收益率（%）':mode==='assets_adjusted'?'排除现金流后的资产涨幅（%，区间起点 = 0）':`账户金额（${currency}）`}</div>
    <div className="performance-main-chart" ref={mainRef} role="img" aria-label={mode==='return'?'按日期显示的累计收益率曲线':mode==='assets_adjusted'?'按日期显示的排除入金和出金影响后的账户资产涨幅':'按日期显示的账户净资产和累计净入金曲线'}/>
    {mode==='return'&&<div className="performance-drawdown-panel"><div><b>从历史高点回落多少</b><span>0% 表示仍在前高；越向下，离前高越远</span></div><div className="performance-drawdown-chart" ref={drawdownRef} role="img" aria-label="按日期显示的距历史高点回落百分比"/></div>}
    <div className="performance-x-title">日期{isPercent?' · 加粗横线为 0%':''}</div>
  </div>
}

function PortfolioPerformanceChart({data,loading,error,range,onRange,currency}:{data:PerformanceSeries|undefined;loading:boolean;error:boolean;range:string;onRange:(value:string)=>void;currency:string}) {
  const points=data?.items||[]
  const [module,setModule]=useState<'return'|'assets'>('return')
  const [assetMode,setAssetMode]=useState<'raw'|'adjusted'>('raw')
  const mode:PerformanceChartMode=module==='return'?'return':assetMode==='raw'?'assets_raw':'assets_adjusted'
  return <section className="ledger-chart-card">
    <div className="portfolio-health-heading"><div><small>ACCOUNT PERFORMANCE</small><h3>组合收益曲线</h3></div><div className="ledger-range">{['1M','3M','6M','YTD','1Y','ALL'].map(value=><button key={value} className={range===value?'active':''} onClick={()=>onRange(value)}>{value}</button>)}</div></div>
    <div className="performance-module-tabs" role="tablist" aria-label="组合收益曲线模块"><button role="tab" aria-selected={module==='return'} className={module==='return'?'active':''} onClick={()=>setModule('return')}>收益率</button><button role="tab" aria-selected={module==='assets'} className={module==='assets'?'active':''} onClick={()=>setModule('assets')}>账户资产</button></div>
    {module==='assets'&&<div className="performance-asset-toolbar"><div><b>账户资产显示</b><span>可查看真实资产金额，或排除入金、出金后的投资涨幅</span></div><div className="ledger-mode" role="group" aria-label="账户资产除权开关"><button className={assetMode==='raw'?'active':''} onClick={()=>setAssetMode('raw')}>资产金额</button><button className={assetMode==='adjusted'?'active':''} onClick={()=>setAssetMode('adjusted')}>除权后涨幅</button></div></div>}
    {loading&&<div className="empty">正在读取账户绩效…</div>}
    {error&&<div className="error">收益曲线暂时无法读取。</div>}
    {!loading&&!error&&points.length<2&&<div className="empty">账户历史绩效数据不足；不会用当前持仓倒推过去收益。</div>}
    {points.length>=2&&<>
      <div className="ledger-chart-legend">{mode==='return'?<><span className="nav">累计收益率</span><span className="drawdown">距历史高点的回撤</span></>:mode==='assets_adjusted'?<span className="nav">排除入金、出金影响后的资产涨幅</span>:<><span className="nav">账户净资产</span><span className="capital">累计净入金</span></>}</div>
      <PerformanceChartCanvas points={points} mode={mode} currency={currency}/>
      {mode==='return'&&<p className="drawdown-explainer"><b>收益率与账户资产分开显示。</b> 回撤表示收益率从此前高点下跌了多少；0% 表示仍在高点，负值越大表示离前高越远。</p>}
      {mode==='assets_adjusted'&&<p className="drawdown-explainer"><b>除权只用于账户资产模块。</b> 这里不显示资产额度，而以区间起点 0% 展示排除入金、加仓资金和出金影响后的真实投资涨幅。</p>}
      <footer><span>{points[0].date}</span><span>{mode==='return'?'账户累计收益率':mode==='assets_adjusted'?'现金流调整后的资产涨幅':'账户资产与累计净入金'} · 完整度 {Math.round((data?.data_completeness||0)*100)}%</span><span>{points.at(-1)?.date}</span></footer>
      {!!data?.warnings.length&&<p className="portfolio-gap-hint">{data.warnings.join('；')}</p>}
    </>}
  </section>
}

function ReturnAttributionPreview({data,positions,currency,loading}:{data:ReturnAttribution|undefined;positions:PositionView[];currency:string;loading:boolean}) {
  const [filter,setFilter]=useState<'all'|'open'|'closed'>('all')
  const currentSymbols=new Set(positions.map(row=>row.symbol))
  const fallback:AttributionItem[]=positions.filter(row=>row.base_currency_total_pnl!=null).map(row=>({symbol:row.symbol,total_pnl:row.base_currency_total_pnl!,realized_pnl:row.base_currency_realized_pnl||0,unrealized_pnl:row.base_currency_unrealized_pnl||0,dividends:row.base_currency_dividend_income||0,fees:row.base_currency_fees||0,taxes:row.base_currency_taxes||0,fx_pnl:0,position_status:'open'}))
  const sourceRows=data?.items?.length?data.items:fallback
  const rows=sourceRows.map(row=>({...row,displayPnl:row.base_currency_total_pnl??row.total_pnl,resolvedStatus:(row.position_status||row.status||(currentSymbols.has(row.symbol)?'open':'closed'))==='open'?'open' as const:'closed' as const})).filter(row=>filter==='all'||row.resolvedStatus===filter).sort((a,b)=>(b.displayPnl??-Infinity)-(a.displayPnl??-Infinity))
  const maximum=Math.max(...rows.map(row=>Math.abs(row.displayPnl||0)),1)
  return <section className="ledger-attribution">
    <div className="portfolio-health-heading"><div><small>RETURN CONTRIBUTION</small><h3>收益贡献排行</h3></div><span>历史清仓 + 当前持仓 · 已实现 + 未实现 + 股息 − 费用税费</span></div>
    <div className="attribution-filter" role="group" aria-label="收益贡献范围">{([['all','全部'],['open','当前持仓'],['closed','历史清仓']] as const).map(([key,label])=><button key={key} className={filter===key?'active':''} onClick={()=>setFilter(key)}>{label}</button>)}</div>
    {loading&&!data&&<div className="empty">正在读取历史收益贡献…</div>}
    {!loading&&rows.map((row,index)=><div className="attribution-row" key={row.symbol}>
      <span className="attribution-rank">{row.displayPnl==null?'—':index+1}</span><div className="attribution-symbol"><b>{row.symbol}</b><small className={row.resolvedStatus}>{row.resolvedStatus==='open'?'持仓中':'已清仓'}</small>{row.displayPnl==null&&<small className="data-gap">汇率不足</small>}</div>
      <i aria-hidden="true"><span className={(row.displayPnl||0)>=0?'positive-bar':'negative-bar'} style={{width:`${Math.abs(row.displayPnl||0)/maximum*100}%`}}/></i>
      <div className="attribution-total">
        <span>{row.resolvedStatus==='open'?'总收益':'已实现净收益'}</span>
        <strong className={row.displayPnl==null?'':row.displayPnl>=0?'positive':'negative'}>{fmtMoney(row.displayPnl,data?.base_currency||currency)}</strong>
        {row.resolvedStatus==='open'?<small>已实现 {fmtMoney(row.realized_pnl,data?.base_currency||currency)} + 未实现 {fmtMoney(row.unrealized_pnl,data?.base_currency||currency)}</small>:<small>已实现 {fmtMoney(row.realized_pnl,data?.base_currency||currency)}</small>}
        {(Math.abs(row.dividends)>0.005||Math.abs(row.fees+row.taxes)>0.005)&&<small>股息 {fmtMoney(row.dividends,data?.base_currency||currency)} · 费用税费 {fmtMoney(row.fees+row.taxes,data?.base_currency||currency)}</small>}
      </div>
    </div>)}
    {!!data?.warnings?.length&&<p className="portfolio-gap-hint">{data.warnings.join('；')}</p>}
    {!data?.items?.length&&positions.some(row=>row.base_currency_total_pnl==null)&&<p className="portfolio-gap-hint">汇率不可用的持仓未参与贡献排序，不会按 1:1 猜算。</p>}
    {!loading&&!rows.length&&<div className="empty">这个范围暂无可归因的收益数据。</div>}
  </section>
}

function PositionAccountPanel({data}:{data:PositionLedgerDetail}) {
  const s=data.summary
  const [section,setSection]=useState<'timeline'|'lots'|'completed'>('timeline')
  const [chartMode,setChartMode]=useState<'return'|'assets'>('return')
  const assetValues=data.performance_curve.flatMap(row=>[row.market_value,row.cumulative_investment]).filter((value):value is number=>value!=null)
  const assetMin=Math.min(...assetValues),assetMax=Math.max(...assetValues)
  return <section className="position-account-panel">
    <div className="portfolio-health-heading"><div><small>MY POSITION</small><h3>{s.symbol} · 我的持仓</h3></div><span>{s.authority_source==='ibkr_flex'?'IBKR 账户事实':'手动账本'} · 行情由项目系统提供</span></div>
    <div className="position-account-summary">
      <div><span>当前市值</span><strong>{fmtMoney(s.market_value,s.currency)}</strong><small>{fmtNum(s.total_quantity)} 股 · 权重 {s.portfolio_weight?.toFixed(1)||'—'}%</small></div>
      <div><span>平均成本</span><strong>{fmtMoney(s.average_cost,s.currency)}</strong><small>当前价 {fmtMoney(s.current_price,s.currency)}</small></div>
      <div><span>未实现盈亏</span><strong className={(s.unrealized_pnl||0)>=0?'positive':'negative'}>{fmtMoney(s.unrealized_pnl,s.currency)}</strong><small>{fmtPercent(s.unrealized_pnl_percent)}</small></div>
      <div><span>总收益</span><strong className={s.total_pnl>=0?'positive':'negative'}>{fmtMoney(s.total_pnl,s.currency)}</strong><small>{fmtPercent(s.total_return_pct)}</small></div>
      <div><span>已实现 / 股息</span><strong>{fmtMoney(s.realized_pnl+s.dividend_income,s.currency)}</strong><small>费用税费 {fmtMoney(s.fees_and_taxes,s.currency)}</small></div>
      <div><span>持有时间</span><strong>{s.holding_days==null?'数据不足':`${s.holding_days} 天`}</strong><small>最近交易 {s.last_transaction_at||'—'}</small></div>
    </div>
    <div className="position-personal-chart">
      <div className="position-chart-heading"><h4>个人持仓收益</h4><div className="ledger-mode"><button className={chartMode==='return'?'active':''} onClick={()=>setChartMode('return')}>收益率</button><button className={chartMode==='assets'?'active':''} onClick={()=>setChartMode('assets')}>仓位资产</button></div></div>
      {data.performance_curve.length>=2?<svg viewBox="0 0 720 150" role="img" aria-label={`${s.symbol} ${chartMode==='return'?'收益率':'仓位资产'}曲线`}>{chartMode==='return'?<polyline points={chartPoints(data.performance_curve.map(row=>row.return_pct),720,130)} className="nav-line"/>:<><polyline points={chartPointsDomain(data.performance_curve.map(row=>row.market_value),assetMin,assetMax,720,130)} className="nav-line"/><polyline points={chartPointsDomain(data.performance_curve.map(row=>row.cumulative_investment),assetMin,assetMax,720,130)} className="capital-line"/></>}</svg>:<div className="empty">单证券每日历史数据不足。</div>}
    </div>
    <div className="position-ledger-tabs">{([['timeline','交易时间线'],['lots','成本批次'],['completed','已完成交易']] as const).map(([key,label])=><button key={key} className={section===key?'active':''} onClick={()=>setSection(key)}>{label}</button>)}</div>
    {section==='timeline'&&<div className="position-timeline">{data.timeline.map(row=><article key={row.event_id}><i/><div><b>{typeLabel[row.event_type]||row.event_type}</b><span>{row.occurred_at?new Date(row.occurred_at).toLocaleString('zh-CN'):'—'} · {row.authority_source==='ibkr_flex'?'IBKR 成交事实':'手动记录'}</span></div><strong>{row.quantity==null?'':`${fmtNum(row.quantity)} × `}{fmtMoney(row.price,row.currency)}</strong></article>)}{!data.timeline.length&&<div className="empty">暂无交易时间线。</div>}</div>}
    {section==='lots'&&<div className="position-ledger-list">{data.open_lots.map(row=><article key={row.lot_id}><b>{row.opened_at||'日期不足'}</b><span>{row.quantity==null?'—':fmtNum(row.quantity)} 股</span><span>批次成本 {fmtMoney(row.cost_basis,s.currency)}</span><span>{row.matching_method}</span></article>)}{!data.open_lots.length&&<div className="empty">暂无开放成本批次。</div>}</div>}
    {section==='completed'&&<div className="position-ledger-list">{data.completed_trades.map(row=><article key={row.id}><b>{row.closed_at?new Date(row.closed_at).toLocaleDateString('zh-CN'):'—'}</b><span>{fmtNum(row.quantity||0)} 股</span><span>{fmtMoney(row.average_entry_price,s.currency)} → {fmtMoney(row.average_exit_price,s.currency)}</span><strong className={(row.net_pnl||0)>=0?'positive':'negative'}>{fmtMoney(row.net_pnl,s.currency)}</strong></article>)}{!data.completed_trades.length&&<div className="empty">暂无已完成交易。</div>}</div>}
  </section>
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
    <div className="portfolio-benchmark-heading"><div><small>PERFORMANCE BASELINE</small><h3>组合与大盘对比</h3></div><span>{data?.portfolio_return_source==='ibkr_flex'?'IBKR 收益自动计算':data?.configured?'自动同步指数收盘价':'设置后开始比较'}</span></div>
    <p>{data?.portfolio_return_source==='ibkr_flex'?'组合累计收益与起始日直接读取最近一次成功的 IBKR Flex 账户绩效；系统持续对照 SPY、QQQ、DIA，不需要手动填写或刷新持仓。':'尚无可用 IBKR 历史绩效时，可手动输入入市日与组合累计涨跌幅作为后备口径。'}相对收益为组合涨跌幅减去对应基准。</p>
    {data?.portfolio_return_source!=='ibkr_flex'&&<form className="portfolio-benchmark-form" onSubmit={event=>{event.preventDefault();if(canSave)onSave({start_date:startDate,portfolio_return_percent:Number(portfolioReturn)})}}>
      <label><span>入市日期</span><input type="date" required max={today} value={startDate} onChange={event=>setStartDate(event.target.value)}/></label>
      <label><span>组合累计涨跌幅</span><div className="benchmark-percent-input"><input type="number" required inputMode="decimal" step="any" min="-100" value={portfolioReturn} onChange={event=>setPortfolioReturn(event.target.value)} placeholder="例如 18.5"/><b>%</b></div></label>
      <button disabled={!canSave||saving}>{saving?'正在更新…':data?.configured?'更新基准':'开始比较'}</button>
    </form>}
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

export function PortfolioHealthView({health,loading,currency,interpretation,interpretationLoading}:{health:PortfolioHealth|undefined;loading:boolean;currency:string;interpretation:PersonalizedInterpretation|undefined;interpretationLoading:boolean}) {
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

    {health.account_analytics&&<section className="health-section">
      <div className="portfolio-health-heading"><div><small>账户历史事实</small><h3>真实绩效与交易结果</h3></div><span>历史表现不代表未来风险</span></div>
      <div className="health-stat-line">
        <div><span>时间加权收益</span><strong>{fmtRatio(health.account_analytics.time_weighted_return)}</strong></div>
        <div><span>最大回撤</span><strong className="negative">{fmtRatio(health.account_analytics.max_drawdown)}</strong></div>
        <div><span>已实现盈亏</span><strong>{fmtMoney(health.account_analytics.realized_pnl,currency)}</strong></div>
        <div><span>费用税费拖累</span><strong>{fmtMoney(health.account_analytics.fees_and_taxes,currency)}</strong></div>
        <div><span>现金占比</span><strong>{health.account_analytics.cash_weight.toFixed(1)}%</strong></div>
      </div>
      <p className="health-quiet">收益贡献、成本、现金与回撤来自账户事实和项目派生层；它们只用于描述已经发生的结果，不参与原有基本面、估值与 SEC 客观评分。</p>
    </section>}

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
    <p className="health-disclaimer">客观评分审视当前持仓结构；账户历史区块单独描述已经发生的表现，两者不会混为预测，也不构成投资建议。</p>
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
