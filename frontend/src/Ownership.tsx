import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

type ShareStatistics = {
  shares_outstanding:number|null;float_shares:number|null;free_float_percent:number|null;
  held_percent_institutions:number|null;held_percent_insiders:number|null;short_percent_of_float:number|null;
  short_ratio:number|null;as_of_date:string|null;source:string;source_url:string|null;fetched_at:string;
  stale:boolean;warning:string|null;confidence:string
}
type OwnershipSummary = {symbol:string;data:ShareStatistics|null;stale:boolean;warning:string|null;capabilities:Record<string,boolean>}
type Page<T> = {items:T[];total:number;available:boolean;message?:string;delayed_notice?:string}
type Insider = {id:number;insider_name:string;insider_title:string|null;transaction_type:string;transaction_code:string|null;transaction_date:string|null;shares:number|null;price:number|null;transaction_value:number|null;shares_owned_after:number|null;source_url:string}
type Holding13F = {id:number;report_period:string;filing_date:string|null;filer:string;cusip:string;shares:number|null;reported_value:number|null;put_call:string|null}

const descriptions:Record<string,string> = {
  '总股本':'公司当前已发行并由投资者持有的股份总数。',
  '流通股':'较合理地可在公开市场交易的股份，不等同于总股本。',
  '自由流通比例':'流通股占总股本的比例，由真实股数计算。',
  '机构持股':'Yahoo 报告的机构持股比例；口径可能晚于实时变动。',
  '内部人持股':'公司内部人持有的股份比例。',
  '空头占流通股':'已报告空头股份占流通股的比例。',
  '空头回补天数':'按平均成交量估算，空头回补全部仓位所需交易日数。',
}
const compact = (value:number|null,percent=false) => {
  if(value==null) return '数据不足'
  if(percent) return `${value.toFixed(2)}%`
  if(Math.abs(value)>=1e9) return `${(value/1e9).toFixed(2)}B`
  if(Math.abs(value)>=1e6) return `${(value/1e6).toFixed(2)}M`
  return value.toLocaleString('zh-CN',{maximumFractionDigits:2})
}

export function OwnershipSection({symbol}:{symbol:string}) {
  const [view,setView] = useState<'summary'|'insider'|'13f'>('summary')
  const summary = useQuery({queryKey:['ownership-summary',symbol],queryFn:()=>api<OwnershipSummary>(`/equity/${encodeURIComponent(symbol)}/ownership/summary`),enabled:!!symbol,staleTime:10*60_000})
  const insider = useQuery({queryKey:['ownership-insider',symbol],queryFn:()=>api<Page<Insider>>(`/equity/${encodeURIComponent(symbol)}/ownership/insider-transactions?limit=25`),enabled:!!symbol&&view==='insider',staleTime:5*60_000})
  const holdings = useQuery({queryKey:['ownership-13f',symbol],queryFn:()=>api<Page<Holding13F>>(`/equity/${encodeURIComponent(symbol)}/ownership/13f?limit=25`),enabled:!!symbol&&view==='13f',staleTime:5*60_000})
  const data=summary.data?.data
  const cards = data ? [
    ['总股本',compact(data.shares_outstanding)],['流通股',compact(data.float_shares)],
    ['自由流通比例',compact(data.free_float_percent,true)],['机构持股',compact(data.held_percent_institutions,true)],
    ['内部人持股',compact(data.held_percent_insiders,true)],['空头占流通股',compact(data.short_percent_of_float,true)],
    ['空头回补天数',data.short_ratio==null?'数据不足':`${data.short_ratio.toFixed(2)} 天`],
  ] : []
  return <section className="ownership-section">
    <div className="ownership-heading"><div><p className="eyebrow">OWNERSHIP & SHARE STATISTICS</p><h2>股权与股本</h2><small>股本结构、SEC 内部人交易与延迟机构申报分开呈现，避免混淆数据口径。</small></div><div className="segmented compact" role="tablist" aria-label="股权数据视图">{[['summary','股本概览'],['insider','内部人交易'],['13f','机构申报']].map(([key,label])=><button key={key} role="tab" aria-selected={view===key} className={view===key?'active':''} onClick={()=>setView(key as typeof view)}>{label}</button>)}</div></div>
    {view==='summary'&&<>
      {summary.isLoading&&<div className="ownership-skeleton">{[1,2,3,4].map(item=><span key={item}/>)}</div>}
      {summary.isError&&<div className="empty">股本数据暂不可用。</div>}
      {summary.data?.warning&&<div className={`ownership-warning${summary.data.stale?' stale':''}`}>{summary.data.warning}</div>}
      {!summary.isLoading&&!data&&<div className="empty">当前数据源暂不支持该市场，或尚无可用股本统计。</div>}
      {!!cards.length&&<div className="ownership-card-grid">{cards.map(([label,value])=><article key={label} title={descriptions[label]}><span>{label}<i aria-label="指标说明">?</i></span><strong>{value}</strong><small>{data?.as_of_date?`截至 ${data.as_of_date}`:'数据日期未披露'}</small></article>)}</div>}
      {data&&<div className="ownership-source"><span>来源：{data.source.toUpperCase()} · 置信度中</span><time>抓取于 {new Date(data.fetched_at).toLocaleString('zh-CN')}</time>{data.source_url&&<a href={data.source_url} target="_blank" rel="noreferrer">查看来源</a>}</div>}
    </>}
    {view==='insider'&&<OwnershipTable loading={insider.isLoading} empty={!insider.data?.items.length} message={insider.data?.message||'暂无 SEC Form 4 内部人交易。'} notice={insider.data?.delayed_notice} columns={['内部人','交易类型','日期','股数','价格','交易金额']} rows={(insider.data?.items||[]).map(row=>[`${row.insider_name}${row.insider_title?` · ${row.insider_title}`:''}`,row.transaction_type,row.transaction_date||'—',compact(row.shares),compact(row.price),compact(row.transaction_value)])}/>}
    {view==='13f'&&<OwnershipTable loading={holdings.isLoading} empty={!holdings.data?.items.length} message={holdings.data?.message||'暂无匹配的 SEC 13F 机构申报。'} notice={holdings.data?.delayed_notice} columns={['申报机构','报告期','申报日','股数','申报市值','Put/Call']} rows={(holdings.data?.items||[]).map(row=>[row.filer,row.report_period,row.filing_date||'—',compact(row.shares),compact(row.reported_value),row.put_call||'—'])}/>}
  </section>
}

function OwnershipTable({loading,empty,message,notice,columns,rows}:{loading:boolean;empty:boolean;message:string;notice?:string;columns:string[];rows:string[][]}) {
  if(loading) return <div className="empty">正在读取已缓存的监管申报…</div>
  return <div className="ownership-table-wrap">{notice&&<p className="ownership-delay-note">{notice}</p>}{empty?<div className="empty">{message}</div>:<div className="ownership-table"><div className="ownership-table-head">{columns.map(column=><span key={column}>{column}</span>)}</div>{rows.map((row,index)=><div className="ownership-table-row" key={index}>{row.map((value,cell)=><span key={cell}>{value}</span>)}</div>)}</div>}</div>
}
