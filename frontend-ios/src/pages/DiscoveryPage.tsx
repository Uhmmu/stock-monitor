import { useQuery } from '@tanstack/react-query'
import { api } from '@shared/api'
import { formatDateTime } from '@shared/format'
import type { DiscoveryCandidate, LatestDiscovery } from '@shared/types'
import { IOSPage, LoadingState, NavigationBar, SectionHeader, StateView, StatusPill } from '../components'

const statusTone = (status: string) => status === 'accepted' ? 'positive' : status === 'rejected' ? 'negative' : 'warning' as const

export function DiscoveryPage({ openCandidate, back }: { openCandidate: (id: number) => void; back?: () => void }) {
  const latest = useQuery({ queryKey: ['ios-discovery'], queryFn: () => api<LatestDiscovery>('/discovery/latest'), staleTime: 30_000 })
  const result = latest.data?.result
  if (latest.isLoading) return <>{back && <NavigationBar title="机会发现" eyebrow="组合之外" back={back}/>}<IOSPage className="detail-page"><LoadingState rows={6}/></IOSPage></>
  if (latest.isError) return <>{back && <NavigationBar title="机会发现" eyebrow="组合之外" back={back}/>}<IOSPage className="detail-page"><StateView title="读取失败" message="已保存的机会结果暂时不可用。" retry={() => latest.refetch()}/></IOSPage></>
  return <>{back && <NavigationBar title="机会发现" eyebrow="组合之外" back={back}/>}<IOSPage className={back ? 'detail-page' : ''}>
    <section className="large-title"><span>DISCOVERY</span><h1>机会发现</h1><p>组合之外，值得进一步研究的方向。</p></section>
    {!result ? <StateView title="还没有发现结果" message="首次付费发现与参数配置请暂时在桌面端完成。"/> : <>
      <section className="discovery-summary"><div><span>本批保留</span><strong>{result.counts.accepted}</strong><small>来自 {result.counts.raw} 个原始候选</small></div><div><span>仅观察</span><strong>{result.counts.watch_only}</strong><small>{latest.data?.using_previous_result ? '显示上一批成功结果' : formatDateTime(result.analysis_date)}</small></div></section>
      {result.groups.map(group => <section className="candidate-section" key={group.id}><SectionHeader title={group.name} caption={group.summary}/><div className="candidate-list">{group.candidates.map(candidate => <CandidateCard candidate={candidate} key={candidate.id} open={() => openCandidate(candidate.id)}/>)}</div></section>)}
      {!result.groups.some(group => group.candidates.length) && <StateView title="没有通过筛选的候选" message="本地验证保留了过滤原因，完整记录可在桌面端查看。"/>}
      <p className="disclaimer">机会发现只用于生成研究对象，不构成买入或卖出建议。</p>
    </>}
  </IOSPage></>
}

function CandidateCard({ candidate, open }: { candidate: DiscoveryCandidate; open: () => void }) {
  return <button className="candidate-card" onClick={open}><div><span className="stock-avatar">{(candidate.normalized_ticker || candidate.raw_ticker).slice(0, 2)}</span><span><strong>{candidate.normalized_ticker || candidate.raw_ticker}</strong><small>{candidate.company_name}</small></span><StatusPill tone={statusTone(candidate.display_status)}>置信度 {candidate.confidence ?? '—'}</StatusPill></div><p>{candidate.discovery_reason || candidate.why_now || '等待更多研究资料'}</p><footer><span>{candidate.groups[0]?.name || '研究候选'}</span><b>查看研究摘要 ›</b></footer></button>
}
