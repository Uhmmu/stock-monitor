import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  HistoryChart,
  MarketMoodCard,
  MoodBoard,
  MoodEmptyState,
  MoodLoadingState,
  MoodReportContent,
  MoodRow,
  filterMoodRows,
  formatPercentValue,
  normalizeMoodRow,
  normalizeOverview,
  sortMoodRows,
  stateLabel,
} from './AIMoodConsole'

const row = (patch: Partial<MoodRow> = {}): MoodRow => ({
  scope_type: 'sector', scope_key: 'chips', name: 'Semiconductor Chips', name_zh: '半导体',
  state: 'strong', candidate_state: null, previous_state: 'neutral', direction: 'improving', phase: 'established', regime: 'risk_on',
  mood_score: 82, confidence: 0.8, quality: 0.9, coverage: 0.75, freshness_status: 'fresh', agreement_score: 0.7, agreement_level: '高共识',
  state_started_on: '2026-08-01', duration_sessions: 5, signals: { trend: 80 }, evidence: [], divergences: [], transition: null,
  missing_sources: [], stale_sources: [], history: [], raw: {}, ...patch,
})

describe('AIMoodConsole normalization', () => {
  it('accepts missing fields and list-form signals without calculating mood', () => {
    const normalized = normalizeMoodRow({
      scope: 'sector', key: 'chips', name: 'Semis', score: 61,
      signals: [{ category: 'technical', metric: 'trend', normalized_score: 72 }, { metric: 'breadth', status: 'mixed' }],
    })
    expect(normalized.scope_type).toBe('sector')
    expect(normalized.scope_key).toBe('chips')
    expect(normalized.mood_score).toBe(61)
    expect(normalized.signals.trend).toBe(72)
    expect(normalized.signals.technical).toBe(72)
    expect(normalized.signals.breadth).toBe('mixed')
    expect(normalized.evidence).toEqual([])
  })

  it('keeps both sectors and industries available to the board', () => {
    const normalized = normalizeOverview({
      sectors: [{ scope_type: 'sector', scope_key: 'a', name: 'A' }],
      industries: [{ scope_type: 'industry', scope_key: 'b', name: 'B' }],
      market_window: { vix: { value: 18.4, change_percent: -3.2, regime: 'NORMAL', as_of: '2026-08-17' }, participation: { improving: 7, deteriorating: 3, tracked: 10 } },
    })
    expect(normalized.industries).toHaveLength(1)
    expect(normalized.sectors.map(item => item.scope_key)).toEqual(['a', 'b'])
    expect(normalized.market_window.vix.value).toBe(18.4)
    expect(normalized.market_window.participation.improving).toBe(7)
  })

  it('normalizes grouped snapshot and object divergence evidence', () => {
    const normalized = normalizeMoodRow({
      scope_type: 'sector', scope_key: 'technology',
      evidence: { supporting: [{ category: 'price', message: 'price: 72', source: 'history' }] },
      divergences: [{ type: 'PRICE_BREADTH', evidence: { metrics: ['price', 'breadth'], left: 72, right: 38 } }],
    })
    expect(normalized.evidence[0]?.message).toBe('price: 72')
    expect(normalized.divergences[0]?.evidence[0]?.message).toContain('price / breadth')
  })

  it('drops inactive divergence placeholders and supports backend up/down directions', () => {
    const normalized = normalizeMoodRow({
      scope_type: 'sector', scope_key: 'technology', direction: 'up',
      divergences: [{ type: 'PRICE_BREADTH', active: false, resolved: false }],
    })
    expect(normalized.divergences).toEqual([])
    expect(filterMoodRows([normalized], 'improving')).toHaveLength(1)
  })
})

