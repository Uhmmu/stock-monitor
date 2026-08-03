import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import { Sheet } from './Sheet'
import { cacheTimeLabel, latestFreshAnalysis, requestsMatch, type PortfolioAnalysisRun, usePortfolioAnalysisHistory } from './PortfolioAnalysisCache'

type ScenarioMode = 'historical_replay' | 'proxy_scenario' | 'custom_scenario'
type Preset = {
  code: string
  name: string
  description: string
  mode: ScenarioMode
  market_shock: number
  sector_shocks: Record<string, number>
  style_shocks: Record<string, number>
  interest_rate_change_bp: number
  currency_shocks: Record<string, number>
  volatility_change: number
  start_date: string | null
  end_date: string | null
}
type StressAsset = {
  symbol: string
  sector: string
  current_weight: number
  estimated_return: number
  portfolio_loss_contribution: number
  estimated_value_change: number
  method: 'actual' | 'proxy' | 'factor_model'
  confidence: 'high' | 'medium' | 'low'
}
export type StressResult = {
  status: string
  message?: string
  scenario: { code: string; name: string; description: string; mode: ScenarioMode; start_date: string | null; end_date: string | null }
  scenario_mode: ScenarioMode
  data_quality: 'actual' | 'mixed' | 'proxy'
  actual_asset_count: number
  proxy_asset_count: number
  factor_model_asset_count: number
  portfolio_value: number
  estimated_portfolio_return: number
  estimated_loss_amount: number
  spy_return: number | null
  equal_weight_return: number
  concentration_amplification: number
  largest_loss_contributor: string
  largest_loss_sector: string
  asset_results: StressAsset[]
  sector_results: { sector: string; portfolio_loss_contribution: number; estimated_value_change: number }[]
  confidence: 'high' | 'medium' | 'low'
  warnings: string[]
  explanation: string
}
type Job = { job_id: number; status: 'pending' | 'running' | 'completed' | 'failed'; result: StressResult | null; error_message: string | null }
export type ScenarioHistoryRun = PortfolioAnalysisRun<StressResult>

const pct = (value: number | null | undefined) => value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
const money = (value: number) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)
const methodLabels: Record<StressAsset['method'], string> = { actual: '真实行情', proxy: '代理估算', factor_model: '因子模型' }

export function findSavedScenarioRun(runs: PortfolioAnalysisRun[] | undefined, code: string | null) {
  if (!code) return undefined
  return latestFreshAnalysis<StressResult>(runs, 'scenario_analysis', run => run.result?.scenario.code === code)
}

function useAnalysisJob(jobId: number | null) {
  return useQuery({
    queryKey: ['portfolio-analysis-job', jobId],
    queryFn: () => api<Job>(`/portfolio/analysis/jobs/${jobId}`),
    enabled: jobId != null,
    refetchInterval: query => ['pending', 'running'].includes(query.state.data?.status || '') ? 2000 : false,
  })
}

