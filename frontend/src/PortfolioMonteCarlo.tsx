import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import { Sheet } from './Sheet'
import { AnalysisDisclaimer } from './PortfolioScenarios'
import { cacheTimeLabel, latestCompletedAnalysis, requestsMatch, usePortfolioAnalysisHistory } from './PortfolioAnalysisCache'

type MonteResult={status:string;message?:string;initial_value:number;horizon_years:number;simulations:number;method:string;terminal_value_percentiles:Record<string,number>;probability_of_loss:number;probability_loss_over_10_percent:number;probability_loss_over_20_percent:number;probability_reach_target:number|null;max_drawdown:{median:number;p10:number;p90:number;probability_over_20_percent:number;probability_over_30_percent:number};fan_chart:{day:number;p5:number;p25:number;p50:number;p75:number;p95:number}[];sample_paths:number[][];terminal_value_sample:number[];max_drawdown_sample:number[];confidence:'high'|'medium'|'low';limitations:string[];cache_hit:boolean}
type ExpectedResult={status:string;portfolio:{bear:number;base:number;bull:number;confidence:string};assets:{symbol:string;bear:number;base:number;bull:number;confidence:string;drivers:string[];warnings:string[]}[];warnings:string[]}
type Job={job_id:number;status:string;result:MonteResult|null;error_message:string|null}
const pct=(v:number|null|undefined)=>v==null?'—':`${(v*100).toFixed(1)}%`
const money=(v:number)=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(v)

function FanChart({data,paths}:{data:MonteResult['fan_chart'];paths:number[][]}){
  if(!data.length)return null
  const width=760,height=300,pad=24
  const all=[...data.flatMap(x=>[x.p5,x.p95]),...paths.slice(0,30).flat()]
  const min=Math.min(...all),max=Math.max(...all)
  const x=(i:number)=>pad+i/(data.length-1)*(width-pad*2)
  const y=(v:number)=>height-pad-(v-min)/(max-min||1)*(height-pad*2)
  const polygon=(upper:keyof MonteResult['fan_chart'][number],lower:keyof MonteResult['fan_chart'][number])=>[...data.map((row,i)=>`${x(i)},${y(row[upper] as number)}`),...data.map((row,i)=>`${x(data.length-1-i)},${y(data[data.length-1-i][lower] as number)}`)].join(' ')
  const line=(key:keyof MonteResult['fan_chart'][number])=>data.map((row,i)=>`${x(i)},${y(row[key] as number)}`).join(' ')
  return <svg className="monte-fan" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="组合价值概率扇形图"><polygon points={polygon('p95','p5')} className="fan-95"/><polygon points={polygon('p75','p25')} className="fan-50"/>{paths.slice(0,30).map((path,index)=>{const step=(data.length-1)/(path.length-1);return <polyline key={index} points={path.map((v,i)=>`${x(i*step)},${y(v)}`).join(' ')} className="fan-path"/>})}<polyline points={line('p50')} className="fan-median"/></svg>
}

function Histogram({values,percent=false}:{values:number[];percent?:boolean}){
  const bins=useMemo(()=>{if(!values.length)return[];const min=Math.min(...values),max=Math.max(...values),step=(max-min||1)/16;const result=Array.from({length:16},(_,i)=>({from:min+i*step,count:0}));values.forEach(v=>result[Math.min(15,Math.floor((v-min)/step))].count++);return result},[values])
  const max=Math.max(...bins.map(x=>x.count),1)
  return <div className="monte-histogram">{bins.map((bin,index)=><i key={index} style={{height:`${bin.count/max*100}%`}} title={`${percent?pct(bin.from):money(bin.from)}: ${bin.count}`}/>)}</div>
}

