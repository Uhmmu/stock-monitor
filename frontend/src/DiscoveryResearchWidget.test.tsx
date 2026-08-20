import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import {
  ResearchRing, clampWidgetPosition, computeWidgetView, formatEta,
  loadWidgetPrefs, saveWidgetPrefs, widgetActivityLabel, widgetAriaLabel,
  type ResearchRunMeta, type WidgetPrefs,
} from './DiscoveryResearchWidget'

const storage = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  clear: () => storage.clear(),
} })

const basePrefs: WidgetPrefs = { x: null, y: null, dismissedRunId: null, dismissedDoneRunId: null, seenRunId: null }

function run(overrides: Partial<ResearchRunMeta>): ResearchRunMeta {
  return {
    id: 7, status: 'running', stage: 'pi_planning', trigger: 'manual',
    requested_at: '', started_at: null, completed_at: null, analysis_date: null,
    next_scheduled_at: null, model_requested: '', model_used: null,
    prompt_version: '', schema_version: '', filter_version: '',
    warnings: [], failure_code: null, failure_reason: null,
    previous_successful_run_id: null, funnel_stats: null,
    ...overrides,
  } as ResearchRunMeta
}

describe('formatEta', () => {
  it('formats unknown as empty and short tasks as almost done', () => {
    expect(formatEta(null)).toBe('')
    expect(formatEta(undefined)).toBe('')
    expect(formatEta(8)).toBe('即将完成')
  })
  it('rounds seconds, minutes and hours naturally', () => {
    expect(formatEta(45)).toBe('~50 秒')
    expect(formatEta(90)).toBe('~2 分钟')
    expect(formatEta(5400)).toBe('~2 小时')
  })
})

describe('computeWidgetView', () => {
  it('hides when there is no run', () => {
    expect(computeWidgetView(null, basePrefs)).toBeNull()
    expect(computeWidgetView(undefined, basePrefs)).toBeNull()
  })
  it('shows running state and honours running dismissal', () => {
    const active = run({ status: 'running' })
    expect(computeWidgetView(active, basePrefs)?.mode).toBe('running')
    expect(computeWidgetView(active, { ...basePrefs, dismissedRunId: 7 })).toBeNull()
  })
  it('keeps completed results visible until seen or dismissed', () => {
    const done = run({ status: 'completed' })
    expect(computeWidgetView(done, basePrefs)?.mode).toBe('completed')
    expect(computeWidgetView(done, { ...basePrefs, seenRunId: 7 })).toBeNull()
    expect(computeWidgetView(done, { ...basePrefs, dismissedDoneRunId: 7 })).toBeNull()
  })
  it('maps failure states to the failed widget', () => {
    expect(computeWidgetView(run({ status: 'failed' }), basePrefs)?.mode).toBe('failed')
    expect(computeWidgetView(run({ status: 'blocked_by_budget' }), basePrefs)?.mode).toBe('failed')
  })
})

describe('clampWidgetPosition', () => {
  it('keeps the widget inside the viewport', () => {
    const clamped = clampWidgetPosition(-100, 5000, { width: 1200, height: 800 }, { width: 84, height: 84 })
    expect(clamped.x).toBe(16)
    expect(clamped.y).toBe(800 - 84 - 16)
  })
})

describe('widget labels', () => {
  it('maps funnel stages to short activities', () => {
    expect(widgetActivityLabel('pi_counter_evidence')).toBe('反方验证')
    expect(widgetActivityLabel('unknown_stage')).toBe('研究中')
    expect(widgetActivityLabel(null)).toBe('研究中')
  })
  it('builds a descriptive aria label', () => {
    const label = widgetAriaLabel({ mode: 'running', run: run({ progress: 62, eta_seconds: 50, stage: 'pi_external_research' }) })
    expect(label).toContain('62%')
    expect(label).toContain('外部研究')
    expect(label).toContain('~50 秒')
  })
})

describe('ResearchRing', () => {
  it('draws partial arc while running and full ring for terminal states', () => {
    const running = renderToStaticMarkup(<ResearchRing progress={67} mode="running" />)
    expect(running).toContain('ring-value')
    expect(running).toContain('stroke-dashoffset')
    expect(running).not.toContain('stroke-dashoffset="0"')
    const done = renderToStaticMarkup(<ResearchRing progress={100} mode="completed" />)
    expect(done).toContain('stroke-dashoffset="0"')
    expect(done).toContain('is-done')
    const failed = renderToStaticMarkup(<ResearchRing progress={null} mode="failed" />)
    expect(failed).toContain('stroke-dashoffset="0"')
  })
})

describe('widget prefs persistence', () => {
  afterEach(() => { localStorage.clear() })

  it('round-trips through localStorage and tolerates malformed data', () => {
    saveWidgetPrefs({ x: 120, y: 40, dismissedRunId: 3, dismissedDoneRunId: null, seenRunId: 9 })
    expect(loadWidgetPrefs()).toEqual({ x: 120, y: 40, dismissedRunId: 3, dismissedDoneRunId: null, seenRunId: 9 })
    localStorage.setItem('stock-monitor:research-widget:v1', '{not json')
    expect(loadWidgetPrefs()).toEqual(basePrefs)
  })
})
