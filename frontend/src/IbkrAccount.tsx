import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'

type Sync = {id:number;account_id_masked:string|null;status:string;report_from_date:string|null;report_to_date:string|null;generated_at:string|null;imported_at:string;completed_at:string|null;parser_version:string;section_counts:Record<string,number>;warning_count:number;warnings:string[];source:string}
type SyncResult = {sync_run_id:number;status:string;stage:string;created?:boolean;imported:Record<string,number>;reconciliation:Record<string,number|boolean>;propagation:Record<string,unknown>;warnings:string[];error?:{stage:string;code:string;message:string}|null}
type Overview = {available:boolean;latest_sync:Sync|null;current_sync?:Sync|null;account_summary?:Record<string,string|number|null>;position_count:number;trade_count:number;order_count:number;cash_ledger_count:number}
type RecordRow = {id:number;section:string;symbol:string|null;conid:string|null;currency:string|null;asset_category:string|null;description:string|null;report_date:string|null;occurred_at:string|null;amount:string|null;quantity:string|null;price:string|null;fields:Record<string,string|null>;source:string}
type Page = {items:RecordRow[];page:number;page_size:number;total:number;has_more:boolean}
type AnalyticsPage = {items:Record<string,unknown>[];[key:string]:unknown}
type CpSyncRun = {sync_run_id:number;status:string;stage:string;trigger_type:string;started_at:string|null;completed_at:string|null;duration_ms:number|null;position_count:number;counts:{inserted:number;updated:number;removed:number};warnings:string[];error:{stage:string|null;code:string|null;message:string|null}|null;created?:boolean;account_id_masked?:string|null}
type CpStatus = {source:string;enabled:boolean;account_configured:boolean;configured:boolean;gateway:{enabled:boolean;live_checked:boolean;reachable?:boolean;authenticated?:boolean;connected?:boolean;probe_error?:{code:string;message:string}|null|null};last_sync:CpSyncRun|null;last_successful_sync:CpSyncRun|null;active_position_count:number;note:string}
type CpPositionRow = {id:number;account_id_masked:string|null;conid:string;symbol:string|null;asset_class:string|null;currency:string|null;exchange:string|null;quantity:string|null;average_cost:string|null;market_price:string|null;market_value:string|null;unrealized_pnl:string|null;realized_pnl:string|null;source:string;last_synced_at:string|null;status:string}
type CpPositions = {items:CpPositionRow[];total:number;note:string}

const tabs = [
  ['positions','当前持仓'],['trades','成交记录'],['orders','历史订单'],['cash-ledger','资金流水'],
  ['corporate-actions','公司活动'],['performance','收益与绩效'],['tax-lots','税务批次'],['fx-rates','多币种'],
] as const

const stageLabel:Record<string,string>={requested:'已排队',downloading:'等待并下载 Flex',downloaded:'下载完成',parsing:'解析',importing:'导入',reconciling:'Portfolio 对账',rebuilding:'重建分析',completed:'完成',failed:'失败'}
const cpStageLabel:Record<string,string>={requested:'已排队',connecting:'连接 Gateway 会话',fetching:'拉取账户与仓位',persisting:'写入数据库',completed:'完成',failed:'失败'}

const important:Record<string,string[]> = {
  positions:['description','side','position','costBasisPrice','costBasisMoney','markPrice','positionValue','fifoPnlUnrealized','percentOfNAV','fxRateToBase','listingExchange','openDateTime','holdingPeriodDateTime'],
  trades:['buySell','quantity','tradePrice','tradeMoney','ibCommission','taxes','netCash','fifoPnlRealized','orderType','tradeDate','settleDateTarget'],
  orders:['buySell','quantity','tradePrice','orderType','orderTime','ibOrderID','exchange','isAPIOrder'],
  'cash-ledger':['activityCode','activityDescription','amount','balance','debit','credit','settleDate','tradeCommission','tradeTax'],
}

function display(value:unknown){return value===null||value===undefined||value===''?'—':String(value)}
function when(value:string|null){return value?new Date(value).toLocaleString('zh-CN'):'—'}
function money(value:string|number|null|undefined,currency:string|number|null|undefined){if(value==null)return '数据不足';const parsed=Number(value);return Number.isFinite(parsed)?`${parsed.toLocaleString('zh-CN',{maximumFractionDigits:2})} ${currency||''}`:String(value)}

