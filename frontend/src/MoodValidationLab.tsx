import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import { Sheet } from './Sheet'
import './mood-validation.css'

type MetricStats = { n?: number; status?: string; mean?: number; median?: number; p25?: number; p75?: number; positive_rate?: number; median_ci?: { low: number; high: number } | null }
type Result = {
  id: number; study_type: string; scope_type: string | null; scope_key: string | null; state: string | null
  transition_from: string | null; transition_to: string | null; divergence_type: string | null; bucket: string | null
  horizon: number | null; sample_mode: string; sample_count: number; metrics: Record<string, any>; quality: string
  warnings: string[]; event_refs: { snapshot_id?: number; scope_key?: string; date?: string; entry_date?: string; duration?: number }[]
}
type Run = { run_id: number; status: string; progress: number; engine_version: string; calculation_version: string; validation_version: string; date_from: string; date_to: string; data_cutoff: string; coverage: { scope_count?: number; snapshot_count?: number; scopes?: Record<string, any>[] }; warnings: string[]; error_message?: string | null }
type Overview = { status: string; run?: Run; studies?: Record<string, Result[]>; limitations?: string[]; available_range?: { from?: string; to?: string; snapshots?: number }; calculation_version?: string; validation_version?: string }
type Snapshot = { snapshot_id: number; scope_type: string; scope_key: string; trading_date: string; state: string; candidate_state: string | null; confidence: number | null; agreement: number | null; quality: number | null; coverage: number | null; signals: Record<string, any>[]; evidence: Record<string, any>; divergences: Record<string, any>[]; transition: Record<string, any> }
type HistoryHealthStatus = 'HEALTHY' | 'DEGRADED' | 'PARTIAL' | 'FAILED' | 'UNAVAILABLE'
export type HistoryHealth = {
  health_status: HistoryHealthStatus
  latest_eod: string | null
  oldest_eod: string | null
  history_days: number
  complete_days: number
  partial_days: number
  today: {
    trading_date: string | null
    status: string | null
    expected: number
    generated: number
    coverage: number
    missing_scopes: string[]
    insufficient_scopes: string[]
    failed_scopes: string[]
    stale_sources: string[]
  }
  quality_distribution: { high: number; medium: number; low: number; insufficient: number }
  source_health: Record<string, { status: string; count: number }>
  calendar: { trading_date: string; status: string; coverage: number }[]
  maturity: { matured_1d_samples: number; matured_5d_samples: number; matured_20d_samples: number; matured_60d_samples: number }
  warnings: string[]
}

const STATE_LABELS: Record<string, string> = {
  DORMANT: '休眠', EARLY_IMPROVEMENT: '早期改善', ACCUMULATION: '积累', EXPANSION: '扩张', LEADERSHIP: '领涨',
  CROWDED: '拥挤', DISTRIBUTION: '派发', DETERIORATION: '恶化', BREAKDOWN: '破位', INSUFFICIENT_DATA: '数据不足',
  TRENDING_UP: '上行', IMPROVING: '改善', NEUTRAL: '中性', WEAKENING: '走弱', TRENDING_DOWN: '下行', STRETCHED: '过度延伸',
}
const label = (value: string | null | undefined) => value ? STATE_LABELS[value] || value : '—'
const percent = (value: unknown) => typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '数据不足'
const number = (value: unknown, digits = 1) => typeof value === 'number' ? value.toFixed(digits) : '数据不足'
const pctPoint = (value: unknown) => typeof value === 'number' ? `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%` : '数据不足'
const study = (overview: Overview | undefined, name: string) => overview?.studies?.[name] || []

