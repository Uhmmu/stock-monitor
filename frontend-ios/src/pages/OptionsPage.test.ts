import { describe, expect, it } from 'vitest'
import { normalizeOptionsOverview, optionStatusLabel } from './OptionsPage'

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
})
