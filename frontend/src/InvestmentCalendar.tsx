import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

type EventType = 'earnings'|'dividend_ex_date'|'dividend_record_date'|'dividend_payment_date'|'dividend_declaration_date'|'stock_split'|'reverse_split'|'ipo'|'company_event'|'macro_event'|'market_holiday'
type CalendarEvent = {
  id:string;event_type:EventType;symbol:string|null;company_name:string|null;title:string;
  event_date:string;event_time:string|null;time_status:string;is_confirmed:boolean;is_estimated:boolean;
  confidence:'high'|'medium'|'low';impact_level:'low'|'medium'|'high'|'critical';
  primary_source:string;sources:string[];has_conflict:boolean;portfolio_relevance:boolean;
  watchlist_relevance:boolean;position_weight:number|null;metadata:Record<string,unknown>;fetched_at:string;
  stale:boolean;warning:string|null
}
type EventResponse = {items:CalendarEvent[];total:number;generated_at:string;capabilities:Record<string,boolean>}
type Summary = {today:number;next_7_days:number;next_30_days:number;high_impact:number;portfolio_events:number}
type CalendarStatus = {
  scope:'tracked';tracked_symbols:number;future_earnings_symbols:number;earnings_coverage_percent:number;
  next_30_day_symbols:number;providers:Record<string,string[]>;last_successful_sync_at:string|null;
  latest_run:{status:string;successful_symbols:number;tracked_symbols:number;failures:{symbol:string;provider:string;error:string}[]} | null
}

const eventNames:Record<string,string> = {
  earnings:'财报',dividend_ex_date:'除息',dividend_record_date:'股权登记',dividend_payment_date:'股息支付',
  dividend_declaration_date:'分红公告',stock_split:'拆股',reverse_split:'反向拆股',ipo:'IPO',
  company_event:'公司活动',macro_event:'宏观事件',market_holiday:'休市',
}
const timingNames:Record<string,string> = {before_market:'盘前',after_market:'盘后',during_market:'盘中',unknown:'时间待定'}
const impactNames:Record<string,string> = {low:'低',medium:'中',high:'高',critical:'重点'}
const filters:{label:string;types:EventType[]}[] = [
  {label:'全部',types:[]},{label:'财报',types:['earnings']},
  {label:'分红',types:['dividend_ex_date','dividend_record_date','dividend_payment_date','dividend_declaration_date']},
  {label:'拆股',types:['stock_split','reverse_split']},{label:'IPO',types:['ipo']},
  {label:'公司活动',types:['company_event']},{label:'宏观事件',types:['macro_event','market_holiday']},
]

const iso = (value:Date) => {
  const year=value.getFullYear(),month=String(value.getMonth()+1).padStart(2,'0'),day=String(value.getDate()).padStart(2,'0')
  return `${year}-${month}-${day}`
}
const dateAfter = (days:number) => { const value=new Date(); value.setDate(value.getDate()+days); return iso(value) }
const money = (value:unknown) => typeof value==='number' ? value.toLocaleString('zh-CN',{maximumFractionDigits:4}) : null

export function CalendarSkeleton() {
  return <div className="calendar-skeleton" aria-busy="true" aria-label="正在读取投资日历">{[1,2,3].map(item=><span key={item}/>)}</div>
}

export function CalendarEmpty() {
  return <div className="empty">当前范围内没有即将发生的事件。可扩大日期范围或切换证券范围。</div>
}

