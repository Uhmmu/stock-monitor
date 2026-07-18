import { FormEvent, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import { api, patch, post } from './api'
import { Sheet } from './Sheet'

type WatchItem = { id:number; ticker:string; enabled:boolean; threshold_20m:number|null; threshold_1h:number|null; threshold_day:number|null }
type Dashboard = { market:{is_open:boolean; checked_at:string}; stocks:{ticker:string;price:number|null;previous_close:number|null;updated_at:string|null;volume:number|null;volume_ratio:number|null;volume_label:string|null}[] }
type IndexQuote = {symbol:string;name:string;price:number|null;previous_close:number|null;change_points:number|null;change_percent:number|null}
type Indices = {indices:IndexQuote[];market:{is_open:boolean;checked_at:string}}
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
type SecEvent = {id:number;form:string;item_code:string;item_label:string;priority:string;text:string|null;summary_zh:string|null;summary_model:string|null;summary_status:string;filing_date:string|null;filing_url:string}
type SecFin = {fiscal_year:number;fiscal_period:string;form:string;period_end:string|null;currency:string|null;revenue:number|null;net_income:number|null;operating_income:number|null;gross_profit:number|null;eps_basic:number|null;eps_diluted:number|null;cash_and_equivalents:number|null;total_debt:number|null;shares_outstanding:number|null;operating_cash_flow:number|null}
type SecInsider = {id:number;insider_name:string;insider_title:string|null;transaction_date:string|null;transaction_code:string|null;shares:number|null;price:number|null;value:number|null;shares_owned_after:number|null;flag:string|null;filing_url:string}
type Sec13FHolding = {id:number;manager_name:string;shares:number|null;value_usd:number|null;put_call:string|null;share_change:number|null;is_new:boolean;filing_date:string|null}
type Sec13F = {report_period:string|null;prev_period:string|null;holdings:Sec13FHolding[]}
type Figure = {slug:string;display_name:string;kind:string;photo_url:string|null;note:string|null;is_seed:boolean;has_positions:boolean}
type CongressTradeRow = {id:number;filer_id:string;filer_name:string;chamber:string|null;party:string|null;state:string|null;ticker:string|null;asset_name:string|null;transaction_type:string|null;transaction_date:string|null;filing_date:string|null;amount_label:string|null;is_late:boolean}
type Position = {ticker:string|null;asset_name:string;category:string;value:number;is_percent:boolean;note:string|null}
type FigureDetail = {slug:string;display_name:string;kind:string;photo_url:string|null;note:string|null;is_seed:boolean;positions:Position[];positions_are_percent:boolean;trades:CongressTradeRow[];moves:{buys:string[];sells:string[]}|null}
type FilerHit = {filer_id:string;full_name:string;chamber:string|null;branch:string|null;party:string|null;state:string|null;trade_count:number|null}
type TradeLogRow = {ticker:string;direction:string;quantity:number|null;price:number|null;fee:number|null;strategy:string;result:string}
type TradeLog = {id:number;trade_date:string;ticker:string|null;direction:string|null;quantity:number|null;price:number|null;note:string|null;content:string|null;table_rows:TradeLogRow[];photo_urls:string[];ai_summary:string|null;ai_summary_model:string|null;ai_summary_created_at:string|null;created_at:string}

const formatPrice = (value:number|null) => value == null ? '等待行情' : `$${value.toFixed(2)}`
const formatDate = (value:string) => new Date(value).toLocaleString('zh-CN')
const typeNames:Record<string,string> = {premarket:'盘前',postmarket:'盘后',movement:'价格异动',earnings_before:'财报前',earnings_after:'财报后'}

const demoDashboard:Dashboard = {
  market:{is_open:true,checked_at:new Date().toISOString()},
  stocks:[
    {ticker:'AAPL',price:214.37,previous_close:211.18,updated_at:new Date().toISOString(),volume:52180300,volume_ratio:1.18,volume_label:'放量'},
    {ticker:'NVDA',price:141.22,previous_close:143.61,updated_at:new Date().toISOString(),volume:183410200,volume_ratio:.91,volume_label:'正常'},
    {ticker:'MSFT',price:468.91,previous_close:465.82,updated_at:new Date().toISOString(),volume:19284600,volume_ratio:1.04,volume_label:'正常'},
    {ticker:'TSLA',price:322.05,previous_close:315.63,updated_at:new Date().toISOString(),volume:84630200,volume_ratio:1.31,volume_label:'放量'},
  ],
}
const demoIndices:Indices = {market:demoDashboard.market,indices:[
  {symbol:'^GSPC',name:'标普 500',price:6216.44,previous_close:6198.01,change_points:18.43,change_percent:.30},
  {symbol:'^IXIC',name:'纳斯达克',price:20273.46,previous_close:20192.18,change_points:81.28,change_percent:.40},
  {symbol:'^DJI',name:'道琼斯',price:44484.49,previous_close:44502.12,change_points:-17.63,change_percent:-.04},
]}
const demoAlerts:Alert[] = [
  {id:-1,ticker:'TSLA',period:'20 分钟',change_percent:2.04,triggered_at:new Date().toISOString()},
  {id:-2,ticker:'NVDA',period:'1 小时',change_percent:-1.66,triggered_at:new Date().toISOString()},
  {id:-3,ticker:'AAPL',period:'当日',change_percent:1.51,triggered_at:new Date().toISOString()},
]
const demoReports:Report[] = [
  {id:-1,ticker:'AAPL',report_type:'movement',title:'Apple 盘中放量上行：关键驱动与风险观察',model:'preview',created_at:new Date().toISOString()},
  {id:-2,ticker:'TSLA',report_type:'movement',title:'Tesla 短线动量增强，市场在交易什么？',model:'preview',created_at:new Date(Date.now()-36e5).toISOString()},
]

function NavIcon({name}:{name:string}) {
  const paths:Record<string,React.ReactNode> = {
    overview:<><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    watchlist:<><path d="M4 19V9"/><path d="M10 19V5"/><path d="M16 19v-7"/><path d="M22 19H2"/></>,
    alerts:<><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    news:<><path d="M4 5h16v14H4z"/><path d="M8 9h8M8 13h5"/></>,
    fundamentals:<><path d="m3 17 5-5 4 3 8-9"/><path d="M15 6h5v5"/></>,
    sec:<><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
    congress:<><circle cx="12" cy="8" r="4"/><path d="M4 21c1-5 4-7 8-7s7 2 8 7"/></>,
    charts:<><path d="M4 19V5M4 19h16"/><path d="m7 15 4-4 3 2 5-6"/></>,
    reports:<><path d="M5 3h14v18H5z"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
    journal:<><path d="M5 4h14v16H5z"/><path d="M9 4v16M12 8h4M12 12h4"/></>,
    settings:<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></>,
  }
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>
}

export default function App() {
  const previewRequested = new URLSearchParams(window.location.search).get('preview')==='1'
  const [token,setToken] = useState(()=>localStorage.getItem('auth_token')||sessionStorage.getItem('auth_token')||'')
  const [demoMode,setDemoMode] = useState(previewRequested)
  const [authUser,setAuthUser] = useState<{username:string;role:string}|null>(()=>previewRequested?{username:'访客',role:'viewer'}:null)
  const [authLoading,setAuthLoading] = useState(()=>!!(localStorage.getItem('auth_token')||sessionStorage.getItem('auth_token')))
  const [tab,setTab] = useState(()=>new URLSearchParams(window.location.search).get('tab')||'overview')
  const [mobileNavOpen,setMobileNavOpen] = useState(false)
  const [ticker,setTicker] = useState('')
  const [selectedReport,setSelectedReport] = useState<number|null>(null)
  const [stocksExpanded,setStocksExpanded] = useState(false)
  const client = useQueryClient()
  const live = !!authUser&&!demoMode
  const dashboard = useQuery({queryKey:['dashboard'],queryFn:()=>api<Dashboard>('/dashboard'),refetchInterval:30000,enabled:live})
  const indices = useQuery({queryKey:['indices'],queryFn:()=>api<Indices>('/indices'),refetchInterval:60000,enabled:live})
  const watchlist = useQuery({queryKey:['watchlist'],queryFn:()=>api<WatchItem[]>('/watchlist'),enabled:live})
  const alerts = useQuery({queryKey:['alerts'],queryFn:()=>api<Alert[]>('/alerts'),refetchInterval:30000,enabled:live})
  const investigations = useQuery({queryKey:['investigations'],queryFn:()=>api<Investigation[]>('/investigations'),refetchInterval:30000,enabled:live})
  const reports = useQuery({queryKey:['reports'],queryFn:()=>api<Report[]>('/reports'),enabled:live})
  const report = useQuery({queryKey:['report',selectedReport],queryFn:()=>api<ReportDetail>(`/reports/${selectedReport}`),enabled:live&&selectedReport!==null})
  const settings = useQuery({queryKey:['settings'],queryFn:()=>api<Settings>('/settings'),enabled:live})
  const add = useMutation({mutationFn:()=>post('/watchlist',{ticker}),onSuccess:()=>{setTicker('');client.invalidateQueries({queryKey:['watchlist']});client.invalidateQueries({queryKey:['dashboard']})}})
  const remove = useMutation({mutationFn:(id:number)=>api(`/watchlist/${id}`,{method:'DELETE'}),onSuccess:()=>{client.invalidateQueries({queryKey:['watchlist']});client.invalidateQueries({queryKey:['dashboard']})}})

  useEffect(()=>{
    if(demoMode){setAuthLoading(false);return}
    if(!token){setAuthUser(null);setAuthLoading(false);return}
    setAuthLoading(true)
    api<{username:string;role:string}>('/auth/me')
      .then(u=>{setAuthUser(u);setAuthLoading(false)})
      .catch(()=>{localStorage.removeItem('auth_token');sessionStorage.removeItem('auth_token');setToken('');setAuthUser(null);setAuthLoading(false)})
  },[token,demoMode])

  useEffect(()=>{
    const onLogout=()=>{setToken('');setAuthUser(null)}
    window.addEventListener('auth:logout',onLogout)
    return ()=>window.removeEventListener('auth:logout',onLogout)
  },[])

  if(authLoading) return <div style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',background:'var(--bg)',color:'var(--text-muted)'}}>加载中…</div>
  if(!authUser) return <AuthGate setToken={setToken} setAuthUser={setAuthUser} onPreview={()=>{setDemoMode(true);setAuthUser({username:'访客',role:'viewer'})}}/>

  const submitTicker = (event:FormEvent) => { event.preventDefault(); if(ticker.trim()) add.mutate() }
  const tabs = [['overview','总览'],['watchlist','自选股'],['alerts','异动中心'],['news','新闻中心'],['fundamentals','基本面'],['sec','SEC 公告'],['congress','名人持仓'],['charts','图表'],['reports','报告中心'],['journal','交易日志'],['settings','监控设置']]
  const tabTitle = tab==='overview'?'投资组合雷达':[['watchlist','自选股管理'],['alerts','价格异动中心'],['news','新闻中心'],['fundamentals','基本面与财报'],['sec','SEC 官方公告'],['congress','名人持仓与交易'],['charts','实时图表'],['reports','智能报告'],['journal','交易日志'],['settings','系统设置']].find(x=>x[0]===tab)?.[1]
  const viewDashboard = demoMode ? demoDashboard : dashboard.data
  const viewIndices = demoMode ? demoIndices : indices.data
  const viewAlerts = demoMode ? demoAlerts : alerts.data
  const viewReports = demoMode ? demoReports : reports.data
  const overviewStocks = [...(viewDashboard?.stocks||[])].sort((a,b)=>{
    const change = (stock:typeof a) => stock.price!=null&&stock.previous_close ? Math.abs((stock.price-stock.previous_close)/stock.previous_close*100) : -1
    return change(b)-change(a)
  })
  return <div className="app">
    <div className="ambient ambient-one"/><div className="ambient ambient-two"/>
    <aside className={mobileNavOpen?'mobile-open':''}>
      <div className="brand"><div className="brand-orb"><img src="/logo.png" className="brand-logo" alt="logo"/></div><div className="brand-copy"><strong>小日向美香</strong><small>Powered by 和泉妃爱</small></div><div className="mobile-quick-stats"><span><b>{viewDashboard?.stocks.length||0}</b><small>监控</small></span><span><b>{viewAlerts?.length||0}</b><small>异动</small></span><span><b>{investigations.data?.length||0}</b><small>调查</small></span></div><button className="mobile-menu-btn" onClick={()=>setMobileNavOpen(v=>!v)} aria-expanded={mobileNavOpen}>{mobileNavOpen?'关闭':'菜单'}</button></div>
      <nav>{tabs.map(([key,label],index)=><button className={tab===key?'active':''} onClick={()=>{setTab(key);setMobileNavOpen(false)}} key={key}>{index===8&&<span className="nav-separator"/>}<NavIcon name={key}/><span>{label}</span>{tab===key&&<i className="nav-active-dot"/>}</button>)}</nav>
      <div className="account-card"><span className="account-avatar">{authUser.username.slice(0,1)}</span><span><b>{demoMode?'演示空间':authUser.username}</b><small>{demoMode?'本地预览模式':'已安全连接'}</small></span><i className={viewDashboard?.market.is_open?'online':''}/></div>
      <button className="logout-btn" onClick={()=>{localStorage.removeItem('auth_token');sessionStorage.removeItem('auth_token');setDemoMode(false);setToken('');setAuthUser(null)}}>{demoMode?'退出预览':'退出登录'}</button></aside>
    {mobileNavOpen&&<button className="mobile-nav-scrim" onClick={()=>setMobileNavOpen(false)} aria-label="关闭菜单"/>}
    <main>
      <header><div><p className="eyebrow">MARKET INTELLIGENCE</p><h1>{tabTitle}</h1></div><div className="header-tools"><span className="market-pill"><i className={viewDashboard?.market.is_open?'online':''}/>{viewDashboard?.market.is_open?'市场开放':'市场休市'}</span><div className="clock">{viewDashboard ? formatDate(viewDashboard.market.checked_at) : '等待同步'}</div></div></header>
      {demoMode&&<div className="preview-banner"><span><b>演示预览</b> 当前展示本地示例行情，所有真实数据仍以服务端为准。</span><button onClick={()=>{setDemoMode(false);setAuthUser(null)}}>连接账户</button></div>}
      {!demoMode&&(dashboard.error||watchlist.error)&&<div className="error">后端暂不可用，请确认服务已启动。</div>}
      <div className="view-stage" key={tab}>
      {tab==='overview'&&<>
        <section className="hero index-hero"><div className="hero-copy"><span className={`badge${viewIndices?.market.is_open?'':' closed'}`}><i/>{viewIndices?.market.is_open?'LIVE MARKET':'MARKET CLOSED'}</span><h2>早上好，{authUser.username}</h2><p>你的市场雷达保持安静。我们只在真正值得注意时打扰你。</p></div><div className="index-row">{(viewIndices?.indices||[{symbol:'^GSPC',name:'标普500'},{symbol:'^IXIC',name:'纳斯达克'},{symbol:'^DJI',name:'道琼斯'}] as IndexQuote[]).map(idx=>{const up=idx.change_percent!=null&&idx.change_percent>=0;return <div className="index-card" key={idx.symbol}><span className="index-name">{idx.name}</span><strong>{idx.price!=null?idx.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}</strong><span className={idx.change_percent==null?'':up?'positive':'negative'}>{idx.change_points==null||idx.change_percent==null?'数据不足':`${up?'+':''}${idx.change_points.toFixed(2)} (${up?'+':''}${idx.change_percent.toFixed(2)}%)`}</span></div>})}</div></section>
        <section><div className="section-title"><div><p>WATCHLIST</p><h2>市场快照</h2></div><div className="section-actions"><button className="stock-collapse-btn" onClick={()=>setStocksExpanded(v=>!v)}>{stocksExpanded?'收起':'展开更多'} <span>{stocksExpanded?'↑':'↓'}</span></button><button onClick={()=>setTab('watchlist')}>管理自选股 <span>→</span></button></div></div><div className={`stock-grid${stocksExpanded?' is-expanded':' is-collapsed'}`}>{overviewStocks.map(stock=>{const change=stock.price&&stock.previous_close?(stock.price-stock.previous_close)/stock.previous_close*100:null;return <article className="stock-card" key={stock.ticker}><div><span className="ticker">{stock.ticker}</span><small>{stock.updated_at?'刚刚更新':'等待首次采集'}</small></div><strong>{formatPrice(stock.price)}</strong><span className={change!=null&&change<0?'negative':'positive'}>{change==null?'—':`${change>=0?'+':''}${change.toFixed(2)}% 今日`}</span>{stock.volume_label&&stock.volume_label!=='正常'&&<span className={`vol-tag ${stock.volume_label==='放量'?'heavy':'light'}`}>{stock.volume_label} · {stock.volume_ratio?.toFixed(2)}×</span>}<div className="card-glow"/></article>})}{!overviewStocks.length&&<div className="empty">添加第一只股票，开始建立你的市场雷达。</div>}</div></section>
        <section className="split"><div><div className="section-title"><div><p>SIGNALS</p><h2>最近异动</h2></div></div>{viewAlerts?.slice(0,5).map(a=><div className="list-row" key={a.id}><span className="signal-symbol">{a.ticker.slice(0,1)}</span><b>{a.ticker}</b><span>{a.period}</span><em className={a.change_percent<0?'negative':'positive'}>{a.change_percent>=0?'+':''}{a.change_percent.toFixed(2)}%</em></div>)}</div><div><div className="section-title"><div><p>INTELLIGENCE</p><h2>最新报告</h2></div></div>{viewReports?.slice(0,5).map(r=><button className="report-row" key={r.id} onClick={()=>!demoMode&&setSelectedReport(r.id)}><span>{typeNames[r.report_type]||r.report_type}</span><b>{r.title}</b><small>{demoMode?'刚刚生成':formatDate(r.created_at)}</small></button>)}</div></section>
      </>}
      {tab==='watchlist'&&<><form className="add-form" onSubmit={submitTicker}><div><label>股票代码</label><input value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} placeholder="例如 AAPL、NVDA" maxLength={16}/></div><button disabled={add.isPending}>添加监控</button></form>{add.error&&<p className="error">{add.error.message}</p>}<div className="watchlist-stack">{watchlist.data?.map(item=><article className="watch-item-card" key={item.id}><div className="watch-item-head"><div><b>{item.ticker}</b><small>价格异动阈值</small></div><button className="watch-delete" aria-label={`删除 ${item.ticker}`} onClick={()=>remove.mutate(item.id)}><TrashIcon/></button></div><div className="threshold-tags"><ThresholdCell item={item} field="threshold_20m" onSaved={()=>client.invalidateQueries({queryKey:['watchlist']})}/><ThresholdCell item={item} field="threshold_1h" onSaved={()=>client.invalidateQueries({queryKey:['watchlist']})}/><ThresholdCell item={item} field="threshold_day" onSaved={()=>client.invalidateQueries({queryKey:['watchlist']})}/></div></article>)}</div></>}
      {tab==='alerts'&&<div className="investigations">{investigations.data?.map(item=><article key={item.id}><div><span className={`status ${item.status}`}>{item.status}</span><h2>{item.ticker} 异动调查</h2><p>{formatDate(item.started_at)} — {formatDate(item.ends_at)}</p></div><strong>{item.news_count}<small> 条新闻线索</small></strong>{item.last_error&&<p className="error">{item.last_error}</p>}</article>)}{!investigations.data?.length&&<div className="empty">尚未触发价格异动调查。</div>}</div>}
      {tab==='reports'&&<div className="report-grid">{reports.data?.map(r=><button className={`report-tile${selectedReport===r.id?' selected':''}`} key={r.id} onClick={()=>setSelectedReport(r.id)}><span>{typeNames[r.report_type]||r.report_type}</span><b>{r.title}</b><small>{formatDate(r.created_at)}</small></button>)}{!reports.data?.length&&<div className="empty">暂无报告。</div>}</div>}
      {tab==='news'&&<NewsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]}/>}
      {tab==='fundamentals'&&<FundamentalsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]}/>}
      {tab==='sec'&&<SecCenter tickers={watchlist.data?.map(w=>w.ticker)||[]}/>}
      {tab==='congress'&&<CongressCenter/>}
      {tab==='charts'&&<ChartsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]}/>}
      {tab==='journal'&&authUser&&<JournalSection username={authUser.username}/>}
      {tab==='settings'&&settings.data&&<><SettingsForm initial={settings.data} onSaved={()=>client.invalidateQueries({queryKey:['settings']})}/>{authUser.role==='admin'&&<AdminPanel/>}</> }
      </div>
    </main>
    <Sheet open={selectedReport!==null} onClose={()=>setSelectedReport(null)} title={report.data?typeNames[report.data.report_type]||report.data.report_type:'报告'}>
      {report.data?<article className="report-detail sheet-report"><p className="eyebrow">{typeNames[report.data.report_type]} · {report.data.model}</p><h2>{report.data.title}</h2><div className="report-content"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{report.data.content}</ReactMarkdown></div><h3>信息来源</h3>{report.data.sources.map((s,i)=><a href={s.url} target="_blank" rel="noreferrer" key={i}>{i+1}. {s.title}</a>)}</article>:<div className="empty">加载中…</div>}
    </Sheet>
  </div>
}

