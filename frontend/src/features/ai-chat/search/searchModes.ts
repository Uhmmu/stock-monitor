import type { WebAccessMode, WebSearchConfig } from './types'

export const SEARCH_MODE_COPY: Record<WebAccessMode, { label: string; description: string }> = {
  off: { label: '不联网', description: '仅使用站内数据' },
  search: { label: '普通搜索', description: '快速联网查找网页和最新消息' },
  deep_minimal: { label: 'Deep · Minimal', description: '最轻量，适合单一事实核查' },
  deep_low: { label: 'Deep · Low', description: '轻量研究，适合简单调查' },
  deep_medium: { label: 'Deep · Medium', description: '平衡质量、速度和费用' },
  deep_high: { label: 'Deep · High', description: '深入研究，费用明显较高' },
  deep_xhigh: { label: 'Deep · X-High', description: '最高强度，可能耗时较长' },
}

export const effortForMode = (mode: WebAccessMode) => mode.startsWith('deep_') ? mode.slice(5) as keyof WebSearchConfig['deep_modes'] : null
export const isDeepMode = (mode: WebAccessMode) => mode.startsWith('deep_')

export function modeCost(mode: WebAccessMode, config: WebSearchConfig): number | null {
  const effort = effortForMode(mode)
  return effort ? config.deep_modes[effort]?.estimated_base_cost_usd ?? null : null
}