export function InvestmentCalendar() {
  const [range,setRange] = useState<'7'|'30'|'month'|'custom'>('30')
  const [scope,setScope] = useState<'mine'|'portfolio'|'watchlist'|'all'>('mine')
  const [typeFilter,setTypeFilter] = useState(0)
  const [symbol,setSymbol] = useState('')
  const [customStart,setCustomStart] = useState(iso(new Date()))
  const [customEnd,setCustomEnd] = useState(dateAfter(30))
  const start = range==='custom'?customStart:iso(new Date())
  const monthEnd = new Date(new Date().getFullYear(),new Date().getMonth()+1,0)
  const end = range==='7'?dateAfter(7):range==='month'?iso(monthEnd):range==='custom'?customEnd:dateAfter(30)
  const params = new URLSearchParams({start_date:start,end_date:end,limit:'250'})
  if(scope==='mine') params.set('relevant_only','true')
  if(scope==='portfolio') params.set('portfolio_only','true')
  if(scope==='watchlist') params.set('watchlist_only','true')
  if(symbol.trim()) params.append('symbols',symbol.trim().toUpperCase())
  filters[typeFilter].types.forEach(value=>params.append('event_types',value))
  const events = useQuery({queryKey:['investment-calendar',params.toString()],queryFn:()=>api<EventResponse>(`/calendar/events?${params}`),staleTime:5*60_000})
  const summary = useQuery({queryKey:['investment-calendar-summary'],queryFn:()=>api<Summary>('/calendar/summary'),staleTime:5*60_000})
  const status = useQuery({queryKey:['investment-calendar-status'],queryFn:()=>api<CalendarStatus>('/calendar/status'),staleTime:5*60_000})
  const grouped = useMemo(()=>{
    const result = new Map<string,CalendarEvent[]>()
    for(const event of events.data?.items||[]) result.set(event.event_date,[...(result.get(event.event_date)||[]),event])
    return [...result.entries()]
  },[events.data])
  const highImpact = (events.data?.items||[]).filter(item=>item.impact_level==='high'||item.impact_level==='critical').slice(0,4)
  const detail = (event:CalendarEvent) => {
    if(event.event_type==='earnings') {
      const eps=money(event.metadata.eps_estimate)
      return eps?`EPS 预期 ${eps}`:null
    }
    if(event.event_type.startsWith('dividend_')) {
      const amount=money(event.metadata.dividend_amount)
      return amount?`每股 ${amount}${event.metadata.currency?` ${event.metadata.currency}`:''}`:null
    }
    if(event.event_type.includes('split')) return String(event.metadata.split_ratio_text||'')
    return null
  }
  return <div className="investment-calendar">
    <section className="calendar-intro">
      <div><p className="eyebrow">PORTFOLIO-AWARE AGENDA</p><h2>未来事件，一处看清</h2><p>聚合持仓与自选股的财报、分红和拆股日期。影响等级只表示与你的组合相关程度，不预测涨跌。</p></div>
      <div className="calendar-summary" aria-label="日历摘要">
        <span><b>{summary.data?.next_7_days??'—'}</b><small>未来 7 天</small></span>
        <span><b>{summary.data?.high_impact??'—'}</b><small>重点事件</small></span>
        <span><b>{summary.data?.portfolio_events??'—'}</b><small>持仓相关</small></span>
        <span><b>{status.data?`${status.data.future_earnings_symbols}/${status.data.tracked_symbols}`:'—'}</b><small>未来财报覆盖</small></span>
      </div>
    </section>
    <div className={`calendar-sync-state ${status.data?.latest_run?.status||''}`}>
      <span>已追踪 {status.data?.tracked_symbols??'—'} 家 · 财报覆盖 {status.data?.earnings_coverage_percent??'—'}%</span>
      <span>数据源 {status.data?Object.keys(status.data.providers).map(value=>value.toUpperCase()).join(' + '):'—'}</span>
      <span>上次成功同步 {status.data?.last_successful_sync_at?new Date(status.data.last_successful_sync_at).toLocaleString('zh-CN'):'尚无记录'}</span>
      {!!status.data?.latest_run?.failures.length&&<span className="warning">最近同步有 {status.data.latest_run.failures.length} 项来源失败，已保留有效缓存</span>}
    </div>

    <section className="calendar-controls" aria-label="日历筛选">
      <div className="calendar-control-row">
        <div className="segmented compact" role="tablist" aria-label="日期范围">
          {[['7','未来 7 天'],['30','未来 30 天'],['month','本月'],['custom','自定义']].map(([key,label])=>
            <button key={key} role="tab" aria-selected={range===key} className={range===key?'active':''} onClick={()=>setRange(key as typeof range)}>{label}</button>)}
        </div>
        <div className="segmented compact" role="tablist" aria-label="证券范围">
          {[['mine','持仓与自选'],['portfolio','我的持仓'],['watchlist','自选股'],['all','全部已追踪']].map(([key,label])=>
            <button key={key} role="tab" aria-selected={scope===key} className={scope===key?'active':''} onClick={()=>setScope(key as typeof scope)}>{label}</button>)}
        </div>
      </div>
      {range==='custom'&&<div className="calendar-custom-range"><label>开始日期<input type="date" value={customStart} onChange={event=>setCustomStart(event.target.value)}/></label><span>至</span><label>结束日期<input type="date" value={customEnd} onChange={event=>setCustomEnd(event.target.value)}/></label></div>}
      <div className="calendar-filter-row">
        <div className="calendar-type-chips">{filters.map((item,index)=><button key={item.label} className={typeFilter===index?'active':''} onClick={()=>setTypeFilter(index)}>{item.label}</button>)}</div>
        <label className="calendar-symbol-search"><span>证券代码</span><input value={symbol} onChange={event=>setSymbol(event.target.value)} placeholder="例如 NVDA" maxLength={16}/></label>
      </div>
    </section>

    {!!highImpact.length&&<section className="calendar-priority"><div className="section-title"><div><p>PRIORITY</p><h2>重点事件</h2></div></div><div className="priority-event-grid">{highImpact.map(event=><article key={event.id}><span className={`event-glyph type-${event.event_type}`}>{eventNames[event.event_type]}</span><div><b>{event.symbol} {event.title}</b><small>{event.event_date} · {timingNames[event.time_status]} · {event.portfolio_relevance?'我的持仓':'自选股'}</small></div><em>影响：{impactNames[event.impact_level]}</em></article>)}</div></section>}

    <section className="calendar-agenda" aria-live="polite">
      {events.isLoading&&<CalendarSkeleton/>}
      {events.isError&&<div className="empty">投资日历暂时无法读取；已缓存数据不会因上游失败被删除。</div>}
      {!events.isLoading&&!events.isError&&!grouped.length&&<CalendarEmpty/>}
      {grouped.map(([day,items])=><section className="agenda-day" key={day}>
        <div className="agenda-day-heading"><time>{new Date(`${day}T12:00:00`).toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'short'})}</time><span>{items.length} 项</span></div>
        <div>{items.map(event=><article className={`agenda-event type-${event.event_type}`} key={event.id}>
          <span className="event-glyph">{eventNames[event.event_type]||'事件'}</span>
          <div className="agenda-event-main"><div><b>{event.symbol||'市场'} · {event.title}</b>{event.has_conflict&&<span className="event-state conflict">来源冲突</span>}{event.is_estimated&&<span className="event-state">日期预计</span>}{event.stale&&<span className="event-state stale">缓存较旧</span>}</div><p>{event.company_name||detail(event)||'结构化事件数据'}</p>{event.company_name&&detail(event)&&<small>{detail(event)}</small>}</div>
          <div className="agenda-event-meta"><span>{timingNames[event.time_status]}</span><span>{event.portfolio_relevance?'我的持仓':event.watchlist_relevance?'自选股':'市场事件'}</span><strong className={`impact-${event.impact_level}`}>影响 {impactNames[event.impact_level]}</strong></div>
          <span className="event-source" title={`抓取于 ${event.fetched_at}`}>{event.primary_source.toUpperCase()}</span>
        </article>)}</div>
      </section>)}
    </section>
    <p className="calendar-footnote">财报日期由 Yahoo 与 Finnhub 交叉验证，分红和拆股来自 Yahoo；后台按持久化同步状态自动补刷。“全部已追踪”不代表全市场。日期可能由上游估算；IPO、公司活动与宏观日历在缺少可靠来源时保持关闭。</p>
  </div>
}
