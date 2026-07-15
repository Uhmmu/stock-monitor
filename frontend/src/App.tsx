import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import { api, patch, post } from './api'

type WatchItem = { id:number; ticker:string; enabled:boolean; threshold_20m:number|null; threshold_1h:number|null; threshold_day:number|null }
type Dashboard = { market:{is_open:boolean; checked_at:string}; stocks:{ticker:string;price:number|null;previous_close:number|null;updated_at:string|null}[] }
type Alert = {id:number;ticker:string;period:string;change_percent:number;triggered_at:string}
type Investigation = {id:number;ticker:string;status:string;started_at:string;ends_at:string;news_count:number;last_error:string|null}
type Report = {id:number;ticker:string|null;report_type:string;title:string;model:string;created_at:string}
type ReportDetail = Report & {content:string;sources:{title:string;url:string}[]}
type Settings = {threshold_20m:number;threshold_1h:number;threshold_day:number;alert_cooldown_minutes:number;investigation_interval_minutes:number;investigation_duration_minutes:number;price_poll_minutes:number}
type NewsRow = {id:number;ticker:string;provider:string;title:string;translated_title:string|null;title_translation_model:string|null;title_translated_at:string|null;url:string;source:string|null;summary:string|null;image_url:string|null;published_at:string|null;found_at:string;relevance_score:number|null;sentiment_score:number|null;ai_summary:string|null;ai_summary_model:string|null}
type NewsArchive = {ticker:string;market_date:string;content:string;model:string;version:number;updated_at:string;included_news_ids:number[]}
type Financial = {fiscal_year:number;fiscal_period:string;period_end:string;filed_at:string|null;currency:string|null;revenue:number|null;eps:number|null;net_income:number|null;operating_income:number|null;gross_margin:number|null;net_margin:number|null;operating_cash_flow:number|null;free_cash_flow:number|null}
type Rating = {period:string|null;strongBuy:number;buy:number;hold:number;sell:number;strongSell:number}
type Fundamentals = {ticker:string;metrics:{label:string;value:number|null}[];rating:Rating|null}

const formatPrice = (value:number|null) => value == null ? '等待行情' : `$${value.toFixed(2)}`
const formatDate = (value:string) => new Date(value).toLocaleString('zh-CN')
const typeNames:Record<string,string> = {premarket:'盘前',postmarket:'盘后',movement:'价格异动',earnings_before:'财报前',earnings_after:'财报后'}

