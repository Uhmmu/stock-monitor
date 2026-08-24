import { useEffect, useState } from 'react'
import { useIsFetching } from '@tanstack/react-query'

export const REFRESH_BAR_DELAY_MS = 800

// 短请求（<800ms）不打扰；持续加载才显示顶部进度条，避免 30s 轮询让页面一直闪烁。
export function progressVisible(fetching: boolean, elapsedMs: number): boolean {
  return fetching && elapsedMs >= REFRESH_BAR_DELAY_MS
}

export function RefreshProgressBar() {
  const fetching = useIsFetching() > 0
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (!fetching) { setVisible(false); return }
    const timer = setTimeout(() => setVisible(true), REFRESH_BAR_DELAY_MS)
    return () => clearTimeout(timer)
  }, [fetching])
  if (!visible) return null
  return <div className="refresh-progress" aria-hidden="true"><i/></div>
}