const HISTORY_HEALTH_LABELS: Record<string, string> = {
  HEALTHY: '健康', DEGRADED: '降级', PARTIAL: '部分完成', FAILED: '失败', UNAVAILABLE: '暂无数据',
}
const HEALTH_DETAIL_LABELS: Record<string, string> = {
  HEALTHY: '健康', READY: '健康', FRESH: '新鲜', DEGRADED: '降级', PARTIAL: '部分可用',
  STALE: '陈旧', MISSING: '缺失', FAILED: '失败', ERROR: '失败', UNAVAILABLE: '暂无数据',
}
const CALENDAR_STATUS_LABELS: Record<string, string> = {
  HEALTHY: '完整', READY: '完整', PARTIAL: '部分', DEGRADED: '降级', MISSING: '缺失', FAILED: '失败',
  NON_TRADING: '非交易日', UNAVAILABLE: '暂无',
}

const statusKey = (value: string | null | undefined) => String(value || 'UNAVAILABLE').toUpperCase()
const healthStatusLabel = (value: string | null | undefined) => HISTORY_HEALTH_LABELS[statusKey(value)] || value || '暂无数据'
const detailStatusLabel = (value: string | null | undefined) => HEALTH_DETAIL_LABELS[statusKey(value)] || value || '状态未知'
const calendarStatusLabel = (value: string | null | undefined) => CALENDAR_STATUS_LABELS[statusKey(value)] || value || '状态未知'
const historyCoverage = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` : '数据不足'
const historyCount = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? String(value) : '数据不足'
const scopeText = (values: string[]) => values.length ? values.join('、') : '无'
const dayText = (value: string | null | undefined) => value || '—'

export function HistoryHealthPanel({ health, loading = false, error = false }: { health?: HistoryHealth; loading?: boolean; error?: boolean }) {
  return <section className="mood-history-health mood-lab-panel" aria-labelledby="mood-history-health-title">
    <div className="mood-lab-section-head"><div><p className="eyebrow">HISTORY HEALTH</p><h2 id="mood-history-health-title">Mood 历史健康</h2></div>{health && <span className={`mood-history-health-status health-status-${statusKey(health.health_status).toLowerCase()}`}>{healthStatusLabel(health.health_status)}</span>}</div>
    {loading && <div className="mood-history-health-state" aria-busy="true" role="status">正在读取 Mood 历史健康…</div>}
    {error && <div className="mood-history-health-state error" role="alert">历史健康暂时无法读取；不影响验证结果。</div>}
    {!loading && !error && !health && <div className="mood-history-health-state">暂无 Mood 历史健康数据。</div>}
    {health && <>
      <div className="mood-history-health-summary">
        <Metric label="最新 EOD" value={dayText(health.latest_eod)} detail={`最早 ${dayText(health.oldest_eod)}`} />
        <Metric label="历史天数" value={`${historyCount(health.history_days)} 天`} detail={`完整 ${historyCount(health.complete_days)} · 部分 ${historyCount(health.partial_days)}`} />
        <Metric label="今日覆盖" value={`${historyCount(health.today.generated)}/${historyCount(health.today.expected)}`} detail={`${dayText(health.today.trading_date)} · ${historyCoverage(health.today.coverage)} · ${detailStatusLabel(health.today.status)}`} />
      </div>
      <div className="mood-history-health-facts">
        <div><span>缺失 scopes</span><strong>{health.today.missing_scopes.length || '无'}</strong><small>{scopeText(health.today.missing_scopes)}</small></div>
        <div><span>数据不足 scopes</span><strong>{health.today.insufficient_scopes.length || '无'}</strong><small>{scopeText(health.today.insufficient_scopes)}</small></div>
        <div><span>失败 scopes</span><strong>{health.today.failed_scopes.length || '无'}</strong><small>{scopeText(health.today.failed_scopes)}</small></div>
        <div><span>陈旧来源</span><strong>{health.today.stale_sources.length || '无'}</strong><small>{scopeText(health.today.stale_sources)}</small></div>
      </div>
      <div className="mood-history-health-columns">
        <section><div className="mood-history-health-subhead"><h3>质量分布</h3><small>仅表示数据证据质量</small></div><div className="mood-history-health-quality">{([['high', '高'], ['medium', '中'], ['low', '低'], ['insufficient', '不足']] as const).map(([key, text]) => <div key={key}><span>{text}</span><strong>{historyCount(health.quality_distribution[key])}</strong></div>)}</div></section>
        <section><div className="mood-history-health-subhead"><h3>来源状态</h3><small>今日已记录</small></div><div className="mood-history-health-sources">{Object.entries(health.source_health).map(([source, value]) => <span key={source} className={`health-detail-${statusKey(value.status).toLowerCase()}`}><b>{source}</b><em>{detailStatusLabel(value.status)} · {historyCount(value.count)}</em></span>)}{!Object.keys(health.source_health).length && <small>暂无来源统计。</small>}</div></section>
      </div>
      <section><div className="mood-history-health-subhead"><h3>结果成熟度</h3><small>达到对应 forward horizon 的样本</small></div><div className="mood-history-health-maturity"><Metric label="1D" value={historyCount(health.maturity.matured_1d_samples)} /><Metric label="5D" value={historyCount(health.maturity.matured_5d_samples)} /><Metric label="20D" value={historyCount(health.maturity.matured_20d_samples)} /><Metric label="60D" value={historyCount(health.maturity.matured_60d_samples)} /></div></section>
      <section><div className="mood-history-health-subhead"><h3>历史连续性</h3><small>{health.calendar.length ? `最近 ${Math.min(health.calendar.length, 14)} 个交易日` : '暂无交易日记录'}</small></div>{health.calendar.length ? <div className="mood-history-health-calendar" aria-label="Mood 历史连续性日历">{health.calendar.slice(-14).map(day => <div className={`mood-history-health-day health-detail-${statusKey(day.status).toLowerCase()}`} key={day.trading_date}><time>{day.trading_date.slice(5)}</time><b>{calendarStatusLabel(day.status)}</b><small>{historyCoverage(day.coverage)}</small></div>)}</div> : <p className="mood-history-health-empty">暂无可显示的交易日历史。</p>}</section>
      {health.warnings.length > 0 && <div className="mood-history-health-warnings" role="status"><b>监控提示</b>{health.warnings.slice(0, 4).map(warning => <span key={warning}>{warning}</span>)}</div>}
    </>}
  </section>
}

export function transitionCells(rows: Result[]) {
  const states = Array.from(new Set(rows.flatMap(row => [row.transition_from, row.transition_to]).filter(Boolean) as string[]))
  const maximum = Math.max(1, ...rows.map(row => row.sample_count))
  return { states, maximum, byPair: new Map(rows.map(row => [`${row.transition_from}:${row.transition_to}`, row])) }
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="mood-lab-metric"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>
}

function SampleBadge({ row }: { row: Result }) {
  return <span className={`mood-lab-sample ${row.quality === 'READY' ? 'ready' : ''}`}>n={row.sample_count}{row.quality === 'READY' ? '' : ' · 样本不足'}</span>
}

function SnapshotDetail({ snapshot }: { snapshot: Snapshot }) {
  return <div className="mood-lab-detail">
    <div className="mood-lab-metrics"><Metric label="正式状态" value={label(snapshot.state)} /><Metric label="候选状态" value={label(snapshot.candidate_state)} /><Metric label="置信度" value={percent(snapshot.confidence)} /><Metric label="Agreement" value={percent(snapshot.agreement)} /><Metric label="Quality" value={percent(snapshot.quality)} /><Metric label="Coverage" value={percent(snapshot.coverage)} /></div>
    <section><h3>当时信号</h3><div className="mood-lab-signal-list">{snapshot.signals.map((item, index) => <div key={`${item.signal_id || 'signal'}-${index}`}><b>{item.category || 'unknown'}</b><span>{item.metric || item.signal_id}</span><strong>{item.normalized_score == null ? '缺失' : number(item.normalized_score)}</strong><small>{item.source} · {item.status}</small></div>)}</div></section>
    <section><h3>状态迁移</h3><pre>{JSON.stringify(snapshot.transition, null, 2)}</pre></section>
    <section><h3>分歧</h3><pre>{JSON.stringify(snapshot.divergences, null, 2)}</pre></section>
  </div>
}

export function MoodValidationLab({ enabled = true, isAdmin = false }: { enabled?: boolean; isAdmin?: boolean }) {
  const client = useQueryClient()
  const [scope, setScope] = useState('market')
  const [state, setState] = useState('EXPANSION')
  const [horizon, setHorizon] = useState(20)
  const [snapshotId, setSnapshotId] = useState<number | null>(null)
  const overviewQuery = useQuery({
    queryKey: ['mood-lab', 'overview'], queryFn: () => api<Overview>('/mood-lab/overview'), enabled,
    refetchInterval: query => ['pending', 'running'].includes(query.state.data?.status || '') ? 8000 : false,
  })
  const historyHealthQuery = useQuery({
    queryKey: ['mood', 'history-health'], queryFn: () => api<HistoryHealth>('/mood/history-health'), enabled,
    staleTime: 60_000, retry: 1,
  })
  const runMutation = useMutation({
    mutationFn: () => post<Run>('/mood-lab/runs', {}),
    onSuccess: () => client.invalidateQueries({ queryKey: ['mood-lab'] }),
  })
  const snapshotQuery = useQuery({ queryKey: ['mood-lab', 'snapshot', snapshotId], queryFn: () => api<Snapshot>(`/mood-lab/snapshots/${snapshotId}`), enabled: snapshotId != null })
  const overview = overviewQuery.data
  const run = overview?.run
  const occupancy = study(overview, 'state_occupancy').filter(row => row.scope_type === scope)
  const transitions = study(overview, 'transition').filter(row => row.scope_type === scope)
  const divergences = study(overview, 'divergence').filter(row => row.scope_type === scope)
  const confidence = study(overview, 'confidence_calibration').filter(row => row.scope_type === scope)
  const agreement = study(overview, 'agreement_calibration').filter(row => row.scope_type === scope)
  const outcomes = study(overview, 'state_outcome').filter(row => row.scope_type === scope && row.state === state && row.horizon === horizon && row.sample_mode === 'episode_entry')
  const evidence = study(overview, 'evidence_contribution').filter(row => row.scope_type === scope)
  const matrix = useMemo(() => transitionCells(transitions), [transitions])

  if (!enabled) return <div className="mood-lab-state">演示模式不运行历史研究。</div>
  if (overviewQuery.isLoading) return <div className="mood-lab-state">正在读取验证结果…</div>
  if (overviewQuery.isError) return <div className="mood-lab-state error">验证结果暂时无法读取。</div>

  return <section className="mood-lab" aria-label="Mood Validation and Calibration Lab">
    <div className="mood-lab-head"><div><p className="eyebrow">VALIDATION & CALIBRATION LAB</p><h1>Mood 验证实验室</h1><p>只读历史验证。研究结果不会修改生产状态、阈值或权重。</p></div><div className="mood-lab-actions"><label>研究范围<select value={scope} onChange={event => setScope(event.target.value)}><option value="market">市场</option><option value="sector">行业</option><option value="ai_chain">AI 链</option><option value="watchlist">自选股</option></select></label>{isAdmin && <button type="button" disabled={runMutation.isPending || ['pending', 'running'].includes(run?.status || '')} onClick={() => runMutation.mutate()}>{['pending', 'running'].includes(run?.status || '') ? `验证中 ${run?.progress || 0}%` : '创建验证运行'}</button>}</div></div>
    <HistoryHealthPanel health={historyHealthQuery.data} loading={historyHealthQuery.isLoading} error={historyHealthQuery.isError} />
    {!run && <div className="mood-lab-notice">尚无研究运行。{isAdmin ? '创建后将在后台消费已存 Mood 快照。' : '请由管理员创建验证运行。'}{overview?.available_range && ` 可用快照范围 ${overview.available_range.from || '—'} 至 ${overview.available_range.to || '—'}。`}</div>}
    {run?.status === 'failed' && <div className="mood-lab-notice error">运行失败：{run.error_message || '未知错误'}</div>}
    {run && <div className="mood-lab-metrics"><Metric label="Engine" value={run.engine_version} detail={run.calculation_version} /><Metric label="Validation" value={run.validation_version} /><Metric label="历史范围" value={`${run.date_from} → ${run.date_to}`} detail={`outcome cutoff ${run.data_cutoff}`} /><Metric label="有效快照" value={String(run.coverage?.snapshot_count || 0)} detail={`${run.coverage?.scope_count || 0} scopes`} /><Metric label="运行状态" value={run.status.toUpperCase()} detail={`${run.progress}%`} /></div>}
    {(run?.warnings?.length || overview?.limitations?.length) ? <div className="mood-lab-notice"><b>研究边界</b>{[...(run?.warnings || []), ...(overview?.limitations || [])].slice(0, 6).map(item => <span key={item}>{item}</span>)}</div> : null}

    {run?.status === 'completed' && <>
      <section className="mood-lab-panel"><div className="mood-lab-section-head"><div><p className="eyebrow">STATE DISTRIBUTION</p><h2>状态分布与持续性</h2></div><small>日观察与 episode 分开计算</small></div><div className="mood-lab-table"><div className="head"><b>状态</b><b>占比</b><b>Episodes</b><b>中位时长</b><b>1日反转</b><b>样本</b></div>{occupancy.map(row => <button type="button" key={row.id} onClick={() => row.event_refs[0]?.snapshot_id && setSnapshotId(row.event_refs[0].snapshot_id)}><b>{label(row.state)}</b><span>{percent(row.metrics.percentage)}</span><span>{row.metrics.episode_count ?? '—'}</span><span>{row.metrics.median_duration == null ? '—' : `${number(row.metrics.median_duration)} 日`}</span><span>{percent(row.metrics.one_day_reversal_rate)}</span><SampleBadge row={row} /></button>)}</div></section>

      <section className="mood-lab-panel"><div className="mood-lab-section-head"><div><p className="eyebrow">STATE OUTCOME</p><h2>状态进入后的分布</h2></div><div className="mood-lab-filters"><select value={state} onChange={event => setState(event.target.value)}>{occupancy.map(row => <option value={row.state || ''} key={row.state}>{label(row.state)}</option>)}</select><select value={horizon} onChange={event => setHorizon(Number(event.target.value))}>{[1, 5, 10, 20, 60].map(value => <option value={value} key={value}>{value}D</option>)}</select></div></div>{outcomes.length ? outcomes.map(row => { const returns = row.metrics.return as MetricStats; const risk = row.metrics.max_drawdown as MetricStats; return <div className="mood-lab-outcome" key={row.id}><Metric label="中位收益" value={pctPoint(returns?.median)} detail={returns?.median_ci ? `95% CI ${pctPoint(returns.median_ci.low)} → ${pctPoint(returns.median_ci.high)}` : '置信区间样本不足'} /><Metric label="均值 / P25–P75" value={pctPoint(returns?.mean)} detail={`${pctPoint(returns?.p25)} → ${pctPoint(returns?.p75)}`} /><Metric label="正收益率" value={percent(returns?.positive_rate)} /><Metric label="最大回撤中位数" value={pctPoint(risk?.median)} /><SampleBadge row={row} /></div>}) : <p className="mood-lab-empty">该筛选没有完整 forward outcome。</p>}</section>

      <section className="mood-lab-panel"><div className="mood-lab-section-head"><div><p className="eyebrow">TRANSITION MATRIX</p><h2>正式状态迁移</h2></div><small>颜色越深，历史次数越多</small></div>{matrix.states.length ? <div className="mood-lab-matrix" style={{ gridTemplateColumns: `minmax(90px,1.2fr) repeat(${matrix.states.length},minmax(48px,1fr))` }}><span />{matrix.states.map(to => <b key={`to-${to}`}>{label(to)}</b>)}{matrix.states.flatMap(from => [<b key={`from-${from}`}>{label(from)}</b>, ...matrix.states.map(to => { const row = matrix.byPair.get(`${from}:${to}`); return <button type="button" key={`${from}-${to}`} disabled={!row} style={{ '--heat': row ? row.sample_count / matrix.maximum : 0 } as React.CSSProperties} onClick={() => row?.event_refs[0]?.snapshot_id && setSnapshotId(row.event_refs[0].snapshot_id)}>{row?.sample_count || '·'}</button> })])}</div> : <p className="mood-lab-empty">尚无正式状态迁移。</p>}</section>

      <section className="mood-lab-grid"><div className="mood-lab-panel"><div className="mood-lab-section-head"><div><p className="eyebrow">DIVERGENCE</p><h2>分歧 Episodes</h2></div></div><div className="mood-lab-rows">{divergences.map(row => <button type="button" key={row.id} onClick={() => row.event_refs[0]?.snapshot_id && setSnapshotId(row.event_refs[0].snapshot_id)}><span><b>{row.divergence_type}</b><small>{row.bucket} · 中位 {number(row.metrics.median_duration)} 日</small></span><span><strong>{row.sample_count}</strong><small>解决 {percent(row.metrics.resolution_rate)}</small></span></button>)}{!divergences.length && <p className="mood-lab-empty">该范围没有分歧 episode。</p>}</div></div>
      <div className="mood-lab-panel"><div className="mood-lab-section-head"><div><p className="eyebrow">CALIBRATION</p><h2>Confidence / Agreement</h2></div></div><div className="mood-lab-calibration"><b>Bucket</b><b>n</b><b>1D</b><b>3D</b><b>5D</b><b>反转</b>{[...confidence, ...agreement].map(row => <div className="contents" key={row.id}><span>{row.study_type.startsWith('confidence') ? 'C ' : 'A '}{row.bucket}</span><span>{row.sample_count}</span><span>{percent(row.metrics.persistence_1d)}</span><span>{percent(row.metrics.persistence_3d)}</span><span>{percent(row.metrics.persistence_5d)}</span><span>{percent(row.metrics.rapid_reversal_rate)}</span></div>)}</div></div></section>

      <section className="mood-lab-panel"><div className="mood-lab-section-head"><div><p className="eyebrow">EVIDENCE CONTRIBUTION</p><h2>实际有效证据权重</h2></div><small>按状态与 category 汇总</small></div><div className="mood-lab-bars">{evidence.sort((a, b) => (b.metrics.mean_effective_weight || 0) - (a.metrics.mean_effective_weight || 0)).slice(0, 18).map(row => <div key={row.id}><span>{label(row.state)} · {row.bucket}</span><i><em style={{ width: `${Math.min(100, (row.metrics.mean_effective_weight || 0) * 400)}%` }} /></i><b>{number(row.metrics.mean_effective_weight, 3)}</b><small>n={row.sample_count}</small></div>)}</div></section>
    </>}
    <Sheet open={snapshotId != null} onClose={() => setSnapshotId(null)} title={snapshotQuery.data ? `${snapshotQuery.data.scope_key} · ${snapshotQuery.data.trading_date}` : '历史样本'} size="wide">{snapshotQuery.isLoading ? <div className="mood-lab-state">读取样本…</div> : snapshotQuery.data ? <SnapshotDetail snapshot={snapshotQuery.data} /> : <div className="mood-lab-state">样本不可用。</div>}</Sheet>
  </section>
}
