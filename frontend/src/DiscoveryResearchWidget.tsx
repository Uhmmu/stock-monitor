import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { type DiscoveryRunMeta } from './OpportunityDiscovery'
import {
  Spring, SPRINGS, animateSpring, VelocityTracker,
  projectMomentum, clampRubber, prefersReducedMotion, haptic,
} from './motion'

// 全局机会发现研究悬浮窗:离开机会发现页面后仍显示后台研究进度。
// · 圆环进度来自 /discovery/latest 的真实 progress / eta(后端混合阶段+历史时长模型)
// · 可拖动(阈值区分点击),位置持久化到 localStorage,限制在 viewport 内
// · 关闭(×)只是隐藏悬浮 UI,绝不取消后台研究;完成后会再提醒一次
// · 用户回到机会发现页面自动隐藏并标记已读
export type ResearchRunMeta = DiscoveryRunMeta & {
  progress?: number | null
  eta_seconds?: number | null
  expected_duration_seconds?: number | null
}
type LatestResearch = { current_run: ResearchRunMeta | null }
type WidgetMode = 'running' | 'completed' | 'failed'
export type WidgetView = { mode: WidgetMode; run: ResearchRunMeta } | null

export type WidgetPrefs = {
  x: number | null
  y: number | null
  dismissedRunId: number | null      // 运行中手动关闭:完成后仍会提醒一次
  dismissedDoneRunId: number | null  // 完成态手动关闭:该 run 不再打扰
  seenRunId: number | null           // 已在机会发现页面看过结果
}

const PREFS_KEY = 'stock-monitor:research-widget:v1'
const MARGIN = 16
const DRAG_THRESHOLD = 8

export function loadWidgetPrefs(): WidgetPrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (!raw) return emptyPrefs()
    const parsed = JSON.parse(raw) as Partial<WidgetPrefs>
    return {
      x: typeof parsed.x === 'number' ? parsed.x : null,
      y: typeof parsed.y === 'number' ? parsed.y : null,
      dismissedRunId: numberOrNull(parsed.dismissedRunId),
      dismissedDoneRunId: numberOrNull(parsed.dismissedDoneRunId),
      seenRunId: numberOrNull(parsed.seenRunId),
    }
  } catch {
    return emptyPrefs()
  }
}

export function saveWidgetPrefs(prefs: WidgetPrefs): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)) } catch { /* 忽略隐私模式等写入失败 */ }
}

function emptyPrefs(): WidgetPrefs {
  return { x: null, y: null, dismissedRunId: null, dismissedDoneRunId: null, seenRunId: null }
}
function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function computeWidgetView(run: ResearchRunMeta | null | undefined, prefs: WidgetPrefs): WidgetView {
  if (!run) return null
  if (run.status === 'pending' || run.status === 'running') {
    if (prefs.dismissedRunId === run.id) return null
    return { mode: 'running', run }
  }
  // 完成与失败都属于"结果待查看":看过或明确关闭过完成提醒才隐藏
  if (prefs.seenRunId === run.id || prefs.dismissedDoneRunId === run.id) return null
  const mode: WidgetMode = run.status === 'failed' || run.status === 'blocked_by_budget' ? 'failed' : 'completed'
  return { mode, run }
}

export function clampWidgetPosition(
  x: number, y: number,
  viewport: { width: number; height: number },
  size: { width: number; height: number },
  margin = MARGIN,
): { x: number; y: number } {
  const maxX = Math.max(margin, viewport.width - size.width - margin)
  const maxY = Math.max(margin, viewport.height - size.height - margin)
  return { x: Math.min(Math.max(x, margin), maxX), y: Math.min(Math.max(y, margin), maxY) }
}

export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  if (seconds <= 10) return '即将完成'
  if (seconds < 60) return `~${Math.max(10, Math.round(seconds / 10) * 10)} 秒`
  if (seconds < 3600) return `~${Math.max(1, Math.round(seconds / 60))} 分钟`
  return `~${Math.round(seconds / 3600)} 小时`
}

const activityLabel: Record<string, string> = {
  pi_planning: '规划中', pi_discovering: '探索主题', pi_internal_verification: '内部筛选',
  pi_external_research: '外部研究', pi_counter_evidence: '反方验证', pi_portfolio_fit: '组合适配',
  pi_synthesizing: '生成中', preparing_portfolio: '准备持仓', preparing_local_data: '读取数据',
  budget_check: '检查预算', searching_market: '检索市场', analyzing_with_local_ai: '分析中',
  running_finance_agent: '生成中', running_exa_finance_agent: '深度研究',
  normalizing_candidates: '整理候选', local_verification: '本地验证', applying_filters: '过滤中',
}

export function widgetActivityLabel(stage: string | null | undefined): string {
  if (!stage) return '研究中'
  return activityLabel[stage] || '研究中'
}