function RatingGauge({r}:{r:Rating}) {
  const items=[
    {k:'strongBuy',label:'强烈买入',n:r.strongBuy},
    {k:'buy',label:'买入',n:r.buy},
    {k:'hold',label:'持有',n:r.hold},
    {k:'sell',label:'卖出',n:r.sell},
    {k:'strongSell',label:'强烈卖出',n:r.strongSell},
  ]
  const total=items.reduce((s,x)=>s+x.n,0)
  if(!total) return <div className="empty">暂无分析师评级。</div>
  const score=items.reduce((s,x,i)=>s+x.n*i,0)/total
  const pos=10+score/4*80
  const consensus=items[Math.round(score)].label
  return <div className="rating-gauge">
    <div className="rg-track">
      <div className="rg-pointer" style={{left:`${pos}%`}}><b>共识：{consensus}</b></div>
    </div>
    <div className="rg-ticks">{items.map(x=><span key={x.k} className="rg-tick"><em>{x.label}</em><small>{x.n}</small></span>)}</div>
    {r.period&&<div className="rg-period">数据期间：{r.period}</div>}
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
    {r?<RatingGauge r={r}/>:<div className="empty">暂无分析师评级。</div>}
    <div className="section-title"><h2>近四季度财报（SEC 单季，已去累计）</h2></div>
    <div className="table"><div className="table-head fin"><span>季度</span><span>报告期</span><span>营收</span><span>净利润</span><span>营业利润</span><span>EPS</span><span>净利率</span><span>经营现金流</span></div>{financials.data?.map(f=><div className="table-row fin" key={`${f.fiscal_year}${f.fiscal_period}`}><b>{f.fiscal_year} {f.fiscal_period}</b><span>{f.period_end}</span><span>{fmtNum(f.revenue)}</span><span>{fmtNum(f.net_income)}</span><span>{fmtNum(f.operating_income)}</span><span>{fmtNum(f.eps)}</span><span>{f.net_margin==null?'数据不足':f.net_margin.toFixed(1)+'%'}</span><span>{fmtNum(f.operating_cash_flow)}</span></div>)}{!financials.data?.length&&<div className="empty">暂无财报数据。</div>}</div>
  </div>
}

