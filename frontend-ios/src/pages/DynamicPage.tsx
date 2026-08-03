import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { api, post } from '@shared/api'
import { formatDateTime, formatMoney, formatPercent } from '@shared/format'
import type { MarketNews, NewsItem, PortfolioSummary, Position, WatchItem } from '@shared/types'
import { GlassCard, IOSPage, LoadingState, SectionHeader, StateView, StatusPill } from '../components'

type DynamicSection = 'news' | 'sentiment' | 'macro' | 'technical' | 'portfolio'
type NewsScope = 'market' | 'company'

type SentimentSource = {
  source: 'reddit' | 'x' | 'news' | 'polymarket' | string
  label: string
  company_name: string | null
  buzz_score: number
  bullish_pct: number | null
  trend: 'rising' | 'falling' | 'stable' | null
  metric_label: string
  metric_value: number
}
type StockSentiment = {
  symbol: string
  company_name: string | null
  period_days: number
  average_buzz: number
  bullish_average: number | null
  source_alignment: string
  available_sources: number
  sources: SentimentSource[]
}

type MacroPoint = { observation_date: string; value: number | null; is_derived?: boolean }
type MacroCard = {
  series_key: string
  display_name_zh: string
  description_zh: string
  unit: string
  frequency: string
  category: string
  latest: MacroPoint | null
  previous: MacroPoint | null
  trend: { direction: string; strength: string }
  current_impact: { label: string; label_zh: string }
  freshness: { status: string; label_zh: string; last_fetched_at?: string | null }
  data_status: string
  sparkline?: MacroPoint[]
}
type MacroSummary = {
  state: string
  label_zh: string
  tone: string
  confidence: number
  drivers: { series_key: string; observation_date: string | null; effect: string; reason: string }[]
}
type MacroOverview = {
  source: { name: string; status_label_zh: string; configured: boolean }
  last_sync_at: string | null
  latest_observation_date: string | null
  summaries: Record<string, MacroSummary>
  cards: MacroCard[]
  curve_analysis: { label_zh: string; spread_10y_2y?: number | null; spread_10y_3m?: number | null }
  disclaimer: string
}
type YieldCurve = {
  curves: { label: string; observation_date: string; points: { maturity: string; value: number | null }[] }[]
  analysis: MacroOverview['curve_analysis']
}

type Candle = { date?: string; time?: string; close: number | null; open?: number | null; high?: number | null; low?: number | null }
type TechnicalZone = { low: number; high: number; center: number; type?: string; strength?: number; touchCount?: number; distancePercent?: number }
type TechnicalAnalysis = {
  latestClose: number
  weeklyTrend: string
  nearestSupport: TechnicalZone | null
  nearestResistance: TechnicalZone | null
  supportZones: TechnicalZone[]
  resistanceZones: TechnicalZone[]
  fibonacci: { available: boolean; direction?: string; levels?: Record<string, number>; omissionReason?: string }
  trendLines: { type: string; projectedPrice: number; priceRelation: string; confidence: number }[]
  indicators: Record<string, number | null>
  omittedReasons: string[]
}
type TechnicalItem = {
  symbol: string
  status: string
  company_name: string | null
  chart_url: string | null
  data_through?: string
  generated_at?: string
  stale?: boolean
  chart_data_status?: string
  chart_data_reason?: string | null
  weekly?: Candle[]
  chart_series?: { week?: { candles?: Candle[] } }
  analysis?: TechnicalAnalysis
  data_status?: Record<string, string | null>
}

type HealthCoverage = { covered_weight: number; freshness: string; status: string }
type PortfolioHealth = {
  as_of: string
  base_currency: string
  total_market_value: number
  health: { score: number | null; grade: string; confidence: number }
  fundamental_quality: { score: number | null; grade: string; coverage_weight: number; subscores: Record<string, { score: number | null; coverage_weight: number }> }
  valuation_risk: { score: number | null; grade: string; coverage_weight: number; average_confidence: number; undervalued_weight: number; fairly_valued_weight: number; overvalued_weight: number; high_risk_weight: number }
  sec_risk: { score: number | null; grade: string; coverage_weight: number; flag_exposures: { label: string; weight: number; affected_symbols: string[] }[] }
  concentration: { available: boolean; reason?: string; risk_score: number | null; largest_position_weight: number | null; top_three_weight: number | null; top_five_weight: number | null; hhi_scaled?: number | null; sector_weights: { sector: string; weight: number; market_value: number }[] }
  coverage: { price: HealthCoverage; fundamental: HealthCoverage; valuation: HealthCoverage; sec: HealthCoverage }
  findings: { severity: string; title: string; message: string; affected_symbols: string[] }[]
}
type AnalysisRun = { job_id: number; analysis_type: string; status: string; result: Record<string, unknown> | null; input_request: Record<string, unknown>; created_at: string; completed_at?: string | null; error_message?: string | null }
type AnalysisJob = { job_id: number; status: string; result: Record<string, unknown> | null; error_message: string | null }
type LedgerEvent = { event_id: string; symbol: string | null; event_type: string; occurred_at: string | null; quantity: number | null; price: number | null; gross_amount: number | null; net_amount: number | null; currency: string | null; source_type: string; is_authoritative: boolean; note?: string | null }

const sectionTabs: [DynamicSection, string][] = [
  ['news', '新闻中心'],
  ['sentiment', '舆情'],
  ['macro', '美国宏观'],
  ['technical', '技术分析'],
  ['portfolio', '组合分析'],
]
const portfolioTabs: [PortfolioSubsection, string][] = [
  ['overview', '组合中心'],
  ['health', '风险体检'],
  ['stress', '压力测试'],
  ['scenario', '情景分析'],
  ['monte_carlo', '蒙特卡洛'],
  ['optimization', '组合优化'],
  ['history', '交易历史'],
]
type PortfolioSubsection = 'overview' | 'health' | 'stress' | 'scenario' | 'monte_carlo' | 'optimization' | 'history'

const alignmentLabels: Record<string, string> = {
  'Bullish alignment': '多源偏多', 'Bearish alignment': '多源偏空', 'Tight alignment': '观点集中',
  'Wide divergence': '分歧显著', Mixed: '观点分化', 'Single-source view': '单一来源', 'No sentiment mix': '暂无倾向',
}
const trendLabels: Record<string, string> = { rising: '升温', falling: '降温', stable: '平稳', bullish: '偏多', bearish: '偏空', neutral: '中性', uptrend: '上升趋势', downtrend: '下降趋势', range: '区间震荡', unknown: '数据不足' }
const macroCategoryLabels: Record<string, string> = { growth: '增长与产出', inflation: '通胀', labor: '就业', rates: '利率', consumer: '消费与工业', policy: '政策' }
const macroSummaryLabels: Record<string, string> = { growth: '增长', inflation: '通胀', labor: '就业', policy: '政策', yield_curve: '收益率曲线', consumer: '消费', composite: '综合环境' }
const healthLabels: Record<string, string> = { profitability: '盈利能力', growth: '成长质量', cashflow_quality: '现金流质量', balance_sheet_health: '资产负债', capital_efficiency: '资本效率' }
const eventLabels: Record<string, string> = { buy: '买入', sell: '卖出', dividend: '分红', commission: '佣金', withholding_tax: '预扣税', deposit: '入金', withdrawal: '出金' }