function ExpectedReturnPanel({portfolioId}:{portfolioId:number}){
  const client=useQueryClient()
  const history=usePortfolioAnalysisHistory()
  const savedRun=latestCompletedAnalysis<ExpectedResult>(history.data?.runs,'expected_return')
  const mutation=useMutation({mutationFn:()=>post<ExpectedResult>('/portfolio/analysis/expected-return',{portfolio_id:portfolioId}),onSuccess:()=>client.invalidateQueries({queryKey:['portfolio-analysis-history']})})
  const data=mutation.data||savedRun?.result
  const confidenceLabel=(value:string)=>value==='high'?'高':value==='medium'?'中':'低'
  return <section className="expected-return-panel"><div className="portfolio-health-heading"><div><small>预期回报模型</small><h3>预期回报区间</h3>{savedRun&&!mutation.data&&<span className="analysis-cache-note">{cacheTimeLabel(savedRun)}</span>}</div><button onClick={()=>mutation.mutate()} disabled={mutation.isPending}>{mutation.isPending?'计算中…':data?'重新计算':'计算区间'}</button></div>{history.isLoading&&!data&&<p className="health-quiet">正在读取七天内的预期回报结果…</p>}{!history.isLoading&&!data&&<p className="health-quiet">最近 7 天没有可用结果。融合历史收益、资本资产定价模型、基本面隐含收益与已有前瞻数据，请手动计算。</p>}{data?.status==='completed'&&<><div className="expected-scenarios"><div><span>保守情景</span><strong>{pct(data.portfolio.bear)}</strong></div><div className="base"><span>基准预期区间</span><strong>约 {pct(data.portfolio.bear)} ～ {pct(data.portfolio.bull)}</strong></div><div><span>乐观情景</span><strong>{pct(data.portfolio.bull)}</strong></div></div><div className="expected-assets">{data.assets.map(row=><div key={row.symbol}><b>{row.symbol}</b><span>约 {pct(row.bear)} ～ {pct(row.bull)}</span><small>{row.drivers.join(' · ')||'可用模型较少'} · 置信度 {confidenceLabel(row.confidence)}</small></div>)}</div></>}{mutation.isError&&<p className="error">预期回报计算失败，请稍后重试。</p>}</section>
}