function SecCenter({tickers}:{tickers:string[]}) {
  const [active,setActive] = useState(tickers[0]||'')
  const [view,setView] = useState<'events'|'financials'|'insider'|'holdings'>('events')
  const client = useQueryClient()
  const current = active||tickers[0]||''
  const events = useQuery({queryKey:['sec-events',current],queryFn:()=>api<SecEvent[]>(`/sec-events?ticker=${current}`),enabled:!!current&&view==='events'})
  const fins = useQuery({queryKey:['sec-financials',current],queryFn:()=>api<SecFin[]>(`/sec-financials?ticker=${current}`),enabled:!!current&&view==='financials'})
  const insider = useQuery({queryKey:['sec-insider',current],queryFn:()=>api<SecInsider[]>(`/sec-insider?ticker=${current}`),enabled:!!current&&view==='insider'})
  const holdings = useQuery({queryKey:['sec-13f',current],queryFn:()=>api<Sec13F>(`/sec-13f?ticker=${current}`),enabled:!!current&&view==='holdings'})
  const refresh13f = useMutation({mutationFn:()=>post(`/sec-13f/refresh`,{}),onSuccess:()=>setTimeout(()=>client.invalidateQueries({queryKey:['sec-13f',current]}),8000)})
  const refresh = useMutation({mutationFn:()=>post(`/sec-filings/refresh?ticker=${current}`,{}),onSuccess:()=>setTimeout(()=>{client.invalidateQueries({queryKey:['sec-events',current]});client.invalidateQueries({queryKey:['sec-financials',current]});client.invalidateQueries({queryKey:['sec-insider',current]})},5000)})
  const priorityName:Record<string,string> = {urgent:'紧急',important:'重要',normal:'常规'}
  const fmtNum = (v:number|null) => {
    if(v==null) return '数据不足'
    const abs=Math.abs(v), sign=v<0?'-':''
    if(abs>=1e8) return `${sign}${(abs/1e8).toFixed(2)}亿`
    if(abs>=1e4) return `${sign}${(abs/1e4).toFixed(2)}万`
    return v.toLocaleString('en-US',{maximumFractionDigits:2})
  }
  const codeName:Record<string,string> = {P:'买入',S:'卖出',M:'期权行权',F:'税务代扣',A:'授予',G:'赠予',D:'处置'}
  if(!tickers.length) return <div className="empty">请先在自选股中添加股票。</div>
  return <div className="news-center">
    <div className="news-tickers">{tickers.map(t=><button key={t} className={t===current?'active':''} onClick={()=>setActive(t)}>{t}</button>)}</div>
    <div className="section-title"><h2>{current} SEC 官方数据</h2><button onClick={()=>refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending?'刷新中…':'刷新数据'}</button></div>
    {refresh.isSuccess&&<p className="saved">已触发后台采集（含 XBRL 解析，约需 1-2 分钟），稍后自动刷新。</p>}
    <div className="news-tickers" style={{marginTop:4}}>{([['events','重大事件'],['financials','财务数据'],['insider','内幕交易'],['holdings','机构持仓']] as const).map(([k,l])=><button key={k} className={view===k?'active':''} onClick={()=>setView(k)}>{l}</button>)}</div>
    <small className="chart-note">数据来自 SEC EDGAR 官方披露（edgartools 解析），仅供参考</small>

    {view==='events'&&<div className="news-list">{events.data?.map(e=><article className={`news-card sec-${e.priority}`} key={e.id}>
      <div className="news-body">
        <div className="news-meta"><span className={`sec-prio ${e.priority}`}>{priorityName[e.priority]||e.priority}</span><span className="sec-form">{e.form}</span><span className="sec-event-tag">Item {e.item_code} · {e.item_label}</span>{e.filing_date&&<span>披露 {e.filing_date}</span>}</div>
        {e.summary_zh
          ? <div className="ai-summary sec-summary"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{e.summary_zh}</ReactMarkdown></div>
          : (e.summary_status==='failed'
              ? (e.text&&<p className="news-summary" style={{whiteSpace:'pre-wrap'}}>{e.text.length>600?e.text.slice(0,600)+'…':e.text}</p>)
              : (e.text?<p className="news-summary sec-summary-pending">AI 中文总结生成中…</p>:null))}
        {e.text&&<details className="sec-original"><summary>展开查看英文原文</summary><p className="news-summary" style={{whiteSpace:'pre-wrap'}}>{e.text}</p></details>}
        <a className="news-title" href={e.filing_url} target="_blank" rel="noreferrer">查看 SEC 原文</a>
      </div>
    </article>)}{!events.data?.length&&<div className="empty">暂无重大事件，点击"刷新数据"触发采集。</div>}</div>}

    {view==='financials'&&<div className="table"><div className="table-head fin"><span>期间</span><span>营收</span><span>净利润</span><span>营业利润</span><span>毛利</span><span>EPS(摊薄)</span><span>现金</span><span>负债/经营现金流</span></div>{fins.data?.map(f=><div className="table-row fin" key={`${f.fiscal_year}${f.fiscal_period}${f.form}`}><b>{f.fiscal_year} {f.fiscal_period}</b><span>{fmtNum(f.revenue)}</span><span>{fmtNum(f.net_income)}</span><span>{fmtNum(f.operating_income)}</span><span>{fmtNum(f.gross_profit)}</span><span>{f.eps_diluted==null?'数据不足':f.eps_diluted.toFixed(2)}</span><span>{fmtNum(f.cash_and_equivalents)}</span><span>{fmtNum(f.total_debt)} / {fmtNum(f.operating_cash_flow)}</span></div>)}{!fins.data?.length&&<div className="empty">暂无 SEC 财务数据（需存在 10-K/10-Q 披露）。</div>}</div>}

    {view==='insider'&&<><div className="explainer"><b>什么是内部人交易（Form 4）？</b><p>公司高管、董事及持股 5% 以上的大股东，买卖本公司股票后须在两个工作日内向 SEC 申报，即 Form 4。这是了解"最懂公司的人"如何用真金白银投票的窗口。<b>CEO 等核心高管的公开市场买入</b>（🌟）通常被视为信心信号；<b>短期内的大额抛售</b>（⚠️）则值得留意，但也可能只是行权、税务或分散配置等中性原因，需结合背景判断。金额栏为该笔交易的市值估算。</p></div><div className="table"><div className="table-head fin"><span>日期</span><span>内幕人</span><span>职务</span><span>类型</span><span>股数</span><span>价格</span><span>金额</span><span>交易后持股</span></div>{insider.data?.map(t=><div className="table-row fin" key={t.id}><b>{t.transaction_date||'—'}{t.flag==='ceo_buy'&&' 🌟'}{t.flag==='heavy_sell'&&' ⚠️'}</b><span>{t.insider_name}</span><span>{t.insider_title||'—'}</span><span className={t.transaction_code==='P'?'positive':t.transaction_code==='S'?'negative':''}>{t.transaction_code?(codeName[t.transaction_code]||t.transaction_code):'—'}</span><span>{fmtNum(t.shares)}</span><span>{t.price==null?'—':`$${t.price.toFixed(2)}`}</span><span>{fmtNum(t.value)}</span><span>{fmtNum(t.shares_owned_after)}</span></div>)}{!insider.data?.length&&<div className="empty">暂无内幕交易记录（Form 4）。</div>}</div></>}

    {view==='holdings'&&<>
      <div className="explainer"><b>什么是机构持仓（13F）？</b><p>管理资产超 1 亿美元的机构投资者（对冲基金、资管、养老金等）须在每个自然季度结束后 <b>45 天内</b>向 SEC 申报所持美股，即 Form 13F。它让我们看到"聪明钱"在这只股票上的整体布局。注意两点：<b>① 数据有约一个季度的滞后</b>，反映的是上季度末的持仓而非当下；<b>② 只含多头（做多），不含做空</b>，且不代表机构全部仓位。下方"环比"是相对上一季度的加减仓，<b>本季新建仓</b>与大幅增持通常被视为看多信号，清仓/大幅减持则相反。</p></div>
      <div className="section-title" style={{marginTop:8}}><span>{holdings.data?.report_period?`季度截至 ${holdings.data.report_period}`:'机构持仓'}{holdings.data?.prev_period&&`（对比 ${holdings.data.prev_period}）`}</span><button onClick={()=>refresh13f.mutate()} disabled={refresh13f.isPending}>{refresh13f.isPending?'采集中…':'重新采集'}</button></div>
      {refresh13f.isSuccess&&<p className="saved">已触发全市场 13F 数据集采集（约需数分钟下载解析），稍后自动刷新。</p>}
      <div className="table"><div className="table-head fin"><span>机构</span><span>持股数</span><span>持仓市值</span><span>类型</span><span>环比变动</span><span>申报日</span></div>{holdings.data?.holdings.map(h=><div className="table-row fin" key={h.id}><b>{h.manager_name}</b><span>{fmtNum(h.shares)}</span><span>{fmtNum(h.value_usd)}</span><span>{h.put_call||'股票'}</span><span className={h.is_new?'positive':h.share_change==null?'':h.share_change>0?'positive':h.share_change<0?'negative':''}>{h.is_new?'本季新建仓':h.share_change==null?'—':`${h.share_change>0?'+':''}${fmtNum(h.share_change)}`}</span><span>{h.filing_date||'—'}</span></div>)}{!holdings.data?.holdings.length&&<div className="empty">暂无 13F 机构持仓数据，点击"重新采集"触发（13F 每季度更新一次）。</div>}</div>
    </>}
  </div>
}

