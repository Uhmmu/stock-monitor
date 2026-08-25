import { describe, expect, it } from 'vitest'
import {
  cryptoIntervalLabel,
  formatCryptoAge,
  formatCryptoNumber,
  formatUtcTime,
  latestSourceLabel,
  parseInstrumentFromSearch,
  prepareCryptoCandles,
  technicalStatusLabel,
  type CryptoCandleRow,
} from './CryptoResearch'

const closed = (openTimeMs: number, overrides: Partial<CryptoCandleRow> = {}): CryptoCandleRow => ({
  open_time_ms: openTimeMs,
  close_time_ms: openTimeMs + 3_600_000 - 1,
  open: '100',
  high: '110',
  low: '95',
  close: '105',
  base_volume: '12.5',
  quote_volume: '1300',
  taker_buy_base_volume: '4',
  trades: 50,
  final: true,
  provider: 'binance_spot',
  feed: 'rest',
  price_type: 'trade',
  ...overrides,
})

describe('加密研究 URL 状态', () => {
  it('从查询参数恢复选中的交易对（刷新/回退后保持）', () => {
    expect(parseInstrumentFromSearch('?tab=crypto&instrument=42')).toBe(42)
    expect(parseInstrumentFromSearch('?tab=crypto')).toBeNull()
    expect(parseInstrumentFromSearch('')).toBeNull()
  })

  it('拒绝非法交易对 id，而不是猜测默认值', () => {
    expect(parseInstrumentFromSearch('?instrument=abc')).toBeNull()
    expect(parseInstrumentFromSearch('?instrument=-3')).toBeNull()
    expect(parseInstrumentFromSearch('?instrument=0')).toBeNull()
  })
})

describe('K 线数据准备', () => {
  it('按时间升序整理并保留 OHLC 与成交量', () => {
    const prepared = prepareCryptoCandles([closed(7_200_000), closed(3_600_000)])
    expect(prepared.candles.map(candle => candle.time)).toEqual([3600, 7200])
    expect(prepared.candles[0]).toMatchObject({ open: 100, high: 110, low: 95, close: 105 })
    expect(prepared.volume[0]).toMatchObject({ value: 12.5 })
    expect(prepared.rejected).toBe(0)
  })

  it('未收盘或无效 K 线被显式拒绝而不是修补', () => {
    const prepared = prepareCryptoCandles([
      closed(3_600_000, { final: false }),
      closed(7_200_000, { high: '90' }),
      closed(10_800_000),
    ])
    expect(prepared.candles).toHaveLength(1)
    expect(prepared.rejected).toBe(2)
  })
})

describe('展示与缺口文案', () => {
  it('缺失数值显示为数据不足', () => {
    expect(formatCryptoNumber(null)).toBe('数据不足')
    expect(formatCryptoNumber('')).toBe('数据不足')
    expect(formatCryptoNumber('not-a-number')).toBe('数据不足')
    expect(formatCryptoNumber('79184.012345', 6)).toBe('79,184.012345')
  })

  it('来源与状态标签稳定', () => {
    expect(latestSourceLabel('ticker_cache')).toBe('实时缓存')
    expect(latestSourceLabel('closed_candle_fallback')).toBe('已收盘 K 线回退')
    expect(latestSourceLabel('unavailable')).toBe('暂无数据')
    expect(technicalStatusLabel('ready')).toBe('指标就绪')
    expect(technicalStatusLabel('insufficient')).toBe('数据不足')
  })

  it('周期与年龄标签', () => {
    expect(cryptoIntervalLabel('1h')).toBe('1 小时')
    expect(cryptoIntervalLabel('4h')).toBe('4 小时')
    expect(cryptoIntervalLabel('1d')).toBe('1 天')
    expect(formatCryptoAge(null)).toBe('未知')
    expect(formatCryptoAge(45)).toBe('45 秒前')
    expect(formatCryptoAge(125)).toBe('2 分钟前')
    expect(formatCryptoAge(7300)).toBe('2 小时前')
  })

  it('UTC 时间戳格式化', () => {
    expect(formatUtcTime(1_787_662_800_000)).toBe('2026-08-25 13:00 UTC')
    expect(formatUtcTime(null)).toBe('未知')
  })
})