function ResultPanel({ data }: { data: StressResult }) {
  if (data.status !== 'completed') return <div className="empty">{data.message || '本次分析无法完成。'}</div>
  const max = Math.max(...data.asset_results.map(row => Math.abs(row.portfolio_loss_contribution)), .001)
  const postValues = data.asset_results.map(row => ({ symbol: row.symbol, value: row.current_weight * (1 + row.estimated_return) }))
  const total = postValues.reduce((sum, row) => sum + row.value, 0)
  return <div className="stress-result">
    <div className="stress-summary-grid">
      <div><span>组合预计变化</span><strong className={data.estimated_portfolio_return < 0 ? 'negative' : 'positive'}>{pct(data.estimated_portfolio_return)}</strong></div>
      <div><span>预计价值变化</span><strong>{money(data.estimated_loss_amount)}</strong></div>
      <div><span>标普 500 对比</span><strong>{pct(data.spy_return)}</strong></div>
      <div><span>等权组合</span><strong>{pct(data.equal_weight_return)}</strong></div>
      <div><span>数据可信度</span><strong>{data.confidence === 'high' ? '高' : data.confidence === 'medium' ? '中' : '低'}</strong></div>
    </div>
    <div className="stress-quality"><b>{data.data_quality === 'actual' ? '真实行情' : data.data_quality === 'mixed' ? '真实与代理混合' : '代理估算'}</b><span>真实行情 {data.actual_asset_count} · 代理估算 {data.proxy_asset_count} · 因子模型 {data.factor_model_asset_count}</span></div>
    <p className="stress-explanation">{data.explanation}</p>
    <div className="stress-chart-grid">
      <section><h4>单股亏损贡献</h4><div className="stress-waterfall">{data.asset_results.map(row => <div key={row.symbol}><span>{row.symbol}<small>{methodLabels[row.method]}</small></span><i><b style={{ width: `${Math.abs(row.portfolio_loss_contribution) / max * 100}%` }} /></i><strong>{pct(row.portfolio_loss_contribution)}</strong></div>)}</div></section>
      <section><h4>行业损失贡献</h4><div className="stress-waterfall">{data.sector_results.map(row => <div key={row.sector}><span>{row.sector}</span><i><b style={{ width: `${Math.abs(row.portfolio_loss_contribution) / Math.max(...data.sector_results.map(x => Math.abs(x.portfolio_loss_contribution)), .001) * 100}%` }} /></i><strong>{pct(row.portfolio_loss_contribution)}</strong></div>)}</div></section>
    </div>
    <section className="allocation-compare"><h4>压力前后仓位结构</h4>{data.asset_results.map(row => { const after = postValues.find(x => x.symbol === row.symbol)!.value / total; return <div key={row.symbol}><b>{row.symbol}</b><span><i style={{ width: `${row.current_weight * 100}%` }} /><em style={{ width: `${after * 100}%` }} /></span><small>{pct(row.current_weight)} → {pct(after)}</small></div> })}</section>
    {data.warnings.map((warning, index) => <p className="stress-warning" key={`${warning}-${index}`}>{warning}</p>)}
  </div>
}

