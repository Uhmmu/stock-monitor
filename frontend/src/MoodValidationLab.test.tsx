import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HistoryHealthPanel, transitionCells, type HistoryHealth } from './MoodValidationLab'

describe('Mood Validation Lab', () => {
  it('builds a sparse transition matrix without inventing missing transitions', () => {
    const row = {
      id: 1, study_type: 'transition', scope_type: 'market', scope_key: null, state: null,
      transition_from: 'ACCUMULATION', transition_to: 'EXPANSION', divergence_type: null, bucket: null,
      horizon: null, sample_mode: 'transition', sample_count: 4, metrics: {}, quality: 'INSUFFICIENT_SAMPLE',
      warnings: ['INSUFFICIENT_SAMPLE'], event_refs: [],
    }
    const matrix = transitionCells([row])
    expect(matrix.states).toEqual(['ACCUMULATION', 'EXPANSION'])
    expect(matrix.byPair.get('ACCUMULATION:EXPANSION')?.sample_count).toBe(4)
    expect(matrix.byPair.has('EXPANSION:ACCUMULATION')).toBe(false)
  })

  it('renders health status, quality, maturity, gaps, and calendar without interpreting quality as risk', () => {
    const health: HistoryHealth = {
      health_status: 'PARTIAL', latest_eod: '2026-08-14', oldest_eod: '2026-08-01', history_days: 10, complete_days: 8, partial_days: 2,
      today: { trading_date: '2026-08-14', status: 'PARTIAL', expected: 4, generated: 3, coverage: 0.75, missing_scopes: ['watchlist:NVDA'], insufficient_scopes: ['sector:energy'], failed_scopes: [], stale_sources: ['options'] },
      quality_distribution: { high: 2, medium: 1, low: 0, insufficient: 1 }, source_health: { options: { status: 'STALE', count: 1 } },
      calendar: [{ trading_date: '2026-08-13', status: 'HEALTHY', coverage: 1 }, { trading_date: '2026-08-14', status: 'PARTIAL', coverage: 0.75 }],
      maturity: { matured_1d_samples: 8, matured_5d_samples: 5, matured_20d_samples: 1, matured_60d_samples: 0 }, warnings: ['缺少一个 watchlist scope'],
    }
    const html = renderToStaticMarkup(<HistoryHealthPanel health={health} />)
    expect(html).toContain('部分完成')
    expect(html).toContain('最新 EOD')
    expect(html).toContain('75%')
    expect(html).toContain('watchlist:NVDA')
    expect(html).toContain('质量分布')
    expect(html).toContain('结果成熟度')
    expect(html).toContain('08-14')
    expect(html).toContain('仅表示数据证据质量')
  })

  it('keeps health failures local to the panel', () => {
    const html = renderToStaticMarkup(<HistoryHealthPanel error />)
    expect(html).toContain('历史健康暂时无法读取')
    expect(html).toContain('不影响验证结果')
  })
})
