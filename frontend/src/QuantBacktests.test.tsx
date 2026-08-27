import { describe, expect, it } from 'vitest'
import {
  compareRunSelection,
  backtestActionPath,
  compareRunsPath,
  isBacktestPollingStatus,
  normalizeEquityPoints,
  normalizeQuantDefinitions,
  normalizeTrades,
  validateQuantBacktestForm,
  type QuantBacktestForm,
} from './QuantBacktests'

const validForm: QuantBacktestForm = {
  strategy_key: 'trend_following', instrument_ids: ['42'], interval: '1d', start_date: '2025-01-01', end_date: '2026-01-01',
  target_exposure: '1', initial_capital: '10000', leverage: '2', taker_fee_bps: '4', spread_bps: '2', slippage_bps: '2', split_mode: 'full',
}

describe('量化回测 UI contract', () => {
  it('validates native form bounds instead of silently clamping values', () => {
    expect(validateQuantBacktestForm(validForm)).toEqual([])
    expect(validateQuantBacktestForm({ ...validForm, instrument_ids: ['1', '2', '3', '4'] })).toContain('请选择 1–3 个永续合约')
    expect(validateQuantBacktestForm({ ...validForm, target_exposure: '1.1' })).toContain('目标仓位范围无效')
    expect(validateQuantBacktestForm({ ...validForm, leverage: '21' })).toContain('杠杆范围无效')
    expect(validateQuantBacktestForm({ ...validForm, initial_capital: '999' })).toContain('初始资金范围无效')
    expect(validateQuantBacktestForm({ ...validForm, end_date: '2027-01-02' })).toContain('回测区间不能超过 365 天')
    expect(validateQuantBacktestForm({ ...validForm, start_date: '2026-01-01', end_date: '2025-01-01' })).toContain('开始日期必须早于结束日期')
  })

  it('polls only active statuses and stops at terminal states', () => {
    expect(isBacktestPollingStatus('pending')).toBe(true)
    expect(isBacktestPollingStatus('running')).toBe(true)
    expect(isBacktestPollingStatus('cancel_requested')).toBe(true)
    expect(isBacktestPollingStatus('completed')).toBe(false)
    expect(isBacktestPollingStatus('failed')).toBe(false)
  })

  it('normalizes definitions while retaining only supplied perpetual IDs', () => {
    const definitions = normalizeQuantDefinitions({
      strategies: [{ strategy_key: 'trend', version: 'v1', display_name: '趋势' }, { key: 'mean', label: '回归' }],
      instruments: [{ id: 1, display_label: 'BTC 永续', kind: 'perpetual' }, { id: 2, display_label: 'BTC 现货', kind: 'spot' }],
      intervals: ['1h', 'bad'],
    })
    expect(definitions.strategies.map(item => item.key)).toEqual(['trend', 'mean'])
    expect(definitions.instruments.map(item => item.id)).toEqual([1])
    expect(definitions.intervals).toEqual(['1h'])
  })

  it('caps comparison at four and preserves error-tolerant detail rows', () => {
    expect(compareRunSelection([1, 2, 3, 4], 5)).toEqual([1, 2, 3, 4])
    expect(compareRunSelection([1, 2], 2)).toEqual([1])
    expect(backtestActionPath(8, 'cancel')).toBe('/crypto/quant/backtests/8/cancel')
    expect(backtestActionPath(8, 'rerun')).toBe('/crypto/quant/backtests/8/rerun')
    expect(compareRunsPath([2, 8])).toBe('/crypto/quant/backtests/compare?run_ids=2,8')
    expect(normalizeEquityPoints({ items: [{ timestamp: '2026-01-01T00:00:00Z', equity: '100' }, { timestamp: 'bad' }] })).toHaveLength(2)
    expect(normalizeTrades({ trades: [{ id: 1, qty: '2', price: '100', fee: null }] })[0]).toMatchObject({ quantity: 2, price: 100 })
  })
})
