import { describe, expect, it } from 'vitest'
import {
  formatExpiry,
  formatPaperNumber,
  normalizeDeployments,
  normalizePaperAccount,
  normalizePaperOrders,
  normalizeSignals,
  signalStatusClass,
  signalStatusLabel,
  validatePaperAccountForm,
} from './QuantPaper'

describe('模拟盘 UI contract', () => {
  it('normalizes the paper account envelope and keeps PAPER semantics explicit', () => {
    const account = normalizePaperAccount({
      account: {
        id: 3, environment: 'paper', base_currency: 'USDT', status: 'paused',
        initial_cash: '10000', cash: '9990.5', nav: '10005.25', gross_exposure: '8250',
        exposure_ratio: '0.8245', leverage_cap: '1', fill_policy: 'paper-fill-v1',
        costs: { taker_fee_bps: '5', spread_bps: '2', slippage_bps: '2' },
        positions: [{
          instrument_id: 7, instrument_symbol: 'BTCUSDT', quantity: '50', avg_entry_price: '165.05',
          mark_price: '166', exposure: '8300', unrealized_pnl: '47.5', realized_pnl: '0', total_fees: '4.96',
        }],
        warnings: [], last_funding_boundary: null, last_reconciliation: null,
      },
    })
    expect(account?.environment).toBe('paper')
    expect(account?.status).toBe('paused')
    expect(account?.positions).toHaveLength(1)
    expect(account?.positions[0].instrument_symbol).toBe('BTCUSDT')
    expect(normalizePaperAccount({ account: null })).toBeNull()
    expect(normalizePaperAccount(undefined)).toBeNull()
  })

  it('labels signal lifecycle states and their visual classes', () => {
    expect(signalStatusLabel('generated')).toBe('生效中')
    expect(signalStatusLabel('superseded')).toBe('已被取代')
    expect(signalStatusLabel('expired')).toBe('已过期')
    expect(signalStatusLabel('rejected')).toBe('已拒绝')
    expect(signalStatusLabel('consumed')).toBe('已消费')
    expect(signalStatusClass('generated')).toBe('active')
    expect(signalStatusClass('rejected')).toBe('failed')
    expect(signalStatusClass('consumed')).toBe('done')
  })

  it('formats expiry countdowns and gaps without inventing data', () => {
    expect(formatExpiry(null)).toBe('已过期')
    expect(formatExpiry(-5)).toBe('已过期')
    expect(formatExpiry(45)).toBe('45 秒')
    expect(formatExpiry(125)).toBe('2 分 5 秒')
    expect(formatExpiry(3700)).toBe('1 时 1 分')
    expect(formatPaperNumber('not-a-number')).toBe('数据不足')
    expect(formatPaperNumber('1234.5')).toBe('1,234.5')
  })

  it('normalizes deployments, signals and order lineage tolerantly', () => {
    const deployments = normalizeDeployments({ items: [
      { id: 1, status: 'active', strategy_key: 'dual-ma-trend-v1', instrument_id: 7, interval: '1h',
        target_exposure: '1', last_signal: { id: 9, target_exposure: '1', status: 'generated', decision_time: 'x' },
        last_run: { id: 4, status: 'signal_created', reason: null, boundary: 'b', created_at: 'c' } },
      { id: 2 }, 'garbage',
    ] })
    expect(deployments).toHaveLength(2)
    expect(deployments[0].last_signal?.id).toBe(9)
    expect(deployments[1].status).toBe('paused')

    const signals = normalizeSignals({ items: [
      { id: 9, status: 'generated', strategy_key: 'dual-ma-trend-v1', interval: '1h',
        target_exposure: '-1', expires_in_seconds: 120, environment: 'paper' },
    ] })
    expect(signals[0].expires_in_seconds).toBe(120)
    expect(signals[0].instrument_symbol).toBeNull()

    const orders = normalizePaperOrders({ items: [
      { id: 5, client_order_id: 'paper-1-9', side: 'buy', status: 'filled',
        intended_quantity: '60.606', filled_quantity: '60.606', reference_price: '165',
        avg_fill_price: '165.05', fee: '5', spread_cost: '1', slippage_cost: '2',
        fills: [{ id: 1, side: 'buy', quantity: '60.606', price: '165.05', fee: '5', realized_pnl: '0', fill_time: 't' }] },
    ] })
    expect(orders[0].fills).toHaveLength(1)
    expect(orders[0].signal_id).toBeNull()
    expect(normalizePaperOrders(null)).toEqual([])
  })

  it('validates account creation bounds', () => {
    expect(validatePaperAccountForm('10000', '1')).toEqual([])
    expect(validatePaperAccountForm('50', '1')).toContain('初始资金必须在 100 至 10,000,000 之间')
    expect(validatePaperAccountForm('10000', '4')).toContain('杠杆上限必须在 1 至 3 之间')
    expect(validatePaperAccountForm('abc', '1')).toHaveLength(1)
  })
})