function ChartsCenter({tickers}:{tickers:string[]}) {
  const [active,setActive] = useState(tickers[0]||'')
  const current = active||tickers[0]||''
  const container = useRef<HTMLDivElement>(null)
  useEffect(()=>{
    if(!current||!container.current) return
    const host = container.current
    host.innerHTML = ''
    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    widget.style.height = '100%'
    host.appendChild(widget)
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.innerHTML = JSON.stringify({
      autosize:true,
      symbol:current,
      interval:'D',
      timezone:'America/New_York',
      theme:'light',
      style:'1',
      locale:'zh_CN',
      allow_symbol_change:true,
      hide_side_toolbar:false,
      support_host:'https://www.tradingview.com',
    })
    host.appendChild(script)
    return ()=>{ host.innerHTML = '' }
  },[current])
  if(!tickers.length) return <div className="empty">请先在自选股中添加股票。</div>
  return <div className="news-center">
    <div className="news-tickers">{tickers.map(t=><button key={t} className={t===current?'active':''} onClick={()=>setActive(t)}>{t}</button>)}</div>
    <div className="section-title"><h2>{current} 实时图表</h2><small className="chart-note">数据由 TradingView 提供，仅供参考</small></div>
    <div className="chart-shell"><div className="tradingview-widget-container" ref={container} style={{height:'100%',width:'100%'}}/></div>
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

const PIE_COLORS = ['#4f7cff','#ff6b6b','#22c55e','#f59e0b','#a855f7','#06b6d4','#ec4899','#84cc16','#f97316','#14b8a6','#eab308','#8b5cf6']
const CAT_NAMES:Record<string,string> = {stock:'股票',etf:'ETF/基金',preferred:'优先股',corp_bond:'企业债',muni_bond:'市政债',treasury:'国债',option:'期权',other:'其他'}

function PieChart({slices}:{slices:{label:string;value:number;color:string}[]}) {
  const total = slices.reduce((s,x)=>s+x.value,0)
  if(total<=0) return <div className="empty">暂无持仓数据。</div>
  const R=90, C=100
  let acc=0
  const arcs = slices.map(s=>{
    const frac=s.value/total
    const a0=acc*2*Math.PI-Math.PI/2, a1=(acc+frac)*2*Math.PI-Math.PI/2
    acc+=frac
    const x0=C+R*Math.cos(a0), y0=C+R*Math.sin(a0), x1=C+R*Math.cos(a1), y1=C+R*Math.sin(a1)
    const large=frac>0.5?1:0
    return {d:`M${C},${C} L${x0},${y0} A${R},${R} 0 ${large},1 ${x1},${y1} Z`,color:s.color,frac}
  })
  return <svg viewBox="0 0 200 200" className="pie-svg" width="200" height="200">
    {arcs.map((a,i)=><path key={i} d={a.d} fill={a.color} stroke="#fff" strokeWidth="1"/>)}
  </svg>
}

function CongressCenter() {
  const client = useQueryClient()
  const [slug,setSlug] = useState('')
  const [q,setQ] = useState('')
  const [doSearch,setDoSearch] = useState('')
  const figures = useQuery({queryKey:['congress-figures'],queryFn:()=>api<Figure[]>('/congress/figures')})
  const current = slug || figures.data?.[0]?.slug || ''
  const detail = useQuery({queryKey:['congress-figure',current],queryFn:()=>api<FigureDetail>(`/congress/figure/${current}`),enabled:!!current})
  const search = useQuery({queryKey:['congress-search',doSearch],queryFn:()=>api<FilerHit[]>(`/congress/search?q=${encodeURIComponent(doSearch)}`),enabled:doSearch.length>=2})
  const subscribe = useMutation({mutationFn:(h:FilerHit)=>post('/congress/subscribe',{filer_id:h.filer_id,full_name:h.full_name}),onSuccess:()=>{setDoSearch('');setQ('');client.invalidateQueries({queryKey:['congress-figures']})}})
  const unsub = useMutation({mutationFn:(s:string)=>api(`/congress/figure/${s}`,{method:'DELETE'}),onSuccess:()=>{setSlug('');client.invalidateQueries({queryKey:['congress-figures']})}})
  const partyName:Record<string,string> = {D:'民主党',R:'共和党',I:'独立'}
  const fmtMoney = (v:number) => v>=1e8?`$${(v/1e8).toFixed(2)}亿`:v>=1e4?`$${(v/1e4).toFixed(1)}万`:`$${v.toFixed(0)}`
  return <div className="news-center">
    <div className="news-tickers">{figures.data?.map(f=><button key={f.slug} className={f.slug===current?'active':''} onClick={()=>setSlug(f.slug)}>{f.display_name}{f.is_seed?'':' ×'}</button>)}</div>
    <form className="add-form" onSubmit={e=>{e.preventDefault();setDoSearch(q.trim())}}><div><label>订阅其他政客</label><input value={q} onChange={e=>setQ(e.target.value)} placeholder="输入名字，如 Pelosi、Tuberville" maxLength={64}/></div><button>搜索</button></form>
    {search.data&&search.data.length>0&&<div className="search-hits">{search.data.map(h=><button key={h.filer_id} className="hit-row" onClick={()=>subscribe.mutate(h)} disabled={subscribe.isPending}><b>{h.full_name}</b><span>{h.chamber||h.branch} · {partyName[h.party||'']||h.party||'—'} {h.state||''}</span><em>{h.trade_count??0} 笔 · 点击订阅</em></button>)}</div>}
    {doSearch.length>=2&&search.data?.length===0&&<div className="empty">未找到匹配的政客。</div>}
    <CongressDetail detail={detail.data} loading={detail.isLoading} onUnsub={s=>unsub.mutate(s)} fmtMoney={fmtMoney}/>
  </div>
}

function CongressDetail({detail,loading,onUnsub,fmtMoney}:{detail:FigureDetail|undefined;loading:boolean;onUnsub:(s:string)=>void;fmtMoney:(v:number)=>string}) {
  if(loading) return <div className="empty">加载中…</div>
  if(!detail) return <div className="empty">请选择一位名人。</div>
  const pct = detail.positions_are_percent
  const total = detail.positions.reduce((s,p)=>s+p.value,0)
  const slices = detail.positions.map((p,i)=>({label:p.ticker||p.asset_name,value:p.value,color:PIE_COLORS[i%PIE_COLORS.length]}))
  const typeName:Record<string,string> = {'Purchase':'买入','Sale (Full)':'清仓','Sale (Partial)':'部分卖出','Exchange':'换股'}
  const typeCls = (t:string|null) => (t||'').includes('Purchase')?'positive':(t||'').includes('Sale')?'negative':''
  return <>
    <div className="section-title"><h2>{detail.display_name}</h2>{!detail.is_seed&&<button className="danger" onClick={()=>onUnsub(detail.slug)}>取消订阅</button>}</div>
    {detail.note&&<small className="chart-note">{detail.note}</small>}
    {detail.is_seed&&detail.positions.length>0&&<>
      <div className="explainer"><b>关于这张持仓饼图</b><p>数据基于 STOCK Act / 年度披露的<b>金额区间中点估算</b>，{pct?'为基金持仓占比（%）':'并叠加基线日期后的逐笔交易（买入加、部分卖出减、清仓归零）'}。<b>这是估算，非实际市值持仓</b>，仅供了解配置结构与方向。</p></div>
      <div className="pie-wrap">
        <PieChart slices={slices}/>
        <div className="pie-legend">{slices.slice(0,14).map((s,i)=>{const p=detail.positions[i];return <div className="legend-row" key={i}><i style={{background:s.color}}/><b>{s.label}</b><span>{CAT_NAMES[p.category]||p.category}</span><em>{pct?`${s.value.toFixed(2)}%`:`${fmtMoney(s.value)} · ${(s.value/total*100).toFixed(1)}%`}</em></div>})}</div>
      </div>
    </>}
    {detail.moves&&<div className="moves-board"><div className="moves-col"><h3>近30天加仓 ⬆️</h3>{detail.moves.buys.map((m,i)=><div key={i} className="move-row positive">{m}</div>)}</div><div className="moves-col"><h3>近30天减仓 ⬇️</h3>{detail.moves.sells.map((m,i)=><div key={i} className="move-row negative">{m}</div>)}</div></div>}
    <div className="section-title"><h2>交易动态（政治家时间轴）</h2></div>
    {detail.trades.length===0&&<div className="empty">{detail.kind==='fund_manager'?'该名人无国会披露交易。':'暂无交易记录，稍后同步。'}</div>}
    <div className="timeline">{detail.trades.map(t=><div className="tl-row" key={t.id}>
      <span className="tl-date">{t.transaction_date||t.filing_date||'—'}{t.is_late&&<em className="late" title="逾期申报"> 迟报</em>}</span>
      <b className="tl-ticker">{t.ticker||'—'}</b>
      <span className={`tl-type ${typeCls(t.transaction_type)}`}>{typeName[t.transaction_type||'']||t.transaction_type||'—'}</span>
      <span className="tl-amount">{t.amount_label||'—'}</span>
      <span className="tl-asset">{t.asset_name||''}</span>
    </div>)}</div>
  </>
}

function TrashIcon() { return <svg className="trash-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg> }

function ThresholdCell({item,field,onSaved}:{item:WatchItem;field:'threshold_20m'|'threshold_1h'|'threshold_day';onSaved:()=>void}) {
  const [editing,setEditing] = useState(false)
  const [value,setValue] = useState('')
  const save = useMutation({mutationFn:(payload:{[k:string]:number|null})=>patch<WatchItem>(`/watchlist/${item.id}`,payload),onSuccess:()=>{setEditing(false);onSaved()}})
  const begin = () => { setValue(item[field]==null?'':String(item[field])); setEditing(true) }
  const commit = () => {
    const trimmed = value.trim()
    if(trimmed===''){ save.mutate({[field]:null}); return }
    const num = Number(trimmed)
    if(!Number.isFinite(num)||num<=0){ setEditing(false); return }
    save.mutate({[field]:num})
  }
  const labels:Record<string,string> = {threshold_20m:'20 分钟',threshold_1h:'1 小时',threshold_day:'当日'}
  return <>
    <button type="button" className="threshold-chip" onClick={begin}><span>{labels[field]}</span><b>{item[field]==null?'默认':`${item[field]}%`}</b></button>
    {createPortal(<Sheet open={editing} onClose={()=>setEditing(false)} title={`${labels[field]}涨跌阈值`}>
      <div className="threshold-drawer"><p>设置 <b>{labels[field]}</b> 内触发异动提醒的涨跌幅。清空后恢复系统默认值。</p><label>涨跌阈值 (%)<input autoFocus type="number" inputMode="decimal" min="0" step="0.1" value={value} placeholder="默认" onChange={e=>setValue(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')commit();if(e.key==='Escape')setEditing(false)}}/></label><div className="threshold-drawer-actions"><button type="button" className="ghost-btn" onClick={()=>setEditing(false)}>取消</button><button type="button" onClick={commit} disabled={save.isPending}>{save.isPending?'保存中…':'保存阈值'}</button></div></div>
    </Sheet>, document.body)}
  </>
}

function SettingsForm({initial,onSaved}:{initial:Settings;onSaved:()=>void}) {
  const [form,setForm]=useState(initial)
  const save=useMutation({mutationFn:()=>patch<Settings>('/settings',form),onSuccess:onSaved})
  const fields:[keyof Settings,string][]=[['threshold_20m','20 分钟涨跌阈值 (%)'],['threshold_1h','1 小时涨跌阈值 (%)'],['threshold_day','当日涨跌阈值 (%)'],['alert_cooldown_minutes','同类警报冷却时间 (分钟)'],['investigation_interval_minutes','异动新闻搜索间隔 (分钟)'],['investigation_duration_minutes','异动调查持续时间 (分钟)']]
  return <section className="settings-card"><h2>监控规则</h2><p>修改后将影响新触发的监控任务。API 密钥只在服务器环境变量中配置。</p><div className="settings-grid">{fields.map(([key,label])=><label key={key}>{label}<input type="number" inputMode="decimal" value={form[key]} onChange={e=>setForm({...form,[key]:Number(e.target.value)})}/></label>)}</div><div className="readonly">行情轮询间隔：{form.price_poll_minutes} 分钟（通过环境变量配置）</div><button onClick={()=>save.mutate()} disabled={save.isPending}>{save.isPending?'保存中…':'保存设置'}</button>{save.isSuccess&&<span className="saved">已保存</span>}</section>
}


// ── 登录 / 注册 ──────────────────────────────────────────────────
function AuthGate({setToken,setAuthUser,onPreview}:{setToken:(t:string)=>void;setAuthUser:(u:{username:string;role:string}|null)=>void;onPreview:()=>void}) {
  const [mode,setMode] = useState<'login'|'register'>('login')
  const [username,setUsername] = useState('')
  const [password,setPassword] = useState('')
  const [remember,setRemember] = useState(false)
  const [msg,setMsg] = useState('')
  const [ok,setOk] = useState(false)

  const handleLogin = async (e:React.FormEvent) => {
    e.preventDefault(); setMsg('')
    try {
      const res = await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,remember})})
      const data = await res.json()
      if(!res.ok){setMsg(data.detail||'登录失败');return}
      if(remember) localStorage.setItem('auth_token',data.token)
      else sessionStorage.setItem('auth_token',data.token)
      setToken(data.token)
      setAuthUser({username:data.username,role:data.role})
    } catch{setMsg('网络错误')}
  }

  const handleRegister = async (e:React.FormEvent) => {
    e.preventDefault(); setMsg('')
    try {
      const res = await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})})
      const data = await res.json()
      if(!res.ok){setMsg(data.detail||'注册失败');return}
      setOk(true); setMsg('注册申请已提交，等待管理员审核')
    } catch{setMsg('网络错误')}
  }

  return <div className="auth-gate">
    <div className="auth-aurora auth-aurora-one"/><div className="auth-aurora auth-aurora-two"/>
    <div className="auth-intro"><span className="auth-kicker">MARKET INTELLIGENCE</span><h1>看见波动背后的<br/>真正信号。</h1><p>把行情、公告与新闻凝聚成清晰判断，<br/>让每一次关注都有意义。</p><div className="auth-signal"><span><i/> AAPL</span><b>214.37</b><em>+1.51%</em></div></div>
    <div className="auth-card">
      <div className="brand"><div className="brand-orb"><img src="/logo.png" className="brand-logo" alt="logo"/></div><div><strong>小日向美香</strong><small>欢迎回来</small></div></div>
      <div className="auth-tabs">
        <button className={mode==='login'?'active':''} onClick={()=>{setMode('login');setMsg('');setOk(false)}}>登录</button>
        <button className={mode==='register'?'active':''} onClick={()=>{setMode('register');setMsg('');setOk(false)}}>申请注册</button>
      </div>
      {mode==='login'
        ?<form onSubmit={handleLogin} className="auth-form">
          <input placeholder="用户名" value={username} onChange={e=>setUsername(e.target.value)} autoFocus/>
          <input type="password" placeholder="密码" value={password} onChange={e=>setPassword(e.target.value)}/>
          <label className="remember-label"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/> 记住我（30天）</label>
          {msg&&<p className="auth-msg">{msg}</p>}
          <button type="submit" className="auth-submit">登录 <span>→</span></button>
        </form>
        :ok
          ?<p className="auth-msg ok">{msg}</p>
          :<form onSubmit={handleRegister} className="auth-form">
            <input placeholder="用户名（至少2位）" value={username} onChange={e=>setUsername(e.target.value)} autoFocus/>
            <input type="password" placeholder="密码（至少6位）" value={password} onChange={e=>setPassword(e.target.value)}/>
            <p className="auth-hint">注册后需等待管理员审核激活</p>
            {msg&&<p className="auth-msg">{msg}</p>}
            <button type="submit" className="auth-submit">提交申请 <span>→</span></button>
          </form>}
      <button className="preview-btn" onClick={onPreview}><span className="preview-icon">⌁</span><span><b>浏览演示界面</b><small>无需账户 · 使用本地示例数据</small></span><em>→</em></button>
    </div>
  </div>
}

