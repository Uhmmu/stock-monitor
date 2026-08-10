import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { post } from './api'
import { SecuritySearchAutocomplete, type SecuritySearchResult } from './SecuritySearchAutocomplete'
import { Sheet } from './Sheet'
import './stock-compare.css'

export type CompareDirection='higher_better'|'lower_better'|'neutral'
export type CompareMetricDefinition={
  key:string;label:string;category:string;unit:string;format:string;source:string;direction:CompareDirection
  sortable:boolean;supports_rank:boolean;supports_percentile:boolean;supports_history:boolean
  cross_industry_comparable:boolean;comparison_mode:string;missing_policy:string;description:string
}
export type CompareCell={
  value:number|null;status:'available'|'missing'|'stale'|'unsupported'|'calculation_failed';source:string|null
  as_of:string|null;period:string|null;rank:number|null;percentile:number|null;is_best:boolean;is_worst:boolean
  relative:{kind:string;value:number;unit:string}|null;trend:'improving'|'deteriorating'|'stable'|'rising'|'falling'|null
}
export type CompareMetric={
  definition:CompareMetricDefinition;cells:Record<string,CompareCell>;available_count:number
  dispersion:number|null;is_differentiator:boolean;period_mismatch:boolean;comparison_warning:string|null
}
type CompareSecurity={symbol:string;name:string|null;sector:string|null;industry:string|null;currency:string|null;instrument_type:string|null}
type CompareHighlight={symbol:string;strengths:{key:string;label:string}[];weaknesses:{key:string;label:string}[]}
type CategoryWinner={category:string;symbol:string|null;ties?:string[];evidence?:{key:string;label:string;rank:number}[];tradeoffs?:{key:string;label:string;rank:number}[]}
export type CompareResponse={
  securities:CompareSecurity[];metrics:CompareMetric[];categories:string[];highlights:CompareHighlight[]
  category_winners:CategoryWinner[];suggested_peers:string[];limitations:string[];generated_at:string
}
type HistoryPoint={date:string;period:string|null;value:number;indexed:number|null}
type CompareHistory={metric:CompareMetricDefinition;mode:'raw'|'indexed';series:{symbol:string;points:HistoryPoint[]}[];limitations:string[]}

const viewLabels={raw:'当前值',rank:'当前对比排名',relative:'相对中位数',trend:'趋势'} as const
type ViewMode=keyof typeof viewLabels
const trendLabels={improving:'改善',deteriorating:'恶化',stable:'稳定',rising:'上升',falling:'下降'}

export function formatCompareValue(value:number|null,definition:Pick<CompareMetricDefinition,'format'|'unit'>){
  if(value==null||!Number.isFinite(value)) return '数据不足'
  if(definition.format==='percent'||definition.unit==='%') return `${value.toFixed(Math.abs(value)>=100?0:1)}%`
  if(definition.format==='currency') return value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})
  if(definition.unit.includes('/share')) return value.toLocaleString('zh-CN',{style:'currency',currency:'USD',maximumFractionDigits:2})
  if(definition.format==='compact_currency') return new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:2}).format(value)
  if(definition.format==='score') return value.toFixed(1)
  const suffix=definition.unit==='multiple'?'×':definition.unit&&definition.unit!=='number'?` ${definition.unit}`:''
  return `${value.toLocaleString('zh-CN',{maximumFractionDigits:2})}${suffix}`
}

export function filterCompareMetrics(metrics:CompareMetric[],query:string,category:string,hideUnavailable:boolean,onlyDifferences:boolean){
  const needle=query.trim().toLocaleLowerCase()
  return metrics.filter(metric=>(category==='all'||metric.definition.category===category)
    &&(!needle||`${metric.definition.label} ${metric.definition.key}`.toLocaleLowerCase().includes(needle))
    &&(!hideUnavailable||metric.available_count>0)
    &&(!onlyDifferences||metric.is_differentiator))
}

