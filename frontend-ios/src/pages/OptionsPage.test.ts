import { describe, expect, it } from 'vitest'
import { normalizeOptionsDetail, normalizeOptionsOverview, normalizeOptionRow, optionStatusLabel } from './OptionsPage'

describe('iOS options research data', () => {
  it('retains no-options status and market rows', () => {
    const result = normalizeOptionsOverview({ status: 'NO_OPTIONS', market: [{ ticker: 'SPY', status: 'NO_OPTIONS' }] })
    expect(result.status).toBe('NO_OPTIONS')
    expect(result.market[0].symbol).toBe('SPY')
    expect(optionStatusLabel('NO_OPTIONS')).toBe('无可用期权')
  })

  it('keeps missing option metrics as null', () => {
    const result = normalizeOptionsOverview({ watchlist: [{ symbol: 'NVDA', price: 120 }] })
    expect(result.watchlist[0].price).toBe(120)
    expect(result.watchlist[0].atmIv).toBeNull()
    expect(result.watchlist[0].pcVolume).toBeNull()
  })

  it('retains enriched state and historical anomaly aliases', () => {
    const item = normalizeOptionRow({ symbol: 'SPY', options_state: { activity: { status: 'READY' } }, historical_comparison: { changes: { activity: { '1': 2 } } } })
    const point = normalizeOptionsDetail({ symbol: 'SPY', history: [{ trading_date: '2026-08-15', activity_anomaly_direction: 'UP' }] }).history[0]
    expect(item.optionsState?.activity).toEqual({ status: 'READY' })
    expect(item.historicalComparison?.changes).toBeTruthy()
    expect(point.date).toBe('2026-08-15')
    expect(point.anomaly_direction).toBe('UP')
  })
})