export default function App() {
  const [tab,setTab] = useState('overview')
  const [ticker,setTicker] = useState('')
  const [selectedReport,setSelectedReport] = useState<number|null>(null)
  const client = useQueryClient()
  const dashboard = useQuery({queryKey:['dashboard'],queryFn:()=>api<Dashboard>('/dashboard'),refetchInterval:30000})
  const watchlist = useQuery({queryKey:['watchlist'],queryFn:()=>api<WatchItem[]>('/watchlist')})
  const alerts = useQuery({queryKey:['alerts'],queryFn:()=>api<Alert[]>('/alerts'),refetchInterval:30000})
  const investigations = useQuery({queryKey:['investigations'],queryFn:()=>api<Investigation[]>('/investigations'),refetchInterval:30000})
  const reports = useQuery({queryKey:['reports'],queryFn:()=>api<Report[]>('/reports')})
  const report = useQuery({queryKey:['report',selectedReport],queryFn:()=>api<ReportDetail>(`/reports/${selectedReport}`),enabled:selectedReport!==null})
  const settings = useQuery({queryKey:['settings'],queryFn:()=>api<Settings>('/settings')})
  const add = useMutation({mutationFn:()=>post('/watchlist',{ticker}),onSuccess:()=>{setTicker('');client.invalidateQueries({queryKey:['watchlist']});client.invalidateQueries({queryKey:['dashboard']})}})
  const remove = useMutation({mutationFn:(id:number)=>api(`/watchlist/${id}`,{method:'DELETE'}),onSuccess:()=>{client.invalidateQueries({queryKey:['watchlist']});client.invalidateQueries({queryKey:['dashboard']})}})

  const submitTicker = (event:FormEvent) => { event.preventDefault(); if(ticker.trim()) add.mutate() }
  return <div className="app">
    <aside>
      <div className="brand"><span className="mark">MS</span><div><strong>Market Signal</strong><small>智能市场监控台 · v0.1</small></div></div>
      <nav>{[['overview','总览'],['watchlist','自选股'],['alerts','异动中心'],['news','新闻中心'],['fundamentals','基本面'],['reports','报告中心'],['settings','监控设置']].map(([key,label])=><button className={tab===key?'active':''} onClick={()=>setTab(key)} key={key}>{label}</button>)}</nav>
      <div className="side-status"><i className={dashboard.data?.market.is_open?'online':''}/><span>{dashboard.data?.market.is_open?'美股交易中':'当前休市'}</span></div>
    </aside>
    <main>
      <header><div><p className="eyebrow">MARKET INTELLIGENCE</p><h1>{tab==='overview'?'投资组合雷达':[['watchlist','自选股管理'],['alerts','价格异动中心'],['news','新闻中心'],['fundamentals','基本面与财报'],['reports','智能报告'],['settings','系统设置']].find(x=>x[0]===tab)?.[1]}</h1></div><div className="clock">更新于 {dashboard.data ? formatDate(dashboard.data.market.checked_at) : '—'}</div></header>
      {(dashboard.error||watchlist.error)&&<div className="error">后端暂不可用，请确认服务已启动。</div>}
      {tab==='overview'&&<>
        <section className="hero"><div><span className="badge">{dashboard.data?.market.is_open?'LIVE':'CLOSED'}</span><h2>{dashboard.data?.stocks.length||0} 只股票正在监控</h2><p>交易时段自动采集行情；价格异动后持续两小时追踪新闻与事件。</p></div><div className="hero-stat"><strong>{alerts.data?.length||0}</strong><span>近期异动</span></div><div className="hero-stat"><strong>{investigations.data?.filter(i=>i.status==='active').length||0}</strong><span>活跃调查</span></div></section>
        <section><div className="section-title"><h2>市场快照</h2><button onClick={()=>setTab('watchlist')}>管理自选股</button></div><div className="stock-grid">{dashboard.data?.stocks.map(stock=>{const change=stock.price&&stock.previous_close?(stock.price-stock.previous_close)/stock.previous_close*100:null;return <article className="stock-card" key={stock.ticker}><div><span className="ticker">{stock.ticker}</span><small>{stock.updated_at?formatDate(stock.updated_at):'等待首次采集'}</small></div><strong>{formatPrice(stock.price)}</strong><span className={change!=null&&change<0?'negative':'positive'}>{change==null?'—':`${change>=0?'+':''}${change.toFixed(2)}% 今日`}</span></article>})}{!dashboard.data?.stocks.length&&<div className="empty">添加第一只股票，开始建立你的市场雷达。</div>}</div></section>
        <section className="split"><div><div className="section-title"><h2>最近异动</h2></div>{alerts.data?.slice(0,5).map(a=><div className="list-row" key={a.id}><b>{a.ticker}</b><span>{a.period}</span><em className={a.change_percent<0?'negative':'positive'}>{a.change_percent.toFixed(2)}%</em></div>)}</div><div><div className="section-title"><h2>最新报告</h2></div>{reports.data?.slice(0,5).map(r=><button className="report-row" key={r.id} onClick={()=>{setSelectedReport(r.id);setTab('reports')}}><span>{typeNames[r.report_type]||r.report_type}</span><b>{r.title}</b><small>{formatDate(r.created_at)}</small></button>)}</div></section>
      </>}
      {tab==='watchlist'&&<><form className="add-form" onSubmit={submitTicker}><div><label>股票代码</label><input value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} placeholder="例如 AAPL、NVDA" maxLength={16}/></div><button disabled={add.isPending}>添加监控</button></form>{add.error&&<p className="error">{add.error.message}</p>}<div className="table"><div className="table-head"><span>代码</span><span>状态</span><span>20 分钟阈值</span><span>1 小时阈值</span><span>当日阈值</span><span/></div>{watchlist.data?.map(item=><div className="table-row" key={item.id}><b>{item.ticker}</b><button className="toggle" onClick={()=>patch(`/watchlist/${item.id}`,{enabled:!item.enabled}).then(()=>client.invalidateQueries({queryKey:['watchlist']}))}>{item.enabled?'监控中':'已暂停'}</button><span>{item.threshold_20m??'默认'}%</span><span>{item.threshold_1h??'默认'}%</span><span>{item.threshold_day??'默认'}%</span><button className="danger" onClick={()=>remove.mutate(item.id)}>删除</button></div>)}</div></>}
      {tab==='alerts'&&<div className="investigations">{investigations.data?.map(item=><article key={item.id}><div><span className={`status ${item.status}`}>{item.status}</span><h2>{item.ticker} 异动调查</h2><p>{formatDate(item.started_at)} — {formatDate(item.ends_at)}</p></div><strong>{item.news_count}<small> 条新闻线索</small></strong>{item.last_error&&<p className="error">{item.last_error}</p>}</article>)}{!investigations.data?.length&&<div className="empty">尚未触发价格异动调查。</div>}</div>}
      {tab==='reports'&&<div className="report-layout"><div className="report-list">{reports.data?.map(r=><button className={selectedReport===r.id?'selected':''} key={r.id} onClick={()=>setSelectedReport(r.id)}><span>{typeNames[r.report_type]||r.report_type}</span><b>{r.title}</b><small>{formatDate(r.created_at)}</small></button>)}</div><article className="report-detail">{report.data?<><p className="eyebrow">{typeNames[report.data.report_type]} · {report.data.model}</p><h2>{report.data.title}</h2><div className="report-content"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{report.data.content}</ReactMarkdown></div><h3>信息来源</h3>{report.data.sources.map((s,i)=><a href={s.url} target="_blank" rel="noreferrer" key={i}>{i+1}. {s.title}</a>)}</>:<div className="empty">选择一份报告查看完整分析。</div>}</article></div>}
      {tab==='news'&&<NewsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]}/>}
      {tab==='fundamentals'&&<FundamentalsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]}/>}
      {tab==='settings'&&settings.data&&<SettingsForm initial={settings.data} onSaved={()=>client.invalidateQueries({queryKey:['settings']})}/>}
    </main>
  </div>
}

