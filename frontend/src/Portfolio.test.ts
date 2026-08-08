import { describe, expect, it } from 'vitest'
import { cashFlowAdjustedGrowth, chartPoints, deriveLivePortfolio, fmtHealthScore, fmtMoney, fmtNum, fmtPercent, type PortfolioSummary, type PositionView } from './Portfolio'
import { normalizeRealtimeQuote } from './realtime'
import { findSavedScenarioRun, type ScenarioHistoryRun } from './PortfolioScenarios'
import { latestFreshAnalysis, requestsMatch, type PortfolioAnalysisRun } from './PortfolioAnalysisCache'

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

describe('portfolio ledger chart', () => {
  it('keeps an empty state when fewer than two real points exist', () => {
    expect(chartPoints([null, 100, null])).toBe('')
  })

  it('does not replace a missing account value with zero', () => {
    const points = chartPoints([100, null, 120], 100, 50)
    expect(points.split(' ')).toHaveLength(2)
    expect(points).toContain('0.0,50.0')
    expect(points).toContain('100.0,0.0')
  })

  it('expresses cash-flow-adjusted account growth around a 0% origin', () => {
    const point = { cash_flow_adjusted_index: 112.5, cumulative_return: .08 } as Parameters<typeof cashFlowAdjustedGrowth>[0]
    expect(cashFlowAdjustedGrowth(point)).toBe(12.5)
  })

  it('uses cumulative return only as a compatibility fallback for adjusted growth', () => {
    const point = { cash_flow_adjusted_index: null, cumulative_return: -.075 } as Parameters<typeof cashFlowAdjustedGrowth>[0]
    expect(cashFlowAdjustedGrowth(point)).toBe(-7.5)
  })
})

describe('live portfolio valuation', () => {
  const position = {
    symbol: 'AAPL', total_quantity: 10, average_cost: 100, total_cost: 1000, currency: 'USD',
    price_available: true, current_price: 102, market_value: 1020, unrealized_pnl: 20, unrealized_pnl_percent: 2,
    previous_close: 105, daily_change_amount: -3, daily_change_percent: -2.86, price_source: 'snapshot',
    fx_rate: 1, fx_rate_source: 'identity', base_currency_market_value: 1020, base_currency_total_cost: 1000,
    base_currency_unrealized_pnl: 20, base_currency_realized_pnl: 0, base_currency_dividend_income: 0,
    base_currency_fees: 0, base_currency_taxes: 0, base_currency_total_pnl: 20, valuation_available: true,
    portfolio_weight: 100, authority_source: 'manual', realized_pnl: 0, dividend_income: 0, fees: 0, taxes: 0,
    fees_and_taxes: 0, total_pnl: 20, total_return_pct: 2, holding_days: 10, last_transaction_at: null,
    first_trade_at: null, price_as_of: null, data_completeness: 'complete', security_id: null,
  } as PositionView
  const summary = {
    base_currency: 'USD', total_market_value: 1020, invested_market_value: 1020, total_cost: 1000,
    total_unrealized_pnl: 20, total_unrealized_pnl_percent: 2, net_asset_value: 1020, cash: 0,
    net_contributions: 1000, investment_pnl: 20, simple_cumulative_return: .02, positions: [position],
  } as PortfolioSummary

  it('recalculates market value, unrealized P&L, and daily P&L from a fresh quote', () => {
    const quote = normalizeRealtimeQuote({ symbol: 'AAPL', price: 110, previous_close: 105, is_stale: false })!
    const result = deriveLivePortfolio(summary, { AAPL: quote })!
    expect(result.positions[0]?.live_market_value).toBe(1100)
    expect(result.positions[0]?.live_unrealized_pnl).toBe(100)
    expect(result.positions[0]?.live_daily_pnl).toBe(50)
    expect(result.total_market_value).toBe(1100)
    expect(result.total_unrealized_pnl).toBe(100)
    expect(result.live_daily_pnl).toBe(50)
    expect(result.investment_pnl).toBe(100)
  })

  it('keeps the persisted valuation when the quote is stale', () => {
    const quote = normalizeRealtimeQuote({ symbol: 'AAPL', price: 110, previous_close: 105, is_stale: true })!
    const result = deriveLivePortfolio(summary, { AAPL: quote })!
    expect(result.positions[0]?.live_price).toBe(102)
    expect(result.positions[0]?.live_market_value).toBe(1020)
    expect(result.live_daily_pnl).toBe(-30)
  })

  it('uses the persisted previous close when a fresh quote only has a latest price', () => {
    const quote = normalizeRealtimeQuote({ symbol: 'AAPL', price: 110, is_stale: false })!
    const result = deriveLivePortfolio(summary, { AAPL: quote })!
    expect(result.positions[0]?.live_daily_pnl).toBe(50)
    expect(result.live_daily_pnl).toBe(50)
    expect(result.live_daily_pnl_count).toBe(1)
  })

  it('derives the previous close from a realtime change when needed', () => {
    const withoutPreviousClose = {...position, previous_close: null, daily_change_amount: null}
    const quote = normalizeRealtimeQuote({ symbol: 'AAPL', price: 110, change: 4, is_stale: false })!
    const result = deriveLivePortfolio({...summary, positions:[withoutPreviousClose]}, { AAPL: quote })!
    expect(result.positions[0]?.live_daily_pnl).toBe(40)
  })
})

