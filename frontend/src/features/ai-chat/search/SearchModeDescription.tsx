import type { WebAccessMode, WebSearchConfig } from './types'
import { effortForMode, modeCost, SEARCH_MODE_COPY } from './searchModes'

export function SearchModeDescription({ mode, config }: { mode: WebAccessMode; config: WebSearchConfig }) {
  const cost = modeCost(mode, config)
  const effort = effortForMode(mode)
  return <span className="ai-search-mode-copy"><b>{SEARCH_MODE_COPY[mode].label}{mode === 'deep_medium' && <em>推荐</em>}</b><small>{SEARCH_MODE_COPY[mode].description}{cost != null ? ` · 参考基础费用约 $${cost.toFixed(cost < .1 ? 3 : 2)}` : ''}{effort && !config.deep_modes[effort]?.enabled ? ' · 当前不可用' : ''}</small></span>
}
