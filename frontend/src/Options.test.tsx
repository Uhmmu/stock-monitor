import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { normalizeOptionRow, normalizeOptionPoint, normalizeOptionsDetail, normalizeOptionsOverview, OptionsEmptyState, sortOptionRows, statusLabel } from './Options'

describe('Options research normalization', () => {
  it('keeps option status and quality gaps explicit', () => {
    const overview = normalizeOptionsOverview({ status: 'NO_OPTIONS', market: [{ ticker: 'SPY', status: 'NO_OPTIONS', quality: { coverage: 0 } }] })
    expect(overview.status).toBe('NO_OPTIONS')
    expect(overview.market[0]).toMatchObject({ symbol: 'SPY', status: 'NO_OPTIONS' })
    expect(statusLabel('NO_OPTIONS')).toBe('无可用期权')
  })

  it('normalizes metric aliases without inventing values', () => {
    const row = normalizeOptionRow({ symbol: 'NVDA', price: 120, at_the_money_iv: 0.42, pc_volume: 1.7, data_status: 'PARTIAL' })
    expect(row).toMatchObject({ symbol: 'NVDA', underlying_price: 120, atm_iv: 0.42, put_call_volume_ratio: 1.7, status: 'PARTIAL' })
    expect(row.put_call_oi_ratio).toBeNull()
  })

  it('sorts only by a requested available metric', () => {
    const rows = [normalizeOptionRow({ symbol: 'A', activity_score: 20 }), normalizeOptionRow({ symbol: 'B', activity_score: 80 })]
    expect(sortOptionRows(rows, 'activity').map(row => row.symbol)).toEqual(['B', 'A'])
    expect(sortOptionRows(rows, 'unknown')).toEqual(rows)
  })

  it('retains state, comparison, dates, and anomaly aliases for enriched history', () => {
    const row = normalizeOptionRow({ symbol: 'SPY', options_state: { activity: { status: 'READY' } }, historical_comparison: { changes: { activity: { '1': 2 } } } })
    const point = normalizeOptionPoint({ trading_date: '2026-08-15', activity_anomaly_direction: 'UP', historical_comparison: { averages: { activity: { '7': 10 } } }, activity_score: 12 })
    expect(row.options_state?.activity).toEqual({ status: 'READY' })
    expect(row.historical_comparison?.changes).toBeTruthy()
    expect(point.date).toBe('2026-08-15')
    expect(point.anomaly_direction).toBe('UP')
    expect(normalizeOptionsDetail({ symbol: 'SPY', history: [{ date: '2026-08-15', activity_anomaly_direction: 'DOWN' }] }).history[0].anomaly_direction).toBe('DOWN')
  })

  it('renders a truthful retryable error state', () => {
    const html = renderToStaticMarkup(<OptionsEmptyState title="期权研究暂不可用" message="接口没有返回有效数据" retry={() => undefined}/>)
    expect(html).toContain('role="alert"')
    expect(html).toContain('重新加载')
    expect(html).toContain('接口没有返回有效数据')
  })
})