export function MonteCarloView({portfolioId}:{portfolioId:number}){
  const client=useQueryClient()
  const history=usePortfolioAnalysisHistory()
  const restoredCache=useRef(false)
  const [horizon,setHorizon]=useState(1),[simulations,setSimulations]=useState(5000),[method,setMethod]=useState('block_bootstrap'),[rebalance,setRebalance]=useState('quarterly'),[contribution,setContribution]=useState(0),[target,setTarget]=useState(''),[seed,setSeed]=useState('42'),[jobId,setJobId]=useState<number|null>(null)
  const [settingsOpen,setSettingsOpen]=useState(false)
  const [launchedRequest,setLaunchedRequest]=useState<Record<string,unknown>|null>(null)
  const currentRequest={portfolio_id:portfolioId,horizon_years:horizon,simulations,method,block_length:10,rebalance_frequency:rebalance,monthly_contribution:contribution,target_value:target?Number(target):null,confidence_levels:[.8,.95],random_seed:seed===''?null:Number(seed)}
  const launch=useMutation({mutationFn:()=>post<{job_id:number}>('/portfolio/analysis/monte-carlo',{...currentRequest,force_refresh:true}),onMutate:()=>setLaunchedRequest(currentRequest),onSuccess:data=>setJobId(data.job_id)})
  const job=useQuery({queryKey:['portfolio-analysis-job',jobId],queryFn:()=>api<Job>(`/portfolio/analysis/jobs/${jobId}`),enabled:jobId!=null,refetchInterval:q=>['pending','running'].includes(q.state.data?.status||'')?2000:false})
  const savedRun=latestCompletedAnalysis<MonteResult>(history.data?.runs,'monte_carlo',run=>requestsMatch(run.input_request,currentRequest))
  const liveResult=requestsMatch(launchedRequest||undefined,currentRequest)&&job.data?.status==='completed'?job.data.result:null
  const data=liveResult||savedRun?.result
  const isRunning=launch.isPending||['pending','running'].includes(job.data?.status||'')

  useEffect(()=>{if(job.data?.status==='completed')void client.invalidateQueries({queryKey:['portfolio-analysis-history']})},[client,job.data?.status])
  useEffect(()=>{
    if(restoredCache.current||!history.data)return
    restoredCache.current=true
    const cached=latestCompletedAnalysis<MonteResult>(history.data.runs,'monte_carlo')
    if(!cached)return
    const request=cached.input_request
    if(request.horizon_years===1||request.horizon_years===3||request.horizon_years===5)setHorizon(request.horizon_years)
    if(request.simulations===1000||request.simulations===5000||request.simulations===10000)setSimulations(request.simulations)
    if(typeof request.method==='string')setMethod(request.method)
    if(typeof request.rebalance_frequency==='string')setRebalance(request.rebalance_frequency)
    if(typeof request.monthly_contribution==='number')setContribution(request.monthly_contribution)
    setTarget(typeof request.target_value==='number'?String(request.target_value):'')
    setSeed(typeof request.random_seed==='number'?String(request.random_seed):'')
  },[history.data])
  const parameters=(mobile=false)=><aside className="analysis-parameters">
    <h3>模拟参数</h3>
    <label><span>期限</span><select value={horizon} onChange={e=>setHorizon(Number(e.target.value))}><option value={1}>1 年</option><option value={3}>3 年</option><option value={5}>5 年</option></select></label>
    <label><span>模拟次数</span><select value={simulations} onChange={e=>setSimulations(Number(e.target.value))}><option value={1000}>1,000</option><option value={5000}>5,000</option><option value={10000}>10,000</option></select></label>
    <label><span>模拟方法</span><select value={method} onChange={e=>setMethod(e.target.value)}><option value="block_bootstrap">联合区块自助法（默认）</option><option value="multivariate_normal">多元正态（快速）</option><option value="student_t">厚尾分布（高级）</option></select></label>
    <label><span>再平衡</span><select value={rebalance} onChange={e=>setRebalance(e.target.value)}><option value="none">不再平衡</option><option value="monthly">每月</option><option value="quarterly">每季度</option><option value="annual">每年</option></select></label>
    <label><span>每月追加资金</span><input type="number" min="0" value={contribution} onChange={e=>setContribution(Number(e.target.value))}/></label>
    <label><span>目标价值</span><input type="number" min="1" value={target} onChange={e=>setTarget(e.target.value)} placeholder="可选"/></label>
    <label><span>固定随机种子</span><input type="number" min="0" value={seed} onChange={e=>setSeed(e.target.value)}/></label>
    <button onClick={()=>{launch.mutate();if(mobile)setSettingsOpen(false)}} disabled={isRunning}>{isRunning?'模拟中…':savedRun?'重新模拟':'运行蒙特卡洛'}</button>
  </aside>
  return <div className="monte-page">
    <button className="analysis-settings-fab" onClick={()=>setSettingsOpen(true)}>调整参数 <span>⚙</span></button>
    <div className="analysis-workspace">
      <div className="analysis-desktop-parameters">{parameters()}</div>
      <main className="analysis-results">
        <div className="analysis-result-heading"><h3>概率分布</h3>{savedRun&&!liveResult&&<span>{cacheTimeLabel(savedRun)}</span>}</div>
        {history.isLoading&&!data&&<div className="empty">正在读取七天内的蒙特卡洛结果…</div>}
        {!history.isLoading&&!data&&!isRunning&&<div className="empty">这组参数在最近 7 天没有可用结果，请手动运行模拟。固定随机种子时结果可重复。</div>}
        {isRunning&&!data&&<div className="empty">正在后台运行蒙特卡洛模拟…</div>}
        {data&&data.status!=='completed'&&<div className="empty">{data.message||'本次模拟无法完成，请调整参数后重试。'}</div>}
        {data?.status==='completed'&&<><div className="monte-summary"><div><span>终值中位数</span><strong>{money(data.terminal_value_percentiles.p50)}</strong></div><div><span>80% 概率区间</span><strong>{money(data.terminal_value_percentiles.p10)} ～ {money(data.terminal_value_percentiles.p90)}</strong></div><div><span>95% 参考区间</span><strong>{money(data.terminal_value_percentiles.p5)} ～ {money(data.terminal_value_percentiles.p95)}</strong></div><div><span>亏损概率</span><strong>{pct(data.probability_of_loss)}</strong></div><div><span>亏损超 20%</span><strong>{pct(data.probability_loss_over_20_percent)}</strong></div><div><span>达到目标概率</span><strong>{pct(data.probability_reach_target)}</strong></div><div><span>最大回撤中位数</span><strong>{pct(data.max_drawdown.median)}</strong></div><div><span>回撤超 30%</span><strong>{pct(data.max_drawdown.probability_over_30_percent)}</strong></div></div><FanChart data={data.fan_chart} paths={data.sample_paths}/><div className="monte-distributions"><section><h4>终值分布</h4><Histogram values={data.terminal_value_sample}/></section><section><h4>最大回撤分布</h4><Histogram values={data.max_drawdown_sample} percent/></section></div><div className="risk-warnings"><p>模型置信度：{data.confidence==='high'?'高':data.confidence==='medium'?'中':'低'}{data.cache_hit?' · 已复用相同输入缓存':''}</p>{data.limitations.map(row=><p key={row}>{row}</p>)}</div></>}
        {job.data?.status==='failed'&&<p className="error">{job.data.error_message}</p>}
      </main>
    </div>
    <ExpectedReturnPanel portfolioId={portfolioId}/><AnalysisDisclaimer/>
    <Sheet open={settingsOpen} onClose={()=>setSettingsOpen(false)} title="蒙特卡洛参数"><div className="analysis-mobile-parameters">{parameters(true)}</div></Sheet>
  </div>
}