export function StressTestView({ portfolioId }: { portfolioId: number }) {
  const queryClient = useQueryClient()
  const history = usePortfolioAnalysisHistory()
  const restoredCache = useRef(false)
  const presets = useQuery({ queryKey: ['portfolio-scenario-presets'], queryFn: () => api<{ presets: Preset[] }>('/portfolio/analysis/scenarios/presets'), staleTime: 3600_000 })
  const [mode, setMode] = useState<ScenarioMode>('proxy_scenario')
  const [preset, setPreset] = useState('recession')
  const [start, setStart] = useState('2022-01-03')
  const [end, setEnd] = useState('2022-10-14')
  const [market, setMarket] = useState(-20)
  const [tech, setTech] = useState(-25)
  const [rates, setRates] = useState(100)
  const [usd, setUsd] = useState(5)
  const [fundamental, setFundamental] = useState(true)
  const [jobId, setJobId] = useState<number | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [launchedRequest, setLaunchedRequest] = useState<Record<string, unknown> | null>(null)
  const currentRequest = { portfolio_id: portfolioId, mode, scenario_code: mode === 'custom_scenario' ? null : preset, start_date: mode === 'historical_replay' ? start : null, end_date: mode === 'historical_replay' ? end : null, market_shock: market / 100, nasdaq_shock: 0, sector_shocks: { Technology: tech / 100 }, style_shocks: {}, interest_rate_change_bp: rates, currency_shocks: { USD: usd / 100 }, volatility_change: 0, use_fundamental_modifiers: fundamental }
  const launch = useMutation({ mutationFn: () => post<{ job_id: number }>('/portfolio/analysis/stress-test', currentRequest), onMutate: () => setLaunchedRequest(currentRequest), onSuccess: data => setJobId(data.job_id) })
  const job = useAnalysisJob(jobId)
  const matching = presets.data?.presets.filter(row => row.mode === mode) || []
  const isRunning = launch.isPending || ['pending', 'running'].includes(job.data?.status || '')
  const savedRun = latestFreshAnalysis<StressResult>(history.data?.runs, 'stress_test', run => requestsMatch(run.input_request, currentRequest))
  const liveResult = requestsMatch(launchedRequest || undefined, currentRequest) && job.data?.status === 'completed' ? job.data.result : null
  const result = liveResult || savedRun?.result

  useEffect(() => {
    if (job.data?.status === 'completed') void queryClient.invalidateQueries({ queryKey: ['portfolio-analysis-history'] })
  }, [job.data?.status, queryClient])

  useEffect(() => {
    if (restoredCache.current || !history.data) return
    restoredCache.current = true
    const cached = latestFreshAnalysis<StressResult>(history.data.runs, 'stress_test')
    if (!cached) return
    const request = cached.input_request
    if (request.mode === 'historical_replay' || request.mode === 'proxy_scenario' || request.mode === 'custom_scenario') setMode(request.mode)
    if (typeof request.scenario_code === 'string') setPreset(request.scenario_code)
    if (typeof request.start_date === 'string') setStart(request.start_date)
    if (typeof request.end_date === 'string') setEnd(request.end_date)
    if (typeof request.market_shock === 'number') setMarket(request.market_shock * 100)
    const sectors = request.sector_shocks as Record<string, unknown> | undefined
    if (typeof sectors?.Technology === 'number') setTech(sectors.Technology * 100)
    if (typeof request.interest_rate_change_bp === 'number') setRates(request.interest_rate_change_bp)
    const currencies = request.currency_shocks as Record<string, unknown> | undefined
    if (typeof currencies?.USD === 'number') setUsd(currencies.USD * 100)
    if (typeof request.use_fundamental_modifiers === 'boolean') setFundamental(request.use_fundamental_modifiers)
  }, [history.data])

  const parameters = (mobile=false) => <aside className="analysis-parameters"><h3>压力参数</h3><label><span>情景类型</span><select value={mode} onChange={event => { const value = event.target.value as ScenarioMode; setMode(value); const first = presets.data?.presets.find(row => row.mode === value); if (first) setPreset(first.code) }}><option value="historical_replay">真实历史回放</option><option value="proxy_scenario">代理历史情景</option><option value="custom_scenario">自定义情景</option></select></label>{mode !== 'custom_scenario' && <label><span>预设情景</span><select value={preset} onChange={event => setPreset(event.target.value)}>{matching.map(row => <option value={row.code} key={row.code}>{row.name}</option>)}</select></label>}{mode === 'historical_replay' && <><label><span>开始日期</span><input type="date" min="2021-01-01" value={start} onChange={e => setStart(e.target.value)} /></label><label><span>结束日期</span><input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label></>}{mode === 'custom_scenario' && <><label><span>标普 500 冲击 <b>{market}%</b></span><input type="range" min="-80" max="80" value={market} onChange={e => setMarket(Number(e.target.value))} /></label><label><span>科技行业冲击 <b>{tech}%</b></span><input type="range" min="-90" max="90" value={tech} onChange={e => setTech(Number(e.target.value))} /></label><label><span>10 年期利率 <b>{rates}个基点</b></span><input type="number" min="-1000" max="1000" value={rates} onChange={e => setRates(Number(e.target.value))} /></label><label><span>美元指数变化 <b>{usd}%</b></span><input type="number" min="-50" max="50" value={usd} onChange={e => setUsd(Number(e.target.value))} /></label></>}<label className="analysis-checkbox"><input type="checkbox" checked={fundamental} onChange={e => setFundamental(e.target.checked)} /><span>启用受限基本面修正</span></label><button onClick={() => {launch.mutate();if(mobile)setSettingsOpen(false)}} disabled={isRunning}>{isRunning ? '计算中…' : savedRun ? '重新计算' : '运行压力测试'}</button></aside>

  return <div className="stress-page">
    <button className="analysis-settings-fab" onClick={()=>setSettingsOpen(true)}>调整参数 <span>⚙</span></button>
    <div className="analysis-workspace">
      <div className="analysis-desktop-parameters">{parameters()}</div>
      <main className="analysis-results"><div className="analysis-result-heading"><h3>压力测试结果</h3>{savedRun && !liveResult && <span>{cacheTimeLabel(savedRun)}</span>}</div>{history.isLoading && <div className="empty">正在读取七天内的历史结果…</div>}{!history.isLoading && !result && !isRunning && <div className="empty">这组参数在最近 7 天没有可用结果，请手动运行压力测试。</div>}{result && <ResultPanel data={result} />}{isRunning && !result && <div className="empty">正在运行压力测试…</div>}{job.data?.status === 'failed' && <p className="error">{job.data.error_message}</p>}</main>
    </div>
    <AnalysisDisclaimer />
    <Sheet open={settingsOpen} onClose={()=>setSettingsOpen(false)} title="压力测试参数"><div className="analysis-mobile-parameters">{parameters(true)}</div></Sheet>
  </div>
}

