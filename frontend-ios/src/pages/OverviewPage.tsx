import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { formatPercent, stockChange } from '@shared/format'
import type { Dashboard, Indices } from '@shared/types'
import { GlassCard, IOSPage, LoadingState, SectionHeader, StateView, StatusPill } from '../components'

export function OverviewPage({ username, openStock, openActivity }: { username: string; openStock: (symbol: string) => void; openActivity: () => void }) {
  const [showAllStocks, setShowAllStocks] = useState(false)
  const dashboard = useQuery({ queryKey: ['ios-dashboard'], queryFn: () => api<Dashboard>('/dashboard'), refetchInterval: 30_000 })
  const indices = useQuery({ queryKey: ['ios-indices'], queryFn: () => api<Indices>('/indices'), refetchInterval: 60_000 })
  const failed = dashboard.isError && indices.isError

  return <IOSPage className="overview-page">
    <section className="large-title overview-title"><div><span>{dashboard.data?.market.is_open ? '市场开放' : '市场休市'}</span><h1>你好，{username}</h1><p>行情和自选，一眼看清。</p></div><button className="activity-entry" onClick={openActivity}><i/><span>动态</span><b>›</b></button></section>
    {failed && <StateView title="暂时无法连接" message="行情服务没有响应，已有页面仍可继续浏览。" retry={() => { dashboard.refetch(); indices.refetch() }}/>}
    <GlassCard className="market-card">
      <div className="market-card-heading"><div><span>市场脉搏</span><strong>{indices.data?.market.is_open ? '交易中' : '已收盘'}</strong></div><StatusPill tone={indices.data?.market.is_open ? 'positive' : 'neutral'}>{indices.data?.market.is_open ? 'LIVE' : 'CLOSED'}</StatusPill></div>
      {indices.isLoading ? <LoadingState rows={3}/> : <div className="index-strip">{indices.data?.indices.slice(0, 3).map(index => <div key={index.symbol}><span>{index.name}</span><strong>{index.price?.toLocaleString('en-US', { maximumFractionDigits: 2 }) ?? '—'}</strong><small className={(index.change_percent ?? 0) >= 0 ? 'gain' : 'loss'}>{formatPercent(index.change_percent)}</small></div>)}</div>}
    </GlassCard>

    <SectionHeader title="自选快照" caption={`${dashboard.data?.stocks.length ?? 0} 只证券`} action={(dashboard.data?.stocks.length || 0) > 6 ? <button className="text-button" onClick={() => setShowAllStocks(value => !value)}>{showAllStocks ? '收起' : '查看更多'}</button> : undefined}/>
    {dashboard.isLoading ? <LoadingState rows={4}/> : <div className="stock-list">{dashboard.data?.stocks.slice(0, showAllStocks ? undefined : 6).map(stock => {
      const change = stockChange(stock.price, stock.previous_close)
      return <button className="stock-row" key={stock.ticker} onClick={() => openStock(stock.ticker)}><span className="stock-avatar">{stock.ticker.slice(0, 2)}</span><span><strong>{stock.ticker}</strong><small>{stock.company_name || stock.volume_label || '等待公司资料'}</small></span><span><strong>{stock.price?.toLocaleString('en-US', { maximumFractionDigits: 2 }) ?? '—'}</strong><small className={(change ?? 0) >= 0 ? 'gain' : 'loss'}>{formatPercent(change)}</small></span></button>
    })}{!dashboard.data?.stocks.length && <StateView title="还没有自选股" message="可从“更多”进入自选股管理。"/>}</div>}
  </IOSPage>
}
