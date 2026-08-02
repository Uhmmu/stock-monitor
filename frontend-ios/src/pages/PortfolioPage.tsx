import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { formatMoney, formatPercent } from '@shared/format'
import type { PortfolioSummary, Position } from '@shared/types'
import { GlassCard, IOSPage, LoadingState, SectionHeader, StateView, StatusPill } from '../components'

export function PortfolioPage({ openPosition }: { openPosition: (symbol: string) => void }) {
  const summary = useQuery({ queryKey: ['ios-portfolio-summary'], queryFn: () => api<PortfolioSummary>('/portfolio/summary'), staleTime: 30_000 })
  const data = summary.data
  if (summary.isLoading) return <IOSPage><section className="large-title"><span>PORTFOLIO</span><h1>持仓</h1></section><LoadingState rows={6}/></IOSPage>
  if (summary.isError) return <IOSPage><section className="large-title"><h1>持仓</h1></section><StateView title="持仓读取失败" message="请检查网络后重试。" retry={() => summary.refetch()}/></IOSPage>
  return <IOSPage>
    <section className="large-title"><span>PORTFOLIO</span><h1>持仓</h1><p>{data?.position_count || 0} 个当前仓位</p></section>
    <GlassCard className="portfolio-hero">
      <span>折算后总市值</span><strong>{formatMoney(data?.total_market_value, data?.base_currency)}</strong>
      <div><span>浮动盈亏</span><b className={(data?.total_unrealized_pnl || 0) >= 0 ? 'gain' : 'loss'}>{formatMoney(data?.total_unrealized_pnl, data?.base_currency)} · {formatPercent(data?.total_unrealized_pnl_percent)}</b></div>
      {(data?.has_unpriced_positions || data?.has_unconverted_positions) && <p>部分持仓因价格或汇率缺失未计入汇总。</p>}
    </GlassCard>
    <SectionHeader title="当前仓位" caption="按组合权重排列"/>
    <div className="position-list">{[...(data?.positions || [])].sort((a, b) => (b.portfolio_weight || 0) - (a.portfolio_weight || 0)).map(position => <PositionCard key={position.symbol} position={position} open={() => openPosition(position.symbol)}/>)}</div>
    {!data?.positions.length && <StateView title="还没有持仓" message="请在桌面端或后续移动端交易入口添加第一笔持仓。"/>}
  </IOSPage>
}

function PositionCard({ position, open }: { position: Position; open: () => void }) {
  const weight = position.portfolio_weight ?? 0
  return <button className="position-card" onClick={open}><div className="position-heading"><span className="stock-avatar">{position.symbol.slice(0, 2)}</span><span><strong>{position.symbol}</strong><small>{position.total_quantity.toLocaleString('zh-CN')} 股</small></span><StatusPill tone={(position.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative'}>{formatPercent(position.unrealized_pnl_percent)}</StatusPill></div><div className="position-values"><span><small>市值</small><strong>{formatMoney(position.market_value, position.currency)}</strong></span><span><small>浮动盈亏</small><strong className={(position.unrealized_pnl || 0) >= 0 ? 'gain' : 'loss'}>{formatMoney(position.unrealized_pnl, position.currency)}</strong></span></div><div className="weight-track"><i style={{ width: `${Math.min(100, Math.max(0, weight))}%` }}/></div><small className="weight-label">组合权重 {formatPercent(weight).replace('+', '')}</small></button>
}