export function ScenarioAnalysisView({ portfolioId }: { portfolioId: number }) {
  const queryClient = useQueryClient()
  const presets = useQuery({ queryKey: ['portfolio-scenario-presets'], queryFn: () => api<{ presets: Preset[] }>('/portfolio/analysis/scenarios/presets'), staleTime: 3600_000 })
  const history = usePortfolioAnalysisHistory()
  const [selected, setSelected] = useState<string | null>(null)
  const [runningCode, setRunningCode] = useState<string | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const launch = useMutation({
    mutationFn: (code: string) => post<{ job_id: number }>('/portfolio/analysis/scenario-analysis', { portfolio_id: portfolioId, scenario_code: code, use_fundamental_modifiers: true }),
    onMutate: code => setRunningCode(code),
    onSuccess: data => setJobId(data.job_id),
  })
  const job = useAnalysisJob(jobId)
  const cards = presets.data?.presets.filter(row => ['soft_landing', 'recession', 'inflation_rebound', 'rapid_cuts', 'growth_repricing', 'ai_continues', 'ai_capex_cools', 'usd_strength', 'yen_reversal'].includes(row.code)) || []
  const savedRun = findSavedScenarioRun(history.data?.runs, selected)
  const liveResult = runningCode === selected && job.data?.status === 'completed' ? job.data.result : null
  const result = liveResult || savedRun?.result
  const isRunning = launch.isPending || ['pending', 'running'].includes(job.data?.status || '')
  const selectedPreset = cards.find(row => row.code === selected)

  useEffect(() => {
    if (selected || !history.data) return
    const cached = latestFreshAnalysis<StressResult>(history.data.runs, 'scenario_analysis')
    if (cached?.result?.scenario.code) setSelected(cached.result.scenario.code)
  }, [history.data, selected])

  useEffect(() => {
    if (job.data?.status === 'completed') void queryClient.invalidateQueries({ queryKey: ['portfolio-analysis-history'] })
  }, [job.data?.status, queryClient])

  const scenarioControls=(mobile=false)=><><div className="scenario-cards">{cards.map(row => {
    const hasSavedResult = Boolean(findSavedScenarioRun(history.data?.runs, row.code))
    const cardRunning = isRunning && runningCode === row.code
    return <button key={row.code} className={`${selected === row.code ? 'active' : ''}${cardRunning ? ' running' : ''}`} onClick={() => setSelected(row.code)}><b>{row.name}</b><span>{row.description}</span><small>{row.mode === 'historical_replay' ? '真实回放' : '代理估算'}{hasSavedResult ? ' · 已有结果' : ''}{cardRunning ? ' · 计算中' : ''}</small></button>
  })}</div>{selected && <div className="scenario-result-toolbar"><div><b>{selectedPreset?.name}</b><span>{savedRun ? cacheTimeLabel(savedRun) : '该情景最近 7 天没有可用结果，可手动开始估算'}</span></div><button onClick={() => {launch.mutate(selected);if(mobile)setSettingsOpen(false)}} disabled={isRunning}>{isRunning ? runningCode === selected ? '正在重新估算…' : '另一情景计算中' : savedRun ? '重新估算' : '开始估算'}</button></div>}</>

  return <div className="scenario-page">
    <button className="analysis-settings-fab" onClick={()=>setSettingsOpen(true)}>选择情景 <span>⚙</span></button>
    <div className="analysis-desktop-parameters scenario-desktop-controls">{scenarioControls()}</div>
    {result ? <ResultPanel data={result} /> : isRunning && runningCode === selected ? <div className="empty">正在运行情景分析…</div> : selected ? <div className="empty">该情景暂无历史结果，点击“开始估算”后才会创建新任务。</div> : <div className="empty">选择一个情景查看已保存的结果，选择本身不会触发重新计算。</div>}
    {runningCode === selected && job.data?.status === 'failed' && <p className="error">{job.data.error_message}</p>}
    {launch.isError && <p className="error">创建情景任务失败，请稍后重试。</p>}
    <AnalysisDisclaimer />
    <Sheet open={settingsOpen} onClose={()=>setSettingsOpen(false)} title="情景分析参数"><div className="analysis-mobile-parameters scenario-mobile-controls">{scenarioControls(true)}</div></Sheet>
  </div>
}

export function AnalysisDisclaimer() {
  return <p className="portfolio-analysis-disclaimer">分析结果基于历史数据、统计模型和用户设定假设，不构成投资建议。历史表现和模拟结果不代表未来收益。<br />当前历史行情主要覆盖 2021 年之后，部分历史风险指标可能低估完整市场周期中的极端风险。</p>
}
