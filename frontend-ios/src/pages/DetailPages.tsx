import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { api } from '@shared/api'
import { formatDateTime, formatPercent } from '@shared/format'
import type { Dashboard, DiscoveryCandidate, Report, ReportDetail, WatchItem } from '@shared/types'
import { InsetList, IOSPage, ListRow, LoadingState, NavigationBar, StateView, StatusPill } from '../components'
import { MobilePositionWorkspace } from './MobilePositionWorkspace'

type CandidateDetail = DiscoveryCandidate & { sources?: { title: string; url: string; origin: string }[]; thesis_breakers?: string[] }

export function StockDetailPage({ symbol, back }: { symbol: string; back: () => void }) {
  const dashboard = useQuery({ queryKey: ['ios-dashboard'], queryFn: () => api<Dashboard>('/dashboard') })
  const stock = dashboard.data?.stocks.find(item => item.ticker === symbol)
  const change = stock?.price != null && stock.previous_close ? (stock.price - stock.previous_close) / stock.previous_close * 100 : null
  return <><NavigationBar title={symbol} eyebrow="证券详情" back={back}/><IOSPage className="detail-page">{dashboard.isLoading ? <LoadingState rows={5}/> : !stock ? <StateView title="找不到证券" message="该证券可能已不在当前自选股中。"/> : <><section className="quote-hero"><span>{stock.company_name || symbol}</span><strong>{stock.price?.toLocaleString('en-US', { maximumFractionDigits: 2 }) ?? '数据不足'}</strong><StatusPill tone={(change || 0) >= 0 ? 'positive' : 'negative'}>{formatPercent(change)}</StatusPill></section><InsetList label="行情摘要"><ListRow title="前收盘" value={stock.previous_close?.toLocaleString() ?? '数据不足'}/><ListRow title="相对成交量" value={stock.volume_ratio ? `${stock.volume_ratio.toFixed(2)}×` : '数据不足'}/><ListRow title="成交量状态" value={stock.volume_label || '数据不足'}/><ListRow title="更新时间" value={formatDateTime(stock.updated_at)}/></InsetList><p className="disclaimer">估值、财报和 SEC 已可从底部“基本面”进入；复杂技术图表仍使用桌面版。</p></>}</IOSPage></>
}

export function PositionDetailPage({ symbol, back }: { symbol: string; back: () => void }) {
  return <MobilePositionWorkspace symbol={symbol} back={back}/>
}

export function CandidateDetailPage({ id, back }: { id: number; back: () => void }) {
  const query = useQuery({ queryKey: ['ios-candidate', id], queryFn: () => api<CandidateDetail>(`/discovery/candidates/${id}`) })
  const item = query.data
  return <><NavigationBar title={item?.normalized_ticker || item?.raw_ticker || '候选详情'} eyebrow="研究摘要" back={back}/><IOSPage className="detail-page">{query.isLoading ? <LoadingState rows={6}/> : query.isError || !item ? <StateView title="无法读取候选" message="该候选资料可能已更新。" retry={() => query.refetch()}/> : <><section className="candidate-detail-hero"><h1>{item.company_name}</h1><p>{item.discovery_reason || '数据不足'}</p><StatusPill tone="warning">置信度 {item.confidence ?? '—'}</StatusPill></section><DetailSection title="投资逻辑" items={item.investment_thesis}/><DetailSection title="主要风险" items={item.major_risks}/><DetailSection title="失效条件" items={item.thesis_breakers || []}/>{item.sources?.length ? <InsetList label="来源">{item.sources.slice(0, 8).map((source, index) => <a className="list-row" href={source.url} target="_blank" rel="noreferrer" key={`${source.url}-${index}`}><span className="row-copy"><strong>{source.title || source.url}</strong><small>{source.origin}</small></span></a>)}</InsetList> : null}<p className="disclaimer">研究候选不构成投资建议。请独立核验来源、估值与风险。</p></>}</IOSPage></>
}

function DetailSection({ title, items }: { title: string; items: string[] }) { return items.length ? <section className="detail-section"><h2>{title}</h2><ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul></section> : null }

export function WatchlistPage({ back, openStock }: { back: () => void; openStock: (symbol: string) => void }) {
  const query = useQuery({ queryKey: ['ios-watchlist'], queryFn: () => api<WatchItem[]>('/watchlist') })
  return <><NavigationBar title="自选股" eyebrow="监控列表" back={back}/><IOSPage className="detail-page">{query.isLoading ? <LoadingState rows={6}/> : <InsetList>{query.data?.map(item => <ListRow key={item.id} title={item.ticker} subtitle={`${item.enabled ? '行情监控开启' : '行情监控关闭'} · ${item.alert_enabled ? '异动提醒开启' : '异动提醒关闭'}`} onClick={() => openStock(item.ticker)}/>)}</InsetList>}</IOSPage></>
}

export function ReportsPage({ back, initialId = null }: { back: () => void; initialId?: number | null }) {
  const list = useQuery({ queryKey: ['ios-reports'], queryFn: () => api<Report[]>('/reports') })
  const [selected, setSelected] = useState<number | null>(initialId)
  const detail = useQuery({ queryKey: ['ios-report', selected], queryFn: () => api<ReportDetail>(`/reports/${selected}`), enabled: selected != null })
  if (selected != null) return <><NavigationBar title="报告" eyebrow={detail.data?.ticker || '智能研究'} back={() => initialId != null ? back() : setSelected(null)}/><IOSPage className="detail-page">{detail.isLoading ? <LoadingState rows={6}/> : detail.data ? <article className="report-detail"><h1>{detail.data.title}</h1><small>{formatDateTime(detail.data.created_at)} · {detail.data.model}</small><div className="pre-wrap report-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{detail.data.content}</ReactMarkdown></div>{detail.data.sources.length > 0 && <InsetList label="信息来源">{detail.data.sources.map((source, index) => <a className="list-row" href={source.url} target="_blank" rel="noreferrer" key={index}><span className="row-copy"><strong>{source.title}</strong></span></a>)}</InsetList>}</article> : <StateView title="报告不可用" message="请返回后重试。"/>}</IOSPage></>
  return <><NavigationBar title="智能报告" eyebrow="研究资料" back={back}/><IOSPage className="detail-page">{list.isLoading ? <LoadingState rows={6}/> : <InsetList>{list.data?.map(item => <ListRow key={item.id} title={item.title} subtitle={`${item.ticker || '市场'} · ${formatDateTime(item.created_at)}`} onClick={() => setSelected(item.id)}/>)}</InsetList>}</IOSPage></>
}