function numberText(value: unknown, digits = 2) {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '数据不足'
}

function percentText(value: unknown, ratio = false) {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? formatPercent(ratio ? number * 100 : number) : '数据不足'
}

function toneFor(value: number | null | undefined) {
  return value == null ? 'neutral' : value >= 60 ? 'positive' : value <= 40 ? 'negative' : 'neutral'
}

function compact(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '数据不足'
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function TickerPicker({ value, items, onChange, label = '选择证券' }: { value: string; items: WatchItem[]; onChange: (value: string) => void; label?: string }) {
  return <label className="dynamic-selector"><span>{label}</span><select value={value} onChange={event => onChange(event.target.value)}><option value="">{items.length ? '请选择' : '暂无自选股'}</option>{items.map(item => <option value={item.ticker} key={item.id}>{item.ticker}</option>)}</select></label>
}

export function DynamicPage() {
  const [section, setSection] = useState<DynamicSection>('news')
  const watchlist = useQuery({ queryKey: ['ios-watchlist'], queryFn: () => api<WatchItem[]>('/watchlist'), staleTime: 60_000 })
  const [ticker, setTicker] = useState('')
  const items = watchlist.data ?? []
  const currentTicker = ticker || items[0]?.ticker || ''

  return <IOSPage className="dynamic-page">
    <section className="large-title dynamic-title"><span>LIVE WORKSPACE</span><h1>动态</h1><p>新闻、舆情、宏观、技术和组合分析，独立展开查看。</p></section>
    <nav className="dynamic-tabs" aria-label="动态分区">{sectionTabs.map(([key, label]) => <button key={key} className={section === key ? 'active' : ''} aria-current={section === key ? 'page' : undefined} onClick={() => setSection(key)}>{label}</button>)}</nav>
    {section === 'news' && <NewsPanel items={items} ticker={currentTicker} setTicker={setTicker}/>}
    {section === 'sentiment' && <SentimentPanel items={items} ticker={currentTicker} setTicker={setTicker}/>}
    {section === 'macro' && <MacroPanel/>}
    {section === 'technical' && <TechnicalPanel items={items} ticker={currentTicker} setTicker={setTicker}/>}
    {section === 'portfolio' && <PortfolioAnalysisPanel/>}
  </IOSPage>
}

function NewsPanel({ items, ticker, setTicker }: { items: WatchItem[]; ticker: string; setTicker: (value: string) => void }) {
  const client = useQueryClient()
  const [scope, setScope] = useState<NewsScope>('market')
  const [topic, setTopic] = useState('')
  const market = useQuery({
    queryKey: ['ios-dynamic-news-market'], queryFn: () => api<MarketNews>('/news/market?limit=100&offset=0'), enabled: scope === 'market', staleTime: 30_000,
    refetchInterval: query => { const data = query.state.data as MarketNews | undefined; return data?.items.some(item => ['queued', 'processing'].includes(item.ai_summary_status)) ? 2_000 : false },
  })
  const company = useQuery({
    queryKey: ['ios-dynamic-news-company', ticker], queryFn: () => api<NewsItem[]>(`/news?ticker=${encodeURIComponent(ticker)}`), enabled: scope === 'company' && !!ticker, staleTime: 30_000,
    refetchInterval: query => { const data = query.state.data as NewsItem[] | undefined; return data?.some(item => ['queued', 'processing'].includes(item.ai_summary_status)) ? 2_000 : false },
  })
  const summarize = useMutation({ mutationFn: ({ id, force }: { id: number; force: boolean }) => post<NewsItem>(`/news/${id}/summarize?force=${force}`, {}), onSuccess: () => { void client.invalidateQueries({ queryKey: ['ios-dynamic-news-market'] }); void client.invalidateQueries({ queryKey: ['ios-dynamic-news-company', ticker] }) } })
  const refresh = useMutation({ mutationFn: () => post(scope === 'market' ? '/news/market/refresh' : `/news/refresh?ticker=${encodeURIComponent(ticker)}`, {}) })
  const allNews = scope === 'market' ? market.data?.items ?? [] : company.data ?? []
  const topics = useMemo(() => [...new Set(allNews.map(item => item.topic).filter((value): value is string => Boolean(value)))].sort(), [allNews])
  const visible = topic ? allNews.filter(item => item.topic === topic) : allNews
  const loading = scope === 'market' ? market.isLoading : company.isLoading
  const error = scope === 'market' ? market.isError : company.isError

  return <div className="dynamic-panel">
    <GlassCard className="dynamic-toolbar"><div className="dynamic-toolbar-row"><label className="dynamic-selector"><span>新闻范围</span><select value={scope} onChange={event => { setScope(event.target.value as NewsScope); setTopic('') }}><option value="market">市场总览</option><option value="company">个股新闻</option></select></label>{scope === 'company' ? <TickerPicker value={ticker} items={items} onChange={setTicker}/> : <label className="dynamic-selector"><span>新闻分类</span><select value={topic} onChange={event => setTopic(event.target.value)}><option value="">全部分类</option>{topics.map(item => <option key={item} value={item}>{item}</option>)}</select></label>}<button className="dynamic-refresh" onClick={() => refresh.mutate()} disabled={refresh.isPending || (scope === 'company' && !ticker)}>{refresh.isPending ? '刷新中…' : '刷新新闻'}</button></div><p className="dynamic-caption">{scope === 'market' ? `市场新闻 · ${visible.length} 条` : `${ticker || '未选择证券'} · ${visible.length} 条`}{refresh.isSuccess ? ' · 已触发后台采集' : ''}</p></GlassCard>
    {loading && <LoadingState rows={6}/>}
    {error && <StateView title="新闻暂不可用" message="新闻服务没有返回有效内容，稍后可重试。" retry={() => { void (scope === 'market' ? market.refetch() : company.refetch()) }}/>}
    {!loading && !error && visible.length === 0 && <StateView title="暂时没有新闻" message="可切换新闻范围或点击刷新重新采集。"/>}
    <div className="dynamic-news-list">{visible.map(item => <DynamicNewsCard key={item.id} item={item} sending={summarize.isPending && summarize.variables?.id === item.id} onSummarize={force => summarize.mutate({ id: item.id, force })}/>)}</div>
  </div>
}

function DynamicNewsCard({ item, sending, onSummarize }: { item: NewsItem; sending: boolean; onSummarize: (force: boolean) => void }) {
  const working = item.ai_summary_status === 'queued' || item.ai_summary_status === 'processing'
  const provider = item.provider === 'yfinance' ? 'Yahoo 财经' : item.provider || item.source || '新闻来源'
  const buttonLabel = working ? item.ai_summary_status === 'queued' ? 'AI 总结排队中…' : 'AI 总结中…' : sending ? '正在提交…' : item.ai_summary_status === 'failed' ? '重试 AI 总结' : item.ai_summary ? '重新总结' : 'AI 总结'
  return <article className="dynamic-news-card"><div className="dynamic-news-meta"><span>{provider}</span>{item.topic && <em>{item.topic}</em>}{(item.importance_score ?? 0) >= .65 && <b>重要</b>}<time>{formatDateTime(item.published_at || item.found_at)}</time></div><a href={item.url} target="_blank" rel="noreferrer"><h2>{item.translated_title || item.title}</h2></a>{item.translated_title && item.translated_title !== item.title && <p className="dynamic-news-original">{item.title}</p>}{item.summary && !item.ai_summary && <p className="dynamic-news-excerpt">{item.summary}</p>}<button className="dynamic-news-ai" disabled={working || sending} onClick={() => onSummarize(Boolean(item.ai_summary))}>{buttonLabel}</button>{item.ai_summary && <div className="dynamic-news-summary"><span>AI 研究摘要 · {item.ai_summary_model || '研究模型'}</span><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{item.ai_summary}</ReactMarkdown>{item.summary && <details><summary>查看原始来源摘要</summary><p className="dynamic-news-excerpt">{item.summary}</p></details>}</div>}{item.ai_summary_status === 'failed' && <small className="dynamic-inline-error">AI 总结失败，请点击重试。</small>}</article>
}

function SentimentPanel({ items, ticker, setTicker }: { items: WatchItem[]; ticker: string; setTicker: (value: string) => void }) {
  const [days, setDays] = useState(7)
  const query = useQuery({ queryKey: ['ios-dynamic-sentiment', ticker, days], queryFn: () => api<StockSentiment | null>(`/sentiment/${encodeURIComponent(ticker)}?days=${days}`), enabled: !!ticker, staleTime: 300_000, retry: 1 })
  const data = query.data
  const score = Math.max(0, Math.min(100, data?.average_buzz ?? 0))
  const sourceNames: Record<string, string> = { reddit: 'Reddit 社区', x: 'X 社区', news: '公开新闻', polymarket: '预测市场' }
  return <div className="dynamic-panel"><div className="dynamic-toolbar-row"><TickerPicker value={ticker} items={items} onChange={setTicker} label="观察证券"/><div className="dynamic-periods" role="tablist" aria-label="观察周期">{[7, 14, 30].map(value => <button key={value} className={days === value ? 'active' : ''} aria-selected={days === value} onClick={() => setDays(value)}>{value} 天</button>)}</div></div>{!ticker && <StateView title="还没有可观察证券" message="请先在自选股中选择一只证券。"/>}{ticker && query.isLoading && <LoadingState rows={5}/>} {ticker && query.isError && <StateView title="舆情暂不可用" message="舆情服务没有响应，稍后可重试。" retry={() => { void query.refetch() }}/>} {ticker && !query.isLoading && !query.isError && !data && <StateView title="暂无可用舆情" message="当前来源没有返回有效数据，系统不会用文字臆测倾向。" retry={() => { void query.refetch() }}/>} {data && <><GlassCard className="dynamic-sentiment-hero"><div className="dynamic-sentiment-identity"><span>多来源市场讨论</span><h2>{data.symbol}</h2><p>{data.company_name || '公司名称暂缺'} · 最近 {data.period_days} 天</p></div><div className="dynamic-sentiment-ring" style={{ '--angle': `${score * 3.6}deg` } as CSSProperties}><strong>{data.average_buzz.toFixed(1)}</strong><small>热度</small></div><div className="dynamic-sentiment-summary"><div><span>看多占比</span><b className={toneFor(data.bullish_average)}>{data.bullish_average == null ? '数据不足' : `${data.bullish_average.toFixed(1)}%`}</b></div><div><span>来源共识</span><b>{alignmentLabels[data.source_alignment] || '观点分化'}</b></div><div><span>数据覆盖</span><b>{data.available_sources} / 4 个来源</b></div></div></GlassCard><SectionHeader title="分来源观察" caption="热度、方向与提及量一并展示"/><div className="dynamic-sentiment-sources">{data.sources.map(source => { const bullish = Math.max(0, Math.min(100, source.bullish_pct ?? 0)); return <article className="dynamic-sentiment-source" key={source.source}><header><div><i>{source.source === 'polymarket' ? 'P' : source.source === 'news' ? 'N' : source.source === 'reddit' ? 'R' : 'X'}</i><strong>{source.label || sourceNames[source.source] || '数据来源'}</strong></div><StatusPill tone={source.trend === 'rising' ? 'positive' : source.trend === 'falling' ? 'negative' : 'neutral'}>{source.trend ? trendLabels[source.trend] : '趋势不足'}</StatusPill></header><div className="dynamic-sentiment-values"><div><span>热度</span><strong>{numberText(source.buzz_score, 1)}</strong></div><div><span>{source.metric_label === 'Mentions' ? '提及量' : source.metric_label === 'Trades' ? '交易数' : '讨论量'}</span><strong>{compact(source.metric_value)}</strong></div><div><span>看多</span><strong className={toneFor(source.bullish_pct)}>{source.bullish_pct == null ? '数据不足' : `${source.bullish_pct.toFixed(1)}%`}</strong></div></div><div className="dynamic-sentiment-track"><i style={{ width: `${bullish}%` }}/></div><small>{source.company_name || sourceNames[source.source] || '独立来源'} · 看多讨论比例</small></article> })}</div><SentimentBars data={data.sources}/><p className="disclaimer">舆情只反映讨论热度与倾向，不能验证事实真伪，也不代表价格走势或投资建议。</p></>}</div>
}

function SentimentBars({ data }: { data: SentimentSource[] }) {
  const max = Math.max(...data.map(item => item.buzz_score), 1)
  return <GlassCard className="dynamic-sentiment-chart"><div className="dynamic-card-heading"><div><span>横向比较</span><h3>各来源热度</h3></div><small>满分 100</small></div><div className="dynamic-sentiment-bars">{data.map(item => <div key={item.source}><span>{item.label || item.source}</span><i><b style={{ width: `${Math.max(0, Math.min(100, item.buzz_score / max * 100))}%` }}/></i><strong>{item.buzz_score.toFixed(1)}</strong></div>)}</div></GlassCard>
}

function MacroPanel() {
  const overview = useQuery({ queryKey: ['ios-dynamic-macro-overview'], queryFn: () => api<MacroOverview>('/fundamentals/macro/us/overview'), staleTime: 600_000 })
  const curve = useQuery({ queryKey: ['ios-dynamic-macro-curve'], queryFn: () => api<YieldCurve>('/fundamentals/macro/us/yield-curve'), staleTime: 600_000 })
  const data = overview.data
  return <div className="dynamic-panel"><div className="dynamic-macro-status"><span className={data?.source.configured ? 'ready' : 'warning'}/><div><strong>{data?.source.configured ? `数据源：${data.source.name}` : '宏观数据源未配置'}</strong><small>{data ? `${data.source.status_label_zh} · 最后同步 ${formatDateTime(data.last_sync_at)}` : '正在读取美国宏观数据'}</small></div><StatusPill tone={data?.source.configured ? 'positive' : 'warning'}>{data?.source.configured ? '已连接' : '数据不足'}</StatusPill></div>{overview.isLoading && <LoadingState rows={7}/>} {overview.isError && <StateView title="美国宏观暂不可用" message="宏观指标接口没有返回有效数据，稍后可重试。" retry={() => { void overview.refetch() }}/>} {data && <><div className="dynamic-macro-summary">{Object.entries(data.summaries).map(([key, summary]) => <article className={`macro-tone-${summary.tone}`} key={key}><span>{macroSummaryLabels[key] || '综合指标'}</span><strong>{summary.label_zh}</strong><small>置信度 {Math.round(summary.confidence * 100)}%</small></article>)}</div><SectionHeader title="美国宏观指标" caption={`最新观察 ${data.latest_observation_date || '数据不足'} · 卡片保留桌面端核心字段`}/><div className="dynamic-macro-grid">{data.cards.map(card => <MacroCardView key={card.series_key} card={card}/>)}</div><YieldCurveView data={curve.data} analysis={data.curve_analysis}/><p className="disclaimer">{data.disclaimer || '宏观数据用于背景判断，不构成投资建议。'}</p></>}</div>
}

function MacroCardView({ card }: { card: MacroCard }) {
  const values = (card.sparkline || []).map(item => item.value).filter((value): value is number => value != null && Number.isFinite(value))
  const direction = card.trend.direction
  return <article className="dynamic-macro-card"><header><div><span>{macroCategoryLabels[card.category] || '宏观指标'}</span><h3>{card.display_name_zh}</h3></div><StatusPill tone={direction === 'rising' ? 'positive' : direction === 'falling' ? 'negative' : 'neutral'}>{direction === 'rising' ? '上升' : direction === 'falling' ? '下降' : direction === 'stable' ? '稳定' : '数据不足'}</StatusPill></header><p>{card.description_zh || '指标说明暂缺。'}</p><div className="dynamic-macro-value"><strong>{card.latest?.value == null ? '数据不足' : numberText(card.latest.value, 3)}</strong><span>{card.unit || '原始单位'} · {card.frequency || '频率未知'}</span></div><MacroSparkline values={values}/><footer><span>当前影响</span><b>{card.current_impact?.label_zh || '数据不足'}</b><small>{card.freshness?.label_zh || '数据新鲜度未知'}</small></footer></article>
}

function MacroSparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="dynamic-chart-empty">历史数据不足</div>
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${42 - ((value - min) / span) * 34}`).join(' ')
  return <svg className="dynamic-sparkline" viewBox="0 0 100 48" preserveAspectRatio="none" role="img" aria-label="宏观指标历史趋势"><polyline points={points}/></svg>
}

function YieldCurveView({ data, analysis }: { data: YieldCurve | undefined; analysis: MacroOverview['curve_analysis'] }) {
  const current = data?.curves.find(item => item.label === 'current') || data?.curves[0]
  const valid = current?.points.filter(point => point.value != null) || []
  if (valid.length < 2) return <GlassCard className="dynamic-yield-card"><SectionHeader title="美国国债收益率曲线" caption="当前期限数据不足，系统不会用直线补齐。"/><div className="dynamic-chart-empty">收益率曲线暂不可用</div></GlassCard>
  const min = Math.min(...valid.map(point => point.value ?? 0)); const max = Math.max(...valid.map(point => point.value ?? 0)); const span = max - min || 1
  const points = current!.points.map((point, index) => `${(index / Math.max(current!.points.length - 1, 1)) * 100},${112 - (((point.value ?? min) - min) / span) * 88}`).join(' ')
  return <GlassCard className="dynamic-yield-card"><div className="dynamic-card-heading"><div><span>利率市场</span><h3>美国国债收益率曲线</h3></div><StatusPill tone="neutral">{analysis.label_zh}</StatusPill></div><svg className="dynamic-yield-chart" viewBox="0 0 100 125" preserveAspectRatio="none" role="img" aria-label="美国国债收益率曲线"><polyline points={points}/></svg><div className="dynamic-yield-labels">{current!.points.map(point => <span key={point.maturity}><b>{point.maturity}</b><small>{point.value == null ? '数据不足' : `${point.value.toFixed(2)}%`}</small></span>)}</div><div className="dynamic-yield-spreads"><span>10年 − 2年 <b>{analysis.spread_10y_2y == null ? '数据不足' : `${analysis.spread_10y_2y.toFixed(2)} 个百分点`}</b></span><span>10年 − 3个月 <b>{analysis.spread_10y_3m == null ? '数据不足' : `${analysis.spread_10y_3m.toFixed(2)} 个百分点`}</b></span></div></GlassCard>
}

function TechnicalPanel({ items, ticker, setTicker }: { items: WatchItem[]; ticker: string; setTicker: (value: string) => void }) {
  const list = useQuery({ queryKey: ['ios-dynamic-technical'], queryFn: () => api<TechnicalItem[]>('/technical-analysis'), staleTime: 60_000 })
  const selected = ticker || list.data?.[0]?.symbol || ''
  const detail = useQuery({ queryKey: ['ios-dynamic-technical-detail', selected], queryFn: () => api<TechnicalItem>(`/technical-analysis/${encodeURIComponent(selected)}`), enabled: !!selected, staleTime: 60_000 })
  const current = detail.data
  const analysis = current?.analysis
  return <div className="dynamic-panel"><div className="dynamic-toolbar-row"><TickerPicker value={selected} items={items} onChange={setTicker} label="观察证券"/><span className="dynamic-data-note">静态缓存图表 · 本地指标</span></div>{!selected && <StateView title="还没有可分析证券" message="请先在自选股中选择证券。"/>}{selected && detail.isLoading && <LoadingState rows={6}/>} {selected && detail.isError && <StateView title="技术分析暂不可用" message="技术分析缓存没有返回有效内容，稍后可重试。" retry={() => { void detail.refetch() }}/>} {current && analysis && <><GlassCard className="dynamic-tech-hero"><div><span>{current.company_name || '公司名称暂缺'}</span><h2>{current.symbol}</h2><p>数据截至 {current.data_through || '数据不足'}{current.stale ? ' · 数据可能已过期' : ''}</p></div><div><strong>{formatMoney(analysis.latestClose, 'USD')}</strong><StatusPill tone={analysis.weeklyTrend === 'uptrend' || analysis.weeklyTrend === 'bullish' ? 'positive' : analysis.weeklyTrend === 'downtrend' || analysis.weeklyTrend === 'bearish' ? 'negative' : 'neutral'}>{trendLabels[analysis.weeklyTrend] || '数据不足'}</StatusPill></div></GlassCard><StaticTechnicalChart item={current}/><SectionHeader title="关键指标" caption="保留电脑端指标，改为适合手机阅读的指标卡"/><div className="dynamic-tech-metrics">{[['rsi14', 'RSI 14'], ['macdHistogram', 'MACD 柱'], ['atr14', 'ATR 14'], ['ma20', '20 日均线'], ['ma50', '50 日均线'], ['ema20', '20 日指数均线']].map(([key, label]) => { const value = analysis.indicators[key]; return <div key={key}><span>{label}</span><strong>{value == null ? '数据不足' : numberText(value, 2)}</strong><small>{key === 'macdHistogram' ? value == null ? '数据不足' : value > 0 ? '动能偏多' : value < 0 ? '动能偏空' : '动能中性' : key === 'rsi14' && value != null ? value >= 70 ? '偏热' : value <= 30 ? '偏冷' : '中性区间' : '后端缓存计算'}</small></div> })}</div><LevelSummary analysis={analysis}/>{(analysis.fibonacci.available || analysis.trendLines.length > 0 || analysis.omittedReasons.length > 0) && <GlassCard className="dynamic-tech-extra"><div className="dynamic-card-heading"><div><span>结构识别</span><h3>斐波那契与趋势线</h3></div></div>{analysis.fibonacci.available ? <p>当前为{analysis.fibonacci.direction === 'up' ? '上升' : '下降'}主摆动，回撤位已计算。</p> : <p>{analysis.fibonacci.omissionReason || '斐波那契数据不足。'}</p>}{analysis.trendLines.map(line => <div className="dynamic-tech-line" key={line.type}><span>{line.type.includes('support') ? '上升支撑线' : '下降阻力线'}</span><b>{formatMoney(line.projectedPrice, 'USD')}</b><small>置信度 {Math.round(line.confidence * 100)}%</small></div>)}{analysis.omittedReasons.slice(0, 3).map(reason => <small className="dynamic-muted" key={reason}>{reason}</small>)}</GlassCard>}{!analysis && <StateView title="分析结果不足" message="历史数据或指标仍在同步，系统不会补造点位。"/>}</>}
    {current && !analysis && <StateView title="技术分析正在准备" message={current.chart_data_reason || '历史数据或分析正在后台同步。'}/>}
  </div>
}

function StaticTechnicalChart({ item }: { item: TechnicalItem }) {
  const [open, setOpen] = useState(false)
  const candles = item.weekly?.length ? item.weekly : item.chart_series?.week?.candles || []
  const values = candles.map(candle => candle.close).filter((value): value is number => value != null && Number.isFinite(value))
  const min = values.length ? Math.min(...values) : 0; const max = values.length ? Math.max(...values) : 1; const span = max - min || 1
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${112 - ((value - min) / span) * 88}`).join(' ')
  const chart = item.chart_url ? <img src={item.chart_url} alt={`${item.symbol} 技术分析静态图`}/> : values.length > 1 ? <svg viewBox="0 0 100 125" preserveAspectRatio="none" role="img" aria-label={`${item.symbol} 历史价格趋势`}><polyline points={points}/></svg> : <div className="dynamic-chart-empty">静态图暂不可用，历史点位不足。</div>
  return <div className="dynamic-tech-chart-anchor"><button className="dynamic-tech-chart-trigger" onClick={() => setOpen(true)}><span>技术图表</span><strong>点击展开静态图 <b>↗</b></strong></button><div className="dynamic-tech-chart-preview">{chart}</div><p>图表使用本地缓存静态图，不加载 TradingView 开源组件。</p>{open && <div className="dynamic-tech-chart-window" role="dialog" aria-label="静态技术分析图"><header><div><span>TECHNICAL SNAPSHOT</span><strong>{item.symbol} · 静态技术图</strong></div><button onClick={() => setOpen(false)} aria-label="关闭技术图">×</button></header><div className="dynamic-tech-chart-scroll">{chart}<small>{item.data_through ? `数据截至 ${item.data_through}` : '图表数据时间未知'} · 指标和点位见下方</small></div></div>}</div>
}

