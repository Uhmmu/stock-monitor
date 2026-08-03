import { useMemo, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { api, post } from '@shared/api'
import { formatDateTime } from '@shared/format'
import type { CalendarEvents, MarketNews, NewsItem, Report, WatchItem } from '@shared/types'
import { IOSPage, LoadingState, StateView, StatusPill } from '../components'
import { NavigationBar } from '../components'

type Segment = 'news' | 'calendar' | 'reports'
const eventLabels: Record<string, string> = { earnings: '财报', dividend: '分红', split: '拆股', economic: '宏观事件' }
const reportLabels: Record<string, string> = { movement: '价格异动', premarket: '盘前', postmarket: '盘后', earnings_before: '财报前', earnings_after: '财报后' }

export function ActivityPage({ openReport, back, initialSegment = 'news', initialTicker = '' }: { openReport: (id: number) => void; back?: () => void; initialSegment?: Segment; initialTicker?: string }) {
  const client = useQueryClient()
  const [segment, setSegment] = useState<Segment>(initialSegment)
  const [newsScope, setNewsScope] = useState<'market' | 'company'>(initialTicker ? 'company' : 'market')
  const [ticker, setTicker] = useState(initialTicker)
  const [topic, setTopic] = useState('')
  const today = useMemo(() => new Date().toISOString().slice(0, 10), [])
  const end = useMemo(() => { const date = new Date(); date.setDate(date.getDate() + 30); return date.toISOString().slice(0, 10) }, [])
  const watchlist = useQuery({ queryKey: ['ios-watchlist'], queryFn: () => api<WatchItem[]>('/watchlist'), staleTime: 60_000 })
  const selectedTicker = ticker || watchlist.data?.[0]?.ticker || ''
  const marketNews = useInfiniteQuery({
    queryKey: ['ios-news-market-full'], queryFn: ({ pageParam }) => api<MarketNews>(`/news/market?limit=100&offset=${pageParam}`), initialPageParam: 0,
    getNextPageParam: (last, _pages, lastOffset) => lastOffset + last.items.length < last.total ? lastOffset + last.items.length : undefined,
    enabled: segment === 'news' && newsScope === 'market',
    refetchInterval: query => query.state.data?.pages.some(page => page.items.some(item => ['queued', 'processing'].includes(item.ai_summary_status))) ? 2_000 : false,
  })
  const companyNews = useQuery({
    queryKey: ['ios-news-company-full', selectedTicker], queryFn: () => api<NewsItem[]>(`/news?ticker=${encodeURIComponent(selectedTicker)}`), enabled: segment === 'news' && newsScope === 'company' && !!selectedTicker,
    refetchInterval: query => (query.state.data as NewsItem[] | undefined)?.some(item => ['queued', 'processing'].includes(item.ai_summary_status)) ? 2_000 : false,
  })
  const calendar = useQuery({ queryKey: ['ios-calendar-events'], queryFn: () => api<CalendarEvents>(`/calendar/events?start_date=${today}&end_date=${end}&relevant_only=true&limit=100`), enabled: segment === 'calendar' })
  const reports = useQuery({ queryKey: ['ios-movement-reports'], queryFn: () => api<Report[]>('/reports?report_type=movement'), enabled: segment === 'reports' })
  const summarize = useMutation({ mutationFn: ({ id, force }: { id: number; force: boolean }) => post<NewsItem>(`/news/${id}/summarize?force=${force}`, {}), onSuccess: () => { void client.invalidateQueries({ queryKey: ['ios-news-market-full'] }); void client.invalidateQueries({ queryKey: ['ios-news-company-full', selectedTicker] }) } })
  const refresh = useMutation({ mutationFn: () => post(newsScope === 'market' ? '/news/market/refresh' : `/news/refresh?ticker=${encodeURIComponent(selectedTicker)}`, {}) })
  const allNews = newsScope === 'market' ? marketNews.data?.pages.flatMap(page => page.items) || [] : companyNews.data || []
  const topics = [...new Set(allNews.map(item => item.topic).filter((value): value is string => Boolean(value)))].sort()
  const visibleNews = topic ? allNews.filter(item => item.topic === topic) : allNews

  return <>{back && <NavigationBar title="动态" eyebrow="新闻 · 日历 · 报告" back={back}/>}<IOSPage className="activity-page detail-page">
    <section className="large-title"><span>ACTIVITY</span><h1>动态</h1><p>新闻、日历与异动研究。</p></section>
    <div className="segmented-control" role="tablist">{([['news', '新闻'], ['calendar', '日历'], ['reports', '异动报告']] as [Segment, string][]).map(([key, label]) => <button role="tab" aria-selected={segment === key} className={segment === key ? 'active' : ''} key={key} onClick={() => setSegment(key)}>{label}</button>)}</div>

    {segment === 'news' && <>
      <div className="news-toolbar">
        <label><span>范围</span><select value={newsScope} onChange={event => { setNewsScope(event.target.value as 'market' | 'company'); setTopic('') }}><option value="market">市场总览</option><option value="company">个股新闻</option></select></label>
        {newsScope === 'company' ? <label><span>证券</span><select value={selectedTicker} onChange={event => setTicker(event.target.value)}>{watchlist.data?.map(item => <option key={item.id} value={item.ticker}>{item.ticker}</option>)}</select></label> : <label><span>分类</span><select value={topic} onChange={event => setTopic(event.target.value)}><option value="">全部分类</option>{topics.map(value => <option value={value} key={value}>{value}</option>)}</select></label>}
        <button onClick={() => refresh.mutate()} disabled={refresh.isPending || (newsScope === 'company' && !selectedTicker)}>{refresh.isPending ? '刷新中' : '刷新'}</button>
      </div>
      {newsScope === 'company' && topics.length > 0 && <label className="news-topic-filter"><span>个股新闻分类</span><select value={topic} onChange={event => setTopic(event.target.value)}><option value="">全部分类</option>{topics.map(value => <option value={value} key={value}>{value}</option>)}</select></label>}
      <p className="result-caption">{newsScope === 'market' ? `全市场 · 已载入 ${visibleNews.length} / ${marketNews.data?.pages[0]?.total ?? 0} 条` : `${selectedTicker} · 本周 ${visibleNews.length} 条`}{refresh.isSuccess ? ' · 已触发后台采集' : ''}</p>
      {(marketNews.isLoading || companyNews.isLoading) && <LoadingState rows={7}/>}
      <div className="full-news-list">{visibleNews.map(item => <NewsCard item={item} key={item.id} summarize={(force) => summarize.mutate({ id: item.id, force })} sending={summarize.isPending && summarize.variables?.id === item.id}/>)}</div>
      {newsScope === 'market' && marketNews.hasNextPage && <button className="load-more-news" onClick={() => void marketNews.fetchNextPage()} disabled={marketNews.isFetchingNextPage}>{marketNews.isFetchingNextPage ? '正在载入…' : '加载更多新闻'}</button>}
      {!visibleNews.length && !marketNews.isLoading && !companyNews.isLoading && <StateView title="暂时没有新闻" message="可切换范围或点击刷新重新采集。"/>}
    </>}

    {segment === 'calendar' && <>{calendar.isLoading && <LoadingState rows={6}/>}<div className="activity-list">{calendar.data?.items.map(item => <article className="activity-card calendar-event" key={item.id}><time>{new Date(`${item.event_date}T00:00:00`).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}</time><div><strong>{item.symbol} · {item.title}</strong><p>{eventLabels[item.event_type] || item.event_type}{item.event_time ? ` · ${item.event_time}` : ''}</p><small>{item.primary_source}</small></div>{['high', 'critical'].includes(item.impact_level) ? <StatusPill tone="warning">高影响</StatusPill> : null}</article>)}{!calendar.isLoading && !calendar.data?.items.length && <StateView title="未来 30 天没有事件" message="这里只展示当前持仓和自选股相关事件。"/>}</div></>}

    {segment === 'reports' && <>{reports.isLoading && <LoadingState rows={6}/>}<div className="movement-report-list">{reports.data?.map(report => <button className="movement-report-card" key={report.id} onClick={() => openReport(report.id)}><div><StatusPill tone={report.confidence === '高' ? 'positive' : report.confidence === '低' ? 'warning' : 'neutral'}>{report.confidence ? `置信度 ${report.confidence}` : reportLabels[report.report_type] || '异动研究'}</StatusPill><time>{formatDateTime(report.created_at)}</time></div><h2>{report.title}</h2><p>{report.ticker || '市场'} · {report.model}</p><b>阅读报告 ›</b></button>)}{!reports.isLoading && !reports.data?.length && <StateView title="还没有异动报告" message="价格异动调查完成后，报告会出现在这里。"/>}</div></>}
  </IOSPage></>
}

function NewsCard({ item, summarize, sending }: { item: NewsItem; summarize: (force: boolean) => void; sending: boolean }) {
  const working = ['queued', 'processing'].includes(item.ai_summary_status)
  return <article className="mobile-news-card"><div className="mobile-news-meta"><span>{item.provider === 'yfinance' ? 'Yahoo 财经' : item.provider}</span>{item.topic && <em>{item.topic}</em>}{(item.importance_score || 0) >= .65 && <b>重要</b>}<time>{formatDateTime(item.published_at || item.found_at)}</time></div><a href={item.url} target="_blank" rel="noreferrer"><h2>{item.translated_title || item.title}</h2></a>{item.translated_title && item.translated_title !== item.title && <p className="original-title">{item.title}</p>}{item.summary && <p className="news-excerpt">{item.summary}</p>}<button className="news-ai-button" onClick={() => summarize(Boolean(item.ai_summary))} disabled={working || sending}>{working ? item.ai_summary_status === 'queued' ? 'AI 总结排队中…' : 'AI 正在总结…' : sending ? '正在提交…' : item.ai_summary_status === 'failed' ? '重试 AI 总结' : item.ai_summary ? '重新总结' : 'AI 总结'}</button>{item.ai_summary && <div className="mobile-ai-summary"><span>AI · {item.ai_summary_model || '研究模型'}</span><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{item.ai_summary}</ReactMarkdown></div>}{item.ai_summary_status === 'failed' && <small className="inline-error">AI 总结失败，请点击重试。</small>}</article>
}
