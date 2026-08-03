import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from '@shared/api'
import { formatDateTime, formatMoney, formatPercent } from '@shared/format'
import type { NewsItem, PortfolioSummary, Position } from '@shared/types'
import { GlassCard, InsetList, IOSPage, ListRow, LoadingState, NavigationBar, SectionHeader, StateView, StatusPill } from '../components'

type JsonRecord = Record<string, unknown>
type LedgerEvent = { event_id: string; symbol: string | null; event_type: string; occurred_at: string | null; quantity: number | null; price: number | null; gross_amount: number | null; net_amount: number | null; currency: string | null; note?: string | null }
type LedgerDetail = { summary: Position; performance_curve: { date: string; market_value: number | null; cumulative_pnl: number | null; return_pct: number | null }[]; timeline: LedgerEvent[]; open_lots: JsonRecord[]; completed_trades: JsonRecord[]; data_sources: JsonRecord; latest_sync_at: string | null }
type PositionTechnical = { available?: boolean; status?: string; current_price?: number | null; atr?: number | null; rsi?: number | null; volatility?: number | null; trend?: string | JsonRecord | null; signals?: JsonRecord[]; support_zones?: JsonRecord[]; resistance_zones?: JsonRecord[]; arrival_estimates?: JsonRecord[]; cost_basis_reference?: JsonRecord }
type TechnicalContext = { status?: string; data_through?: string | null; generated_at?: string | null; stale?: boolean; chart_url?: string | null; analysis?: JsonRecord | null }
type AnalysisRun = { job_id: number; analysis_type: string; status: string; result: JsonRecord | null; created_at: string; completed_at: string | null; error_message: string | null }
type AnalysisHistory = { runs: AnalysisRun[] }
type AnalysisJob = { job_id: number; analysis_type: string; status: string; result: JsonRecord | null; error_message: string | null }
type DynamicPanel = 'news' | 'sentiment' | 'macro' | 'technical'
type AnalysisPanel = 'overview' | 'health' | 'stress' | 'scenario' | 'monte-carlo' | 'optimization' | 'history'
type RunnableAnalysis = Exclude<AnalysisPanel, 'overview' | 'health' | 'history'>

const dynamicTabs: [DynamicPanel, string][] = [['news', '新闻中心'], ['sentiment', '舆情'], ['macro', '美国宏观'], ['technical', '技术分析']]
const analysisTabs: [AnalysisPanel, string][] = [['overview', '组合中心'], ['health', '风险体检'], ['stress', '压力测试'], ['scenario', '情景分析'], ['monte-carlo', '蒙特卡洛'], ['optimization', '组合优化'], ['history', '交易历史']]
const analysisLabels: Record<RunnableAnalysis, string> = { stress: '压力测试', scenario: '情景分析', 'monte-carlo': '蒙特卡洛', optimization: '组合优化' }

function finite(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null }
function record(value: unknown): JsonRecord | null { return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : null }
function text(value: unknown): string | null {
  if (value == null) return null
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
  if (typeof value === 'boolean') return value ? '是' : '否'
  return null
}
function flattenFacts(value: unknown, prefix = '', depth = 0): [string, string][] {
  if (depth > 2 || value == null) return []
  const primitive = text(value)
  if (primitive != null) return prefix ? [[prefix, primitive]] : []
  if (Array.isArray(value)) return value.slice(0, 6).flatMap((item, index) => flattenFacts(item, prefix ? `${prefix} ${index + 1}` : `${index + 1}`, depth + 1))
  const object = record(value)
  if (!object) return []
  return Object.entries(object).slice(0, 16).flatMap(([key, item]) => flattenFacts(item, prefix ? `${prefix} · ${key}` : key, depth + 1))
}
function factLabel(key: string) { return key.replaceAll('_', ' ').replace('daily return pct', '日收益率').replace('overall score', '综合评分').replace('coverage', '覆盖率') }
function asDate(value: string | null | undefined) { return value ? formatDateTime(value) : '时间未知' }
function tone(value: number | null | undefined): 'positive' | 'negative' | 'neutral' { return (value ?? 0) >= 0 ? 'positive' : 'negative' }