const assetClassLabel:Record<string,string>={STK:'股票',ETF:'ETF',ADR:'ADR',OPT:'期权',FUT:'期货',FOP:'期货期权',CASH:'外汇',BOND:'债券',MF:'基金'}

export function IbkrAccount(){
  const client=useQueryClient()
  const [tab,setTab]=useState<(typeof tabs)[number][0]>('positions')
  const [page,setPage]=useState(1)
  const [symbol,setSymbol]=useState('')
  const [expanded,setExpanded]=useState<number|null>(null)
  const [section,setSection]=useState<'records'|'performance'|'round-trips'|'income'|'health'>('records')
  const [syncRunId,setSyncRunId]=useState<number|null>(null)
  const [cpSyncRunId,setCpSyncRunId]=useState<number|null>(null)
  const [cpOpen,setCpOpen]=useState(false)
  const overview=useQuery({queryKey:['ibkr-overview'],queryFn:()=>api<Overview>('/ibkr/overview'),staleTime:60_000})
  const records=useQuery({queryKey:['ibkr-records',tab,page,symbol],queryFn:()=>api<Page>(`/ibkr/${tab}?page=${page}&page_size=50${symbol?`&symbol=${encodeURIComponent(symbol)}`:''}`),enabled:!!overview.data?.available,staleTime:60_000})
  const syncStatus=useQuery({queryKey:['ibkr-sync',syncRunId],queryFn:()=>api<SyncResult>(`/ibkr/sync/${syncRunId}`),enabled:syncRunId!==null,refetchInterval:q=>['queued','running'].includes((q.state.data as SyncResult|undefined)?.status||'')?1500:false})
  const startSync=useMutation({mutationFn:()=>post<SyncResult>('/ibkr/sync',{}),onSuccess:value=>setSyncRunId(value.sync_run_id)})
  const cpStatus=useQuery({queryKey:['ibkr-cp-status'],queryFn:()=>api<CpStatus>('/ibkr/client-portal/status'),staleTime:30_000})
  const cpLive=useQuery({queryKey:['ibkr-cp-status-live'],queryFn:()=>api<CpStatus>('/ibkr/client-portal/status?live=1'),staleTime:60_000})
  const cpPositions=useQuery({queryKey:['ibkr-cp-positions'],queryFn:()=>api<CpPositions>('/ibkr/client-portal/positions'),enabled:!!cpStatus.data?.configured,staleTime:30_000})
  const cpSyncStatus=useQuery({queryKey:['ibkr-cp-sync',cpSyncRunId],queryFn:()=>api<CpSyncRun>(`/ibkr/client-portal/sync/${cpSyncRunId}`),enabled:cpSyncRunId!==null,refetchInterval:q=>['queued','running'].includes((q.state.data as CpSyncRun|undefined)?.status||'')?1500:false})
  const startCpSync=useMutation({mutationFn:()=>post<CpSyncRun>('/ibkr/client-portal/sync',{}),onSuccess:value=>setCpSyncRunId(value.sync_run_id)})
  const analyticsPath=section==='performance'?'/ibkr/performance/daily':section==='round-trips'?'/ibkr/trades/round-trips':section==='income'?'/ibkr/dividends/summary':section==='health'?'/ibkr/data-health':''
  const analytics=useQuery({queryKey:['ibkr-analytics',section],queryFn:()=>api<AnalyticsPage>(analyticsPath),enabled:section!=='records',staleTime:60_000})
  const activeSync=syncStatus.data
  const activeCpSync=cpSyncStatus.data
  const cpBusy=['queued','running'].includes(activeCpSync?.status||'')
  useEffect(()=>{const current=overview.data?.current_sync;if(syncRunId===null&&current&&['queued','running'].includes(current.status))setSyncRunId(current.id)},[overview.data?.current_sync,syncRunId])
  useEffect(()=>{const current=cpStatus.data?.last_sync;if(cpSyncRunId===null&&current&&['queued','running'].includes(current.status))setCpSyncRunId(current.sync_run_id)},[cpStatus.data?.last_sync,cpSyncRunId])
  useEffect(()=>{
    if(!activeCpSync||!['completed','failed'].includes(activeCpSync.status))return
    client.invalidateQueries({queryKey:['ibkr-cp-status']});client.invalidateQueries({queryKey:['ibkr-cp-positions']})
  },[activeCpSync?.status,client])
  useEffect(()=>{
    if(!activeSync||!['completed','failed','partial_failed'].includes(activeSync.status))return
    client.invalidateQueries({queryKey:['ibkr-overview']});client.invalidateQueries({queryKey:['ibkr-records']})
    client.invalidateQueries({queryKey:['portfolio-summary']});client.invalidateQueries({queryKey:['portfolio-health']})
    client.invalidateQueries({queryKey:['portfolio-interpretation']});client.invalidateQueries({queryKey:['portfolio-transactions']})
    client.invalidateQueries({queryKey:['portfolio-performance']});client.invalidateQueries({queryKey:['portfolio-attribution']})
    client.invalidateQueries({queryKey:['portfolio-position-ledger']});client.invalidateQueries({queryKey:['portfolio-technical']})
    client.invalidateQueries({queryKey:['portfolio-completed-trades']});client.invalidateQueries({queryKey:['portfolio-open-lots']})
    client.invalidateQueries({queryKey:['portfolio-analysis-history']})
  },[activeSync?.status,client])
  const sync=overview.data?.latest_sync
  const cp=cpStatus.data
  const cpLast=cp?.last_sync
  const cpOk=cp?.last_successful_sync
  const cpGateway=cpLive.data?.gateway
  const cpGatewayState=!cp?.enabled?'未启用':!cpGateway?.live_checked?'状态未知':cpGateway.probe_error?'不可达':cpGateway.authenticated?(cpGateway.connected?'已连接':'已认证 · 未连接'):'未认证'
  if(overview.isLoading)return <div className="empty">正在读取 IBKR 数据库快照…</div>
  if(overview.isError)return <div className="error">IBKR 正式数据暂时无法读取。</div>
  const data=overview.data
  if(!data)return <div className="empty">IBKR 数据尚未就绪。</div>
  return <div className="ibkr-account">
    <section className="ibkr-source-grid">
      <div className="ibkr-source-card">
        <div className="ibkr-source-head"><div><small>CLIENT PORTAL GATEWAY · CURRENT</small><h2>Gateway 当前仓位</h2><p>当前账户与仓位的近实时快照，独立入库；不会修改 Portfolio 权威数据。</p></div>
          <span className={`ibkr-cp-state ${cpGateway?.reachable&&cpGateway?.authenticated?'ok':cpGateway?.probe_error?'bad':''}`}>{cpGatewayState}</span></div>
        <div className="ibkr-source-meta">
          <span>当前仓位 <b>{cp?.configured?cp.active_position_count:'—'}</b></span>
          <span>上次成功同步 <b>{when(cpOk?.completed_at||null)}</b></span>
          <span>账户 <b>{cpOk?.account_id_masked||'—'}</b></span>
        </div>
        <div className="ibkr-sync-action">
          <button onClick={()=>startCpSync.mutate()} disabled={!cp?.enabled||startCpSync.isPending||cpBusy} className="ibkr-cp-sync-btn">{startCpSync.isPending?'正在请求…':cpBusy?(cpStageLabel[activeCpSync?.stage||'requested']||'同步中'):'同步 Client Portal Gateway'}</button>
          {cp?.configured&&<button className="ibkr-cp-toggle" onClick={()=>setCpOpen(v=>!v)}>{cpOpen?'收起仓位':'查看 Gateway 仓位'}</button>}
        </div>
        {activeCpSync&&<p className={`ibkr-cp-result ${activeCpSync.status}`}>{activeCpSync.status==='completed'
          ?`同步完成：${activeCpSync.position_count} 个仓位 · 新增 ${activeCpSync.counts.inserted} · 更新 ${activeCpSync.counts.updated} · 移除 ${activeCpSync.counts.removed}${activeCpSync.warnings.length?` · ${activeCpSync.warnings.length} 项说明`:''}`
          :activeCpSync.status==='failed'?`同步失败：${activeCpSync.error?.message||'未知错误'}（阶段：${cpStageLabel[activeCpSync.error?.stage||'']||activeCpSync.error?.stage||'—'}）`
          :`${cpStageLabel[activeCpSync.stage]||activeCpSync.stage} · 运行 #${activeCpSync.sync_run_id}`}</p>}
        {!cp?.enabled&&<p className="ibkr-cp-hint">服务端未启用 IBKR_CP_ENABLED，无法同步。</p>}
        {cpOpen&&<div className="ibkr-cp-positions">
          {cpPositions.isLoading&&<div className="empty">正在读取 Gateway 仓位…</div>}
          {(cpPositions.data&&!cpPositions.data.items.length)&&<div className="empty">Gateway 当前没有仓位；空结果只在会话验证成功后写入。</div>}
          {cpPositions.data?.items.map(row=><div className="ibkr-cp-row" key={row.id}>
            <span><b>{row.symbol||row.conid}</b><small>{row.asset_class?assetClassLabel[row.asset_class]||row.asset_class:'—'}{row.exchange?` · ${row.exchange}`:''}</small></span>
            <span><small>数量</small><b>{display(row.quantity)}</b></span>
            <span><small>市值</small><b>{money(row.market_value,row.currency)}</b></span>
            <span><small>未实现盈亏</small><b>{money(row.unrealized_pnl,row.currency)}</b></span>
            <span><small>同步时间</small><b>{when(row.last_synced_at)}</b></span>
          </div>)}
        </div>}
      </div>
      <div className="ibkr-source-card">
        <div className="ibkr-source-head"><div><small>IBKR FLEX · END-OF-DAY</small><h2>Flex 账户快照</h2><p>IBKR Flex 日终报告：历史成交、现金流与权威持仓对账。数量与成本以 IBKR 为准，当前价格仍由项目行情系统提供。</p></div>
          <span>账户 {sync?.account_id_masked||'已脱敏'}</span></div>
        <div className="ibkr-source-meta">
          <span>报告期间 <b>{sync?.report_from_date||'—'} — {sync?.report_to_date||'—'}</b></span>
          <span>上次同步 <b>{when(sync?.completed_at||sync?.imported_at||null)}</b></span>
          <span>{sync?.warning_count?<b className="warn">{sync.warning_count} 项数据说明</b>:<b className="ok">数据完整</b>}</span>
        </div>
        <div className="ibkr-sync-action">
          <button onClick={()=>startSync.mutate()} disabled={startSync.isPending||['queued','running'].includes(activeSync?.status||'')}>{startSync.isPending?'正在请求…':['queued','running'].includes(activeSync?.status||'')?(stageLabel[activeSync?.stage||'requested']||'同步中'):'同步 Flex 报告'}</button>
        </div>
        {!data.available&&<p className="ibkr-cp-hint">尚未导入 Flex 报告；只有点击上方按钮才会通过受控代理请求 IBKR。</p>}
      </div>
    </section>
    {activeSync&&<section className={`ibkr-sync-progress ${activeSync.status}`}><div><b>{stageLabel[activeSync.stage]||activeSync.stage}</b><span>同步运行 #{activeSync.sync_run_id}</span></div>{activeSync.status==='completed'&&<p>Portfolio 已使用 IBKR 最新数据 · 应用 {Number(activeSync.reconciliation.applied_updates||0)} 项权威更新 · 派生分析与 AI 上下文已刷新。</p>}{['failed','partial_failed'].includes(activeSync.status)&&<p className="error">同步未完成：{activeSync.error?.message||'未知错误'}（阶段：{activeSync.error?.stage||activeSync.stage}）。Portfolio 不会被标记为已传播。</p>}</section>}
    {data.available&&<>
    <section className="ibkr-overview-grid">
      <div><span>Net Liquidation</span><strong>{money(overview.data.account_summary?.net_liquidation,overview.data.account_summary?.base_currency)}</strong><small>IBKR Flex</small></div>
      <div><span>Total Cash</span><strong>{money(overview.data.account_summary?.total_cash,overview.data.account_summary?.base_currency)}</strong><small>日终余额</small></div>
      <div><span>Settled Cash</span><strong>{money(overview.data.account_summary?.settled_cash,overview.data.account_summary?.base_currency)}</strong><small>日终余额</small></div>
      <div><span>Unrealized P&amp;L</span><strong>{money(overview.data.account_summary?.unrealized_pnl,overview.data.account_summary?.base_currency)}</strong><small>报告期间变化</small></div>
    </section>
    <section className="ibkr-sync-strip"><span>报告期间 <b>{sync?.report_from_date||'—'} — {sync?.report_to_date||'—'}</b></span><span>报告生成 <b>{when(sync?.generated_at||null)}</b></span><span>导入时间 <b>{when(sync?.imported_at||null)}</b></span><span className={sync?.warning_count?'warn':'ok'}>{sync?.warning_count?`${sync.warning_count} 项数据说明`:'数据完整'}</span></section>
    <nav className="ibkr-analysis-nav">{([['records','账户明细'],['performance','每日绩效'],['round-trips','交易闭环'],['income','股息与税费'],['health','数据健康']] as const).map(([key,label])=><button key={key} className={section===key?'active':''} onClick={()=>setSection(key)}>{label}</button>)}</nav>
    {section!=='records'&&<section className="ibkr-analysis-panel">
      {analytics.isLoading&&<div className="empty">正在读取派生分析…</div>}
      {analytics.isError&&<div className="error">该分析暂时无法读取。</div>}
      {section==='health'&&analytics.data&&<div className="ibkr-health-json"><h3>数据健康</h3><p>缺失区块、匹配率、archive、派生重建与 Portfolio 传播均由后端权威状态提供；缺失值不会显示为零。</p><pre>{JSON.stringify(analytics.data,null,2)}</pre></div>}
      {section!=='health'&&!analytics.isLoading&&!(analytics.data?.items?.length)&&<div className="empty">当前没有可显示的派生记录；数据不足不会被伪造为 0。</div>}
      {section!=='health'&&analytics.data?.items?.map((row,index)=><article className="ibkr-analysis-row" key={String(row.id||row.performance_date||row.symbol||index)}>{Object.entries(row).slice(0,10).map(([key,value])=><span key={key}><small>{key}</small><b>{display(value)}</b></span>)}</article>)}
    </section>}
    {section==='records'&&<>
    <div className="ibkr-tabs">{tabs.map(([key,label])=><button className={tab===key?'active':''} key={key} onClick={()=>{setTab(key);setPage(1);setExpanded(null)}}>{label}<small>{sync?.section_counts[key.replaceAll('-','_')]||0}</small></button>)}</div>
    <section className="ibkr-record-panel">
      <div className="ibkr-filter"><div><small>DATABASE SNAPSHOT</small><h3>{tabs.find(row=>row[0]===tab)?.[1]}</h3></div><label>证券代码<input value={symbol} onChange={event=>{setSymbol(event.target.value.toUpperCase());setPage(1)}} placeholder="全部"/></label></div>
      {records.isLoading&&<div className="empty">正在读取快照…</div>}
      {records.data?.items.map(row=><article className="ibkr-record" key={row.id}>
        <button className="ibkr-record-main" onClick={()=>setExpanded(expanded===row.id?null:row.id)}>
          <span><b>{row.symbol||row.fields.fromCurrency||'账户记录'}</b><small>{row.description||row.asset_category||row.section}</small></span>
          <span><small>数量</small><b>{display(row.quantity||row.fields.position)}</b></span>
          <span><small>价格 / 金额</small><b>{display(row.price||row.amount||row.fields.positionValue||row.fields.tradeMoney)}</b></span>
          <span><small>币种</small><b>{row.currency||row.fields.toCurrency||'—'}</b></span>
          <span><small>日期</small><b>{row.report_date||when(row.occurred_at)}</b></span>
          <i>{expanded===row.id?'−':'+'}</i>
        </button>
        {expanded===row.id&&<div className="ibkr-record-detail"><div className="ibkr-detail-grid">{(important[tab]||Object.keys(row.fields).slice(0,16)).map(key=><span key={key}><small>{key}</small><b>{display(row.fields[key])}</b></span>)}</div><footer>来源：{row.source} · conid {row.conid||'—'} · 原始 section：{row.section}</footer></div>}
      </article>)}
      {!records.isLoading&&!records.data?.items.length&&<div className="empty">该区块当前没有可显示的记录；不会将缺失数据当作零。</div>}
      {records.data&&records.data.total>records.data.page_size&&<div className="ibkr-pagination"><button disabled={page===1} onClick={()=>setPage(v=>v-1)}>上一页</button><span>第 {page} 页 · 共 {records.data.total} 条</span><button disabled={!records.data.has_more} onClick={()=>setPage(v=>v+1)}>下一页</button></div>}
    </section>
    </>}
    </>}
  </div>
}
