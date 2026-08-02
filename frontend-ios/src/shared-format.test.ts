import { describe, expect, it } from 'vitest'
import { formatPercent, stockChange } from '@shared/format'

describe('shared market formatting', () => {
  it('derives a quote change without normalizing missing data to zero', () => {
    expect(stockChange(105, 100)).toBe(5)
    expect(stockChange(null, 100)).toBeNull()
    expect(stockChange(100, 0)).toBeNull()
  })
  it('keeps explicit data gaps visible', () => {
    expect(formatPercent(null)).toBe('—')
    expect(formatPercent(-1.234)).toBe('-1.23%')
  })
})