function LevelSummary({ analysis }: { analysis: TechnicalAnalysis }) {
  const levels = [...analysis.supportZones.map(zone => ({ ...zone, type: 'support' })), ...analysis.resistanceZones.map(zone => ({ ...zone, type: 'resistance' }))].sort((a, b) => Math.abs(a.distancePercent ?? 0) - Math.abs(b.distancePercent ?? 0)).slice(0, 6)
  const maxDistance = Math.max(...levels.map(zone => Math.abs(zone.distancePercent ?? 0)), 1)
  return <GlassCard className="dynamic-tech-levels"><div className="dynamic-card-heading"><div><span>重要点位</span><h3>支撑与阻力区域</h3></div><small>按距离现价排序</small></div>{levels.length ? <div className="dynamic-level-list">{levels.map((zone, index) => <div key={`${zone.type}-${zone.center}-${index}`}><div><b className={zone.type === 'support' ? 'gain' : 'loss'}>{zone.type === 'support' ? '支撑' : '阻力'}</b><strong>{zone.low.toFixed(2)} – {zone.high.toFixed(2)}</strong><span>{zone.distancePercent == null ? '距离不足' : `${zone.distancePercent >= 0 ? '+' : ''}${zone.distancePercent.toFixed(1)}%`}</span></div><i><b className={zone.type === 'support' ? 'support' : 'resistance'} style={{ width: `${Math.min(100, Math.abs(zone.distancePercent ?? 0) / maxDistance * 100)}%` }}/></i><small>强度 {zone.strength == null ? '数据不足' : `${Math.round(zone.strength * 100)} 分`} · 触及 {zone.touchCount == null ? '数据不足' : `${zone.touchCount} 次`}</small></div>)}</div> : <div className="dynamic-chart-empty">暂无已确认的支撑或阻力区域。</div>}</GlassCard>
}