describe('AIMoodConsole presentation helpers', () => {
  it('labels lifecycle, traffic-light, unknown, and ratio values safely', () => {
    expect(stateLabel('emerging')).toBe('形成')
    expect(stateLabel('green')).toBe('绿灯')
    expect(stateLabel('future_state')).toBe('future state')
    expect(formatPercentValue(0.72)).toBe('72%')
  })

  it('sorts and filters authoritative rows without mutating the input', () => {
    const improving = row({ scope_key: 'improving', mood_score: 60, direction: 'improving' })
    const weak = row({ scope_key: 'weak', mood_score: 30, direction: 'deteriorating' })
    const divergent = row({ scope_key: 'divergent', mood_score: 50, direction: 'stable', divergences: [{ type: 'breadth', direction: 'mixed', severity: 2, confidence: 0.5, duration_sessions: 2, first_seen: null, last_seen: null, evidence: [], resolved: false }] })
    const rows = [weak, improving, divergent]
    expect(sortMoodRows(rows, 'strongest').map(item => item.scope_key)).toEqual(['improving', 'divergent', 'weak'])
    expect(filterMoodRows(rows, 'improving').map(item => item.scope_key)).toEqual(['improving'])
    expect(filterMoodRows(rows, 'divergent').map(item => item.scope_key)).toEqual(['divergent'])
    expect(rows[0]).toBe(weak)
  })
})

describe('AIMoodConsole static states and history', () => {
  it('renders loading, long names, stale data, and low confidence', () => {
    const loading = renderToStaticMarkup(<MoodLoadingState />)
    const stale = renderToStaticMarkup(<MarketMoodCard row={row({ name_zh: '一个非常长但不应破坏布局的行业板块名称', freshness_status: 'stale', confidence: 0.12 })} />)
    const board = renderToStaticMarkup(<MoodBoard rows={[row({ name_zh: '一个非常长但不应破坏布局的行业板块名称' })]} />)
    expect(loading).toContain('aria-busy="true"')
    expect(stale).toContain('数据待更新')
    expect(stale).toContain('12%')
    expect(board).toContain('一个非常长但不应破坏布局的行业板块名称')
  })

  it('renders one market overview window with VIX and participation', () => {
    const overview = normalizeOverview({
      market: { ...row({ scope_type: 'market', scope_key: 'US', name_zh: '美国市场', state: 'risk_on' }), evidence: { category_scores: { breadth: 66, options: 48, news: 57 } } },
      market_window: { coverage: 0.82, category_scores: { breadth: 66, options: 48, news: 57 }, vix: { value: 18.4, change_percent: -3.2, regime: 'NORMAL', as_of: '2026-08-17' }, participation: { improving: 7, deteriorating: 3, tracked: 10 }, active_divergences: 2 },
    })
    const markup = renderToStaticMarkup(<MarketMoodCard row={overview.market} />)
    expect(markup).toContain('VIX 恐慌指数')
    expect(markup).toContain('18.4')
    expect(markup).toContain('7</b> 行业改善')
    expect(markup).toContain('市场广度')
  })

  it('renders explicit empty and insufficient-history states', () => {
    const empty = renderToStaticMarkup(<MoodEmptyState message="没有快照" />)
    const history = renderToStaticMarkup(<HistoryChart row={row()} />)
    expect(empty).toContain('没有快照')
    expect(history).toContain('历史不足')
  })

  it('renders native SVG history markers and report limitations', () => {
    const history = renderToStaticMarkup(<HistoryChart row={row()} history={[{ date: '2026-08-01', as_of: null, mood_score: 40, state: 'yellow', direction: 'stable', phase: null, transition: null }, { date: '2026-08-15', as_of: null, mood_score: 70, state: 'green', direction: 'improving', phase: null, transition: null }]} />)
    const report = renderToStaticMarkup(<MoodReportContent report={{ market_mood: 'green', sector_regime: 'emerging', regime_changes: [], ai_chain_mood: null, key_divergences: [{ left: '价格', right: '广度' }], crowding_signals: [], improving_sectors: [], deteriorating_sectors: [], limitations: ['来源覆盖有限'], raw: {} }} />)
    expect(history).toContain('<svg')
    expect(history).toContain('情绪分数历史趋势')
    expect(report).toContain('来源覆盖有限')
    expect(report).toContain('价格 与 广度')
  })
})