export function MobilePositionWorkspace({ symbol, back }: { symbol: string; back: () => void }) {
  const client = useQueryClient()
  const [section, setSection] = useState<'holding' | 'dynamic' | 'analysis'>('holding')
  const [dynamicPanel, setDynamicPanel] = useState<DynamicPanel>('news')
  const [analysisPanel, setAnalysisPanel] = useState<AnalysisPanel>('overview')
  const [chartOpen, setChartOpen] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)
  const summary = useQuery({ queryKey: ['ios-portfolio-summary'], queryFn: () => api<PortfolioSummary>('/portfolio/summary'), staleTime: 30_000 })
  const detail = useQuery({ queryKey: ['ios-position-ledger-detail', symbol], queryFn: () => api<LedgerDetail>(`/portfolio/positions/${encodeURIComponent(symbol)}`), staleTime: 30_000 })
  const position = detail.data?.summary || summary.data?.positions.find(item => item.symbol === symbol)
  const news = useQuery({ queryKey: ['ios-position-news', symbol], queryFn: () => api<NewsItem[]>(`/news?ticker=${encodeURIComponent(symbol)}`), enabled: section === 'dynamic' && dynamicPanel === 'news', staleTime: 60_000 })
  const sentiment = useQuery({ queryKey: ['ios-position-sentiment', symbol], queryFn: () => api<JsonRecord>(`/sentiment/${encodeURIComponent(symbol)}?days=7`), enabled: section === 'dynamic' && dynamicPanel === 'sentiment', staleTime: 60_000 })
  const macro = useQuery({ queryKey: ['ios-us-macro-overview'], queryFn: () => api<JsonRecord>('/fundamentals/macro/us/overview'), enabled: section === 'dynamic' && dynamicPanel === 'macro', staleTime: 5 * 60_000 })
  const technical = useQuery({ queryKey: ['ios-position-technical', symbol], queryFn: () => api<PositionTechnical>(`/portfolio/positions/${encodeURIComponent(symbol)}/technical`), enabled: section === 'dynamic' && dynamicPanel === 'technical', staleTime: 60_000 })
  const technicalContext = useQuery({ queryKey: ['ios-technical-context', symbol], queryFn: () => api<TechnicalContext>(`/technical-analysis/${encodeURIComponent(symbol)}`), enabled: section === 'dynamic' && dynamicPanel === 'technical', staleTime: 60_000 })
  const health = useQuery({ queryKey: ['ios-portfolio-health'], queryFn: () => api<JsonRecord>('/portfolio/health'), enabled: section === 'analysis' && analysisPanel === 'health', staleTime: 60_000 })
  const history = useQuery({ queryKey: ['ios-portfolio-analysis-history'], queryFn: () => api<AnalysisHistory>('/portfolio/analysis/history'), enabled: section === 'analysis' && !['overview', 'health', 'history'].includes(analysisPanel), staleTime: 10_000 })
  const job = useQuery({ queryKey: ['ios-portfolio-analysis-job', jobId], queryFn: () => api<AnalysisJob>(`/portfolio/analysis/jobs/${jobId}`), enabled: jobId != null, refetchInterval: query => ['pending', 'running', 'queued'].includes(query.state.data?.status || '') ? 1_500 : false })
  const runAnalysis = useMutation({
    mutationFn: async (kind: RunnableAnalysis) => {
      const portfolioId = summary.data?.portfolio_id
      if (!portfolioId) throw new Error('组合资料尚未准备好')
      const requests: Record<RunnableAnalysis, [string, JsonRecord]> = {
        stress: ['/portfolio/analysis/stress-test', { portfolio_id: portfolioId, scenario_code: 'recession', mode: 'proxy_scenario' }],
        scenario: ['/portfolio/analysis/scenario-analysis', { portfolio_id: portfolioId, scenario_code: 'recession' }],
        'monte-carlo': ['/portfolio/analysis/monte-carlo', { portfolio_id: portfolioId, horizon_years: 1, simulations: 1000, method: 'block_bootstrap', block_length: 10, rebalance_frequency: 'quarterly', monthly_contribution: 0, confidence_levels: [0.8, 0.95] }],
        optimization: ['/portfolio/analysis/optimize', { portfolio_id: portfolioId, objective: 'balanced', covariance_method: 'ledoit_wolf', constraints: { only_current_positions: true } }],
      }
      return post<{ job_id: number }>(requests[kind][0], requests[kind][1])
    },
    onSuccess: result => { setJobId(result.job_id); void client.invalidateQueries({ queryKey: ['ios-portfolio-analysis-history'] }) },
  })
  const latestRun = history.data?.runs.find(item => item.analysis_type === analysisPanel)
  const currentJob = job.data?.job_id === jobId ? job.data : null
  const loading = summary.isLoading || detail.isLoading

  if (loading) return <><NavigationBar title={symbol} eyebrow="持仓详情" back={back}/><IOSPage className="detail-page"><LoadingState rows={7}/></IOSPage></>
  if (summary.isError || detail.isError || !position) return <><NavigationBar title={symbol} eyebrow="持仓详情" back={back}/><IOSPage className="detail-page"><StateView title="持仓资料暂不可用" message="无法读取这只证券的账户事实，请稍后重试。" retry={() => { void summary.refetch(); void detail.refetch() }}/></IOSPage></>

  const displayPosition = position
  return <><NavigationBar title={symbol} eyebrow="持仓详情" back={back}/><IOSPage className="detail-page position-workspace">
    <section className="position-detail-hero"><div><span>{displayPosition.currency} · {displayPosition.authority_source === 'ibkr_flex' ? 'IBKR 同步' : '手动账本'}</span><h1>{symbol}</h1></div><div className="position-detail-price"><strong>{formatMoney(displayPosition.current_price, displayPosition.currency)}</strong><StatusPill tone={tone(displayPosition.daily_change_percent)}>{formatPercent(displayPosition.daily_change_percent)}</StatusPill></div></section>
    <div className="position-detail-tabs" role="tablist">{([['holding', '持仓字段'], ['dynamic', '动态'], ['analysis', '组合分析']] as ['holding' | 'dynamic' | 'analysis', string][]).map(([key, label]) => <button key={key} role="tab" aria-selected={section === key} className={section === key ? 'active' : ''} onClick={() => setSection(key)}>{label}</button>)}</div>
    {section === 'holding' && <HoldingPanel position={displayPosition} detail={detail.data}/>}
    {section === 'dynamic' && <DynamicPanel panel={dynamicPanel} setPanel={setDynamicPanel} symbol={symbol} news={news} sentiment={sentiment} macro={macro} technical={technical} technicalContext={technicalContext} chartOpen={chartOpen} setChartOpen={setChartOpen}/>}
    {section === 'analysis' && <AnalysisPanel panel={analysisPanel} setPanel={setAnalysisPanel} summary={summary.data} detail={detail.data} health={health} history={history} latestRun={latestRun} currentJob={currentJob} runAnalysis={runAnalysis}/>}
  </IOSPage></>
}

