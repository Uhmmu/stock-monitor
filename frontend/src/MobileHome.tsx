import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { Sheet } from './Sheet'
import {
  PortfolioHealthView,
  PortfolioSummary,
  PortfolioHealth,
  PersonalizedInterpretation,
  PositionView,
} from './Portfolio'
import { StressTestView, ScenarioAnalysisView } from './PortfolioScenarios'
import { MonteCarloView } from './PortfolioMonteCarlo'
import { PortfolioOptimizationView } from './PortfolioOptimization'
import { PortfolioAnalysisHistory } from './PortfolioAnalysisHistory'
import { PortfolioRiskAnalysis } from './PortfolioAnalysis'
import './mobile-home.css'

type MobileIndexQuote = {
  symbol: string
  name: string
  price: number | null
  previous_close: number | null
  change_points: number | null
  change_percent: number | null
}

type MobileIndices = { indices: MobileIndexQuote[]; market: { is_open: boolean; checked_at: string } }
type MobileAlert = { id: number; ticker: string; period: string; change_percent: number; triggered_at: string }
type TradeLog = {
  id: number
  trade_date: string
  ticker: string | null
  direction: string | null
  quantity: number | null
  price: number | null
  status: 'draft' | 'published'
  source_type: 'manual' | 'ibkr_sync'
  objective_facts: Record<string, unknown>
  created_at: string
}

type TechnicalSnapshot = {
  symbol: string
  status: string
  company_name: string | null
  chart_url: string | null
  data_through?: string
  stale?: boolean
  chart_data_status?: 'ready' | 'insufficient'
  weekly?: { time: string; open: number; high: number; low: number; close: number; volume: number }[]
  moving_averages?: { ma20: { time: string; value: number }[]; ma50: { time: string; value: number }[] }
  analysis?: {
    latestClose: number
    weeklyTrend: string
    nearestSupport: { low: number; high: number; center: number } | null
    nearestResistance: { low: number; high: number; center: number } | null
    indicators: Record<string, number | null>
    historicalCausalHeatmap?: {
      currentLevels?: { source: string; price: number; role: string; distancePercent: number }[]
    }
  }
}

type MobileHomeProps = {
  username: string
  indices: MobileIndices | undefined
  alerts: MobileAlert[] | undefined
  demoMode?: boolean
  onOpenTab: (tab: string, symbol?: string, query?: string) => void
}

type AnalysisTab = 'overview' | 'health' | 'stress' | 'scenario' | 'monte-carlo' | 'optimization' | 'history'

const demoPositions: PositionView[] = [
  {
    symbol: 'AAPL', security_id: null, total_quantity: 18, average_cost: 184.2, total_cost: 3315.6,
    currency: 'USD', last_transaction_at: null, price_available: true, current_price: 227.52,
    price_source: 'demo', market_value: 4095.36, unrealized_pnl: 779.76, unrealized_pnl_percent: 23.51,
    previous_close: 225.1, daily_change_amount: 2.42, daily_change_percent: 1.08, fx_rate: 1,
    fx_rate_source: 'demo', base_currency_market_value: 4095.36, base_currency_total_cost: 3315.6,
    base_currency_unrealized_pnl: 779.76, base_currency_realized_pnl: 0, base_currency_dividend_income: 0,
    base_currency_fees: 0, base_currency_taxes: 0, base_currency_total_pnl: 779.76, valuation_available: true,
    portfolio_weight: 38.4, authority_source: 'manual', realized_pnl: 0, dividend_income: 0, fees: 0,
    taxes: 0, fees_and_taxes: 0, total_pnl: 779.76, total_return_pct: 23.51, holding_days: null,
    first_trade_at: null, data_completeness: 'partial',
  },
  {
    symbol: 'NVDA', security_id: null, total_quantity: 12, average_cost: 118.4, total_cost: 1420.8,
    currency: 'USD', last_transaction_at: null, price_available: true, current_price: 174.16,
    price_source: 'demo', market_value: 2089.92, unrealized_pnl: 669.12, unrealized_pnl_percent: 47.1,
    previous_close: 171.23, daily_change_amount: 2.93, daily_change_percent: 1.71, fx_rate: 1,
    fx_rate_source: 'demo', base_currency_market_value: 2089.92, base_currency_total_cost: 1420.8,
    base_currency_unrealized_pnl: 669.12, base_currency_realized_pnl: 0, base_currency_dividend_income: 0,
    base_currency_fees: 0, base_currency_taxes: 0, base_currency_total_pnl: 669.12, valuation_available: true,
    portfolio_weight: 19.6, authority_source: 'manual', realized_pnl: 0, dividend_income: 0, fees: 0,
    taxes: 0, fees_and_taxes: 0, total_pnl: 669.12, total_return_pct: 47.1, holding_days: null,
    first_trade_at: null, data_completeness: 'partial',
  },
]

