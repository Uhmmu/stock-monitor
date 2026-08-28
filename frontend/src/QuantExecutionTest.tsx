import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import { formatPaperNumber, formatPaperTime } from './QuantPaper'
import './quant-backtests.css'

type Row = Record<string, unknown>

const rows = (value: unknown): Row[] => {
  if (!value || typeof value !== 'object') return []
  const candidate = (value as Row).items ?? value
  return Array.isArray(candidate) ? candidate.filter(item => item && typeof item === 'object') as Row[] : []
}
const text = (value: unknown) => value == null ? '' : String(value)
const ids = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean).map(Number).filter(item => Number.isInteger(item) && item > 0)

export type ExecutionPolicyForm = {
  deployments: string; instruments: string; symbols: string; capital: string; order: string; gross: string; net: string
  leverage: string; dailyLoss: string; drawdown: string; openOrders: string; cooldown: string
  signalAge: string; accountAge: string; funding: string; volatility: string
}

export function validateExecutionPolicy(value: ExecutionPolicyForm): string[] {
  const errors: string[] = []
  if (!ids(value.deployments).length) errors.push('至少允许一个策略部署')
  if (!ids(value.instruments).length) errors.push('至少允许一个标的')
  if (!value.symbols.split(',').some(item => /^[A-Z0-9]{5,20}$/.test(item.trim().toUpperCase()))) errors.push('至少允许一个 Binance 标的代码')
  const positive = ['capital','order','gross','net','leverage','dailyLoss','drawdown','openOrders','signalAge','accountAge','funding','volatility'] as const
  if (positive.some(key => !Number.isFinite(Number(value[key])) || Number(value[key]) <= 0)) errors.push('风险上限必须是正数')
  if (Number(value.order) > Number(value.gross) || Number(value.net) > Number(value.gross)) errors.push('单笔和净敞口上限不能超过总敞口上限')
  if (Number(value.leverage) > 3) errors.push('Goal 6 测试杠杆不能超过 3 倍')
  return errors
}

function TestBadge() {
  return <span className="test-environment-badge" aria-label="Binance 测试环境">TEST ONLY</span>
}