// ── 交易日志 ───────────────────────────────────────────────
const emptyTradeRow = ():TradeLogRow => ({ticker:'',direction:'',quantity:null,price:null,fee:null,strategy:'',result:''})

function JournalSection({username}:{username:string}) {
  const client = useQueryClient()
  const today = new Date().toISOString().slice(0,10)
  const logs = useQuery({queryKey:['trade-logs'],queryFn:()=>api<TradeLog[]>('/trade-logs')})
  const [editing,setEditing] = useState<TradeLog|null>(null)
  const [editorOpen,setEditorOpen] = useState(()=>new URLSearchParams(window.location.search).get('journal')==='new')
  const [form,setForm] = useState({trade_date:today,ticker:'',direction:'',quantity:'',price:'',note:'',content:'',table_rows:[emptyTradeRow()],photo_urls:[] as string[]})
  const payload = () => ({
    trade_date:form.trade_date,
    ticker:null,
    direction:null,
    quantity:null,
    price:null,
    note:form.note||null,
    content:form.content||null,
    table_rows:form.table_rows.filter(r=>r.ticker||r.direction||r.quantity!=null||r.price!=null||r.strategy||r.result).map(r=>({...r,fee:null})),
    photo_urls:form.photo_urls,
  })
  const reset = () => {setEditing(null);setEditorOpen(false);setForm({trade_date:today,ticker:'',direction:'',quantity:'',price:'',note:'',content:'',table_rows:[emptyTradeRow()],photo_urls:[]})}
  const save = useMutation({
    mutationFn:()=>editing?patch<TradeLog>(`/trade-logs/${editing.id}`,payload()):post<TradeLog>('/trade-logs',payload()),
    onSuccess:()=>{reset();client.invalidateQueries({queryKey:['trade-logs']})},
  })
  const del = useMutation({mutationFn:(id:number)=>api<unknown>(`/trade-logs/${id}`,{method:'DELETE'}),onSuccess:()=>client.invalidateQueries({queryKey:['trade-logs']})})
  const summarize = useMutation({mutationFn:(id:number)=>post<TradeLog>(`/trade-logs/${id}/summarize`,{}),onSuccess:()=>client.invalidateQueries({queryKey:['trade-logs']})})
  const edit = (log:TradeLog) => {
    setEditing(log)
    setForm({
      trade_date:log.trade_date,
      ticker:log.ticker||'',
      direction:log.direction||'',
      quantity:log.quantity==null?'':String(log.quantity),
      price:log.price==null?'':String(log.price),
      note:log.note||'',
      content:log.content||'',
      table_rows:log.table_rows.length?log.table_rows:[emptyTradeRow()],
      photo_urls:log.photo_urls||[],
    })
    setEditorOpen(true)
  }
  const updateRow = (index:number, patch:Partial<TradeLogRow>) => setForm(f=>({...f,table_rows:f.table_rows.map((row,i)=>i===index?{...row,...patch}:row)}))
  const addPhotos = (files:FileList|null) => {
    if(!files) return
    Array.from(files).slice(0,6).forEach(file=>{
      const reader = new FileReader()
      reader.onload = () => setForm(f=>({...f,photo_urls:[...f.photo_urls,String(reader.result)].slice(0,12)}))
      reader.readAsDataURL(file)
    })
  }
  const beginNew = () => {setEditing(null);setForm({trade_date:today,ticker:'',direction:'',quantity:'',price:'',note:'',content:'',table_rows:[emptyTradeRow()],photo_urls:[]});setEditorOpen(true)}
  const removeRow = (index:number) => setForm(f=>({...f,table_rows:f.table_rows.length>1?f.table_rows.filter((_,i)=>i!==index):[emptyTradeRow()]}))
  return <div className="journal">
      <div className="journal-list">
        <div className="section-title journal-list-title"><div><p>TRADING JOURNAL</p><h2>我的日志</h2></div><div className="journal-list-actions"><span>{logs.data?.length||0} 条</span><button className="journal-new-btn" onClick={beginNew}><span>＋</span> 新建日志</button></div></div>
        {logs.data?.map(log=><article className="journal-card" key={log.id}>
          <div className="journal-card-head"><div><b>{log.trade_date}</b><span>{[log.ticker,log.direction].filter(Boolean).join(' · ')||'未填写标的'}</span></div><small>{formatDate(log.created_at)}</small></div>
          {log.note&&<p>{log.note}</p>}
          {log.content&&<p className="journal-content">{log.content}</p>}
          {log.table_rows.length>0&&<div className="journal-mini-table">{log.table_rows.map((row,i)=><span key={i}>{row.ticker||'—'} {row.direction||''} {row.quantity??'—'} @ {row.price??'—'}</span>)}</div>}
          {log.photo_urls.length>0&&<div className="photo-strip">{log.photo_urls.map((src,i)=><img src={src} alt={`交易截图 ${i+1}`} key={i}/>)}</div>}
          {log.ai_summary&&<div className="ai-summary"><span className="ai-tag">AI · {log.ai_summary_model}</span><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{log.ai_summary}</ReactMarkdown></div>}
          <div className="journal-card-actions"><button onClick={()=>summarize.mutate(log.id)} disabled={summarize.isPending}>{summarize.isPending?'处理中…':'AI 优化总结'}</button><button onClick={()=>edit(log)}>编辑</button><button className="danger" aria-label="删除日志" onClick={()=>del.mutate(log.id)}><TrashIcon/></button></div>
        </article>)}
        {logs.isLoading&&<div className="empty">加载交易日志中…</div>}
        {!logs.isLoading&&!logs.data?.length&&<div className="empty">还没有日志。每天收盘后写一条，数据只对当前登录用户可见。</div>}
      </div>
    {createPortal(<Sheet open={editorOpen} onClose={reset} title={editing?'编辑交易日志':'新建交易日志'}>
      <form className="journal-editor" onSubmit={event=>{event.preventDefault();save.mutate()}}>
        <div className="journal-editor-intro"><div><p className="eyebrow">{editing?'EDIT ENTRY':'NEW ENTRY'}</p><h2>{editing?'编辑交易日志':'把这次交易留下来'}</h2></div><span>当前用户：{username}</span></div>
        <label className="journal-date-field">日期<input type="date" value={form.trade_date} onChange={e=>setForm({...form,trade_date:e.target.value})} required/></label>
        <label className="journal-note">简短备注<input value={form.note} onChange={e=>setForm({...form,note:e.target.value})} placeholder="一句话记录当天最重要的交易背景"/></label>
        <label className="journal-note">文字记录<textarea value={form.content} onChange={e=>setForm({...form,content:e.target.value})} placeholder="记录交易计划、执行、情绪、复盘和明天要验证的条件"/></label>
        <div className="journal-table">
          <div className="journal-table-heading"><div><b>交易明细</b><span>{form.table_rows.length} 张便签</span></div><small>每张便签可以记录一笔交易</small></div>
          {form.table_rows.map((row,index)=><div className="journal-row-note" key={index}>
            <div className="journal-row-top"><label><span>标的</span><input value={row.ticker} onChange={e=>updateRow(index,{ticker:e.target.value.toUpperCase()})} placeholder="NVDA"/></label><label><span>方向</span><select value={row.direction} onChange={e=>updateRow(index,{direction:e.target.value})}><option value="">选择方向</option><option>买入</option><option>卖出</option><option>观望</option><option>挂单</option></select></label><button type="button" className="row-delete" aria-label="删除这笔交易" onClick={()=>removeRow(index)}><TrashIcon/></button></div>
            <div className="journal-row-bottom"><label><span>数量</span><input type="number" inputMode="decimal" min="0" step="any" value={row.quantity??''} onChange={e=>updateRow(index,{quantity:e.target.value===''?null:Number(e.target.value)})} placeholder="0"/></label><label><span>价格</span><input type="number" inputMode="decimal" min="0" step="any" value={row.price??''} onChange={e=>updateRow(index,{price:e.target.value===''?null:Number(e.target.value)})} placeholder="0.00"/></label><label><span>自定义标签</span><input value={row.strategy} onChange={e=>updateRow(index,{strategy:e.target.value})} placeholder="突破 / 试仓"/></label><label><span>其他</span><input value={row.result} onChange={e=>updateRow(index,{result:e.target.value})} placeholder="补充说明"/></label></div>
          </div>)}
          <button type="button" className="add-note-btn" onClick={()=>setForm(f=>({...f,table_rows:[...f.table_rows,emptyTradeRow()]}))}><span>＋</span> 添加交易便签</button>
        </div>
        <div className="photo-uploader"><label>照片<input type="file" accept="image/*" multiple onChange={e=>addPhotos(e.target.files)}/></label><div className="photo-grid">{form.photo_urls.map((src,index)=><div className="photo-thumb" key={index}><img src={src} alt={`交易截图 ${index+1}`}/><button type="button" onClick={()=>setForm(f=>({...f,photo_urls:f.photo_urls.filter((_,i)=>i!==index)}))}>移除</button></div>)}</div></div>
        {save.error&&<p className="error">{save.error.message}</p>}
        <div className="journal-actions"><button disabled={save.isPending}>{save.isPending?'保存中…':'保存日志'}</button>{editing&&<button type="button" className="ghost-btn" onClick={reset}>取消编辑</button>}</div>
      </form>
    </Sheet>, document.body)}
  </div>
}

