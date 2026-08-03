import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { formatDateTime, formatMoney, formatPercent } from '@shared/format'
import type { Indices, PortfolioSummary, Position, Report } from '@shared/types'
import { GlassCard, IOSPage, LoadingState, SectionHeader, StateView, StatusPill } from '../components'
import { Icon } from '../icons'

type MobilePosition = Position & {
  total_cost?: number | null
}

type MobilePortfolioSummary = Omit<PortfolioSummary, 'positions'> & {
  latest_daily_return?: number | null
  positions: MobilePosition[]
}

type JournalRow = {
  ticker?: string | null
  direction?: string | null
  quantity?: number | null
  price?: number | null
}

type JournalLog = {
  id: number
  trade_date: string
  ticker: string | null
  direction: string | null
  quantity: number | null
  price: number | null
  note: string | null
  content: string | null
  table_rows: JournalRow[]
  status: 'draft' | 'published' | string
  source_type: 'manual' | 'ibkr_sync' | string
  objective_facts: Record<string, unknown>
  created_at: string
}

export type JournalOpenRequest =
  | { mode: 'list' }
  | { mode: 'new' }
  | { mode: 'edit'; id: number }

export type OverviewPageProps = {
  username: string
  openStock: (symbol: string) => void
  openPosition?: (symbol: string) => void
  openActivity: (section?: 'movement') => void
  openJournal?: (request: JournalOpenRequest) => void
  openReport?: (id: number) => void
}

const INDEX_ORDER = [
  { symbol: '^DJI', label: '道琼斯' },
  { symbol: '^IXIC', label: '纳斯达克' },
  { symbol: '^GSPC', label: '标普500' },
] as const