function PortfolioAnalysisPanel() {
  const client = useQueryClient()
  const [subsection, setSubsection] = useState<PortfolioSubsection>('overview')
  const summary = useQuery({ queryKey: ['ios-dynamic-portfolio-summary'], queryFn: () => api<PortfolioSummary>('/portfolio/summary'), staleTime: 30_000 })
  const health = useQuery({ queryKey: ['ios-dynamic-portfolio-health'], queryFn: () => api<PortfolioHealth>('/portfolio/health'), enabled: subsection === 'health', staleTime: 60_000 })
  const history = useQuery({ queryKey: ['ios-dynamic-analysis-history'], queryFn: () => api<{ runs: AnalysisRun[] }>('/portfolio/analysis/history'), enabled: subsection !== 'overview' && subsection !== 'health' && subsection !== 'history', staleTime: 30_000 })
  const transactions = useQuery({ queryKey: ['ios-dynamic-transactions'], queryFn: () => api<LedgerEvent[]>('/portfolio/transactions'), enabled: subsection === 'history', staleTime: 30_000 })
  const [jobId, setJobId] = useState<number | null>(null)
  const [runningType, setRunningType] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [params, setParams] = useState({ scenarioCode: 'recession', marketShock: -20, rateBp: 100, horizon: 1, simulations: 1000, contribution: 0 })
  const job = useQuery({ queryKey: ['ios-dynamic-analysis-job', jobId], queryFn: () => api<AnalysisJob>(`/portfolio/analysis/jobs/${jobId}`), enabled: jobId != null, refetchInterval: query => ['pending', 'running'].includes((query.state.data as AnalysisJob | undefined)?.status || '') ? 2_000 : false })
  const launch = useMutation({ mutationFn: async ({ type, body }: { type: PortfolioSubsection; body: Record<string, unknown> }) => { const path = type === 'stress' ? '/portfolio/analysis/stress-test' : type === 'scenario' ? '/portfolio/analysis/scenario-analysis' : type === 'monte_carlo' ? '/portfolio/analysis/monte-carlo' : '/portfolio/analysis/optimize'; return post<{ job_id: number }>(path, body) }, onMutate: ({ type }) => setRunningType(type), onSuccess: result => setJobId(result.job_id), onSettled: () => { void client.invalidateQueries({ queryKey: ['ios-dynamic-analysis-history'] }) } })
  useEffect(() => { if (job.data?.status === 'completed') { setRunningType(null); void client.invalidateQueries({ queryKey: ['ios-dynamic-analysis-history'] }) } if (job.data?.status === 'failed') setRunningType(null) }, [client, job.data?.status])

  const portfolioId = summary.data?.portfolio_id
  const analysisType = subsection === 'monte_carlo' ? 'monte_carlo' : subsection === 'stress' ? 'stress_test' : subsection === 'scenario' ? 'scenario_analysis' : subsection === 'optimization' ? 'optimization' : ''
  const saved = history.data?.runs.find(run => run.analysis_type === analysisType && run.status === 'completed')
  const live = job.data?.status === 'completed' && runningType === subsection ? job.data.result : null
  const result = live || saved?.result || null
  const run = () => {
    if (!portfolioId || subsection === 'overview' || subsection === 'health' || subsection === 'history') return
    const base = { portfolio_id: portfolioId }
    if (subsection === 'stress') launch.mutate({ type: subsection, body: { ...base, mode: 'proxy_scenario', scenario_code: params.scenarioCode, market_shock: params.marketShock / 100, nasdaq_shock: params.marketShock / 100, sector_shocks: {}, style_shocks: {}, interest_rate_change_bp: params.rateBp, currency_shocks: {}, volatility_change: 0, use_fundamental_modifiers: true } })
    if (subsection === 'scenario') launch.mutate({ type: subsection, body: { ...base, scenario_code: params.scenarioCode, use_fundamental_modifiers: true } })
    if (subsection === 'monte_carlo') launch.mutate({ type: subsection, body: { ...base, horizon_years: params.horizon, simulations: params.simulations, method: 'block_bootstrap', block_length: 10, rebalance_frequency: 'quarterly', monthly_contribution: params.contribution, target_value: null, confidence_levels: [.8, .95], random_seed: 42, force_refresh: true } })
    if (subsection === 'optimization') launch.mutate({ type: subsection, body: { ...base, objective: 'balanced', covariance_method: 'ledoit_wolf', constraints: { only_current_positions: true } } })
  }
  const configurable = ['health', 'stress', 'scenario', 'monte_carlo', 'optimization'].includes(subsection)
  return <div className="dynamic-panel dynamic-portfolio-panel"><nav className="dynamic-portfolio-tabs" aria-label="组合分析子分区">{portfolioTabs.map(([key, label]) => <button key={key} className={subsection === key ? 'active' : ''} onClick={() => setSubsection(key)}>{label}</button>)}</nav>{summary.isLoading && <LoadingState rows={5}/>} {summary.isError && <StateView title="组合资料暂不可用" message="组合接口没有返回有效数据，稍后可重试。" retry={() => { void summary.refetch() }}/>} {subsection === 'overview' && summary.data && <PortfolioCenter data={summary.data}/>} {subsection === 'health' && <HealthPanel query={health}/>} {subsection === 'history' && <HistoryPanel query={transactions}/>} {!['overview', 'health', 'history'].includes(subsection) && <AnalysisPanel type={subsection} result={result} saved={saved} running={Boolean(runningType === subsection || launch.isPending)} error={job.data?.status === 'failed' ? job.data.error_message : launch.error ? '分析任务创建失败，请稍后重试。' : null} onRun={run}/>} {configurable && <button className="analysis-settings-fab" onClick={() => setSettingsOpen(true)} aria-label="打开分析参数">⚙<span>参数</span></button>} {settingsOpen && <AnalysisSettings subsection={subsection} params={params} setParams={setParams} close={() => setSettingsOpen(false)}/>}</div>
}