function HoldingPanel({ position, detail }: { position: Position; detail?: LedgerDetail }) {
  const fields: [string, string][] = [
    ['持有数量', position.total_quantity.toLocaleString('zh-CN')],
    ['平均成本', formatMoney(position.average_cost, position.currency)],
    ['买入金额', formatMoney(position.total_cost ?? position.total_quantity * position.average_cost, position.currency)],
    ['当前价格', formatMoney(position.current_price, position.currency)],
    ['当前市值', formatMoney(position.market_value, position.currency)],
    ['今日盈亏', formatMoney(position.daily_pnl ?? (position.daily_change_amount != null ? position.daily_change_amount * position.total_quantity : null), position.currency)],
    ['累计盈亏', formatMoney(position.total_pnl ?? position.unrealized_pnl, position.currency)],
    ['累计收益率', formatPercent(position.total_return_pct ?? position.unrealized_pnl_percent)],
    ['组合权重', formatPercent(position.portfolio_weight).replace('+', '')],
    ['行情来源', position.price_source || '数据不足'],
    ['数量来源', position.quantity_source || '数据不足'],
    ['成本来源', position.average_cost_source || '数据不足'],
    ['汇率', position.fx_rate != null ? `${position.fx_rate.toFixed(4)} · ${position.fx_rate_source || '缓存'}` : '无需折算 / 数据不足'],
    ['首次交易', asDate(position.first_trade_at)],
    ['价格时间', asDate(position.price_as_of)],
    ['IBKR 报告日期', asDate(position.ibkr_report_date)],
  ]
  return <>
    <GlassCard className="position-pnl-card"><div><span>累计盈亏</span><strong className={tone(position.total_pnl ?? position.unrealized_pnl)}>{formatMoney(position.total_pnl ?? position.unrealized_pnl, position.currency)}</strong></div><div><span>当前市值</span><b>{formatMoney(position.market_value, position.currency)}</b></div><div><span>仓位</span><b>{formatPercent(position.portfolio_weight).replace('+', '')}</b></div></GlassCard>
    <InsetList label="账户与行情字段">{fields.map(([label, value]) => <ListRow key={label} title={label} value={value}/>)}</InsetList>
    {detail?.data_sources && <InsetList label="数据来源">{Object.entries(detail.data_sources).map(([key, value]) => <ListRow key={key} title={factLabel(key)} value={text(value) || '数据不足'}/>)}</InsetList>}
    {detail?.open_lots?.length ? <InsetList label={`开放批次 · ${detail.open_lots.length}`}>{detail.open_lots.slice(0, 5).map((lot, index) => <ListRow key={index} title={`批次 ${index + 1}`} subtitle={text(lot.opened_at) || '开仓日期未知'} value={text(lot.quantity) || '数据不足'}/>)}</InsetList> : null}
    <p className="disclaimer">账户数量与交易事实优先来自 IBKR 同步；市场价格来自项目行情系统。缺失项显示“数据不足”，不以估算值替代。</p>
  </>
}