export function widgetAriaLabel(view: { mode: WidgetMode; run: ResearchRunMeta }): string {
  const { mode, run } = view
  if (mode === 'completed') return '机会发现研究完成，点击查看结果'
  if (mode === 'failed') return '机会发现研究失败，点击查看原因'
  const eta = formatEta(run.eta_seconds)
  return `机会发现研究进行中 ${run.progress ?? 0}%，${widgetActivityLabel(run.stage)}${eta ? `，${eta}` : ''}。点击返回机会发现页面。`
}

export function ResearchRing({ progress, mode, size = 46 }: { progress: number | null; mode: WidgetMode; size?: number }) {
  const stroke = 3.5
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = mode === 'running' ? Math.min(100, Math.max(0, Math.round(progress ?? 0))) : 100
  const offset = circumference * (1 - clamped / 100)
  return <svg className={`research-widget-ring ${mode}`} width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
    <circle className="ring-track" cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} />
    {mode === 'running' && <circle className="ring-value" cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke}
      strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" />}
    {(mode === 'completed' || mode === 'failed') && <circle className="ring-value is-done" cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke}
      strokeDasharray={circumference} strokeDashoffset={0} strokeLinecap="round" />}
  </svg>
}

export function DiscoveryResearchWidget({ activeTab, onNavigate, enabled = true }: {
  activeTab: string
  onNavigate: (tab: string) => void
  enabled?: boolean
}) {
  const latest = useQuery({
    queryKey: ['discovery-latest'],
    queryFn: () => api<LatestResearch>('/discovery/latest'),
    staleTime: 30_000,
    refetchInterval: query => {
      const status = (query.state.data as LatestResearch | undefined)?.current_run?.status
      return status === 'pending' || status === 'running' ? 8000 : false
    },
    enabled,
  })
  const [prefs, setPrefs] = useState<WidgetPrefs>(() => (typeof localStorage === 'undefined' ? emptyPrefs() : loadWidgetPrefs()))
  const run = latest.data?.current_run ?? null
  const view = computeWidgetView(run, prefs)
  const onDiscovery = activeTab === 'discovery'

  // 回到机会发现页面即视为已查看该 run 的结果
  useEffect(() => {
    if (!onDiscovery || !run) return
    if (!['completed', 'completed_with_warnings', 'failed', 'blocked_by_budget'].includes(run.status)) return
    if (prefs.seenRunId === run.id) return
    const next = { ...prefs, seenRunId: run.id }
    setPrefs(next); saveWidgetPrefs(next)
  }, [onDiscovery, run, prefs])

  const updatePrefs = useCallback((patch: Partial<WidgetPrefs>) => {
    setPrefs(previous => {
      const next = { ...previous, ...patch }
      saveWidgetPrefs(next)
      return next
    })
  }, [])

  const el = useRef<HTMLDivElement>(null)
  const sx = useRef<Spring | null>(null)
  const sy = useRef<Spring | null>(null)
  const stopX = useRef<(() => void) | null>(null)
  const stopY = useRef<(() => void) | null>(null)
  const tx = useRef(new VelocityTracker())
  const ty = useRef(new VelocityTracker())
  const grab = useRef({ x: 0, y: 0 })
  const start = useRef({ x: 0, y: 0 })
  const pos = useRef({ x: 0, y: 0 })
  const size = useRef({ width: 84, height: 84 })
  const moved = useRef(false)
  const dragging = useRef(false)

  const bounds = useCallback(() => {
    const rect = el.current?.getBoundingClientRect()
    if (rect) size.current = { width: rect.width, height: rect.height }
    return {
      minX: MARGIN, maxX: Math.max(MARGIN, window.innerWidth - size.current.width - MARGIN),
      minY: MARGIN, maxY: Math.max(MARGIN, window.innerHeight - size.current.height - MARGIN),
    }
  }, [])

  const draw = useCallback(() => {
    if (el.current) el.current.style.transform = `translate3d(${pos.current.x}px,${pos.current.y}px,0)`
  }, [])

  // 定位:优先恢复保存的位置,否则右下角
  useEffect(() => {
    const b = bounds()
    const initial = prefs.x != null && prefs.y != null
      ? clampWidgetPosition(prefs.x, prefs.y, { width: window.innerWidth, height: window.innerHeight }, size.current)
      : { x: b.maxX, y: b.maxY }
    pos.current = initial
    sx.current = new Spring(initial.x, SPRINGS.move)
    sy.current = new Spring(initial.y, SPRINGS.move)
    draw()
    const onResize = () => {
      const nb = bounds()
      pos.current.x = Math.min(Math.max(pos.current.x, nb.minX), nb.maxX)
      pos.current.y = Math.min(Math.max(pos.current.y, nb.minY), nb.maxY)
      draw()
    }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); stopX.current?.(); stopY.current?.() }
    // 仅在组件挂载时定位一次;后续拖动自行更新
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const settle = useCallback((axis: 'x' | 'y', target: number, v: number) => {
    const s = (axis === 'x' ? sx : sy).current!
    const stopper = axis === 'x' ? stopX : stopY
    stopper.current?.()
    if (prefersReducedMotion()) {
      s.value = target; s.velocity = 0
      pos.current[axis] = target; draw()
      return
    }
    s.value = pos.current[axis]
    s.target = target
    s.velocity = v
    const onFrame = (val: number) => { pos.current[axis] = val; draw() }
    stopper.current = animateSpring(s, onFrame)
  }, [draw])

  const onPointerDown = (event: React.PointerEvent) => {
    stopX.current?.(); stopY.current?.()
    dragging.current = true
    moved.current = false
    start.current = { x: event.clientX, y: event.clientY }
    grab.current = { x: event.clientX - pos.current.x, y: event.clientY - pos.current.y }
    tx.current.reset(pos.current.x)
    ty.current.reset(pos.current.y)
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent) => {
    if (!dragging.current) return
    if (!moved.current) {
      if (Math.hypot(event.clientX - start.current.x, event.clientY - start.current.y) < DRAG_THRESHOLD) return
      moved.current = true
      el.current?.classList.add('dragging')
    }
    const b = bounds()
    pos.current.x = clampRubber(event.clientX - grab.current.x, b.minX, b.maxX, window.innerWidth)
    pos.current.y = clampRubber(event.clientY - grab.current.y, b.minY, b.maxY, window.innerHeight)
    tx.current.add(pos.current.x)
    ty.current.add(pos.current.y)
    draw()
  }

  const onPointerUp = () => {
    if (!dragging.current) return
    dragging.current = false
    el.current?.classList.remove('dragging')
    if (!moved.current) return
    const b = bounds()
    const vx = tx.current.velocity()
    const vy = ty.current.velocity()
    const projX = projectMomentum(pos.current.x, vx)
    const mid = (b.minX + b.maxX) / 2
    haptic(6)
    settle('x', projX < mid ? b.minX : b.maxX, vx)
    const projY = Math.min(Math.max(projectMomentum(pos.current.y, vy), b.minY), b.maxY)
    settle('y', projY, vy)
    // 吸附动画的落点即为保存位置(与视觉一致,含动量投影)
    const finalX = projX < mid ? b.minX : b.maxX
    updatePrefs({ x: finalX, y: Math.round(projY) })
  }

  const activate = () => {
    if (!run) return
    if (view && view.mode !== 'running') updatePrefs({ seenRunId: run.id })
    onNavigate('discovery')
  }

  const dismiss = () => {
    if (!run) return
    if (view?.mode === 'running') updatePrefs({ dismissedRunId: run.id })
    else updatePrefs({ dismissedDoneRunId: run.id })
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); return }
    if (event.key === 'Escape') { dismiss(); return }
    const step = event.shiftKey ? 48 : 24
    const deltas: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
    }
    const delta = deltas[event.key]
    if (!delta) return
    event.preventDefault()
    const b = bounds()
    const next = clampWidgetPosition(pos.current.x + delta[0], pos.current.y + delta[1],
      { width: window.innerWidth, height: window.innerHeight }, size.current)
    pos.current = next
    settle('x', next.x, 0); settle('y', next.y, 0)
    updatePrefs({ x: Math.round(next.x), y: Math.round(next.y) })
  }

  if (!enabled || !view || onDiscovery) return null
  const { mode, run: viewRun } = view
  const eta = formatEta(viewRun.eta_seconds)
  const percent = Math.min(100, Math.max(0, Math.round(viewRun.progress ?? 0)))
  return <div
    className={`research-widget ${mode}`}
    ref={el}
    role="button"
    tabIndex={0}
    aria-label={widgetAriaLabel(view)}
    onPointerDown={onPointerDown}
    onPointerMove={onPointerMove}
    onPointerUp={onPointerUp}
    onPointerCancel={onPointerUp}
    onClick={() => { if (!moved.current) activate() }}
    onKeyDown={onKeyDown}
  >
    <span className="research-widget-live" role="status" aria-live="polite">{widgetAriaLabel(view)}</span>
    <button type="button" className="research-widget-close" aria-label="关闭悬浮进度（不会取消后台研究）"
      onPointerDown={event => event.stopPropagation()}
      onClick={event => { event.stopPropagation(); dismiss() }}>×</button>
    <div className="research-widget-body">
      <div className="research-widget-ring-wrap">
        <ResearchRing progress={viewRun.progress ?? null} mode={mode} />
        <span className="research-widget-percent">
          {mode === 'completed' ? '✓' : mode === 'failed' ? '!' : `${percent}%`}
        </span>
      </div>
      <div className="research-widget-info">
        <b>{mode === 'completed' ? '研究完成' : mode === 'failed' ? '研究失败' : widgetActivityLabel(viewRun.stage)}</b>
        <small>{mode === 'running' ? (eta || '预计时长未知') : '点击查看结果'}</small>
      </div>
    </div>
  </div>
}
