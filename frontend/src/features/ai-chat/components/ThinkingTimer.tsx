import { useEffect, useState } from 'react'

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m${String(seconds % 60).padStart(2, '0')}s`
}

/**
 * Reasoning models stay silent for tens of seconds before the first text
 * delta; a live elapsed counter keeps the waiting state visibly alive.
 */
export function ThinkingTimer({ startedAt, label }: {
  startedAt?: string | null
  label: string
}) {
  const start = startedAt ? new Date(startedAt).getTime() : Number.NaN
  const elapsed = () => Number.isFinite(start) ? Math.max(0, Math.round((Date.now() - start) / 1000)) : 0
  const [seconds, setSeconds] = useState(elapsed)
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds(elapsed()), 1000)
    return () => window.clearInterval(timer)
  }, [start])
  return <span className="ai-thinking-timer">{label} · {formatElapsed(seconds)}</span>
}