function FundamentalsCenter({tickers}:{tickers:string[]}) {
  const [active,setActive] = useState(tickers[0]||'')
  const current = active||tickers[0]||''
  const fundamentals = useQuery({queryKey:['fundamentals',current],queryFn:()=>api<Fundamentals>(`/fundamentals?ticker=${current}`),enabled:!!current})
  const financials = useQuery({queryKey:['financials',current],queryFn:()=>api<Financial[]>(`/financials?ticker=${current}`),enabled:!!current})
  const fmtNum = (v:number|null) => {
    if(v==null) return '数据不足'
    const abs=Math.abs(v), sign=v<0?'-':''
    if(abs>=1e8) return `${sign}${(abs/1e8).toFixed(2)}亿`
    if(abs>=1e4) return `${sign}${(abs/1e4).toFixed(2)}万`
    return v.toLocaleString('en-US',{maximumFractionDigits:2})
  }
  const fmtMetric = (v:number|null) => v==null?'—':v.toLocaleString('en-US',{maximumFractionDigits:2})
  const r = fundamentals.data?.rating
  if(!tickers.length) return <div className="empty">请先在自选股中添加股票。</div>
  return <div className="news-center">
    <div className="news-tickers">{tickers.map(t=><button key={t} className={t===current?'active':''} onClick={()=>setActive(t)}>{t}</button>)}</div>
    <div className="section-title"><h2>{current} 基本面指标</h2></div>
    <div className="metric-grid">{fundamentals.data?.metrics.map(m=><div className="metric-card" key={m.label}><span>{m.label}</span><strong>{fmtMetric(m.value)}</strong></div>)}{fundamentals.isError&&<div className="empty">基本面数据暂不可用。</div>}</div>
    <div className="section-title"><h2>分析师评级</h2></div>
    {r?<div className="rating-bar"><span className="rt strong-buy">强烈买入 {r.strongBuy}</span><span className="rt buy">买入 {r.buy}</span><span className="rt hold">持有 {r.hold}</span><span className="rt sell">卖出 {r.sell}</span><span className="rt strong-sell">强烈卖出 {r.strongSell}</span>{r.period&&<small>（{r.period}）</small>}</div>:<div className="empty">暂无分析师评级。</div>}
    <div className="section-title"><h2>近四季度财报（SEC 单季，已去累计）</h2></div>
    <div className="table"><div className="table-head fin"><span>季度</span><span>报告期</span><span>营收</span><span>净利润</span><span>营业利润</span><span>EPS</span><span>净利率</span><span>经营现金流</span></div>{financials.data?.map(f=><div className="table-row fin" key={`${f.fiscal_year}${f.fiscal_period}`}><b>{f.fiscal_year} {f.fiscal_period}</b><span>{f.period_end}</span><span>{fmtNum(f.revenue)}</span><span>{fmtNum(f.net_income)}</span><span>{fmtNum(f.operating_income)}</span><span>{fmtNum(f.eps)}</span><span>{f.net_margin==null?'数据不足':f.net_margin.toFixed(1)+'%'}</span><span>{fmtNum(f.operating_cash_flow)}</span></div>)}{!financials.data?.length&&<div className="empty">暂无财报数据。</div>}</div>
  </div>
}