describe('findSavedScenarioRun', () => {
  const result = (code: string) => ({ status: 'completed', scenario: { code } }) as ScenarioHistoryRun['result']
  const run = (overrides: Partial<ScenarioHistoryRun>): ScenarioHistoryRun => ({
    job_id: 1,
    analysis_type: 'scenario_analysis',
    status: 'completed',
    result: result('recession'),
    input_request: {},
    model_version: 'test',
    created_at: '2026-07-28T01:00:00Z',
    completed_at: '2026-07-28T01:00:00Z',
    expires_at: '2026-08-04T01:00:00Z',
    is_fresh: true,
    error_message: null,
    ...overrides,
  })

  it('reuses the latest completed result for the selected scenario', () => {
    const runs: ScenarioHistoryRun[] = [
      run({ job_id: 3, result: result('recession'), created_at: '2026-07-28T03:00:00Z' }),
      run({ job_id: 2, result: result('growth_repricing'), created_at: '2026-07-28T02:00:00Z' }),
    ]
    expect(findSavedScenarioRun(runs, 'recession')?.job_id).toBe(3)
  })

  it('does not reuse pending, expired, or unrelated analysis runs', () => {
    const runs: ScenarioHistoryRun[] = [
      run({ job_id: 5, is_fresh: false }),
      run({ job_id: 4, status: 'pending' }),
      run({ job_id: 3, analysis_type: 'stress_test' }),
    ]
    expect(findSavedScenarioRun(runs, 'recession')).toBeUndefined()
  })
})

describe('portfolio analysis cache matching', () => {
  it('matches the same analysis parameters regardless of object key order and portfolio id', () => {
    const saved = { portfolio_id: 1, method: 'block_bootstrap', constraints: { max_sector: .35, max_position: .2 } }
    const current = { constraints: { max_position: .2, max_sector: .35 }, method: 'block_bootstrap', portfolio_id: 9 }
    expect(requestsMatch(saved, current)).toBe(true)
  })

  it('returns only fresh completed runs', () => {
    const runs = [
      { analysis_type: 'monte_carlo', status: 'completed', is_fresh: false, job_id: 2 },
      { analysis_type: 'monte_carlo', status: 'completed', is_fresh: true, job_id: 1 },
    ] as PortfolioAnalysisRun[]
    expect(latestFreshAnalysis(runs, 'monte_carlo')?.job_id).toBe(1)
  })
})
