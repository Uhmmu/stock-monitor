import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AreaSeries, ColorType, LineSeries, createChart, type Time } from 'lightweight-charts'
import { post } from './api'
import { cacheTimeLabel, latestFreshAnalysis, usePortfolioAnalysisHistory } from './PortfolioAnalysisCache'

export type RiskPoint={date:string;value:number}
export type RiskContribution={symbol:string;weight:number;risk_contribution:number;contribution_amount:number}
export type SectorContribution={sector:string;risk_contribution:number;contribution_amount:number}
export type PortfolioRiskResult={
  run_id:number;status:'completed'|'insufficient_data';portfolio_value:number;base_currency?:string
  data_period:{start:string|null;end:string|null;mode:'common_start'|'dynamic_available'}
  metrics:Record<string,number|null>;max_drawdown_detail?:Record<string,string|number|boolean|null>
  asset_risk_contributions:RiskContribution[];sector_risk_contributions:SectorContribution[]
  correlation_matrix:Record<string,Record<string,number>>
  portfolio_curve:RiskPoint[];drawdown_curve:RiskPoint[]
  confidence:'high'|'medium'|'low';confidence_reasons:string[];warnings:string[];coverage_warning:string
}

const pct=(value:number|null|undefined)=>value==null?'—':`${(value*100).toFixed(2)}%`
const ratio=(value:number|null|undefined)=>value==null?'—':value.toFixed(2)
const money=(value:number,currency='USD')=>new Intl.NumberFormat('zh-CN',{style:'currency',currency,maximumFractionDigits:0}).format(value)

function RiskLineChart({curve,drawdown=false}:{curve:RiskPoint[];drawdown?:boolean}){
  const ref=useRef<HTMLDivElement>(null)
  useEffect(()=>{
    if(!ref.current||!curve.length)return
    const chart=createChart(ref.current,{height:250,width:ref.current.clientWidth,layout:{background:{type:ColorType.Solid,color:'transparent'},textColor:'#718096'},grid:{vertLines:{color:'rgba(100,116,139,.09)'},horzLines:{color:'rgba(100,116,139,.09)'}},rightPriceScale:{borderVisible:false},timeScale:{borderVisible:false}})
    const series=drawdown
      ? chart.addSeries(AreaSeries,{lineColor:'#d64f5f',topColor:'rgba(214,79,95,.24)',bottomColor:'rgba(214,79,95,.02)',priceFormat:{type:'percent'}})
      : chart.addSeries(LineSeries,{color:'#3677d8',lineWidth:2})
    series.setData(curve.map(row=>({time:row.date as Time,value:drawdown?row.value*100:row.value})))
    chart.timeScale().fitContent()
    const observer=new ResizeObserver(entries=>chart.applyOptions({width:entries[0].contentRect.width}))
    observer.observe(ref.current)
    return()=>{observer.disconnect();chart.remove()}
  },[curve,drawdown])
  return <div className="risk-line-chart" ref={ref}/>
}

function ContributionBars({rows}:{rows:{label:string;value:number}[]}){
  const max=Math.max(...rows.map(row=>Math.abs(row.value)),.0001)
  return <div className="risk-bars">{rows.map(row=><div key={row.label}><span>{row.label}</span><i><b style={{width:`${Math.abs(row.value)/max*100}%`}}/></i><strong>{pct(row.value)}</strong></div>)}</div>
}

function CorrelationHeatmap({matrix}:{matrix:Record<string,Record<string,number>>}){
  const symbols=Object.keys(matrix)
  if(!symbols.length)return <div className="empty">相关性数据不足。</div>
  return <div className="correlation-wrap"><div className="correlation-grid" style={{gridTemplateColumns:`72px repeat(${symbols.length},minmax(48px,1fr))`}}>
    <span/>{symbols.map(s=><b key={`h-${s}`}>{s}</b>)}
    {symbols.flatMap(symbol=>[<b key={`r-${symbol}`}>{symbol}</b>,...symbols.map(other=>{const value=matrix[symbol]?.[other]??0;const alpha=.1+Math.abs(value)*.75;return <span key={`${symbol}-${other}`} title={`${symbol}/${other}: ${value.toFixed(2)}`} style={{background:value>=0?`rgba(54,119,216,${alpha})`:`rgba(214,79,95,${alpha})`,color:Math.abs(value)>.55?'white':'inherit'}}>{value.toFixed(2)}</span>})])}
  </div></div>
}

