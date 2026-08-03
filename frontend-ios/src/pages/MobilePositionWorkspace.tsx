import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { formatDateTime, formatMoney, formatPercent } from '@shared/format'
import type { PortfolioSummary, Position } from '@shared/types'
import { GlassCard, InsetList, IOSPage, ListRow, LoadingState, NavigationBar, StateView, StatusPill } from '../components'

type LedgerDetail = {
  summary: Position
  open_lots: { opened_at?: string | null; quantity?: number | null; cost_basis?: number | null; cost_per_share?: number | null; source_type?: string | null }[]
  data_sources?: Record<string, unknown>
  latest_sync_at?: string | null
}

function numberLabel(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '数据不足' : value.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function dateLabel(value: string | null | undefined) {
  return value ? formatDateTime(value) : '数据不足'
}

function sourceLabel(value: string | null | undefined) {
  if (!value) return '数据不足'
  if (value === 'ibkr_flex') return 'IBKR 同步'
  if (value === 'project_market_data') return '项目行情系统'
  if (value === 'portfolio_transactions') return '组合交易账本'
  return value
}

function positionRows(position: Position): [string, string][] {
  const totalCost = position.total_cost ?? (position.average_cost * position.total_quantity)
  const dailyPnl = position.daily_pnl ?? (position.daily_change_amount == null ? null : position.daily_change_amount * position.total_quantity)
  return [
    ['持有数量', numberLabel(position.total_quantity)],
    ['平均成本', formatMoney(position.average_cost, position.currency)],
    ['买入金额 / 总成本', formatMoney(totalCost, position.currency)],
    ['当前价格', formatMoney(position.current_price, position.currency)],
    ['当前市值', formatMoney(position.market_value, position.currency)],
    ['当日涨跌幅', formatPercent(position.daily_change_percent)],
    ['当日盈亏', formatMoney(dailyPnl, position.currency)],
    ['累计浮动盈亏', formatMoney(position.unrealized_pnl, position.currency)],
    ['累计收益率', formatPercent(position.total_return_pct ?? position.unrealized_pnl_percent)],
    ['组合权重', formatPercent(position.portfolio_weight).replace('+', '')],
    ['币种', position.currency || '数据不足'],
    ['汇率', position.fx_rate == null ? '无需折算 / 数据不足' : numberLabel(position.fx_rate)],
    ['价格来源', sourceLabel(position.price_source)],
    ['价格时间', dateLabel(position.price_as_of)],
    ['数量来源', sourceLabel(position.quantity_source)],
    ['成本来源', sourceLabel(position.average_cost_source)],
    ['IBKR 报告日期', dateLabel(position.ibkr_report_date)],
  ]
}

export function MobilePositionWorkspace({ symbol, back }: { symbol: string; back: () => void }) {
  const summary = useQuery({ queryKey: ['ios-portfolio-summary'], queryFn: () => api<PortfolioSummary>('/portfolio/summary'), staleTime: 30_000, refetchInterval: 30_000, refetchIntervalInBackground: true })
  const detail = useQuery({ queryKey: ['ios-position-ledger-detail', symbol], queryFn: () => api<LedgerDetail>('/portfolio/positions/' + encodeURIComponent(symbol)), staleTime: 30_000, refetchInterval: 30_000, refetchIntervalInBackground: true })
  const position = detail.data?.summary ?? summary.data?.positions.find(item => item.symbol === symbol)

  if (summary.isLoading || detail.isLoading) return <><NavigationBar title={symbol} eyebrow="持仓详情" back={back}/><IOSPage className="detail-page"><LoadingState rows={6}/></IOSPage></>
  if (summary.isError || detail.isError || !position) return <><NavigationBar title={symbol} eyebrow="持仓详情" back={back}/><IOSPage className="detail-page"><StateView title="持仓资料暂不可用" message="无法读取这只证券的账户事实，请稍后重试。" retry={() => { void summary.refetch(); void detail.refetch() }}/></IOSPage></>

  const pnl = position.unrealized_pnl ?? position.total_pnl
  const rows = positionRows(position)
  return <><NavigationBar title={symbol} eyebrow="持仓详情" back={back}/><IOSPage className="detail-page position-detail-page">
    <section className="position-detail-hero">
      <div><span>{position.currency} · {sourceLabel(position.authority_source)}</span><h1>{symbol}</h1></div>
      <div className="position-detail-price"><strong>{formatMoney(position.current_price, position.currency)}</strong><StatusPill tone={(position.daily_change_percent ?? 0) >= 0 ? 'positive' : 'negative'}>{formatPercent(position.daily_change_percent)}</StatusPill></div>
    </section>
    <GlassCard className="holding-summary-card">
      <div><span>当前市值</span><strong>{formatMoney(position.market_value, position.currency)}</strong></div>
      <div><span>累计盈亏</span><b className={(pnl ?? 0) >= 0 ? 'gain' : 'loss'}>{formatMoney(pnl, position.currency)}</b></div>
      <div><span>组合权重</span><b>{formatPercent(position.portfolio_weight).replace('+', '')}</b></div>
    </GlassCard>
    <InsetList label="持仓字段">{rows.map(([label, value]) => <ListRow key={label} title={label} value={value}/>)}</InsetList>
    {detail.data?.open_lots?.length ? <InsetList label={'持仓批次 · ' + detail.data.open_lots.length}><div className="holding-lot-list">{detail.data.open_lots.slice(0, 8).map((lot, index) => <article key={index}><div><strong>{'批次 ' + (index + 1)}</strong><small>{dateLabel(lot.opened_at)}</small></div><span>{lot.quantity == null ? '数量不足' : numberLabel(lot.quantity) + ' 股'}</span><span>{lot.cost_per_share == null ? '成本不足' : formatMoney(lot.cost_per_share, position.currency)}</span></article>)}</div></InsetList> : null}
    <InsetList label="账户事实与数据完整性">
      <ListRow title="账户来源" value={sourceLabel(position.authority_source)}/>
      <ListRow title="最近同步" value={dateLabel(detail.data?.latest_sync_at)}/>
      <ListRow title="行情可用" value={position.price_available ? '可用' : '数据不足'}/>
      <ListRow title="估值可用" value={position.valuation_available ? '已计入组合' : '未计入组合'}/>
      <ListRow title="汇率来源" value={sourceLabel(position.fx_rate_source)}/>
      {(position.price_is_report_fallback || position.authority_source === 'ibkr_flex') && <ListRow title="数据提示" value={position.price_is_report_fallback ? '当前价格为 IBKR 报告标记价' : '数量与成本来自 IBKR 客观事实'}/>}
    </InsetList>
    <p className="disclaimer">这里仅展示这只证券的持仓与账户字段。账户数量、成本和交易事实优先来自 IBKR；缺失项显示“数据不足”，不会用估算值替代。</p>
  </IOSPage></>
}
