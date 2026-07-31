import { useEffect, useState } from 'react'
import type { DeepSearchRun } from './types'

const statusCopy: Record<DeepSearchRun['status'], string> = { pending: '正在准备深度研究', queued: '等待开始', running: '正在搜索并分析公开来源', completed: '已完成', failed: '研究失败', cancelled: '已取消' }

export function DeepSearchProgress({ run, cancelling, onCancel }: { run: DeepSearchRun; cancelling?: boolean; onCancel?: () => void }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!['pending', 'queued', 'running'].includes(run.status)) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [run.status])
  const started = Date.parse(run.started_at || run.created_at)
  const ended = run.completed_at || run.cancelled_at
  const elapsed = Math.max(0, Math.round(((ended ? Date.parse(ended) : now) - started) / 1000))
  const active = ['pending', 'queued', 'running'].includes(run.status)
  return <section className={`ai-deep-progress ${run.status}`} aria-live="polite"><div><span className="ai-deep-pulse" aria-hidden="true"/><b>Deep · {run.effort === 'xhigh' ? 'X-High' : run.effort[0].toUpperCase() + run.effort.slice(1)}</b><em>{statusCopy[run.status]}</em></div><dl><div><dt>耗时</dt><dd>{elapsed}s</dd></div>{run.sources.length > 0 && <div><dt>来源</dt><dd>{run.sources.length}</dd></div>}<div><dt>{run.cost_estimated ? '参考费用' : '实际费用'}</dt><dd>{run.cost_usd == null ? '待确认' : `$${Number(run.cost_usd).toFixed(3)}`}</dd></div></dl>{run.error_message_safe && <p>{run.error_message_safe}</p>}{active && onCancel && <button type="button" onClick={onCancel} disabled={cancelling}>{cancelling ? '取消中…' : '取消研究'}</button>}</section>
}