export function PortfolioRiskAnalysis({portfolioId,currency,healthContent}:{portfolioId:number;currency:string;healthContent:React.ReactNode}){
  const client=useQueryClient()
  const history=usePortfolioAnalysisHistory()
  const restoredCache=useRef(false)
  const [mode,setMode]=useState<'common_start'|'dynamic_available'>('common_start')
  const [launchedMode,setLaunchedMode]=useState<'common_start'|'dynamic_available'|null>(null)
  const run=useMutation({mutationFn:(selectedMode:'common_start'|'dynamic_available')=>post<PortfolioRiskResult>('/portfolio/analysis/metrics',{portfolio_id:portfolioId,mode:selectedMode,covariance_method:'ledoit_wolf',confidence_level:.95}),onMutate:selectedMode=>setLaunchedMode(selectedMode),onSuccess:()=>client.invalidateQueries({queryKey:['portfolio-analysis-history']})})
  const savedRun=latestFreshAnalysis<PortfolioRiskResult>(history.data?.runs,'metrics',item=>item.result?.data_period.mode===mode)
  const liveResult=launchedMode===mode?run.data:null
  const data=liveResult||savedRun?.result

  useEffect(()=>{
    if(restoredCache.current||!history.data)return
    restoredCache.current=true
    const cached=latestFreshAnalysis<PortfolioRiskResult>(history.data.runs,'metrics')
    if(cached?.result?.data_period.mode)setMode(cached.result.data_period.mode)
  },[history.data])
  return <div className="portfolio-risk-analysis">
    {healthContent}
    <section className="health-section portfolio-risk-section">
      <div className="portfolio-health-heading"><div><small>历史风险</small><h3>组合风险</h3>{savedRun&&!liveResult&&<span className="analysis-cache-note">{cacheTimeLabel(savedRun)}</span>}</div><span>收缩协方差估计</span></div>
      <div className="risk-toolbar"><div><button className={mode==='common_start'?'active':''} onClick={()=>setMode('common_start')} disabled={run.isPending}>完整持仓共同区间</button><button className={mode==='dynamic_available'?'active':''} onClick={()=>setMode('dynamic_available')} disabled={run.isPending}>动态可用区间</button></div><button className="risk-run" onClick={()=>run.mutate(mode)} disabled={run.isPending}>{run.isPending?'计算中…':data?'重新计算':'运行组合风险分析'}</button></div>
      {history.isLoading&&<div className="empty">正在读取七天内的风险分析…</div>}
      {!history.isLoading&&!data&&!run.isPending&&<div className="empty">该计算口径在最近 7 天没有可用结果，请手动运行组合风险分析。</div>}
      {run.error&&<p className="error">{run.error.message}</p>}
      {data&&<>
        <div className="risk-metric-grid">
          <div><span>当前组合总市值</span><strong>{money(data.portfolio_value,data.base_currency||currency)}</strong></div>
          <div><span>年化收益率</span><strong>{pct(data.metrics.annual_return)}</strong></div>
          <div><span>年化波动率</span><strong>{pct(data.metrics.annual_volatility)}</strong></div>
          <div><span>最大回撤</span><strong className="negative">{pct(data.metrics.max_drawdown)}</strong></div>
          <div><span>历史 VaR 95%</span><strong>{pct(data.metrics.var_95)}</strong></div>
          <div><span>历史 CVaR 95%</span><strong>{pct(data.metrics.cvar_95)}</strong></div>
          <div><span>Sharpe</span><strong>{ratio(data.metrics.sharpe_ratio)}</strong></div>
          <div><span>Beta / SPY</span><strong>{ratio(data.metrics.beta)}</strong></div>
          <div><span>集中度 HHI</span><strong>{ratio(data.metrics.hhi)}</strong></div>
          <div><span>数据覆盖</span><strong>{data.data_period.start||'—'}<br/>{data.data_period.end||'—'}</strong></div>
        </div>
        <div className="risk-mode-note"><b>{data.data_period.mode==='common_start'?'完整持仓共同区间':'动态可用区间'}</b><span>{data.data_period.mode==='common_start'?'仅使用所有资产均有有效行情的日期。':'早期缺失资产暂时排除，其余权重按日重新归一化。'}</span><em>置信度：{data.confidence==='high'?'高':data.confidence==='medium'?'中':'低'}</em></div>
        {data.portfolio_curve.length>0&&<div className="risk-chart-grid"><section><h4>组合历史净值</h4><RiskLineChart curve={data.portfolio_curve}/></section><section><h4>组合回撤</h4><RiskLineChart curve={data.drawdown_curve} drawdown/></section></div>}
        <div className="risk-chart-grid"><section><h4>单股风险贡献</h4><ContributionBars rows={data.asset_risk_contributions.map(row=>({label:row.symbol,value:row.risk_contribution}))}/></section><section><h4>行业风险贡献</h4><ContributionBars rows={data.sector_risk_contributions.map(row=>({label:row.sector,value:row.risk_contribution}))}/></section></div>
        <section className="risk-correlation"><h4>持仓相关性</h4><CorrelationHeatmap matrix={data.correlation_matrix}/></section>
        {(data.warnings.length>0||data.confidence_reasons.length>0)&&<div className="risk-warnings">{[...data.confidence_reasons,...data.warnings].map((warning,index)=><p key={`${warning}-${index}`}>{warning}</p>)}</div>}
        <p className="risk-coverage-warning">{data.coverage_warning}</p>
      </>}
    </section>
    <p className="portfolio-analysis-disclaimer">分析结果基于历史数据、统计模型和用户设定假设，不构成投资建议。历史表现和模拟结果不代表未来收益。<br/>当前历史行情主要覆盖 2021 年之后，部分历史风险指标可能低估完整市场周期中的极端风险。</p>
  </div>
}