function DynamicPanel({ panel, setPanel, symbol, news, sentiment, macro, technical, technicalContext, chartOpen, setChartOpen }: { panel: DynamicPanel; setPanel: (panel: DynamicPanel) => void; symbol: string; news: ReturnType<typeof useQuery<NewsItem[]>>; sentiment: ReturnType<typeof useQuery<JsonRecord>>; macro: ReturnType<typeof useQuery<JsonRecord>>; technical: ReturnType<typeof useQuery<PositionTechnical>>; technicalContext: ReturnType<typeof useQuery<TechnicalContext>>; chartOpen: boolean; setChartOpen: (open: boolean) => void }) {
  return <>
    <div className="mobile-subnav mobile-dynamic-nav" role="tablist">{dynamicTabs.map(([key, label]) => <button key={key} role="tab" aria-selected={panel === key} className={panel === key ? 'active' : ''} onClick={() => setPanel(key)}>{label}</button>)}</div>
    {panel === 'news' && <DynamicNews symbol={symbol} query={news}/>}
    {panel === 'sentiment' && <DynamicFacts title="舆情摘要" query={sentiment} empty="当前没有可用的舆情数据。"/>}
    {panel === 'macro' && <DynamicFacts title="美国宏观" query={macro} empty="宏观数据尚未同步。"/>}
    {panel === 'technical' && <TechnicalPanel query={technical} context={technicalContext} chartOpen={chartOpen} setChartOpen={setChartOpen}/>}
  </>
}