function NewsCenter({tickers}:{tickers:string[]}) {
  const [active,setActive] = useState(tickers[0]||'')
  const client = useQueryClient()
  const current = active||tickers[0]||''
  const news = useQuery({queryKey:['news',current],queryFn:()=>api<NewsRow[]>(`/news?ticker=${current}`),enabled:!!current})
  const archive = useQuery({queryKey:['news-archive',current],queryFn:()=>api<NewsArchive|null>(`/news/archive?ticker=${current}`),enabled:!!current})
  const refresh = useMutation({mutationFn:()=>post(`/news/refresh?ticker=${current}`,{})})
  const summarize = useMutation({mutationFn:(id:number)=>post<NewsRow>(`/news/${id}/summarize`,{}),onSuccess:()=>client.invalidateQueries({queryKey:['news',current]})})
  const stripExcluded = (md:string) => md.replace(/###\s*剔除[\s\S]*?(?=\n###\s|$)/g,'').trim()
  const includedIds = archive.data?.included_news_ids || []
  const orderNo = (id:number) => { const i = includedIds.indexOf(id); return i>=0 ? i+1 : null }
  if(!tickers.length) return <div className="empty">请先在自选股中添加股票。</div>
  return <div className="news-center">
    <div className="news-tickers">{tickers.map(t=><button key={t} className={t===current?'active':''} onClick={()=>setActive(t)}>{t}</button>)}</div>
    <div className="section-title"><h2>每日定档（Luna 去重）</h2></div>
    {archive.data?<article className="report-detail"><p className="eyebrow">{archive.data.market_date} · v{archive.data.version} · {archive.data.model}</p><div className="report-content"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{stripExcluded(archive.data.content)}</ReactMarkdown></div></article>:<div className="empty">尚未生成每日定档。</div>}
    <div className="section-title"><h2>{current} 新闻</h2><button onClick={()=>refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending?'刷新中…':'刷新新闻'}</button></div>
    {refresh.isSuccess&&<p className="saved">已触发后台采集，稍后刷新查看。</p>}
    <div className="news-list">{news.data?.map(item=>{const no=orderNo(item.id);return <article className="news-card" key={item.id}>
      <div className="news-body">
        <div className="news-meta">{no&&<span className="news-no">[{no}]</span>}<span className={`prov ${item.provider}`}>{item.provider==='finnhub'?'Finnhub':item.provider==='tavily'?'Tavily':item.provider==='yfinance'?'Yahoo财经':item.provider}</span>{item.source&&<span>{item.source}</span>}<span>{item.published_at?formatDate(item.published_at):formatDate(item.found_at)}</span></div>
        <a className="news-title" href={item.url} target="_blank" rel="noreferrer">{item.translated_title||item.title}</a>
        {item.translated_title&&item.translated_title!==item.title&&<p className="news-original-title">{item.title}</p>}
        {item.summary&&<p className="news-summary">{item.summary}</p>}
        <button className="ai-btn" onClick={()=>summarize.mutate(item.id)} disabled={summarize.isPending&&summarize.variables===item.id}>{summarize.isPending&&summarize.variables===item.id?'AI 总结中…':item.ai_summary?'重新总结':'AI 总结'}</button>
        {item.ai_summary&&<div className="ai-summary"><span className="ai-tag">Luna · {item.ai_summary_model}</span><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{item.ai_summary}</ReactMarkdown></div>}
      </div>
    </article>})}{!news.data?.length&&<div className="empty">暂无原始新闻，点击"刷新新闻"触发采集。</div>}</div>
  </div>
}

function SettingsForm({initial,onSaved}:{initial:Settings;onSaved:()=>void}) {
  const [form,setForm]=useState(initial)
  const save=useMutation({mutationFn:()=>patch<Settings>('/settings',form),onSuccess:onSaved})
  const fields:[keyof Settings,string][]=[['threshold_20m','20 分钟涨跌阈值 (%)'],['threshold_1h','1 小时涨跌阈值 (%)'],['threshold_day','当日涨跌阈值 (%)'],['alert_cooldown_minutes','同类警报冷却时间 (分钟)'],['investigation_interval_minutes','异动新闻搜索间隔 (分钟)'],['investigation_duration_minutes','异动调查持续时间 (分钟)']]
  return <section className="settings-card"><h2>监控规则</h2><p>修改后将影响新触发的监控任务。API 密钥只在服务器环境变量中配置。</p><div className="settings-grid">{fields.map(([key,label])=><label key={key}>{label}<input type="number" value={form[key]} onChange={e=>setForm({...form,[key]:Number(e.target.value)})}/></label>)}</div><div className="readonly">行情轮询间隔：{form.price_poll_minutes} 分钟（通过环境变量配置）</div><button onClick={()=>save.mutate()} disabled={save.isPending}>{save.isPending?'保存中…':'保存设置'}</button>{save.isSuccess&&<span className="saved">已保存</span>}</section>
}
