import { useState, type CSSProperties, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type SentimentTrend = 'rising'|'falling'|'stable'
export type SentimentSource = {
  source:'reddit'|'x'|'news'|'polymarket'
  label:string
  company_name:string|null
  buzz_score:number
  bullish_pct:number|null
  trend:SentimentTrend|null
  metric_label:string
  metric_value:number
}
export type StockSentiment = {
  symbol:string
  company_name:string|null
  period_days:number
  average_buzz:number
  bullish_average:number|null
  source_alignment:string
  available_sources:number
  sources:SentimentSource[]
}

const alignmentLabels:Record<string,string> = {
  'Bullish alignment':'多源偏多',
  'Bearish alignment':'多源偏空',
  'Tight alignment':'观点集中',
  'Wide divergence':'分歧显著',
  'Mixed':'观点分化',
  'Single-source view':'单一来源',
  'No sentiment mix':'暂无倾向',
}
const trendLabels:Record<string,string> = {rising:'升温',falling:'降温',stable:'平稳'}
const metricLabels:Record<string,string> = {Mentions:'提及量',Trades:'交易数'}

export const compactNumber = (value:number) => new Intl.NumberFormat('zh-CN',{
  notation:'compact', maximumFractionDigits:1,
}).format(value)

export function sentimentTone(value:number|null) {
  if(value==null) return 'neutral'
  if(value>=60) return 'positive'
  if(value<=40) return 'negative'
  return 'neutral'
}

export function SentimentSkeleton() {
  return <section className="sentiment-skeleton" aria-label="正在加载舆情数据" aria-busy="true">
    <div className="sentiment-skeleton-hero shimmer"/>
    <div className="sentiment-skeleton-grid">{[0,1,2,3].map(item=><div className="shimmer" key={item}/>)}</div>
  </section>
}

export function SentimentContent({data,compact=false}:{data:StockSentiment;compact?:boolean}) {
  const bullishTone=sentimentTone(data.bullish_average)
  if(compact) return <>
    <section className="sentiment-preview-card">
      <div className="sentiment-preview-heading"><p className="eyebrow">ADANOS · CROSS-SOURCE SIGNAL</p><h2>{data.symbol}<span>{data.company_name||'公司名称暂缺'}</span></h2></div>
      <div className="sentiment-preview-rings">
        {([['reddit','Reddit'],['x','X'],['news','新闻'],['polymarket','Polymarket']] as const).map(([key,label])=>{
          const source=data.sources.find(item=>item.source===key)
          return <div className="sentiment-preview-source" key={key}>
            <div className={`sentiment-preview-ring${source?'':' unavailable'}`} style={{'--score':`${Math.max(0,Math.min(100,source?.buzz_score??0))*3.6}deg`} as CSSProperties}>
              <strong>{source?source.buzz_score.toFixed(1):'—'}</strong><small>热度</small>
            </div>
            <b>{label}</b><span className={sentimentTone(source?.bullish_pct??null)}>{source?.bullish_pct==null?'数据不足':`看多 ${source.bullish_pct.toFixed(1)}%`}</span>
          </div>
        })}
      </div>
    </section>
    <p className="sentiment-disclaimer">最近 {data.period_days} 天 · 舆情只反映讨论热度与倾向，不代表价格走势或投资建议。</p>
  </>
  return <>
    <section className="sentiment-hero">
      <div className="sentiment-identity">
        <p className="eyebrow">ADANOS · CROSS-SOURCE SIGNAL</p>
        <h2>{data.symbol}<span>{data.company_name||'公司名称暂缺'}</span></h2>
        <p>汇总 Reddit、X.com、公开新闻与 Polymarket 的结构化市场讨论。</p>
      </div>
      <div className="sentiment-score" aria-label={`平均热度 ${data.average_buzz.toFixed(1)}`}>
        <div className="sentiment-ring" style={{'--score':`${Math.max(0,Math.min(100,data.average_buzz)) * 3.6}deg`} as CSSProperties}>
          <strong>{data.average_buzz.toFixed(1)}</strong><small>热度</small>
        </div>
      </div>
      <dl className="sentiment-summary">
        <div><dt>看多占比</dt><dd className={bullishTone}>{data.bullish_average==null?'数据不足':`${data.bullish_average.toFixed(1)}%`}</dd></div>
        <div><dt>来源共识</dt><dd>{alignmentLabels[data.source_alignment]||data.source_alignment}</dd></div>
        <div><dt>数据覆盖</dt><dd>{data.available_sources}<small> / 4</small></dd></div>
      </dl>
    </section>

    <div className="sentiment-section-heading">
      <div><p>分来源观察</p><h2>讨论温度与方向</h2></div>
      <small>最近 {data.period_days} 天 · 成功来源 {data.available_sources} 个</small>
    </div>
    <section className="sentiment-source-grid" aria-label="分来源舆情">
      {data.sources.map(source=>{
        const tone=sentimentTone(source.bullish_pct)
        const bullish=Math.max(0,Math.min(100,source.bullish_pct??0))
        return <article className={`sentiment-source source-${source.source}`} key={source.source}>
          <div className="sentiment-source-title">
            <span className="sentiment-source-mark" aria-hidden="true">{source.source==='polymarket'?'P':source.source==='news'?'N':source.source==='reddit'?'R':'X'}</span>
            <div><h3>{source.label}</h3><small>{source.source==='news'?'公开媒体':source.source==='polymarket'?'预测市场':'社区讨论'}</small></div>
            <em className={`trend-${source.trend||'unknown'}`}>{source.trend?trendLabels[source.trend]:'趋势不足'}</em>
          </div>
          <div className="sentiment-source-values">
            <div><span>热度</span><strong>{source.buzz_score.toFixed(1)}</strong><small>/ 100</small></div>
            <div><span>{metricLabels[source.metric_label]||source.metric_label}</span><strong>{compactNumber(source.metric_value)}</strong></div>
          </div>
          <div className="sentiment-direction">
            <span>看多讨论</span><b className={tone}>{source.bullish_pct==null?'数据不足':`${source.bullish_pct.toFixed(1)}%`}</b>
            <div className="sentiment-track" role="progressbar" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={source.bullish_pct??undefined} aria-label={`${source.label} 看多占比`}>
              <i className={tone} style={{width:`${bullish}%`}}/>
            </div>
          </div>
        </article>
      })}
    </section>
    <p className="sentiment-disclaimer">最近 {data.period_days} 天 · 舆情只反映讨论热度与倾向，不代表价格走势或投资建议。</p>
  </>
}

export function SentimentModule({ticker,selector,compact=false}:{ticker:string;selector?:ReactNode;compact?:boolean}) {
  const [days,setDays]=useState(7)
  const result=useQuery({
    queryKey:['sentiment',ticker,days],
    queryFn:()=>api<StockSentiment|null>(`/sentiment/${encodeURIComponent(ticker)}?days=${days}`),
    enabled:!!ticker,
    staleTime:300_000,
    retry:1,
  })
  return <div className={`sentiment-page${compact?' compact':''}`}>
    <div className="sentiment-toolbar">
      {selector&&<div>{selector}</div>}
      <div className="sentiment-period" role="tablist" aria-label="舆情观察周期">
        {[7,14,30].map(value=><button role="tab" aria-selected={days===value} className={days===value?'active':''}
          onClick={()=>setDays(value)} key={value}>{value} 天</button>)}
      </div>
    </div>
    {!ticker&&<div className="empty">从自选股中选择，或搜索一只证券查看舆情。</div>}
    {ticker&&result.isLoading&&<SentimentSkeleton/>}
    {ticker&&result.isError&&<div className="sentiment-empty"><strong>暂时无法连接舆情服务</strong><p>已有页面不受影响，可以稍后重试。</p><button onClick={()=>result.refetch()}>重新加载</button></div>}
    {ticker&&!result.isLoading&&!result.isError&&!result.data&&<div className="sentiment-empty"><strong>暂无可用舆情</strong><p>四个来源当前都没有返回 {ticker} 的有效数据，或服务端尚未配置 Adanos API Key。</p><button onClick={()=>result.refetch()}>重新检查</button></div>}
    {result.data&&<SentimentContent data={result.data} compact={compact}/>}
  </div>
}