function AnalysisSettings({ subsection, params, setParams, close }: { subsection: PortfolioSubsection; params: { scenarioCode: string; marketShock: number; rateBp: number; horizon: number; simulations: number; contribution: number }; setParams: (value: { scenarioCode: string; marketShock: number; rateBp: number; horizon: number; simulations: number; contribution: number }) => void; close: () => void }) {
  const field = (key: keyof typeof params, value: string) => setParams({ ...params, [key]: key === 'scenarioCode' ? value : Number(value) })
  return <><button className="analysis-settings-scrim" onClick={close} aria-label="关闭参数设置"/><section className="analysis-settings-sheet" role="dialog" aria-modal="true" aria-label="分析参数设置"><header><div><span>ANALYSIS PARAMETERS</span><h2>参数设置</h2></div><button onClick={close}>完成</button></header><div className="analysis-settings-fields">
    {subsection === 'health' && <p>风险体检使用当前持仓、最新已存估值、基本面与 SEC 资料；评分规则保持客观且不会由手机端参数改写。</p>}
    {['stress', 'scenario'].includes(subsection) && <label>情景<select value={params.scenarioCode} onChange={event => field('scenarioCode', event.target.value)}><option value="recession">经济衰退</option><option value="stagflation">滞胀</option><option value="soft_landing">软着陆</option><option value="rate_shock">利率冲击</option></select></label>}
    {subsection === 'stress' && <><label>市场冲击（%）<input type="number" inputMode="decimal" value={params.marketShock} onChange={event => field('marketShock', event.target.value)}/></label><label>利率变化（基点）<input type="number" inputMode="decimal" value={params.rateBp} onChange={event => field('rateBp', event.target.value)}/></label></>}
    {subsection === 'monte_carlo' && <><label>模拟期限（年）<input type="number" min="1" max="30" value={params.horizon} onChange={event => field('horizon', event.target.value)}/></label><label>模拟次数<input type="number" min="500" max="20000" step="500" value={params.simulations} onChange={event => field('simulations', event.target.value)}/></label><label>每月投入<input type="number" inputMode="decimal" min="0" value={params.contribution} onChange={event => field('contribution', event.target.value)}/></label></>}
    {subsection === 'optimization' && <p>组合优化沿用桌面端的平衡目标、Ledoit-Wolf 协方差和仅限当前持仓约束。</p>}
  </div></section></>
}

