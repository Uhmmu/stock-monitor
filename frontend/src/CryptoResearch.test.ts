import { describe, expect, it } from 'vitest'
import {
  cryptoIntervalLabel,
  cryptoFreshnessLabel,
  formatCryptoAge,
  formatCryptoCoverage,
  formatCryptoEvidence,
  formatCryptoNumber,
  formatCryptoRate,
  formatUtcTime,
  latestDerivativeValue,
  latestSourceLabel,
  parseInstrumentFromSearch,
  prepareCryptoCandles,
  regimeLabel,
  safeCryptoUrl,
  sparklineSegments,
  technicalStatusLabel,
  type CryptoCandleRow,
  type CryptoDerivativeMetric,
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
    expect(formatCryptoCoverage(null)).toBe('覆盖未知')
    expect(formatCryptoCoverage(0.75)).toBe('75.0%')
    expect(formatCryptoCoverage('82')).toBe('82.0%')
  })

  it('基本面新鲜度和新闻链接保持明确且安全', () => {
    expect(cryptoFreshnessLabel('fresh')).toBe('新鲜')
    expect(cryptoFreshnessLabel('expired')).toBe('已过期')
    expect(cryptoFreshnessLabel(null)).toBe('新鲜度未知')
    expect(safeCryptoUrl('https://example.com/btc')).toBe('https://example.com/btc')
    expect(safeCryptoUrl('javascript:alert(1)')).toBeNull()
    expect(safeCryptoUrl('not a url')).toBeNull()
    expect(formatCryptoEvidence({ matched_name: 'Bitcoin' })).toBe('{"matched_name":"Bitcoin"}')
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

  it('衍生品比率与 regime 文案不夸大语义', () => {
    expect(formatCryptoRate('0.0005')).toBe('0.050%')
    expect(regimeLabel('BALANCED')).toBe('未触发联合阈值')
    expect(regimeLabel('INSUFFICIENT_DATA')).toBe('数据不足')
  })

  it('sparkline 保留缺口，不连接缺失数据', () => {
    const segments = sparklineSegments(['1', '2', null, '3', '4'])
    expect(segments).toHaveLength(2)
  })

  it('卡片读取各指标最后一个非空值，不把供应商一小时错位显示成缺失', () => {
    const metrics = [
      { basis_rate: '0.001', open_interest_usd: '100', taker_buy_sell_ratio: '1.2' },
      { basis_rate: null, open_interest_usd: '110', taker_buy_sell_ratio: null },
    ] as CryptoDerivativeMetric[]
    expect(latestDerivativeValue(metrics, 'basis_rate')).toBe('0.001')
    expect(latestDerivativeValue(metrics, 'open_interest_usd')).toBe('110')
    expect(latestDerivativeValue(metrics, 'taker_buy_sell_ratio')).toBe('1.2')
  })
})
