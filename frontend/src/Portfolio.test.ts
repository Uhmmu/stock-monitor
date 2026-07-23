import { describe, expect, it } from 'vitest'
import { fmtHealthScore, fmtMoney, fmtNum, fmtPercent } from './Portfolio'

describe('fmtMoney', () => {
  it('renders an explicit gap instead of fabricating a value', () => {
    expect(fmtMoney(null)).toBe('数据不足')
  })

  it('formats USD with a $ prefix', () => {
    expect(fmtMoney(1234.5, 'USD')).toBe('$1,234.50')
  })

  it('formats a non-USD currency with its code prefix', () => {
    expect(fmtMoney(1000, 'HKD')).toBe('HKD 1,000.00')
  })
})

describe('fmtPercent', () => {
  it('renders an em dash for unknown values', () => {
    expect(fmtPercent(null)).toBe('—')
  })

  it('prefixes positive values with +', () => {
    expect(fmtPercent(12.345)).toBe('+12.35%')
  })

  it('does not double-prefix negative values', () => {
    expect(fmtPercent(-5.1)).toBe('-5.10%')
  })
})

describe('fmtNum', () => {
  it('formats with the default precision', () => {
    expect(fmtNum(10)).toBe('10')
  })

  it('respects a custom digit count', () => {
    expect(fmtNum(1.23456, 2)).toBe('1.23')
  })
})

describe('fmtHealthScore', () => {
  it('keeps missing analysis explicit', () => {
    expect(fmtHealthScore(null)).toBe('数据不足')
  })

  it('rounds a score for compact display', () => {
    expect(fmtHealthScore(74.6)).toBe('75')
  })
})