function PortfolioCenter({ data }: { data: PortfolioSummary }) {
  const daily = data.latest_daily_return
  return <><GlassCard className="dynamic-portfolio-hero"><div><span>组合中心</span><h2>{formatMoney(data.net_asset_value ?? data.total_market_value, data.base_currency)}</h2><p>账户净资产 / 当前估值</p></div><StatusPill tone={daily == null ? 'neutral' : daily >= 0 ? 'positive' : 'negative'}>{formatPercent(daily)}</StatusPill></GlassCard><div className="dynamic-portfolio-metrics"><div><span>投入市值</span><strong>{formatMoney(data.invested_market_value ?? data.total_market_value, data.base_currency)}</strong></div><div><span>浮动盈亏</span><strong className={(data.total_unrealized_pnl ?? 0) >= 0 ? 'gain' : 'loss'}>{formatMoney(data.total_unrealized_pnl, data.base_currency)}</strong></div><div><span>持仓数量</span><strong>{data.position_count} 个</strong></div><div><span>现金</span><strong>{formatMoney(data.cash, data.base_currency)}</strong></div></div><SectionHeader title="组合权重" caption="当前持仓按市值排序"/><div className="dynamic-portfolio-weights">{[...data.positions].sort((a, b) => (b.portfolio_weight ?? 0) - (a.portfolio_weight ?? 0)).map(position => <PositionWeight key={position.symbol} position={position}/>)}</div>{(data.has_unpriced_positions || data.has_unconverted_positions) && <p className="dynamic-warning">部分持仓因价格或汇率不足未计入完整汇总。</p>}</>
}