export function buildCompareConclusion(metrics:CompareMetric[],symbol:string,currency:string|null='USD'){
  const cell=(key:string)=>metrics.find(metric=>metric.definition.key===key)?.cells[symbol]
  const value=(key:string)=>cell(key)?.value??null
  const current=value('price'),target=currency==='USD'?value('consensus_fair_value'):null,dcf=currency==='USD'?value('dcf_base_value'):null
  const distance=(goal:number|null)=>current&&goal!=null?(goal/current-1)*100:null
  return {
    current,target,dcf,targetDistance:distance(target),dcfDistance:distance(dcf),
    day:value('day_change_pct'),month:value('return_1m_pct'),quarter:value('return_3m_pct'),
    halfYear:value('return_6m_pct'),year:value('return_1y_pct'),highDistance:value('distance_52w_high_pct'),
    agreement:value('valuation_model_agreement_pct'),priceAsOf:cell('price')?.as_of??null,valuationAsOf:cell('consensus_fair_value')?.as_of??null,
  }
}

function signedPercent(value:number|null){
  if(value==null||!Number.isFinite(value))return '数据不足'
  return `${value>0?'+':''}${value.toFixed(Math.abs(value)>=100?0:1)}%`
}

function plainPercent(value:number|null){
  if(value==null||!Number.isFinite(value))return '数据不足'
  return `${value.toFixed(Math.abs(value)>=100?0:1)}%`
}

function conclusionPrice(value:number|null,currency:string|null){
  if(value==null||!Number.isFinite(value))return '数据不足'
  return `${value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}${currency?` ${currency}`:''}`
}

function ConclusionCard({security,metrics}:{security:CompareSecurity;metrics:CompareMetric[]}){
  const row=buildCompareConclusion(metrics,security.symbol,security.currency)
  const distanceText=(value:number|null)=>value==null?'目标空间待同步':value>=0?`距目标价仍有 ${signedPercent(value)}`:`现价高于目标价 ${Math.abs(value).toFixed(1)}%`
  const tone=(value:number|null)=>value==null?'':value>0?'positive':value<0?'negative':'neutral'
  const market=[['当日',row.day],['1 个月',row.month],['3 个月',row.quarter],['6 个月',row.halfYear],['1 年',row.year]] as const
  return <article className="compare-conclusion-card">
    <div className="compare-conclusion-card-header"><div><b>{security.symbol}</b><span>{security.name||'公司资料待同步'}</span></div><small>{security.currency||'币种待同步'}</small></div>
    <div className="compare-conclusion-prices">
      <div><span>当前价</span><strong>{conclusionPrice(row.current,security.currency)}</strong></div>
      <div className="primary"><span>模型共识目标价</span><strong>{security.currency==='USD'?conclusionPrice(row.target,security.currency):'币种待校验'}</strong><em className={tone(row.targetDistance)}>{security.currency==='USD'?distanceText(row.targetDistance):'暂不计算目标空间'}</em></div>
      <div><span>DCF 基准价值</span><strong>{security.currency==='USD'?conclusionPrice(row.dcf,security.currency):'币种待校验'}</strong><em className={tone(row.dcfDistance)}>{security.currency==='USD'?distanceText(row.dcfDistance):'暂不计算目标空间'}</em></div>
    </div>
    <dl>{market.map(([label,value])=><div key={label}><dt>{label}涨跌</dt><dd className={tone(value)}>{signedPercent(value)}</dd></div>)}</dl>
    <footer><span>距 52 周高点 <b>{signedPercent(row.highDistance)}</b></span><span>估值模型一致度 <b>{plainPercent(row.agreement)}</b></span><small>行情 {row.priceAsOf||'待同步'} · 估值 {row.valuationAsOf||'待同步'}</small></footer>
  </article>
}

function relativeText(cell:CompareCell){
  if(!cell.relative) return '数据不足'
  const sign=cell.relative.value>0?'+':''
  const suffix=cell.relative.kind==='percentage_point'?'pct':cell.relative.unit==='%'?'%':cell.relative.unit==='multiple'?'×':cell.relative.unit
  return `${sign}${cell.relative.value.toFixed(Math.abs(cell.relative.value)>=100?0:1)}${suffix} vs 中位数`
}