// ── 管理员用户管理 ────────────────────────────────────────────────
type UserRow = {id:number;username:string;role:string;status:string;created_at:string}

function AdminPanel() {
  const client = useQueryClient()
  const users = useQuery({queryKey:['admin-users'],queryFn:()=>api<UserRow[]>('/auth/admin/users')})
  const approve = useMutation({mutationFn:(id:number)=>post<unknown>(`/auth/admin/users/${id}/approve`,{}),onSuccess:()=>client.invalidateQueries({queryKey:['admin-users']})})
  const del = useMutation({mutationFn:(id:number)=>api<unknown>(`/auth/admin/users/${id}`,{method:'DELETE'}),onSuccess:()=>client.invalidateQueries({queryKey:['admin-users']})})
  const statusLabel:Record<string,string> = {active:'已激活',pending:'待审核'}
  return <div style={{marginTop:32}}>
    <div className="section-title"><h2>用户管理</h2></div>
    <div className="table">
      <div className="table-head"><span>用户名</span><span>角色</span><span>状态</span><span>注册时间</span><span/></div>
      {users.data?.map(u=><div className="table-row" key={u.id}>
        <b>{u.username}</b>
        <span>{u.role==='admin'?'管理员':'普通用户'}</span>
        <span className={u.status==='active'?'positive':''}>{statusLabel[u.status]||u.status}</span>
        <span>{new Date(u.created_at).toLocaleDateString('zh-CN')}</span>
        <span style={{display:'flex',gap:6}}>
          {u.status==='pending'&&<button onClick={()=>approve.mutate(u.id)}>激活</button>}
          {u.role!=='admin'&&<button className="danger" onClick={()=>del.mutate(u.id)}>删除</button>}
        </span>
      </div>)}
      {!users.data?.length&&<div className="empty">暂无用户数据。</div>}
    </div>
  </div>
}