function PositionWeight({ position }: { position: Position }) {
  const weight = Math.max(0, Math.min(100, position.portfolio_weight ?? 0))
  return <div className="dynamic-position-weight"><div><b>{position.symbol}</b><span>{formatMoney(position.market_value, position.currency)}</span><strong>{formatPercent(position.portfolio_weight).replace('+', '')}</strong></div><i><b style={{ width: `${weight}%` }}/></i></div>
}

function HealthPanel({ query }: { query: ReturnType<typeof useQuery<PortfolioHealth>> }) {
  const data = query.data
  if (query.isLoading) return <LoadingState rows={8}/>
  if (query.isError || !data) return <StateView title="风险体检暂不可用" message="健康检查需要组合资料和已同步的分析数据。" retry={() => { void query.refetch() }}/>
  const metrics = [['组合健康', data.health.score, data.health.grade], ['基本面质量', data.fundamental_quality.score, data.fundamental_quality.grade], ['估值风险', data.valuation_risk.score, data.valuation_risk.grade], ['集中度风险', data.concentration.risk_score, data.concentration.available ? '可用' : '数据不足'], ['SEC 风险', data.sec_risk.score, data.sec_risk.grade]] as [string, number | null, string][]
  return <><div className="dynamic-health-score-grid">{metrics.map(([label, score, grade]) => <div key={label}><span>{label}</span><strong className={score == null ? '' : score >= 70 ? 'gain' : score <= 40 ? 'loss' : ''}>{score == null ? '数据不足' : score.toFixed(0)}</strong><small>{grade}</small></div>)}</div><GlassCard className="dynamic-health-card"><div className="dynamic-card-heading"><div><span>质量分析</span><h3>基本面质量分项</h3></div><small>覆盖 {data.fundamental_quality.coverage_weight.toFixed(0)}%</small></div><div className="dynamic-health-bars">{Object.entries(data.fundamental_quality.subscores).map(([key, item]) => <div key={key}><div><b>{healthLabels[key] || '质量分项'}</b><span>{item.score == null ? '数据不足' : item.score.toFixed(0)}</span></div><i><b style={{ width: `${Math.max(0, Math.min(100, item.score ?? 0))}%` }}/></i></div>)}</div></GlassCard><GlassCard className="dynamic-health-card"><div className="dynamic-card-heading"><div><span>配置结构</span><h3>集中度与行业暴露</h3></div><small>{data.base_currency}</small></div>{data.concentration.available ? <><div className="dynamic-health-stats"><span>最大持仓 <b>{data.concentration.largest_position_weight == null ? '数据不足' : `${data.concentration.largest_position_weight.toFixed(1)}%`}</b></span><span>前三大 <b>{data.concentration.top_three_weight == null ? '数据不足' : `${data.concentration.top_three_weight.toFixed(1)}%`}</b></span><span>HHI <b>{data.concentration.hhi_scaled == null ? '数据不足' : data.concentration.hhi_scaled.toFixed(0)}</b></span></div><div className="dynamic-sector-list">{data.concentration.sector_weights.map(row => <div key={row.sector}><div><b>{row.sector}</b><span>{row.weight.toFixed(1)}%</span></div><i><b style={{ width: `${Math.min(100, row.weight)}%` }}/></i></div>)}</div></> : <div className="dynamic-chart-empty">{data.concentration.reason || '配置数据不足'}</div>}</GlassCard><div className="dynamic-coverage-grid">{(['price', 'fundamental', 'valuation', 'sec'] as const).map(key => { const row = data.coverage[key]; const labels: Record<string, string> = { price: '价格', fundamental: '基本面', valuation: '估值', sec: 'SEC' }; return <div key={key}><span>{labels[key]}</span><strong>{row.covered_weight.toFixed(0)}%</strong><small>{row.freshness === 'fresh' ? '数据新鲜' : row.freshness === 'mixed' ? '部分过期' : row.freshness === 'stale' ? '数据已过期' : '暂无数据'}</small></div> })}</div><GlassCard className="dynamic-findings"><div className="dynamic-card-heading"><div><span>规则结论</span><h3>需要关注的事项</h3></div></div>{data.findings.slice(0, 5).map((finding, index) => <article key={`${finding.title}-${index}`}><StatusPill tone={finding.severity === 'high' ? 'negative' : finding.severity === 'warning' ? 'warning' : 'neutral'}>{finding.severity === 'high' ? '高关注' : finding.severity === 'warning' ? '需留意' : '提示'}</StatusPill><div><b>{finding.title}</b><p>{finding.message}</p><small>{finding.affected_symbols.join('、') || '组合层面'}</small></div></article>)}{!data.findings.length && <p className="dynamic-muted">当前没有需要突出显示的规则结论。</p>}</GlassCard><p className="disclaimer">健康评分只描述当前组合的资料覆盖与风险结构，不构成投资建议。</p></>
}

function HistoryPanel({ query }: { query: ReturnType<typeof useQuery<LedgerEvent[]>> }) {
  if (query.isLoading) return <LoadingState rows={7}/>
  if (query.isError) return <StateView title="交易历史暂不可用" message="暂时无法读取账户交易事实。" retry={() => { void query.refetch() }}/>
  const events = query.data ?? []
  return <><SectionHeader title="交易历史" caption={`共 ${events.length} 条账户事件 · 客观事实优先`}/>{events.length ? <div className="dynamic-transaction-list">{events.map(event => <article className="dynamic-transaction" key={event.event_id}><div><StatusPill tone={event.event_type === 'sell' ? 'negative' : event.event_type === 'buy' ? 'positive' : 'neutral'}>{eventLabels[event.event_type] || '账户事件'}</StatusPill><b>{event.symbol || '账户'}</b><time>{formatDateTime(event.occurred_at)}</time></div><div><span>{event.quantity == null ? '数量不足' : `${numberText(event.quantity, 4)} 股`}</span><span>{event.price == null ? '价格不足' : formatMoney(event.price, event.currency || 'USD')}</span><strong>{event.net_amount == null && event.gross_amount == null ? '金额不足' : formatMoney(event.net_amount ?? event.gross_amount, event.currency || 'USD')}</strong></div><small>{event.is_authoritative ? 'IBKR 客观事实' : '项目交易账本'}{event.note ? ` · ${event.note}` : ''}</small></article>)}</div> : <StateView title="暂无交易历史" message="同步 IBKR 或新增交易记录后，这里会显示账户事件。"/>}</>
}