function DynamicNews({ symbol, query }: { symbol: string; query: ReturnType<typeof useQuery<NewsItem[]>> }) {
  if (query.isLoading) return <LoadingState rows={5}/>
  if (query.isError) return <StateView title="新闻暂不可用" message={`${symbol} 的新闻服务暂时没有响应。`} retry={() => query.refetch()}/>
  if (!query.data?.length) return <StateView title="暂无个股新闻" message="当前没有已保存的相关新闻。"/>
  return <div className="mobile-dynamic-list">{query.data.slice(0, 12).map(item => <article className="mobile-dynamic-card" key={item.id}><header><StatusPill tone={item.sentiment_score == null ? 'neutral' : tone(item.sentiment_score)}>{item.topic || item.news_type || '新闻'}</StatusPill><time>{asDate(item.published_at || item.found_at)}</time></header><a href={item.url} target="_blank" rel="noreferrer"><strong>{item.translated_title || item.title}</strong><span>↗</span></a>{(item.ai_summary || item.summary) && <p>{item.ai_summary || item.summary}</p>}<small>{item.source || item.provider || '来源未知'}</small></article>)}</div>
}

function DynamicFacts({ title, query, empty }: { title: string; query: ReturnType<typeof useQuery<JsonRecord>>; empty: string }) {
  if (query.isLoading) return <LoadingState rows={5}/>
  if (query.isError) return <StateView title={`${title}暂不可用`} message="数据服务暂时没有响应。" retry={() => query.refetch()}/>
  const facts = flattenFacts(query.data)
  return facts.length ? <section className="mobile-facts-card"><header><span>{title}</span><small>已保存数据</small></header><div className="mobile-fact-grid">{facts.slice(0, 24).map(([key, value], index) => <div key={`${key}-${index}`}><small>{factLabel(key)}</small><strong>{value}</strong></div>)}</div><p className="mobile-data-note">不同指标的更新时间可能不同，请以各项来源和时间为准。</p></section> : <StateView title={title} message={empty}/>
}

function TechnicalPanel({ query, context, chartOpen, setChartOpen }: { query: ReturnType<typeof useQuery<PositionTechnical>>; context: ReturnType<typeof useQuery<TechnicalContext>>; chartOpen: boolean; setChartOpen: (open: boolean) => void }) {
  if (query.isLoading || context.isLoading) return <LoadingState rows={6}/>
  if (query.isError && context.isError) return <StateView title="技术分析暂不可用" message="技术数据尚未准备好，请稍后重试。" retry={() => { void query.refetch(); void context.refetch() }}/>
  const data = query.data
  const chart = context.data
  const trend = typeof data?.trend === 'string' ? data.trend : text(record(data?.trend)?.label) || '趋势不明'
  const zones: JsonRecord[] = [...(data?.support_zones || []).slice(0, 3).map(zone => ({ ...zone, type: '支撑' })), ...(data?.resistance_zones || []).slice(0, 3).map(zone => ({ ...zone, type: '阻力' }))]
  return <section className="technical-mobile-section"><div className="technical-mobile-section-head"><div><span>TECHNICAL</span><h2>静态技术图与关键点位</h2></div><StatusPill tone={data?.available ? 'positive' : 'warning'}>{data?.available ? 'READY' : '数据不足'}</StatusPill></div><div className="technical-floating-anchor"><button className="technical-float-trigger" onClick={() => setChartOpen(true)}><span>⌁</span><b>打开静态图</b></button>{chartOpen && <div className="technical-float-window" role="dialog" aria-label="静态技术图"><header><div><span>STATIC CHART</span><strong>技术分析</strong></div><button onClick={() => setChartOpen(false)} aria-label="关闭技术图">×</button></header><div className="technical-float-scroll">{chart?.chart_url ? <img src={chart.chart_url} alt="静态技术分析图"/> : <div className="technical-chart-empty">暂无已生成的静态图</div>}<small>{chart?.data_through ? `数据截至 ${chart.data_through}` : '图表数据时间未知'}</small></div></div>}</div><div className="technical-metric-grid"><div><small>趋势</small><strong>{trend}</strong></div><div><small>ATR</small><strong>{finite(data?.atr)?.toFixed(2) || '—'}</strong></div><div><small>RSI</small><strong>{finite(data?.rsi)?.toFixed(1) || '—'}</strong></div><div><small>波动率</small><strong>{finite(data?.volatility) != null ? `${(finite(data?.volatility)! * 100).toFixed(1)}%` : '—'}</strong></div></div>{zones.length ? <div className="technical-level-list"><SectionHeader title="关键点位" caption="来自标准化技术分析"/>{zones.map((zone, index) => <div key={index}><span>{text(zone.type) || '点位'}</span><b>{text(zone.center_price) || text(zone.price) || '—'}</b><small>{text(zone.strength) || text(zone.status) || '—'}</small></div>)}</div> : <p className="mobile-data-note">当前没有可用的支撑或阻力区间。</p>}<p className="mobile-data-note">技术图为静态图片，不加载 TradingView 开源组件；指标缺失时保留“数据不足”。</p></section>
}

