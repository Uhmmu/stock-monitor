import { useQuery } from '@tanstack/react-query'
import { api, clearToken } from '@shared/api'
import type { AuthUser } from '@shared/api'
import type { Report, WatchItem } from '@shared/types'
import { IOSPage, InsetList, ListRow } from '../components'
import { Icon } from '../icons'

export function MorePage({ user, openWatchlist, openReports, openDiscovery, logout }: { user: AuthUser; openWatchlist: () => void; openReports: () => void; openDiscovery: () => void; logout: () => void }) {
  const watchlist = useQuery({ queryKey: ['ios-watchlist-count'], queryFn: () => api<WatchItem[]>('/watchlist'), staleTime: 60_000 })
  const reports = useQuery({ queryKey: ['ios-report-count'], queryFn: () => api<Report[]>('/reports'), staleTime: 60_000 })
  const useDesktop = () => { localStorage.setItem('preferred_ui', 'desktop'); window.location.assign('/') }
  const signOut = () => { clearToken(); logout() }
  return <IOSPage>
    <section className="large-title"><span>MORE</span><h1>更多</h1></section>
    <section className="profile-card"><span>{user.username.slice(0, 1).toUpperCase()}</span><div><strong>{user.username}</strong><small>{user.role === 'admin' ? '管理员' : '已安全连接'}</small></div></section>
    <InsetList label="研究资料">
      <ListRow title="机会发现" subtitle="查看组合之外的研究候选" icon={<Icon name="discovery"/>} onClick={openDiscovery}/>
      <ListRow title="自选股" subtitle="查看当前监控证券" value={watchlist.data?.length ?? '—'} icon={<Icon name="overview"/>} onClick={openWatchlist}/>
      <ListRow title="智能报告" subtitle="阅读完整分析报告" value={reports.data?.length ?? '—'} icon={<Icon name="news"/>} onClick={openReports}/>
    </InsetList>
    <InsetList label="桌面端高级功能">
      <ListRow title="技术分析" subtitle="复杂周线图、热力区与价格提醒" onClick={useDesktop}/>
      <ListRow title="组合高级分析" subtitle="压力测试、模拟与优化" onClick={useDesktop}/>
      <ListRow title="交易日志与管理设置" subtitle="写入和管理工作流继续使用桌面版" onClick={useDesktop}/>
    </InsetList>
    <InsetList label="界面">
      <ListRow title="切换到桌面版" subtitle="选择会保存在本机" onClick={useDesktop}/>
    </InsetList>
    <button className="logout-row" onClick={signOut}>退出登录</button>
    <p className="version-note">iPhone 前端 · 第一阶段</p>
  </IOSPage>
}
