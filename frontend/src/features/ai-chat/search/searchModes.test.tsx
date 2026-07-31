import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SearchModeDescription } from './SearchModeDescription'
import { effortForMode, isDeepMode, modeCost, SEARCH_MODE_COPY } from './searchModes'
import type { WebAccessMode, WebSearchConfig } from './types'

const modes: WebAccessMode[] = [
  'off', 'search', 'deep_minimal', 'deep_low', 'deep_medium', 'deep_high', 'deep_xhigh',
]

const config: WebSearchConfig = {
  enabled: true,
  configured: true,
  default_mode: 'off',
  available_modes: modes,
  deep_modes: {
    minimal: { label: 'Deep · Minimal', estimated_base_cost_usd: 0.012, confirmation_required: false, enabled: true },
    low: { label: 'Deep · Low', estimated_base_cost_usd: 0.025, confirmation_required: false, enabled: true },
    medium: { label: 'Deep · Medium', estimated_base_cost_usd: 0.1, confirmation_required: false, enabled: true },
    high: { label: 'Deep · High', estimated_base_cost_usd: 0.5, confirmation_required: true, enabled: true },
    xhigh: { label: 'Deep · X-High', estimated_base_cost_usd: 1, confirmation_required: true, enabled: true },
  },
}

describe('Exa chat search modes', () => {
  it('defines exactly off, normal search, and five fixed Agent efforts', () => {
    expect(Object.keys(SEARCH_MODE_COPY)).toEqual(modes)
    expect(modes.filter(isDeepMode)).toHaveLength(5)
    expect(modes.map(effortForMode)).toEqual([null, null, 'minimal', 'low', 'medium', 'high', 'xhigh'])
    expect(Object.keys(config.deep_modes)).not.toContain('auto')
  })

  it('uses backend config prices and marks Medium as recommended', () => {
    expect(modeCost('off', config)).toBeNull()
    expect(modeCost('search', config)).toBeNull()
    expect(modeCost('deep_xhigh', config)).toBe(1)
    const html = renderToStaticMarkup(<>{modes.map(mode => <SearchModeDescription key={mode} mode={mode} config={config}/>)}</>)
    expect(html).toContain('仅使用站内数据')
    expect(html).toContain('快速联网查找网页和最新消息')
    expect(html).toContain('Deep · Minimal')
    expect(html).toContain('Deep · X-High')
    expect(html).toContain('推荐')
    expect(html).toContain('$1.00')
  })

  it('keeps High and X-High confirmation policy config-driven', () => {
    expect(config.deep_modes.medium.confirmation_required).toBe(false)
    expect(config.deep_modes.high.confirmation_required).toBe(true)
    expect(config.deep_modes.xhigh.confirmation_required).toBe(true)
  })
})