function AnalysisPanel({ panel, setPanel, summary, detail, health, history, latestRun, currentJob, runAnalysis }: { panel: AnalysisPanel; setPanel: (panel: AnalysisPanel) => void; summary?: PortfolioSummary; detail?: LedgerDetail; health: ReturnType<typeof useQuery<JsonRecord>>; history: ReturnType<typeof useQuery<AnalysisHistory>>; latestRun?: AnalysisRun; currentJob: AnalysisJob | null; runAnalysis: ReturnType<typeof useMutation<{ job_id: number }, Error, RunnableAnalysis>> }) {
  return <>
    <div className="mobile-subnav mobile-analysis-nav" role="tablist">{analysisTabs.map(([key, label]) => <button key={key} role="tab" aria-selected={panel === key} className={panel === key ? 'active' : ''} onClick={() => setPanel(key)}>{label}</button>)}</div>
    {panel === 'overview' && <AnalysisOverview summary={summary} position={detail?.summary}/>}
    {panel === 'health' && <HealthPanel query={health}/>}
    {panel === 'history' && <TransactionHistory detail={detail}/>}
    {['stress', 'scenario', 'monte-carlo', 'optimization'].includes(panel) && <AsyncAnalysisPanel panel={panel as RunnableAnalysis} history={history} latestRun={latestRun} currentJob={currentJob} runAnalysis={runAnalysis}/>}
  </>
}

function AnalysisOverview({ summary, position }: { summary?: PortfolioSummary; position?: Position }) {
  return <><GlassCard className="analysis-overview-card"><span>组合中心</span><strong>{formatMoney(summary?.total_market_value, summary?.base_currency)}</strong><div><span>当前持仓 {summary?.position_count ?? '—'} 只</span><span>组合浮盈 {formatMoney(summary?.total_unrealized_pnl, summary?.base_currency)}</span></div><p>从这里进入风险体检、压力测试、情景分析、蒙特卡洛、组合优化与交易历史；每个模块单独打开，避免手机页面一次堆满。</p></GlassCard>{position && <InsetList label="当前个股在组合中的位置"><ListRow title="组合权重" value={formatPercent(position.portfolio_weight).replace('+', '')}/><ListRow title="持仓市值" value={formatMoney(position.market_value, position.currency)}/><ListRow title="累计收益率" value={formatPercent(position.total_return_pct ?? position.unrealized_pnl_percent)}/></InsetList>}</>
}

