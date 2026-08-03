import { useEffect, useReducer, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, clearToken, getToken, type AuthUser } from '@shared/api'
import { AuthGate } from './AuthGate'
import { Icon } from './icons'
import { initialNavigation, navigationReducer, type DetailRoute, type RootTab } from './navigation'
import { ActivityPage } from './pages/ActivityPage'
import { ChatPage } from './pages/ChatPage'
import { CandidateDetailPage, PositionDetailPage, ReportsPage, StockDetailPage, WatchlistPage } from './pages/DetailPages'
import { DiscoveryPage } from './pages/DiscoveryPage'
import { DynamicPage } from './pages/DynamicPage'
import { FundamentalsPage } from './pages/FundamentalsPage'
import { MorePage } from './pages/MorePage'
import { OverviewPage } from './pages/OverviewPage'
import { JournalPage } from './pages/JournalPage'

const tabs: { key: RootTab; label: string; icon: string }[] = [
  { key: 'overview', label: '主页', icon: 'overview' },
  { key: 'dynamic', label: '动态', icon: 'news' },
  { key: 'chat', label: 'Chat', icon: 'chat' },
  { key: 'fundamentals', label: '基本面', icon: 'fundamentals' },
  { key: 'more', label: '更多', icon: 'more' },
]

export default function App() {
  const [navigation, dispatch] = useReducer(navigationReducer, initialNavigation)
  const [tokenVersion, setTokenVersion] = useState(0)
  const queryClient = useQueryClient()
  const token = getToken()
  const user = useQuery({ queryKey: ['ios-auth-user', tokenVersion], queryFn: () => api<AuthUser>('/auth/me'), enabled: !!token, retry: false })
  useEffect(() => { const logout = () => setTokenVersion(value => value + 1); window.addEventListener('auth:logout', logout); return () => window.removeEventListener('auth:logout', logout) }, [])
  useEffect(() => { if ('serviceWorker' in navigator && import.meta.env.PROD) navigator.serviceWorker.register('./sw.js').catch(() => undefined) }, [])

  if (!token || user.isError) return <AuthGate authenticated={() => setTokenVersion(value => value + 1)}/>
  if (user.isLoading || !user.data) return <div className="launch-screen"><div className="app-mark">↗</div><span>正在安全连接…</span></div>

  const push = (route: DetailRoute) => dispatch({ type: 'push', route })
  const detail = navigation.stack.at(-1)
  if (detail) {
    const back = () => dispatch({ type: 'back' })
    if (detail.kind === 'stock') return <StockDetailPage symbol={String(detail.id)} back={back}/>
    if (detail.kind === 'position') return <PositionDetailPage symbol={String(detail.id)} back={back}/>
    if (detail.kind === 'candidate') return <CandidateDetailPage id={Number(detail.id)} back={back}/>
    if (detail.kind === 'watchlist') return <WatchlistPage back={back} openStock={symbol => push({ kind: 'stock', id: symbol })}/>
    if (detail.kind === 'reports') return <ReportsPage back={back} initialId={detail.id == null ? null : Number(detail.id)}/>
    if (detail.kind === 'activity') return <ActivityPage back={back} initialSegment={detail.segment || 'news'} initialTicker={typeof detail.id === 'string' ? detail.id : ''} openReport={id => push({ kind: 'reports', id })}/>
    if (detail.kind === 'discovery') return <DiscoveryPage back={back} openCandidate={id => push({ kind: 'candidate', id })}/>
    if (detail.kind === 'journal') return <JournalPage back={back} initialMode={detail.mode || 'list'} initialLogId={typeof detail.id === 'number' ? detail.id : null}/>
  }

  const pages: Record<RootTab, ReactNode> = {
    overview: <OverviewPage username={user.data.username} openStock={symbol => push({ kind: 'stock', id: symbol })} openPosition={symbol => push({ kind: 'position', id: symbol })} openActivity={section => push({ kind: 'activity', segment: section === 'movement' ? 'reports' : 'news' })} openReport={id => push({ kind: 'reports', id })} openJournal={request => push({ kind: 'journal', id: request.mode === 'edit' ? request.id : undefined, mode: request.mode === 'new' ? 'new' : 'list' })}/>,
    dynamic: <DynamicPage/>,
    chat: <ChatPage/>,
    fundamentals: <FundamentalsPage/>,
    more: <MorePage user={user.data} openDiscovery={() => push({ kind: 'discovery' })} openWatchlist={() => push({ kind: 'watchlist' })} openReports={() => push({ kind: 'reports' })} logout={() => { clearToken(); queryClient.clear(); setTokenVersion(value => value + 1) }}/>,
  }

  return <div className="ios-app"><div className="ambient-orb one"/><div className="ambient-orb two"/><div className="page-stage" key={navigation.tab}>{pages[navigation.tab]}</div><nav className="tab-bar glass" aria-label="主导航">{tabs.map(tab => <button key={tab.key} className={navigation.tab === tab.key ? 'active' : ''} aria-current={navigation.tab === tab.key ? 'page' : undefined} onClick={() => dispatch({ type: 'tab', tab: tab.key })}><Icon name={tab.icon}/><span>{tab.label}</span></button>)}</nav></div>
}