function AnalysisPanel({ type, result, saved, running, error, onRun }: { type: PortfolioSubsection; result: Record<string, unknown> | null; saved: AnalysisRun | undefined; running: boolean; error: string | null; onRun: () => void }) {
  const titles: Record<string, string> = { stress: '压力测试', scenario: '情景分析', monte_carlo: '蒙特卡洛', optimization: '组合优化' }
  const subtitle: Record<string, string> = { stress: '模拟衰退与利率冲击下的组合损失贡献。', scenario: '比较预设宏观情景对组合的影响。', monte_carlo: '用历史联合分布估计未来组合价值区间。', optimization: '在现实约束下比较当前与目标配置。' }
  return <><GlassCard className="dynamic-analysis-toolbar"><div><span>组合分析</span><h2>{titles[type]}</h2><p>{subtitle[type]}</p></div><button className="primary-button" onClick={onRun} disabled={running}>{running ? '计算中…' : result ? '重新运行' : '运行分析'}</button></GlassCard>{saved && !running && <p className="dynamic-cache-note">已展示最近一次成功结果 · {formatDateTime(saved.completed_at || saved.created_at)}</p>}{running && <div className="dynamic-analysis-running"><i/>后台正在计算，页面会自动刷新结果。</div>}{error && <p className="dynamic-inline-error">{error}</p>}{!running && !result && <StateView title="还没有可用结果" message="点击上方按钮运行一次分析；没有结果时不会用示例数据填充。"/>}{result && <AnalysisResult type={type} result={result}/>}<p className="disclaimer">分析结果基于历史数据、统计模型和当前设定假设，不构成投资建议；历史表现和模拟结果不代表未来收益。</p></>
}

function AnalysisResult({ type, result }: { type: PortfolioSubsection; result: Record<string, unknown> }) {
  const get = (key: string) => result[key]
  if (type === 'monte_carlo') { const percentile = (get('terminal_value_percentiles') || {}) as Record<string, number>; const fan = Array.isArray(get('fan_chart')) ? get('fan_chart') as { p5: number; p25: number; p50: number; p75: number; p95: number }[] : []; return <><div className="dynamic-result-metrics"><Metric label="终值中位数" value={percentile.p50 == null ? '数据不足' : formatMoney(percentile.p50, 'USD')}/><Metric label="80% 概率区间" value={percentile.p10 == null || percentile.p90 == null ? '数据不足' : `${formatMoney(percentile.p10, 'USD')} – ${formatMoney(percentile.p90, 'USD')}`}/><Metric label="亏损概率" value={percentText(get('probability_of_loss'), true)}/><Metric label="最大回撤中位数" value={percentText((get('max_drawdown') as Record<string, unknown> | undefined)?.median, true)}/></div>{fan.length > 1 && <ProbabilityFan data={fan}/>}<ResultWarnings result={result}/></> }
  if (type === 'optimization') return <OptimizationResult result={result}/>
  const assetRows = Array.isArray(get('asset_results')) ? get('asset_results') as Record<string, unknown>[] : []
  const metrics = [['组合影响', get('portfolio_return') ?? get('portfolio_loss_contribution') ?? get('portfolio_loss')], ['真实行情资产', get('actual_asset_count')], ['代理估算资产', get('proxy_asset_count')], ['数据质量', get('data_quality') || '数据不足']] as [string, unknown][]
  return <><div className="dynamic-result-metrics">{metrics.map(([label, value]) => <Metric key={label} label={label} value={typeof value === 'number' && Math.abs(value) <= 1 ? percentText(value, true) : numberText(value)}/>)}</div>{assetRows.length > 0 && <GlassCard className="dynamic-result-bars"><div className="dynamic-card-heading"><div><span>结果拆分</span><h3>各持仓影响</h3></div></div>{assetRows.slice(0, 8).map((row, index) => { const value = Number(row.portfolio_loss_contribution ?? row.contribution ?? row.return ?? 0); const max = Math.max(...assetRows.map(item => Math.abs(Number(item.portfolio_loss_contribution ?? item.contribution ?? item.return ?? 0))), .001); return <div key={`${String(row.symbol || row.sector || '资产')}-${index}`}><span>{String(row.symbol || row.sector || '资产')}</span><i><b className={value >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.min(100, Math.abs(value) / max * 100)}%` }}/></i><strong>{Math.abs(value) <= 1 ? percentText(value, true) : numberText(value)}</strong></div> })}</GlassCard>}<ResultWarnings result={result}/></>
}

function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div> }

function ProbabilityFan({ data }: { data: { p5: number; p25: number; p50: number; p75: number; p95: number }[] }) {
  const all = data.flatMap(item => [item.p5, item.p95]); const min = Math.min(...all); const max = Math.max(...all); const span = max - min || 1
  const points = (key: 'p5' | 'p25' | 'p50' | 'p75' | 'p95') => data.map((item, index) => `${(index / Math.max(data.length - 1, 1)) * 100},${112 - ((item[key] - min) / span) * 92}`).join(' ')
  return <GlassCard className="dynamic-probability-chart"><div className="dynamic-card-heading"><div><span>模拟路径</span><h3>组合价值概率区间</h3></div></div><svg viewBox="0 0 100 125" preserveAspectRatio="none" role="img" aria-label="组合价值概率区间"><polygon points={`${points('p95')} ${points('p5').split(' ').reverse().join(' ')}`} className="fan-wide"/><polygon points={`${points('p75')} ${points('p25').split(' ').reverse().join(' ')}`} className="fan-mid"/><polyline points={points('p50')} className="fan-line"/></svg><div className="dynamic-chart-legend"><span><i className="wide"/>95% 区间</span><span><i className="mid"/>50% 区间</span><span><i className="median"/>中位数</span></div></GlassCard>
}

function OptimizationResult({ result }: { result: Record<string, unknown> }) {
  const changes = Array.isArray(result.weight_changes) ? result.weight_changes as Record<string, unknown>[] : []
  const metrics = (result.optimized_metrics || {}) as Record<string, number | null>
  return <><div className="dynamic-result-metrics"><Metric label="换手率" value={percentText(result.turnover, true)}/><Metric label="预计交易项" value={numberText(result.estimated_trade_count, 0)}/><Metric label="预计交易金额" value={formatMoney(typeof result.estimated_trade_amount === 'number' ? result.estimated_trade_amount : null, 'USD')}/><Metric label="优化后夏普" value={metrics.sharpe_ratio == null ? '数据不足' : metrics.sharpe_ratio.toFixed(2)}/></div><GlassCard className="dynamic-result-bars"><div className="dynamic-card-heading"><div><span>配置变化</span><h3>当前权重 → 目标权重</h3></div></div>{changes.slice(0, 10).map((row, index) => { const current = Number(row.current_weight || 0); const target = Number(row.target_weight || 0); return <div key={`${String(row.symbol)}-${index}`}><span>{String(row.symbol || '资产')}</span><i><b className="current" style={{ width: `${Math.max(0, Math.min(100, current * 100))}%` }}/><em style={{ width: `${Math.max(0, Math.min(100, target * 100))}%` }}/></i><strong>{percentText(current, true)} → {percentText(target, true)}</strong></div> })}</GlassCard></>
}

function ResultWarnings({ result }: { result: Record<string, unknown> }) { const warnings = Array.isArray(result.warnings) ? result.warnings.filter((item): item is string => typeof item === 'string') : []; return warnings.length ? <div className="dynamic-result-warnings">{warnings.slice(0, 4).map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}</div> : null }