export function QuantExecutionTest({ enabled = true }: { enabled?: boolean }) {
  const client = useQueryClient()
  const [password, setPassword] = useState('')
  const [accountName, setAccountName] = useState('Binance USD-M Demo')
  const [agentName, setAgentName] = useState('local-test-executor')
  const [accountId, setAccountId] = useState('')
  const [oneTimeToken, setOneTimeToken] = useState('')
  const [policy, setPolicy] = useState<ExecutionPolicyForm>({
    deployments: '', instruments: '', symbols: 'BTCUSDT', capital: '100', order: '50', gross: '100', net: '100',
    leverage: '1', dailyLoss: '20', drawdown: '20', openOrders: '1', cooldown: '60',
    signalAge: '3600', accountAge: '30', funding: '0.001', volatility: '0.05',
  })

  const status = useQuery({
    queryKey: ['execution-test-status'], queryFn: () => api<Row>('/execution/admin/status'),
    enabled, refetchInterval: 15_000, staleTime: 5_000,
  })
  const orders = useQuery({ queryKey: ['execution-test-orders'], queryFn: () => api<unknown>('/execution/admin/orders?limit=20'), enabled, staleTime: 10_000 })
  const events = useQuery({ queryKey: ['execution-test-events'], queryFn: () => api<unknown>('/execution/admin/events?limit=20'), enabled, staleTime: 10_000 })
  const accounts = Array.isArray(status.data?.accounts) ? status.data.accounts as Row[] : []
  const agents = Array.isArray(status.data?.agents) ? status.data.agents as Row[] : []
  const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)
  const refresh = () => {
    for (const key of ['execution-test-status', 'execution-test-orders', 'execution-test-events']) client.invalidateQueries({ queryKey: [key] })
  }
  const guarded = <T,>(fn: () => Promise<T>) => {
    if (!password) return Promise.reject(new Error('高风险变更需要重新输入管理员密码'))
    return fn()
  }

  const createAccount = useMutation({
    mutationFn: () => guarded(() => post<Row>('/execution/admin/accounts', { name: accountName, password })),
    onSuccess: data => { setAccountId(text(data.id || (data.account as Row | undefined)?.id)); refresh() },
  })
  const registerAgent = useMutation({
    mutationFn: () => guarded(() => post<Row>('/execution/admin/agents', { account_id: Number(accountId), name: agentName, password })),
    onSuccess: data => { setOneTimeToken(text(data.token)); refresh() },
  })
  const createPolicy = useMutation({
    mutationFn: () => {
      const errors = validateExecutionPolicy(policy)
      if (errors.length) return Promise.reject(new Error(errors.join('；')))
      return guarded(() => post<Row>('/execution/admin/policies', {
      account_id: Number(accountId), password,
      limits: {
        allowed_deployment_ids: ids(policy.deployments), allowed_instrument_ids: ids(policy.instruments),
        allowed_symbols: policy.symbols.split(',').map(item => item.trim().toUpperCase()).filter(Boolean),
        capital_allocation_usdt: policy.capital, max_order_notional_usdt: policy.order,
        max_gross_notional_usdt: policy.gross, max_net_notional_usdt: policy.net, max_leverage: policy.leverage,
        max_daily_loss_usdt: policy.dailyLoss, max_drawdown_usdt: policy.drawdown,
        max_open_orders: Number(policy.openOrders), cooldown_seconds: Number(policy.cooldown),
        stale_signal_seconds: Number(policy.signalAge), stale_account_seconds: Number(policy.accountAge),
        max_funding_rate_abs: policy.funding, max_volatility: policy.volatility,
      },
    }))}, onSuccess: refresh,
  })
  const kill = useMutation({
    mutationFn: (active: boolean) => guarded(() => post<Row>('/execution/admin/kill-switches', {
      scope_type: 'account', scope_id: Number(accountId),
      enabled: active, reason: active ? '管理员紧急停止' : '管理员解除停止', password,
    })), onSuccess: refresh,
  })
  const revoke = useMutation({
    mutationFn: (id: number) => guarded(() => post<Row>(`/execution/admin/agents/${id}/revoke`, { password })), onSuccess: refresh,
  })

  const busyError = createAccount.error || registerAgent.error || createPolicy.error || kill.error || revoke.error
  const health = text(status.data?.health || 'BLOCKED')
  return <div className="quant-backtests-page quant-execution-test-page">
    <section className="quant-hero">
      <div><p className="crypto-eyebrow">GOAL 6 · LOCAL EXECUTOR <TestBadge /></p><h2>测试执行控制台</h2>
        <p>这里只管理测试账户、策略额度、机器租约和审计。Binance 凭据始终留在本机执行器；没有实盘环境或网页下单入口。</p></div>
      <div className="quant-status-card"><span>执行就绪度 <TestBadge /></span><b className={health === 'TEST_READY' ? 'positive' : 'negative'}>{health}</b>
        <small>LIVE_READY 永久为 {status.data?.live_ready === true ? '异常开启' : 'false'}</small></div>
    </section>

    {status.error && <section className="quant-card"><p className="quant-error" role="alert">测试执行状态不可用：{errorText(status.error)}</p></section>}
    <section className="quant-card quant-config" aria-label="测试执行安全配置">
      <header><div><p className="crypto-eyebrow">TEST CONTROL PLANE <TestBadge /></p><h3>账户、执行器与风险策略</h3></div>
        <button className="danger" type="button" onClick={() => kill.mutate(true)} disabled={!accountId || kill.isPending}>紧急停止</button></header>
      <div className="quant-form-grid">
        <label><span>管理员密码（仅本次操作）</span><input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></label>
        <label><span>测试账户</span><select value={accountId} onChange={event => setAccountId(event.target.value)}><option value="">请选择</option>{accounts.map(item => <option key={text(item.id)} value={text(item.id)}>#{text(item.id)} {text(item.name || item.venue)} · {text(item.status)}</option>)}</select></label>
        <label><span>新账户名称</span><input value={accountName} onChange={event => setAccountName(event.target.value)} /></label>
        <label><span>本地执行器名称</span><input value={agentName} onChange={event => setAgentName(event.target.value)} /></label>
      </div>
      <div className="quant-run-actions">
        <button type="button" onClick={() => createAccount.mutate()} disabled={createAccount.isPending}>创建 TEST 账户</button>
        <button type="button" onClick={() => registerAgent.mutate()} disabled={!accountId || registerAgent.isPending}>注册本地执行器</button>
        <button type="button" onClick={() => kill.mutate(false)} disabled={!accountId || kill.isPending}>解除停止</button>
      </div>
      {oneTimeToken && <div className="execution-token-once" role="status"><b>机器 Token 仅显示一次</b><code>{oneTimeToken}</code><button type="button" onClick={() => setOneTimeToken('')}>我已保存到本机</button></div>}
      {busyError && <p className="quant-error" role="alert">操作失败：{errorText(busyError)}</p>}

      <h4>不可变风险策略</h4>
      <div className="quant-form-grid execution-policy-grid">
        <label><span>允许部署 ID（逗号）</span><input value={policy.deployments} onChange={event => setPolicy({ ...policy, deployments: event.target.value })} /></label>
        <label><span>允许标的 ID（逗号）</span><input value={policy.instruments} onChange={event => setPolicy({ ...policy, instruments: event.target.value })} /></label>
        <label><span>允许 Binance 代码（逗号）</span><input value={policy.symbols} onChange={event => setPolicy({ ...policy, symbols: event.target.value })} /></label>
        {([
          ['capital','分配资金 USDT'],['order','单笔上限'],['gross','总敞口上限'],['net','净敞口上限'],['leverage','杠杆上限'],
          ['dailyLoss','单日亏损上限'],['drawdown','回撤上限'],['openOrders','最大未完成订单'],['cooldown','冷却秒数'],
          ['signalAge','信号最大年龄秒'],['accountAge','账户快照最大年龄秒'],['funding','资金费率绝对值上限'],['volatility','实现波动率上限'],
        ] as const).map(([key,label]) => <label key={key}><span>{label}</span><input type="number" inputMode="decimal" value={policy[key]} onChange={event => setPolicy({ ...policy, [key]: event.target.value })} /></label>)}
      </div>
      <button className="quant-primary-button" type="button" onClick={() => createPolicy.mutate()} disabled={!accountId || createPolicy.isPending}>批准新策略版本</button>
    </section>

    <section className="quant-card"><header><div><p className="crypto-eyebrow">AGENTS <TestBadge /></p><h3>本地执行器</h3></div></header>
      <div className="execution-agent-list">{agents.map(item => <article key={text(item.id)}><div><b>{text(item.name)}</b><small>#{text(item.id)} · {text(item.status)} · 最近心跳 {formatPaperTime(text(item.last_seen_at || item.last_seen))}</small></div>
        {text(item.status) !== 'revoked' && <button className="danger" onClick={() => revoke.mutate(Number(item.id))}>吊销</button>}</article>)}{!agents.length && <p className="quant-muted">尚未注册本地执行器。</p>}</div>
    </section>

    <section className="quant-card"><header><div><p className="crypto-eyebrow">ORDERS & EVENTS <TestBadge /></p><h3>订单与审计</h3></div></header>
      <div className="quant-trade-table execution-order-table"><div className="quant-trade-head"><span>时间</span><span>标的</span><span>客户端 ID</span><span>状态</span><span>数量</span><span>成交</span></div>
        {rows(orders.data).map(item => <div className="quant-trade-row" key={text(item.id)}><span>{formatPaperTime(text(item.created_at))}</span><span>{text(item.symbol || item.instrument_symbol)}</span><span>{text(item.client_order_id)}</span><span>{text(item.status)}</span><span>{formatPaperNumber(item.quantity, 6)}</span><span>{formatPaperNumber(item.filled_quantity, 6)}</span></div>)}</div>
      <div className="execution-event-list">{rows(events.data).map(item => <article key={text(item.id || item.event_id)}><b>{text(item.event_type || item.type)}</b><span>{text(item.status || item.severity)}</span><small>{formatPaperTime(text(item.created_at))}</small></article>)}</div>
    </section>
  </div>
}

export default QuantExecutionTest