function cellText(cell:CompareCell,definition:CompareMetricDefinition,mode:ViewMode,total:number){
  if(cell.value==null) return cell.status==='unsupported'?'不适用':'数据不足'
  if(mode==='rank') return cell.rank==null?'中性指标':`#${cell.rank} / ${total}`
  if(mode==='relative') return relativeText(cell)
  if(mode==='trend') return cell.trend?trendLabels[cell.trend]:'历史不足'
  return formatCompareValue(cell.value,definition)
}

function TrendChart({history}:{history:CompareHistory}){
  const all=history.series.flatMap(series=>series.points.map(point=>history.mode==='indexed'?(point.indexed??point.value):point.value))
  if(!all.length)return <div className="empty">该指标暂无可比较历史。</div>
  const low=Math.min(...all),high=Math.max(...all),span=high-low||1
  const colors=['#1677e8','#7b61d1','#2e9b68','#dc8b2c','#d04f60','#4d91a8']
  const dates=[...new Set(history.series.flatMap(series=>series.points.map(point=>point.date)))].sort()
  const width=760,height=250,pad=24
  const paths=history.series.map((series,index)=>{
    const points=series.points.map(point=>{
      const value=history.mode==='indexed'?(point.indexed??point.value):point.value
      const x=pad+(width-pad*2)*(dates.length===1?.5:dates.indexOf(point.date)/(dates.length-1))
      const y=pad+(height-pad*2)*(1-(value-low)/span)
      return `${x},${y}`
    }).join(' ')
    return <polyline key={series.symbol} points={points} fill="none" stroke={colors[index%colors.length]} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round"/>
  })
  return <figure className="compare-trend-chart">
    <div>{history.series.map((series,index)=><span key={series.symbol}><i style={{background:colors[index%colors.length]}}/>{series.symbol}</span>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${history.metric.label} 历史对比`} preserveAspectRatio="none"><path d={`M${pad} ${pad}V${height-pad}H${width-pad}`} className="axis"/>{paths}</svg>
    <figcaption>{history.mode==='indexed'?'各股票从共同可用区间起点标准化为 100。':'同一指标按各公司已披露期间绘制；财年截止日可能不同。'} 范围 {formatCompareValue(low,history.metric)} – {formatCompareValue(high,history.metric)}</figcaption>
  </figure>
}

function HighlightCard({item}:{item:CompareHighlight}){
  return <article className="compare-highlight-card"><h3>{item.symbol}</h3><div><span>优势</span>{item.strengths.length?item.strengths.map(row=><b key={row.key}>{row.label}</b>):<small>暂无明确领先项</small>}</div><div><span>劣势</span>{item.weaknesses.length?item.weaknesses.map(row=><b className="weak" key={row.key}>{row.label}</b>):<small>暂无明确落后项</small>}</div></article>
}

export function StockCompare({watchlist=[]}:{watchlist:string[]}){
  const urlSymbols=new URLSearchParams(window.location.search).get('symbols')?.split(',').map(item=>item.trim().toUpperCase()).filter(Boolean)||[]
  const [symbols,setSymbols]=useState<string[]>(()=>[...new Set(urlSymbols)].slice(0,6))
  const [candidate,setCandidate]=useState<SecuritySearchResult|null>(null)
  const [category,setCategory]=useState('all')
  const [query,setQuery]=useState('')
  const [hideUnavailable,setHideUnavailable]=useState(false)
  const [onlyDifferences,setOnlyDifferences]=useState(false)
  const [mode,setMode]=useState<ViewMode>('raw')
  const [historyMetric,setHistoryMetric]=useState<string|null>(null)
  useEffect(()=>{if(symbols.length<2&&watchlist.length>=2)setSymbols([...new Set(watchlist.map(item=>item.toUpperCase()))].slice(0,3))},[watchlist.join('|')])
  useEffect(()=>{
    const params=new URLSearchParams(window.location.search);params.set('tab','compare')
    if(symbols.length)params.set('symbols',symbols.join(','));else params.delete('symbols')
    window.history.replaceState({},'',`/?${params}`)
  },[symbols.join('|')])
  const comparison=useQuery({
    queryKey:['stock-compare',symbols],queryFn:()=>post<CompareResponse>('/compare',{symbols}),enabled:symbols.length>=2,staleTime:60_000,
  })
  const history=useQuery({
    queryKey:['stock-compare-history',historyMetric,symbols],
    queryFn:()=>post<CompareHistory>('/compare/history',{symbols,metric_key:historyMetric}),enabled:!!historyMetric&&symbols.length>=2,staleTime:5*60_000,
  })
  const visible=useMemo(()=>filterCompareMetrics(comparison.data?.metrics||[],query,category,hideUnavailable,onlyDifferences),[comparison.data,query,category,hideUnavailable,onlyDifferences])
  const quick=[...new Set([...watchlist,...(comparison.data?.suggested_peers||[])].map(item=>item.toUpperCase()))].filter(item=>!symbols.includes(item))
  const add=(symbol:string)=>setSymbols(current=>current.length>=6||current.includes(symbol)?current:[...current,symbol])
  const selectedHistory=comparison.data?.metrics.find(metric=>metric.definition.key===historyMetric)?.definition
  const columnStyle={'--compare-columns':comparison.data?.securities.length||2} as CSSProperties
  const limitations=comparison.data?.limitations.filter(item=>!item.toLocaleLowerCase().startsWith('percentile'))||[]

  return <div className="stock-compare">
    <section className="compare-selector">
      <div><p className="eyebrow">STOCK COMPARE</p><h2>把真正拉开差距的数据放在一起</h2><p>只读取已入库快照与历史，不会因打开页面触发外部抓取、估值或 AI 调用。</p></div>
      <div className="compare-symbols" aria-label="已选股票">{symbols.map(symbol=><span className="ticker-chip" key={symbol}><b>{symbol}</b><button aria-label={`移除 ${symbol}`} onClick={()=>setSymbols(rows=>rows.filter(item=>item!==symbol))}>×</button></span>)}</div>
      <form onSubmit={event=>{event.preventDefault();if(candidate){add(candidate.display_symbol.toUpperCase());setCandidate(null)}}}>
        <SecuritySearchAutocomplete compact value={candidate} onSelect={setCandidate} excludeSymbols={symbols} disabledSymbols={symbols} placeholder="搜索并加入股票"/>
        <button disabled={!candidate||symbols.length>=6}>加入对比</button>
      </form>
      <div className="compare-quick"><span>快捷加入</span>{quick.slice(0,12).map(symbol=><button key={symbol} onClick={()=>add(symbol)} disabled={symbols.length>=6}>+ {symbol}</button>)}</div>
      <small>支持 2–6 只股票；搜索到但尚无本地快照的股票会保留，并明确显示数据不足。</small>
    </section>

    {symbols.length<2&&<div className="empty compare-empty">至少选择两只股票开始横向研究。</div>}
    {comparison.isLoading&&<div className="empty compare-empty">正在聚合已入库数据…</div>}
    {comparison.isError&&<div className="error">对比数据暂不可用，请稍后重试。</div>}
    {comparison.data&&<>
      <section className="compare-conclusions"><div className="section-title"><div><p>DECISION SNAPSHOT</p><h2>关键结论</h2></div><small>目标空间按最新已存价格重新计算；模型共识不是券商目标价或收益承诺</small></div><div>{comparison.data.securities.map(item=><ConclusionCard security={item} metrics={comparison.data.metrics} key={item.symbol}/>)}</div></section>
      <section className="compare-universe">{comparison.data.securities.map(item=><article key={item.symbol}><b>{item.symbol}</b><strong>{item.name||'公司资料待同步'}</strong><span>{[item.sector,item.industry].filter(Boolean).join(' · ')||'分类待同步'}</span><small>{[item.currency,item.instrument_type].filter(Boolean).join(' · ')}</small></article>)}</section>
      <section><div className="section-title"><div><p>COMPARE HIGHLIGHTS</p><h2>优势与劣势</h2></div><small>只比较当前所选股票；不生成主观总分</small></div><div className="compare-highlights">{comparison.data.highlights.map(item=><HighlightCard item={item} key={item.symbol}/>)}</div></section>
      {!!comparison.data.category_winners.length&&<section><div className="section-title"><div><p>CATEGORY WINNERS</p><h2>维度胜者</h2></div><small>按当前所选股票的明确领先项计数，并列时不强行决胜</small></div><div className="compare-winners">{comparison.data.category_winners.map(item=><article key={item.category}><span>{item.category}</span><b>{item.symbol||item.ties?.join(' / ')||'无明确胜者'}</b><small>{item.evidence?.slice(0,3).map(row=>`${row.label} #${row.rank}`).join(' · ')||'有效指标不足'}</small>{!!item.tradeoffs?.length&&<em>权衡：{item.tradeoffs.slice(0,2).map(row=>`${row.label} #${row.rank}`).join(' · ')}</em>}</article>)}</div></section>}
      <section className="compare-matrix-section">
        <div className="section-title"><div><p>METRIC MATRIX</p><h2>指标矩阵</h2></div><small>{visible.length} / {comparison.data.metrics.length} 项</small></div>
        <div className="compare-toolbar">
          <div className="compare-categories"><button className={category==='all'?'active':''} onClick={()=>setCategory('all')}>全部</button>{comparison.data.categories.map(item=><button className={category===item?'active':''} onClick={()=>setCategory(item)} key={item}>{item}</button>)}</div>
          <div className="compare-controls"><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="搜索指标" aria-label="搜索指标"/><label><input type="checkbox" checked={hideUnavailable} onChange={event=>setHideUnavailable(event.target.checked)}/> 隐藏全缺失</label><label><input type="checkbox" checked={onlyDifferences} onChange={event=>setOnlyDifferences(event.target.checked)}/> 仅明显差异</label></div>
          <div className="compare-modes">{(Object.keys(viewLabels) as ViewMode[]).map(item=><button className={mode===item?'active':''} onClick={()=>setMode(item)} key={item}>{viewLabels[item]}</button>)}</div>
        </div>
        <div className="compare-table" role="table">
          <div className="compare-row compare-head" role="row" style={columnStyle}><div role="columnheader">指标</div>{comparison.data.securities.map(item=><div role="columnheader" key={item.symbol}>{item.symbol}</div>)}</div>
          {visible.map(metric=><div className={`compare-row${metric.is_differentiator?' differentiator':''}`} role="row" style={columnStyle} key={metric.definition.key}>
            <button className="compare-metric-label" role="rowheader" title={metric.definition.description} disabled={!metric.definition.supports_history} onClick={()=>metric.definition.supports_history&&setHistoryMetric(metric.definition.key)}><b>{metric.definition.label}</b><span>{metric.definition.category} · {metric.definition.source}</span>{metric.period_mismatch&&<em>期间不一致</em>}{metric.definition.supports_history&&<small>查看历史 →</small>}</button>
            {comparison.data.securities.map(security=>{const cell=metric.cells[security.symbol];return <div role="cell" data-label={security.symbol} className={`${cell?.is_best?'best ':''}${cell?.is_worst?'worst ':''}${cell?.status||'missing'}`} key={security.symbol} title={[cell?.period,cell?.as_of,cell?.source].filter(Boolean).join(' · ')}><strong>{cell?cellText(cell,metric.definition,mode,comparison.data.securities.length):'数据不足'}</strong>{cell?.rank!=null&&mode==='raw'&&<span>当前对比第 {cell.rank}</span>}{cell?.status==='stale'&&<em>较旧</em>}</div>})}
          </div>)}
          {!visible.length&&<div className="empty">当前筛选下没有指标。</div>}
        </div>
      </section>
      {!!limitations.length&&<section className="compare-limitations"><b>数据边界</b>{limitations.map(item=><p key={item}>{item}</p>)}</section>}
    </>}
    <Sheet open={!!historyMetric} onClose={()=>setHistoryMetric(null)} title={`${selectedHistory?.label||'指标'}历史`} size="wide"><section className="compare-history-content"><div className="compare-history-heading"><p className="eyebrow">HISTORICAL COMPARISON</p><button type="button" onClick={()=>setHistoryMetric(null)}>关闭</button></div>{history.isLoading?<div className="empty">正在读取历史快照…</div>:history.data?<TrendChart history={history.data}/>:<div className="empty">历史数据不可用。</div>}</section></Sheet>
  </div>
}