function localDateKey(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function changeClass(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return ''
  return value >= 0 ? 'gain' : 'loss'
}

function indexPrice(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '数据不足'
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function positionPrice(position: MobilePosition) {
  return formatMoney(position.current_price, position.currency)
}

function portfolioDailyChange(positions: MobilePosition[], fallback: number | null | undefined) {
  const rows = positions.filter((position) => (
    position.daily_change_percent != null &&
    Number.isFinite(position.daily_change_percent) &&
    position.portfolio_weight != null &&
    Number.isFinite(position.portfolio_weight)
  ))
  const weight = rows.reduce((total, position) => total + (position.portfolio_weight ?? 0), 0)
  if (weight > 0) {
    return rows.reduce((total, position) => total + (position.daily_change_percent ?? 0) * (position.portfolio_weight ?? 0), 0) / weight
  }
  return fallback != null && Number.isFinite(fallback) ? fallback * 100 : null
}

function PositionRow({ position, open }: { position: MobilePosition; open: () => void }) {
  const dailyChange = position.daily_change_percent
  const totalChange = position.unrealized_pnl
  const weight = position.portfolio_weight
  return <button className="list-row" onClick={open} aria-label={`打开 ${position.symbol} 持仓详情`}>
    <span className="row-copy">
      <strong>{position.symbol}</strong>
      <small>当前价 {positionPrice(position)} · 日 {formatPercent(dailyChange)}</small>
      <small>买入金额 {formatMoney(position.total_cost, position.currency)} · 权重 {weight == null ? '数据不足' : formatPercent(weight).replace('+', '')}</small>
    </span>
    <span className="row-value" style={{ display: 'grid', gap: '.15rem', justifyItems: 'end' }}>
      <small style={{ color: 'var(--secondary)', fontSize: '.64rem' }}>累计涨跌</small>
      <strong className={changeClass(totalChange)} style={{ fontSize: '.82rem' }}>{formatMoney(totalChange, position.currency)}</strong>
      <small className={changeClass(position.unrealized_pnl_percent)}>{formatPercent(position.unrealized_pnl_percent)}</small>
    </span>
    <Icon name="chevron" size={18}/>
  </button>
}

function DraftSummary({ log, open, enabled }: { log: JournalLog; open: () => void; enabled: boolean }) {
  const facts = log.objective_facts || {}
  const before = facts.quantity_before
  const after = facts.quantity_after
  const factsAvailable = log.source_type === 'ibkr_sync' && (before != null || after != null || facts.execution_price != null)
  return <article className="activity-card" style={{ display: 'block' }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '.7rem' }}>
      <div style={{ minWidth: 0, display: 'grid', gap: '.3rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '.45rem' }}>
          <StatusPill tone="warning">待写复盘</StatusPill>
          <strong>{log.ticker || '未填写标的'}</strong>
        </div>
        <small>{log.trade_date} · {log.direction || '持仓变化'}</small>
      </div>
      <button className="text-button" onClick={open} disabled={!enabled}>填写</button>
    </div>
    <p style={{ margin: '.7rem 0 0', color: 'var(--secondary)', fontSize: '.76rem', lineHeight: 1.5 }}>
      {log.source_type === 'ibkr_sync' ? 'IBKR 同步已填入客观事实，等待补充你的交易复盘。' : (log.note || '等待补充交易背景。')}
    </p>
    {factsAvailable && <small style={{ display: 'block', marginTop: '.55rem', color: 'var(--tertiary)', lineHeight: 1.45 }}>
      仓位 {before == null ? '数据不足' : String(before)} → {after == null ? '数据不足' : String(after)}
      {facts.execution_price != null ? ` · 成交价 ${String(facts.execution_price)} ${String(facts.currency || '')}` : ''}
    </small>}
  </article>
}

export function OverviewPage({ username, openStock, openPosition, openActivity, openJournal, openReport }: OverviewPageProps) {
  const indices = useQuery({ queryKey: ['ios-indices'], queryFn: () => api<Indices>('/indices'), refetchInterval: 60_000 })
  const summary = useQuery({ queryKey: ['ios-portfolio-summary'], queryFn: () => api<MobilePortfolioSummary>('/portfolio/summary'), refetchInterval: 30_000 })
  const reports = useQuery({ queryKey: ['ios-overview-movement-reports'], queryFn: () => api<Report[]>('/reports?report_type=movement'), refetchInterval: 60_000 })
  const journals = useQuery({ queryKey: ['ios-trade-logs'], queryFn: () => api<JournalLog[]>('/trade-logs'), refetchInterval: 30_000 })

  const positions = summary.data?.positions ?? []
  const sortedPositions = useMemo(() => [...positions].sort((left, right) => {
    const weightDifference = (right.portfolio_weight ?? Number.NEGATIVE_INFINITY) - (left.portfolio_weight ?? Number.NEGATIVE_INFINITY)
    return weightDifference || left.symbol.localeCompare(right.symbol)
  }), [positions])
  const orderedIndices = useMemo(() => INDEX_ORDER.map((definition) => ({
    ...definition,
    quote: indices.data?.indices.find((item) => item.symbol === definition.symbol),
  })), [indices.data])
  const dailyChange = portfolioDailyChange(positions, summary.data?.latest_daily_return)
  const dailyCoverage = positions.filter((position) => position.daily_change_percent != null).length
  const recentDateKeys = useMemo(() => {
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    return new Set([localDateKey(today), localDateKey(yesterday)])
  }, [])
  const recentReports = useMemo(() => (reports.data ?? [])
    .filter((report) => {
      const date = new Date(report.created_at)
      return report.report_type === 'movement' && !Number.isNaN(date.getTime()) && recentDateKeys.has(localDateKey(date))
    })
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()), [reports.data, recentDateKeys])
  const drafts = (journals.data ?? []).filter((log) => log.status === 'draft')

  const openPositionDetail = (symbol: string) => openPosition ? openPosition(symbol) : openStock(symbol)
  const openReportDetail = (id: number) => openReport ? openReport(id) : openActivity('movement')

  return <IOSPage className="overview-page">
    <section className="large-title overview-title">
      <div>
        <span>{indices.data?.market.is_open ? '市场开放' : '市场休市'}</span>
        <h1>你好，{username}</h1>
        <p>持仓、市场与今日异动，集中查看。</p>
      </div>
      <button className="activity-entry" onClick={() => openActivity()}><i/><span>动态</span><b>›</b></button>
    </section>

    <GlassCard className="market-card">
      <div className="market-card-heading">
        <div><span>三大指数</span><strong>{indices.data?.market.is_open ? '交易中' : '已收盘'}</strong></div>
        <StatusPill tone={indices.data?.market.is_open ? 'positive' : 'neutral'}>{indices.data?.market.is_open ? 'LIVE' : 'CLOSED'}</StatusPill>
      </div>
      {indices.isLoading ? <LoadingState rows={3}/> : indices.isError ? <StateView title="指数暂不可用" message="市场数据没有响应，稍后可重试。" retry={() => { void indices.refetch() }}/> : <div className="index-strip">
        {orderedIndices.map(({ symbol, label, quote }) => <div key={symbol}>
          <span>{label}</span>
          <strong>{indexPrice(quote?.price)}</strong>
          <small className={changeClass(quote?.change_percent)}>{formatPercent(quote?.change_percent)}</small>
        </div>)}
      </div>}
    </GlassCard>

    <SectionHeader title="我的仓位涨跌幅" caption={dailyCoverage > 0 ? `按组合权重计算 · 已覆盖 ${dailyCoverage} / ${positions.length} 个仓位` : '等待持仓日变动数据'}/>
    <GlassCard className="portfolio-hero">
      <span>今日持仓表现</span>
      <strong className={changeClass(dailyChange)}>{formatPercent(dailyChange)}</strong>
      <div><span>数据口径</span><b>{dailyChange == null ? '数据不足' : '当前组合权重'}</b></div>
    </GlassCard>

    <SectionHeader title="相对三大指数" caption="我的仓位涨跌幅 − 指数涨跌幅"/>
    <div className="index-strip">
      {orderedIndices.map(({ symbol, label, quote }) => {
        const gap = dailyChange != null && quote?.change_percent != null ? dailyChange - quote.change_percent : null
        return <div key={symbol}>
          <span>{label}</span>
          <strong>差距</strong>
          <small className={changeClass(gap)}>{formatPercent(gap)}</small>
        </div>
      })}
    </div>

    <SectionHeader title="全部持仓" caption={`${positions.length} 个仓位 · 按权重降序`}/>
    {summary.isLoading ? <LoadingState rows={5}/> : summary.isError ? <StateView title="持仓读取失败" message="请检查网络后重试。" retry={() => { void summary.refetch() }}/> : sortedPositions.length ? <div className="inset-list">
      {sortedPositions.map((position) => <PositionRow key={position.symbol} position={position} open={() => openPositionDetail(position.symbol)}/>)}
    </div> : <StateView title="暂无持仓" message="同步或添加持仓后，这里会显示完整仓位。"/>}

    <SectionHeader title="今日与昨日异动" caption="仅展示最近两个自然日的异动报告" action={<button className="text-button" onClick={() => openActivity('movement')}>进入异动报告</button>}/>
    {reports.isLoading ? <LoadingState rows={3}/> : reports.isError ? <StateView title="异动暂不可用" message="报告服务没有响应，稍后可重试。" retry={() => { void reports.refetch() }}/> : recentReports.length ? <div className="movement-report-list">
      {recentReports.map((report) => <button className="movement-report-card" key={report.id} onClick={() => openReportDetail(report.id)}>
        <div><StatusPill tone={report.confidence === '高' ? 'positive' : report.confidence === '低' ? 'warning' : 'neutral'}>{report.ticker || '市场'}</StatusPill><time>{formatDateTime(report.created_at)}</time></div>
        <h2>{report.title}</h2>
        <p>{report.ticker || '市场'} · {report.model}</p>
        <b>阅读报告 ›</b>
      </button>)}
    </div> : <StateView title="最近两天暂无异动" message="主页只保留今天和昨天的异动报告。"/>}

    <SectionHeader title="交易日志" caption="IBKR 同步后的持仓变化先进入草稿" action={<button className="text-button" onClick={() => openJournal?.({ mode: 'list' })} disabled={!openJournal}>进入完整日志</button>}/>
    <GlassCard className="market-card">
      <div className="market-card-heading">
        <div><span>复盘入口</span><strong>{drafts.length ? `${drafts.length} 条待写草稿` : '没有待写草稿'}</strong></div>
        <button className="primary-button" style={{ minHeight: '2.5rem', padding: '0 .8rem', fontSize: '.75rem' }} onClick={() => openJournal?.({ mode: 'new' })} disabled={!openJournal}>写交易日志</button>
      </div>
      {journals.isLoading ? <LoadingState rows={2}/> : journals.isError ? <StateView title="交易日志暂不可用" message="日志接口没有响应；不会在这里编造交易数据。" retry={() => { void journals.refetch() }}/> : drafts.length ? <div className="activity-list" style={{ marginTop: '1rem' }}>
        {drafts.slice(0, 3).map((log) => <DraftSummary key={log.id} log={log} open={() => openJournal?.({ mode: 'edit', id: log.id })} enabled={Boolean(openJournal)}/>)}
      </div> : <StateView title="暂无草稿" message="同步 IBKR 持仓变化后，草稿摘要会显示在这里。"/>}
    </GlassCard>
  </IOSPage>
}