function HealthPanel({ query }: { query: ReturnType<typeof useQuery<JsonRecord>> }) {
  if (query.isLoading) return <LoadingState rows={6}/>
  if (query.isError) return <StateView title="风险体检暂不可用" message="组合健康数据暂时没有响应。" retry={() => query.refetch()}/>
  const facts = flattenFacts(query.data)
  return <section className="mobile-facts-card"><header><span>风险体检</span><small>规则化组合检查</small></header>{facts.length ? <div className="mobile-fact-grid">{facts.slice(0, 24).map(([key, value], index) => <div key={`${key}-${index}`}><small>{factLabel(key)}</small><strong>{value}</strong></div>)}</div> : <StateView title="暂无健康结论" message="当前组合数据覆盖不足，暂时无法形成风险结论。"/>}<p className="mobile-data-note">健康检查不触发新分析；覆盖不足的组件会明确显示数据缺口。</p></section>
}

function TransactionHistory({ detail }: { detail?: LedgerDetail }) {
  const rows = detail?.timeline || []
  if (!rows.length) return <StateView title="暂无交易历史" message="这只持仓还没有可显示的交易事件。"/>
  return <div className="mobile-transaction-list">{rows.slice(0, 30).map(row => <article key={row.event_id}><div><StatusPill tone={row.event_type === 'buy' ? 'positive' : row.event_type === 'sell' ? 'negative' : 'neutral'}>{row.event_type === 'buy' ? '买入' : row.event_type === 'sell' ? '卖出' : row.event_type}</StatusPill><time>{asDate(row.occurred_at)}</time></div><strong>{row.quantity != null ? `${row.quantity.toLocaleString('zh-CN')} 股` : '—'}{row.price != null ? ` · ${formatMoney(row.price, row.currency || 'USD')}` : ''}</strong><small>{row.net_amount != null ? `净额 ${formatMoney(row.net_amount, row.currency || 'USD')}` : row.note || '账户事实'}</small></article>)}</div>
}

function AsyncAnalysisPanel({ panel, history, latestRun, currentJob, runAnalysis }: { panel: RunnableAnalysis; history: ReturnType<typeof useQuery<AnalysisHistory>>; latestRun?: AnalysisRun; currentJob: AnalysisJob | null; runAnalysis: ReturnType<typeof useMutation<{ job_id: number }, Error, RunnableAnalysis>> }) {
  const result = currentJob?.result || latestRun?.result
  const facts = flattenFacts(result)
  const busy = runAnalysis.isPending || ['pending', 'running', 'queued'].includes(currentJob?.status || '')
  return <section className="mobile-analysis-result"><header><div><span>PORTFOLIO ANALYSIS</span><h2>{analysisLabels[panel]}</h2></div><button className="analysis-run-button" onClick={() => runAnalysis.mutate(panel)} disabled={busy}>{busy ? '运行中…' : '运行一次'}</button></header>{runAnalysis.isError && <p className="inline-error">{runAnalysis.error instanceof Error ? runAnalysis.error.message : '分析任务提交失败'}</p>}{currentJob && <p className="analysis-job-status">任务 #{currentJob.job_id} · {currentJob.status === 'completed' ? '已完成' : currentJob.status === 'failed' ? currentJob.error_message || '运行失败' : '后台计算中，页面会自动更新'}</p>}{history.isLoading && <LoadingState rows={4}/>} {!history.isLoading && facts.length > 0 && <div className="mobile-fact-grid">{facts.slice(0, 24).map(([key, value], index) => <div key={`${key}-${index}`}><small>{factLabel(key)}</small><strong>{value}</strong></div>)}</div>}{!history.isLoading && !facts.length && !currentJob && <StateView title="还没有分析结果" message="点击右上角运行一次，结果完成后会留在这个模块。"/>}<p className="mobile-data-note">分析由后台任务完成，结果会写入组合分析历史；等待时可以返回其他模块。</p></section>
}
