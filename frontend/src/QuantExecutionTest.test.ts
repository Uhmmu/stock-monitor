import { describe, expect, it } from 'vitest'
import { validateExecutionPolicy, type ExecutionPolicyForm } from './QuantExecutionTest'

const valid: ExecutionPolicyForm = {
  deployments: '1', instruments: '7', symbols: 'BTCUSDT', capital: '100', order: '50', gross: '100', net: '100',
  leverage: '1', dailyLoss: '20', drawdown: '20', openOrders: '1', cooldown: '60',
  signalAge: '3600', accountAge: '30', funding: '0.001', volatility: '0.05',
}

describe('Goal 6 TEST policy form', () => {
  it('keeps the browser control plane bounded and TEST-only', () => {
    expect(validateExecutionPolicy(valid)).toEqual([])
    expect(validateExecutionPolicy({ ...valid, deployments: '' })).toContain('至少允许一个策略部署')
    expect(validateExecutionPolicy({ ...valid, symbols: '' })).toContain('至少允许一个 Binance 标的代码')
    expect(validateExecutionPolicy({ ...valid, order: '101' })).toContain('单笔和净敞口上限不能超过总敞口上限')
    expect(validateExecutionPolicy({ ...valid, leverage: '4' })).toContain('Goal 6 测试杠杆不能超过 3 倍')
    expect(validateExecutionPolicy({ ...valid, funding: '0' })).toContain('风险上限必须是正数')
  })
})