const formatMoney = (value: number | null | undefined, currency = 'USD') => {
  if (value == null || !Number.isFinite(value)) return '数据不足'
  return `${currency === 'USD' ? '$' : `${currency} `}${value.toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
}
const formatPercent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
const tone = (value: number | null | undefined) => value == null ? '' : value >= 0 ? 'positive' : 'negative'
const indexPercent = (value: number | null | undefined) => value == null ? null : value
const marketDayKey = (value: string) => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date(value))

function findIndex(indices: MobileIndexQuote[], kind: 'dow' | 'nasdaq' | 'sp500') {
  const symbol = kind === 'dow' ? '^DJI' : kind === 'nasdaq' ? '^IXIC' : '^GSPC'
  const words = kind === 'dow' ? ['道琼'] : kind === 'nasdaq' ? ['纳斯达克', 'NASDAQ'] : ['标普', 'S&P', 'SP500']
  return indices.find(item => item.symbol === symbol) || indices.find(item => words.some(word => item.name.toUpperCase().includes(word.toUpperCase()))) || {
    symbol,
    name: kind === 'dow' ? '道琼斯' : kind === 'nasdaq' ? '纳斯达克' : '标普500',
    price: null,
    previous_close: null,
    change_points: null,
    change_percent: null,
  }
}

function MobileIndexCard({ item, label }: { item: MobileIndexQuote; label: string }) {
  return <article className="mobile-index-card">
    <span>{label}</span>
    <strong>{item.price == null ? '—' : item.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
    <b className={tone(item.change_percent)}>{formatPercent(indexPercent(item.change_percent))}</b>
  </article>
}

function MobilePositionRow({ position, onOpen }: { position: PositionView; onOpen: () => void }) {
  return <button type="button" className="mobile-position-row" onClick={onOpen}>
    <span className="mobile-position-symbol"><b>{position.symbol}</b><small>{position.portfolio_weight == null ? '仓位未计算' : `仓位 ${position.portfolio_weight.toFixed(1)}%`}</small></span>
    <span className="mobile-position-quote"><strong>{formatMoney(position.current_price, position.currency)}</strong><small className={tone(position.daily_change_percent)}>今日 {formatPercent(position.daily_change_percent)}</small></span>
    <span className="mobile-position-cost"><small>买入金额</small><b>{formatMoney(position.total_cost, position.currency)}</b></span>
    <span className="mobile-position-pnl"><small>累计涨跌</small><b className={tone(position.total_pnl)}>{formatMoney(position.total_pnl, position.currency)}</b><em className={tone(position.total_return_pct)}>{formatPercent(position.total_return_pct)}</em></span>
    <i aria-hidden="true">›</i>
  </button>
}

function MobileAlertCard({ alert }: { alert: MobileAlert }) {
  return <article className="mobile-alert-card">
    <span className="mobile-alert-symbol">{alert.ticker.slice(0, 2)}</span>
    <div><b>{alert.ticker}</b><small>{alert.period} · {new Date(alert.triggered_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</small></div>
    <strong className={tone(alert.change_percent)}>{formatPercent(alert.change_percent)}</strong>
  </article>
}

function MobileJournalDraft({ log, onOpen }: { log: TradeLog; onOpen: () => void }) {
  const facts = log.objective_facts || {}
  return <button type="button" className="mobile-journal-draft" onClick={onOpen}>
    <span className="mobile-draft-mark">✎</span>
    <span><b>{log.ticker || '持仓变动'}</b><small>{log.direction || '调整'} · {log.trade_date}</small></span>
    <span className="mobile-draft-facts"><small>仓位 {String(facts.quantity_before ?? '—')} → {String(facts.quantity_after ?? '—')}</small><small>成交点位 {String(facts.execution_price ?? log.price ?? '—')}</small></span>
    <i aria-hidden="true">›</i>
  </button>
}

function MobileTechnicalWindow({ symbol, open, onClose }: { symbol: string; open: boolean; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['mobile-technical-analysis', symbol],
    queryFn: () => api<TechnicalSnapshot>(`/technical-analysis/${symbol}`),
    enabled: open,
    staleTime: 60_000,
  })
  const data = query.data
  const analysis = data?.analysis
  const indicatorRows = analysis?.indicators ? Object.entries(analysis.indicators).filter(([, value]) => value != null).slice(0, 8) : []
  const label: Record<string, string> = { rsi14: 'RSI 14', macdHistogram: 'MACD 柱', atr14: 'ATR 14', adx14: 'ADX 14', ma20: 'MA 20', ma50: 'MA 50' }
  const zone = (item: { low: number; high: number; center: number } | null | undefined) => item ? `$${item.low.toFixed(2)}–${item.high.toFixed(2)}` : '数据不足'
  return <Sheet open={open} onClose={onClose} title={`${symbol} 技术分析`}>
    <div className="mobile-technical-window">
      <div className="mobile-technical-window-head"><div><p className="eyebrow">STATIC TECHNICAL VIEW</p><h2>{symbol}</h2></div><button type="button" onClick={onClose} aria-label="关闭技术分析">完成</button></div>
      {query.isLoading && <div className="empty">正在读取静态技术缓存…</div>}
      {query.isError && <div className="empty">技术分析暂时不可用。</div>}
      {data && analysis && <>
        <div className="mobile-technical-quote"><strong>${analysis.latestClose.toFixed(2)}</strong><span>{data.data_through ? `截至 ${data.data_through}` : '本地缓存'}</span><b className={`trend-${analysis.weeklyTrend}`}>{analysis.weeklyTrend}</b></div>
        {data.chart_url ? <figure className="mobile-static-chart"><img src={data.chart_url} alt={`${symbol} 静态技术分析图`} /><figcaption>周线静态图 · 不加载 TradingView</figcaption></figure> : <div className="mobile-static-chart-empty">静态图暂未生成，但指标点位仍可查看。</div>}
        <div className="mobile-technical-metrics">{indicatorRows.map(([key, value]) => <div key={key}><small>{label[key] || key}</small><b>{typeof value === 'number' ? value.toFixed(2) : String(value)}</b></div>)}</div>
        <div className="mobile-technical-zones"><div><small>最近支撑</small><b>{zone(analysis.nearestSupport)}</b></div><div><small>最近压力</small><b>{zone(analysis.nearestResistance)}</b></div></div>
        {analysis.historicalCausalHeatmap?.currentLevels?.length ? <section className="mobile-technical-levels"><div className="mobile-detail-section-heading"><h3>关键价格点位</h3><small>{analysis.historicalCausalHeatmap.currentLevels.length} 个指标坐标</small></div>{analysis.historicalCausalHeatmap.currentLevels.slice(0, 10).map(item => <div key={`${item.source}-${item.price}`}><span>{item.source.replaceAll('_', ' ')}</span><b>${item.price.toFixed(2)}</b><em className={item.role === 'support' ? 'positive' : item.role === 'resistance' ? 'negative' : ''}>{item.distancePercent >= 0 ? '+' : ''}{item.distancePercent.toFixed(1)}%</em></div>)}</section> : null}
      </>}
    </div>
  </Sheet>
}

function MobilePositionDetail({ position, summary, onClose, onOpenTab }: { position: PositionView | null; summary: PortfolioSummary | undefined; onClose: () => void; onOpenTab: (tab: string, symbol?: string, query?: string) => void }) {
  const [view, setView] = useState<'position' | 'dynamic' | 'analysis'>('position')
  const [analysisTab, setAnalysisTab] = useState<AnalysisTab>('overview')
  const [technicalOpen, setTechnicalOpen] = useState(false)
  const health = useQuery({ queryKey: ['mobile-portfolio-health'], queryFn: () => api<PortfolioHealth>('/portfolio/health'), enabled: position != null && view === 'analysis' && analysisTab === 'health', staleTime: 60_000 })
  const interpretation = useQuery({ queryKey: ['mobile-portfolio-interpretation'], queryFn: () => api<PersonalizedInterpretation>('/portfolio/interpretation'), enabled: position != null && view === 'analysis' && analysisTab === 'health', staleTime: 60_000 })
  const transactions = useQuery({ queryKey: ['mobile-portfolio-transactions'], queryFn: () => api<{ event_id: string; symbol: string | null; event_type: string; occurred_at: string | null; quantity: number | null; price: number | null; currency: string }[]>('/portfolio/transactions'), enabled: position != null && view === 'analysis' && analysisTab === 'history', staleTime: 60_000 })
  const analysisButtons: [AnalysisTab, string][] = [
    ['overview', '组合中心'], ['health', '风险体检'], ['stress', '压力测试'], ['scenario', '情景分析'],
    ['monte-carlo', '蒙特卡洛'], ['optimization', '组合优化'], ['history', '交易历史'],
  ]
  if (!position) return null
  const positionSummary = summary
  const healthContent = <PortfolioHealthView health={health.data} loading={health.isLoading} currency={positionSummary?.base_currency || position.currency} interpretation={interpretation.data} interpretationLoading={interpretation.isLoading} />
  const detailContent = analysisTab === 'health' && positionSummary ? <PortfolioRiskAnalysis portfolioId={positionSummary.portfolio_id} currency={positionSummary.base_currency || position.currency} healthContent={healthContent} />
    : analysisTab === 'health' ? healthContent
    : analysisTab === 'stress' && positionSummary ? <StressTestView portfolioId={positionSummary.portfolio_id} />
      : analysisTab === 'scenario' && positionSummary ? <ScenarioAnalysisView portfolioId={positionSummary.portfolio_id} />
        : analysisTab === 'monte-carlo' && positionSummary ? <MonteCarloView portfolioId={positionSummary.portfolio_id} />
          : analysisTab === 'optimization' && positionSummary ? <PortfolioOptimizationView portfolioId={positionSummary.portfolio_id} symbols={positionSummary.positions.map(item => item.symbol)} />
            : analysisTab === 'history' ? <div className="mobile-history-content"><div className="mobile-detail-section-heading"><h3>交易历史</h3><small>IBKR 事实与手动账本</small></div>{transactions.isLoading && <div className="empty">正在读取交易历史…</div>}{transactions.data?.filter(item => item.symbol === position.symbol).slice(0, 30).map(item => <div className="mobile-history-row" key={item.event_id}><span>{item.occurred_at ? new Date(item.occurred_at).toLocaleDateString('zh-CN') : '—'}</span><b>{item.event_type}</b><span>{item.quantity == null ? '—' : `${item.quantity} 股`}</span><strong>{item.price == null ? '—' : formatMoney(item.price, item.currency)}</strong></div>)}{!transactions.isLoading && !transactions.data?.filter(item => item.symbol === position.symbol).length && <div className="empty">暂无该持仓的交易记录。</div>}<PortfolioAnalysisHistory /></div>
              : <div className="mobile-analysis-overview"><div className="mobile-detail-section-heading"><h3>组合中心</h3><small>从这里进入独立分析模块</small></div><div className="mobile-analysis-summary-grid"><div><small>组合净值</small><b>{formatMoney(positionSummary?.net_asset_value, positionSummary?.base_currency)}</b></div><div><small>组合日收益</small><b className={tone(positionSummary?.latest_daily_return)}>{formatPercent(positionSummary?.latest_daily_return == null ? null : positionSummary.latest_daily_return * 100)}</b></div><div><small>最大回撤</small><b className="negative">{formatPercent(positionSummary?.max_drawdown == null ? null : positionSummary.max_drawdown * 100)}</b></div><div><small>持仓数量</small><b>{positionSummary?.position_count ?? '—'}</b></div></div><p className="mobile-analysis-note">风险体检、压力测试、情景分析、蒙特卡洛、组合优化和交易历史会分别打开，避免把所有内容堆在一页。</p></div>
  return <>
    <Sheet open={position !== null} onClose={onClose} title={`${position.symbol} 持仓详情`}>
      <div className="mobile-position-detail">
        <header className="mobile-position-detail-head"><div><p className="eyebrow">MY POSITION</p><h2>{position.symbol}</h2></div><div><strong>{formatMoney(position.current_price, position.currency)}</strong><small className={tone(position.daily_change_percent)}>今日 {formatPercent(position.daily_change_percent)}</small></div></header>
        <nav className="mobile-detail-tabs" aria-label="个股详情分区"><button className={view === 'position' ? 'active' : ''} onClick={() => setView('position')}>持仓</button><button className={view === 'dynamic' ? 'active' : ''} onClick={() => setView('dynamic')}>动态</button><button className={view === 'analysis' ? 'active' : ''} onClick={() => setView('analysis')}>组合分析</button></nav>
        {view === 'position' && <section className="mobile-position-facts"><div className="mobile-fact-primary"><div><small>当前市值</small><b>{formatMoney(position.market_value, position.currency)}</b></div><div><small>累计涨跌</small><b className={tone(position.total_pnl)}>{formatMoney(position.total_pnl, position.currency)}</b><em className={tone(position.total_return_pct)}>{formatPercent(position.total_return_pct)}</em></div></div><div className="mobile-fact-grid"><div><small>持仓数量</small><b>{position.total_quantity.toLocaleString('zh-CN')}</b></div><div><small>平均成本</small><b>{formatMoney(position.average_cost, position.currency)}</b></div><div><small>买入金额</small><b>{formatMoney(position.total_cost, position.currency)}</b></div><div><small>浮动盈亏</small><b className={tone(position.unrealized_pnl)}>{formatMoney(position.unrealized_pnl, position.currency)}</b></div><div><small>组合权重</small><b>{position.portfolio_weight == null ? '—' : `${position.portfolio_weight.toFixed(1)}%`}</b></div><div><small>数据来源</small><b>{position.authority_source === 'ibkr_flex' ? 'IBKR' : '手动账本'}</b></div><div><small>价格来源</small><b>{position.price_source || '数据不足'}</b></div><div><small>最近交易</small><b>{position.last_transaction_at ? new Date(position.last_transaction_at).toLocaleDateString('zh-CN') : '—'}</b></div></div><div className="mobile-position-fact-note">所有金额按 {position.currency} 显示；组合聚合、权重和风险分析按 {positionSummary?.base_currency || position.currency} 折算。汇率不可用时不会用 1:1 代替。</div></section>}
        {view === 'dynamic' && <section className="mobile-dynamic-grid"><div className="mobile-detail-section-heading"><h3>动态</h3><small>{position.symbol} 的研究入口</small></div><button onClick={() => onOpenTab('news', position.symbol)}><span>新闻中心</span><small>查看最新公司与市场新闻</small><i>›</i></button><button onClick={() => onOpenTab('sentiment', position.symbol)}><span>舆情</span><small>查看情绪、讨论度与方向</small><i>›</i></button><button onClick={() => onOpenTab('macro', position.symbol)}><span>美国宏观</span><small>查看利率、通胀和市场环境</small><i>›</i></button><button onClick={() => setTechnicalOpen(true)}><span>技术分析</span><small>静态图、指标和关键价格点位</small><i>›</i></button><p className="mobile-analysis-note">动态入口会带入 {position.symbol}，回到模块时保留当前证券。</p></section>}
        {view === 'analysis' && <section className="mobile-portfolio-analysis"><div className="mobile-analysis-nav">{analysisButtons.map(([key, label]) => <button key={key} className={analysisTab === key ? 'active' : ''} onClick={() => setAnalysisTab(key)}>{label}</button>)}</div><div className="mobile-analysis-view">{detailContent}</div></section>}
      </div>
    </Sheet>
    <MobileTechnicalWindow symbol={position.symbol} open={technicalOpen} onClose={() => setTechnicalOpen(false)} />
  </>
}

export function MobileHome({ username, indices, alerts, demoMode = false, onOpenTab }: MobileHomeProps) {
  const summary = useQuery({ queryKey: ['mobile-home-portfolio-summary'], queryFn: () => api<PortfolioSummary>('/portfolio/summary'), enabled: !demoMode, staleTime: 30_000, refetchInterval: 30_000 })
  const tradeLogs = useQuery({ queryKey: ['mobile-home-trade-logs'], queryFn: () => api<TradeLog[]>('/trade-logs'), enabled: !demoMode, staleTime: 30_000, refetchInterval: 30_000 })
  const [selectedPosition, setSelectedPosition] = useState<PositionView | null>(null)
  const positions = useMemo(() => [...(demoMode ? demoPositions : summary.data?.positions || [])].sort((a, b) => (b.portfolio_weight ?? -1) - (a.portfolio_weight ?? -1) || (b.market_value ?? -1) - (a.market_value ?? -1)), [demoMode, summary.data?.positions])
  const indexItems = useMemo(() => {
    const rows = indices?.indices || []
    return [findIndex(rows, 'dow'), findIndex(rows, 'nasdaq'), findIndex(rows, 'sp500')]
  }, [indices?.indices])
  const portfolioDaily = demoMode ? 1.24 : summary.data?.latest_daily_return == null ? null : summary.data.latest_daily_return * 100
  const alertItems = useMemo(() => {
    const today = marketDayKey(new Date().toISOString())
    const yesterday = marketDayKey(new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString())
    return (alerts || []).filter(item => [today, yesterday].includes(marketDayKey(item.triggered_at))).slice(0, 5)
  }, [alerts])
  const drafts = (tradeLogs.data || []).filter(log => log.status === 'draft').slice(0, 3)
  const openJournal = (query?: string) => onOpenTab('journal', undefined, query)
  return <div className="mobile-home" aria-label="主页">
    <section className="mobile-home-welcome"><div><p className="eyebrow">PORTFOLIO HOME</p><h2>早上好，{username}</h2><p>先看市场，再看你的仓位；需要深入研究时再进入详情。</p></div><span className={`mobile-market-status${indices?.market.is_open ? ' open' : ''}`}><i />{indices?.market.is_open ? '交易中' : '市场休市'}</span></section>
    <section className="mobile-index-panel"><div className="mobile-section-heading"><div><small>MARKET PULSE</small><h3>三大指数</h3></div><time>{indices?.market.checked_at ? new Date(indices.market.checked_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '—'}</time></div><div className="mobile-index-grid"><MobileIndexCard item={indexItems[0]} label="道琼斯" /><MobileIndexCard item={indexItems[1]} label="纳斯达克" /><MobileIndexCard item={indexItems[2]} label="标普500" /></div></section>
    <section className="mobile-performance-panel"><div className="mobile-section-heading"><div><small>PORTFOLIO VS MARKET</small><h3>我的仓位表现</h3></div><span className={tone(portfolioDaily)}>{formatPercent(portfolioDaily)}</span></div><div className="mobile-performance-highlight"><div><small>今日组合涨跌幅</small><strong className={tone(portfolioDaily)}>{formatPercent(portfolioDaily)}</strong><span>{summary.data?.latest_sync_at ? `账户同步于 ${new Date(summary.data.latest_sync_at).toLocaleString('zh-CN')}` : demoMode ? '本地示例数据' : '等待账户绩效同步'}</span></div><div className="mobile-benchmark-list">{indexItems.map(item => { const gap = portfolioDaily == null || item.change_percent == null ? null : portfolioDaily - item.change_percent; return <div key={item.symbol}><span>对 {item.name || item.symbol}</span><b className={tone(gap)}>{gap == null ? '—' : `${gap >= 0 ? '+' : ''}${gap.toFixed(2)}%`}</b><small>组合 − 指数</small></div> })}</div></div></section>
    <section className="mobile-holdings-panel"><div className="mobile-section-heading"><div><small>MY HOLDINGS</small><h3>我的持仓</h3></div><button onClick={() => onOpenTab('holdings')}>完整组合 <span>→</span></button></div>{summary.isLoading && !demoMode && <div className="empty">正在读取持仓数据…</div>}{!summary.isLoading && positions.length === 0 && <div className="empty">还没有持仓，先在组合中心添加一笔交易。</div>}{positions.map(position => <MobilePositionRow key={position.symbol} position={position} onOpen={() => setSelectedPosition(position)} />)}<p className="mobile-holdings-note">按仓位大小排列 · 不显示公司全名和 Logo · 点击一行查看完整字段与组合分析</p></section>
    <section className="mobile-alerts-panel"><div className="mobile-section-heading"><div><small>RECENT SIGNALS</small><h3>最近异动</h3></div><button onClick={() => onOpenTab('alerts')}>异动报告 <span>→</span></button></div>{alertItems.length ? alertItems.map(alert => <MobileAlertCard key={alert.id} alert={alert} />) : <div className="mobile-empty-inline">今天和昨天暂无异动。</div>}<button className="mobile-primary-link" onClick={() => onOpenTab('alerts')}>进入异动报告中心 <span>↗</span></button></section>
    <section className="mobile-journal-panel"><div className="mobile-section-heading"><div><small>TRADING JOURNAL</small><h3>交易日志</h3></div><button onClick={() => openJournal()}>专门模块 <span>→</span></button></div><div className="mobile-journal-actions"><button className="mobile-journal-primary" onClick={() => openJournal('new')}>＋ 写交易日志</button><span>IBKR 同步持仓变化会自动生成草稿</span></div>{drafts.length ? <div className="mobile-drafts"><div className="mobile-draft-heading"><b>草稿区</b><small>先补充你的交易逻辑</small></div>{drafts.map(log => <MobileJournalDraft key={log.id} log={log} onOpen={() => openJournal()} />)}</div> : <div className="mobile-empty-inline">暂无待写草稿。</div>}</section>
    <MobilePositionDetail position={selectedPosition} summary={demoMode ? undefined : summary.data} onClose={() => setSelectedPosition(null)} onOpenTab={onOpenTab} />
  </div>
}
