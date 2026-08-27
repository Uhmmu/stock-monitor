import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './api'
import './quant-backtests.css'

/**
 * Goal 5 paper trading console.  Every section carries a PAPER badge: this is
 * a virtual rehearsal environment and must never read as live trading.
 */

export type PaperPositionView = {
  instrument_id: number
  instrument_symbol: string | null
  quantity: string
  avg_entry_price: string
  mark_price: string | null
  exposure: string | null
  unrealized_pnl: string | null
  realized_pnl: string
  total_fees: string
}

export type PaperAccountView = {
  id: number
  environment: string
  base_currency: string
  status: string
  paused_at: string | null
  pause_reason: string | null
  initial_cash: string
  cash: string
  nav: string
  gross_exposure: string
  exposure_ratio: string | null
  leverage_cap: string
  fill_policy: string
  costs: { taker_fee_bps: string; spread_bps: string; slippage_bps: string }
  positions: PaperPositionView[]
  warnings: string[]
  last_funding_boundary: string | null
  last_reconciliation: {
    id: number; status: string; created_at: string; mismatches: unknown[]; warnings: unknown[]
  } | null
}

export type PaperDeploymentView = {
  id: number
  status: string
  strategy_key: string
  strategy_version: string
  instrument_id: number
  instrument_symbol: string | null
  interval: string
  target_exposure: string
  paused_at: string | null
  pause_reason: string | null
  active_signal_id: number | null
  last_signal: { id: number; target_exposure: string; status: string; decision_time: string } | null
  last_run: { id: number; status: string; reason: string | null; boundary: string; created_at: string } | null
}

export type QuantSignalView = {
  id: number
  status: string
  strategy_key: string
  instrument_symbol: string | null
  interval: string
  decision_time: string
  target_exposure: string
  reason: string | null
  expires_at: string
  expires_in_seconds: number
  generated_at: string
  consumed_reason: string | null
  rejected_reason: string | null
  superseded_by_id: number | null
  environment: string
}

export type PaperOrderView = {
  id: number
  signal_id: number | null
  client_order_id: string
  instrument_symbol: string | null
  side: string
  status: string
  intended_quantity: string
  filled_quantity: string
  reference_price: string
  avg_fill_price: string | null
  fee: string
  spread_cost: string
  slippage_cost: string
  reject_reason: string | null
  created_at: string
  fills: {
    id: number; side: string; quantity: string; price: string; fee: string
    realized_pnl: string; fill_time: string
  }[]
}

type Recordish = Record<string, unknown> | null | undefined

const asRecord = (value: unknown): Recordish =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])
const text = (value: unknown): string => (value == null ? '' : String(value))
const num = (value: unknown): number | null => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function formatPaperNumber(value: unknown, digits = 2): string {
  const parsed = num(value)
  return parsed === null ? '数据不足' : parsed.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

export function formatExpiry(seconds: number | null): string {
  if (seconds === null || seconds < 0) return '已过期'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`
  return `${Math.floor(seconds / 3600)} 时 ${Math.floor((seconds % 3600) / 60)} 分`
}

export function formatPaperTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export const SIGNAL_STATUS_LABELS: Record<string, string> = {
  generated: '生效中', superseded: '已被取代', expired: '已过期', rejected: '已拒绝', consumed: '已消费',
}

export function signalStatusLabel(status: string): string {
  return SIGNAL_STATUS_LABELS[status] || status || '未知状态'
}

export function signalStatusClass(status: string): string {
  if (status === 'generated') return 'active'
  if (status === 'rejected' || status === 'expired') return 'failed'
  return 'done'
}

export function normalizePaperAccount(value: unknown): PaperAccountView | null {
  const envelope = asRecord(value)
  const account = asRecord(envelope?.account)
  if (!account || !account.id) return null
  const costs = asRecord(account.costs) ?? {}
  const lastRec = asRecord(account.last_reconciliation)
  return {
    id: Number(account.id),
    environment: text(account.environment) || 'paper',
    base_currency: text(account.base_currency) || 'USDT',
    status: text(account.status) || 'active',
    paused_at: text(account.paused_at) || null,
    pause_reason: text(account.pause_reason) || null,
    initial_cash: text(account.initial_cash) || '0',
    cash: text(account.cash) || '0',
    nav: text(account.nav) || '0',
    gross_exposure: text(account.gross_exposure) || '0',
    exposure_ratio: account.exposure_ratio == null ? null : text(account.exposure_ratio),
    leverage_cap: text(account.leverage_cap) || '1',
    fill_policy: text(account.fill_policy) || 'paper-fill-v1',
    costs: {
      taker_fee_bps: text(costs.taker_fee_bps) || '0',
      spread_bps: text(costs.spread_bps) || '0',
      slippage_bps: text(costs.slippage_bps) || '0',
    },
    positions: asArray(account.positions).flatMap(row => {
      const item = asRecord(row)
      if (!item || !item.instrument_id) return []
      return [{
        instrument_id: Number(item.instrument_id),
        instrument_symbol: text(item.instrument_symbol) || null,
        quantity: text(item.quantity) || '0',
        avg_entry_price: text(item.avg_entry_price) || '0',
        mark_price: item.mark_price == null ? null : text(item.mark_price),
        exposure: item.exposure == null ? null : text(item.exposure),
        unrealized_pnl: item.unrealized_pnl == null ? null : text(item.unrealized_pnl),
        realized_pnl: text(item.realized_pnl) || '0',
        total_fees: text(item.total_fees) || '0',
      }]
    }),
    warnings: asArray(account.warnings).map(item => text(item)).filter(Boolean),
    last_funding_boundary: text(account.last_funding_boundary) || null,
    last_reconciliation: lastRec && lastRec.id ? {
      id: Number(lastRec.id),
      status: text(lastRec.status),
      created_at: text(lastRec.created_at),
      mismatches: asArray(lastRec.mismatches),
      warnings: asArray(lastRec.warnings),
    } : null,
  }
}

export function normalizeDeployments(value: unknown): PaperDeploymentView[] {
  const record = asRecord(value)
  return asArray(record?.items ?? value).flatMap(row => {
    const item = asRecord(row)
    if (!item || !item.id) return []
    const lastSignal = asRecord(item.last_signal)
    const lastRun = asRecord(item.last_run)
    return [{
      id: Number(item.id),
      status: text(item.status) || 'paused',
      strategy_key: text(item.strategy_key),
      strategy_version: text(item.strategy_version) || 'v1',
      instrument_id: Number(item.instrument_id),
      instrument_symbol: item.instrument_symbol == null ? null : text(item.instrument_symbol),
      interval: text(item.interval) || '1h',
      target_exposure: text(item.target_exposure) || '1',
      paused_at: text(item.paused_at) || null,
      pause_reason: text(item.pause_reason) || null,
      active_signal_id: item.active_signal_id == null ? null : Number(item.active_signal_id),
      last_signal: lastSignal && lastSignal.id ? {
        id: Number(lastSignal.id),
        target_exposure: text(lastSignal.target_exposure) || '0',
        status: text(lastSignal.status),
        decision_time: text(lastSignal.decision_time),
      } : null,
      last_run: lastRun && lastRun.id ? {
        id: Number(lastRun.id),
        status: text(lastRun.status),
        reason: text(lastRun.reason) || null,
        boundary: text(lastRun.boundary),
        created_at: text(lastRun.created_at),
      } : null,
    }]
  })
}

export function normalizeSignals(value: unknown): QuantSignalView[] {
  const record = asRecord(value)
  return asArray(record?.items ?? value).flatMap(row => {
    const item = asRecord(row)
    if (!item || !item.id) return []
    return [{
      id: Number(item.id),
      status: text(item.status),
      strategy_key: text(item.strategy_key),
      instrument_symbol: item.instrument_symbol == null ? null : text(item.instrument_symbol),
      interval: text(item.interval) || '1h',
      decision_time: text(item.decision_time),
      target_exposure: text(item.target_exposure) || '0',
      reason: text(item.reason) || null,
      expires_at: text(item.expires_at),
      expires_in_seconds: num(item.expires_in_seconds) ?? 0,
      generated_at: text(item.generated_at),
      consumed_reason: text(item.consumed_reason) || null,
      rejected_reason: text(item.rejected_reason) || null,
      superseded_by_id: item.superseded_by_id == null ? null : Number(item.superseded_by_id),
      environment: text(item.environment) || 'paper',
    }]
  })
}

export function normalizePaperOrders(value: unknown): PaperOrderView[] {
  const record = asRecord(value)
  return asArray(record?.items ?? value).flatMap(row => {
    const item = asRecord(row)
    if (!item || !item.id) return []
    return [{
      id: Number(item.id),
      signal_id: item.signal_id == null ? null : Number(item.signal_id),
      client_order_id: text(item.client_order_id),
      instrument_symbol: item.instrument_symbol == null ? null : text(item.instrument_symbol),
      side: text(item.side),
      status: text(item.status),
      intended_quantity: text(item.intended_quantity) || '0',
      filled_quantity: text(item.filled_quantity) || '0',
      reference_price: text(item.reference_price) || '0',
      avg_fill_price: item.avg_fill_price == null ? null : text(item.avg_fill_price),
      fee: text(item.fee) || '0',
      spread_cost: text(item.spread_cost) || '0',
      slippage_cost: text(item.slippage_cost) || '0',
      reject_reason: text(item.reject_reason) || null,
      created_at: text(item.created_at),
      fills: asArray(item.fills).flatMap(fillRow => {
        const fill = asRecord(fillRow)
        if (!fill || !fill.id) return []
        return [{
          id: Number(fill.id), side: text(fill.side), quantity: text(fill.quantity) || '0',
          price: text(fill.price) || '0', fee: text(fill.fee) || '0',
          realized_pnl: text(fill.realized_pnl) || '0', fill_time: text(fill.fill_time),
        }]
      }),
    }]
  })
}

export function validatePaperAccountForm(initial: string, leverage: string): string[] {
  const errors: string[] = []
  const initialNum = Number(initial)
  const leverageNum = Number(leverage)
  if (!Number.isFinite(initialNum) || initialNum < 100 || initialNum > 10_000_000) errors.push('初始资金必须在 100 至 10,000,000 之间')
  if (!Number.isFinite(leverageNum) || leverageNum < 1 || leverageNum > 3) errors.push('杠杆上限必须在 1 至 3 之间')
  return errors
}

function PaperBadge() {
  return <span className="paper-environment-badge" aria-label="虚拟模拟环境">PAPER</span>
}

export function QuantPaper({ enabled = true }: { enabled?: boolean }) {
  const queryClient = useQueryClient()
  const [accountForm, setAccountForm] = useState({ initial_cash: '10000', leverage_cap: '1' })
  const [accountErrors, setAccountErrors] = useState<string[]>([])
  const [deploymentForm, setDeploymentForm] = useState({ strategy_key: 'dual-ma-trend-v1', instrument_id: '', interval: '1h', target_exposure: '1' })
  const [deploymentError, setDeploymentError] = useState<string | null>(null)

  const paperQuery = useQuery({ queryKey: ['crypto-quant-paper'], queryFn: () => api<unknown>('/crypto/quant/paper'), enabled, staleTime: 10_000 })
  const account = normalizePaperAccount(paperQuery.data)
  const definitionsQuery = useQuery({ queryKey: ['crypto-quant-definitions'], queryFn: () => api<unknown>('/crypto/quant/definitions'), staleTime: 5 * 60_000, enabled })
  const definitionsRecord = asRecord(definitionsQuery.data)
  const strategies = asArray(definitionsRecord?.strategies).map(row => asRecord(row)).filter((row): row is Record<string, unknown> => row !== null)
  const instruments = asArray(definitionsRecord?.instruments).map(row => asRecord(row)).filter((row): row is Record<string, unknown> => row !== null)
  const deploymentsQuery = useQuery({ queryKey: ['crypto-quant-deployments'], queryFn: () => api<unknown>('/crypto/quant/deployments'), enabled, staleTime: 15_000 })
  const deployments = normalizeDeployments(deploymentsQuery.data)
  const signalsQuery = useQuery({
    queryKey: ['crypto-quant-signals'], queryFn: () => api<unknown>('/crypto/quant/signals?limit=20'), enabled, staleTime: 8_000,
    refetchInterval: 15_000,
  })
  const signals = normalizeSignals(signalsQuery.data)
  const ordersQuery = useQuery({ queryKey: ['crypto-quant-paper-orders'], queryFn: () => api<unknown>('/crypto/quant/paper/orders?limit=20'), enabled, staleTime: 10_000 })
  const orders = normalizePaperOrders(ordersQuery.data)
  const reconciliationQuery = useQuery({ queryKey: ['crypto-quant-paper-reconciliations'], queryFn: () => api<unknown>('/crypto/quant/paper/reconciliations?limit=10'), enabled, staleTime: 30_000 })
  const reconciliations = asArray(asRecord(reconciliationQuery.data)?.items).map(row => asRecord(row)).filter((row): row is Record<string, unknown> => row !== null)

  const invalidateAll = () => {
    for (const key of ['crypto-quant-paper', 'crypto-quant-deployments', 'crypto-quant-signals', 'crypto-quant-paper-orders', 'crypto-quant-paper-reconciliations']) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }
  const wrapError = (error: unknown): string => (error instanceof Error ? error.message : String(error))

  const createAccount = useMutation({ mutationFn: () => post<unknown>('/crypto/quant/paper/account', {
    initial_cash: Number(accountForm.initial_cash), leverage_cap: Number(accountForm.leverage_cap),
  }), onSuccess: invalidateAll })
  const accountStatus = useMutation({ mutationFn: (action: 'pause' | 'resume') => post<unknown>(
    `/crypto/quant/paper/${action}`, action === 'pause' ? { reason: '用户暂停' } : {},
  ), onSuccess: invalidateAll })
  const createDeployment = useMutation({ mutationFn: () => post<unknown>('/crypto/quant/deployments', {
    strategy_key: deploymentForm.strategy_key, instrument_id: Number(deploymentForm.instrument_id),
    interval: deploymentForm.interval, target_exposure: Number(deploymentForm.target_exposure),
  }), onSuccess: () => { setDeploymentError(null); invalidateAll() }, onError: error => setDeploymentError(wrapError(error)) })
  const deploymentStatus = useMutation({ mutationFn: ({ id, action }: { id: number; action: 'pause' | 'resume' }) => post<unknown>(
    `/crypto/quant/deployments/${id}/${action}`, action === 'pause' ? { reason: '用户暂停' } : {},
  ), onSuccess: invalidateAll })
  const generate = useMutation({ mutationFn: () => post<unknown>('/crypto/quant/signals/generate', {}), onSuccess: invalidateAll })
  const process = useMutation({ mutationFn: () => post<unknown>('/crypto/quant/paper/process', {}), onSuccess: invalidateAll })
  const reconcile = useMutation({ mutationFn: () => post<unknown>('/crypto/quant/paper/reconcile', {}), onSuccess: invalidateAll })

  const submitAccount = (event: React.FormEvent) => {
    event.preventDefault()
    const errors = validatePaperAccountForm(accountForm.initial_cash, accountForm.leverage_cap)
    setAccountErrors(errors)
    if (!errors.length && enabled) createAccount.mutate()
  }
  const submitDeployment = (event: React.FormEvent) => {
    event.preventDefault()
    if (!deploymentForm.instrument_id) { setDeploymentError('请选择标的'); return }
    if (enabled) createDeployment.mutate()
  }

  return <div className="quant-backtests-page quant-paper-page">
    <section className="quant-hero">
      <div>
        <p className="crypto-eyebrow">PAPER TRADING · GOAL 5 <PaperBadge /></p>
        <h2>模拟交易</h2>
        <p>策略目标仓位 → 风险预检 → 虚拟订单/成交 → 台账对账。全部为虚拟资金演练，不连接交易所、不下真实订单，与实盘账户完全隔离。</p>
      </div>
      {account && <div className="quant-status-card">
        <span>账户状态 <PaperBadge /></span>
        <b>{account.status === 'active' ? '运行中' : '已暂停'}</b>
        <small>NAV {formatPaperNumber(account.nav)} {account.base_currency} · 敞口 {formatPaperNumber(account.gross_exposure)}</small>
      </div>}
    </section>

    {paperQuery.error && <section className="quant-card"><p className="quant-error" role="alert">模拟盘暂时不可用：{wrapError(paperQuery.error)}</p></section>}

    {!account && <section className="quant-card quant-config" aria-label="创建模拟盘账户">
      <header><div><p className="crypto-eyebrow">VIRTUAL ACCOUNT <PaperBadge /></p><h3>创建模拟盘账户</h3></div></header>
      <form onSubmit={submitAccount} noValidate>
        <div className="quant-form-grid">
          <label><span>初始资金（USDT）</span><input type="number" inputMode="decimal" min="100" max="10000000" step="any" value={accountForm.initial_cash} onChange={event => setAccountForm({ ...accountForm, initial_cash: event.target.value })} /></label>
          <label><span>杠杆上限（1 至 3）</span><input type="number" inputMode="decimal" min="1" max="3" step="0.1" value={accountForm.leverage_cap} onChange={event => setAccountForm({ ...accountForm, leverage_cap: event.target.value })} /></label>
        </div>
        {accountErrors.map(error => <p className="quant-error" role="alert" key={error}>{error}</p>)}
        {createAccount.error && <p className="quant-error" role="alert">创建失败：{wrapError(createAccount.error)}</p>}
        <button className="quant-primary-button" type="submit" disabled={!enabled || createAccount.isPending}>{createAccount.isPending ? '创建中…' : '创建虚拟账户'}</button>
        <p className="quant-muted">成本假设沿用回测默认：taker 5 bps、价差 2 bps、滑点 2 bps；成交按决策 bar 收盘价加不利偏移模拟。</p>
      </form>
    </section>}

    {account && <>
      <section className="quant-card" aria-label="模拟盘账户总览">
        <header><div><p className="crypto-eyebrow">ACCOUNT OVERVIEW <PaperBadge /></p><h3>账户总览</h3></div>
          <div className="quant-run-actions">
            <button onClick={() => accountStatus.mutate(account.status === 'active' ? 'pause' : 'resume')} disabled={accountStatus.isPending}>{account.status === 'active' ? '暂停模拟盘' : '恢复模拟盘'}</button>
            <button onClick={() => process.mutate()} disabled={process.isPending}>手动处理信号</button>
            <button onClick={() => reconcile.mutate()} disabled={reconcile.isPending}>立即对账</button>
          </div>
        </header>
        <dl className="quant-metrics">
          <div><dt>NAV</dt><dd>{formatPaperNumber(account.nav)}</dd></div>
          <div><dt>现金</dt><dd>{formatPaperNumber(account.cash)}</dd></div>
          <div><dt>总敞口</dt><dd>{formatPaperNumber(account.gross_exposure)}</dd></div>
          <div><dt>敞口/NAV</dt><dd>{account.exposure_ratio ? formatPaperNumber(Number(account.exposure_ratio) * 100, 1) + '%' : '数据不足'}</dd></div>
          <div><dt>杠杆上限</dt><dd>{formatPaperNumber(account.leverage_cap, 1)}×</dd></div>
          <div><dt>成本假设</dt><dd>taker {formatPaperNumber(account.costs.taker_fee_bps, 1)} · 价差 {formatPaperNumber(account.costs.spread_bps, 1)} · 滑点 {formatPaperNumber(account.costs.slippage_bps, 1)} bps</dd></div>
        </dl>
        {account.pause_reason && <p className="quant-error" role="status">暂停原因：{account.pause_reason}（{formatPaperTime(account.paused_at)}）</p>}
        {account.warnings.map(warning => <p className="quant-error" role="status" key={warning}>{warning}</p>)}
        <div className="quant-trade-table paper-position-table">
          <div className="quant-trade-head"><span>标的</span><span>数量</span><span>均价</span><span>标记价</span><span>未实现</span><span>已实现</span></div>
          {account.positions.map(position => <div className="quant-trade-row" key={position.instrument_id}>
            <span>{position.instrument_symbol || `#${position.instrument_id}`}</span>
            <span>{formatPaperNumber(position.quantity, 4)}</span>
            <span>{formatPaperNumber(position.avg_entry_price, 2)}</span>
            <span>{position.mark_price ? formatPaperNumber(position.mark_price, 2) : '数据不足'}</span>
            <span>{position.unrealized_pnl ? formatPaperNumber(position.unrealized_pnl, 2) : '数据不足'}</span>
            <span>{formatPaperNumber(position.realized_pnl, 2)}</span>
          </div>)}
          {!account.positions.length && <p className="quant-empty">暂无持仓。信号被消费后才会生成虚拟订单。</p>}
        </div>
      </section>

      <section className="quant-card quant-config" aria-label="策略部署管理">
        <header><div><p className="crypto-eyebrow">STRATEGY DEPLOYMENTS <PaperBadge /></p><h3>策略部署</h3></div>
          <div className="quant-run-actions"><button onClick={() => generate.mutate()} disabled={generate.isPending}>手动生成信号</button></div>
        </header>
        <form onSubmit={submitDeployment} noValidate>
          <div className="quant-form-grid">
            <label><span>策略</span><select value={deploymentForm.strategy_key} onChange={event => setDeploymentForm({ ...deploymentForm, strategy_key: event.target.value })}>
              {strategies.map(strategy => <option key={text(strategy.key)} value={text(strategy.key)}>{text(strategy.label || strategy.name) || text(strategy.key)}</option>)}
            </select></label>
            <label><span>标的</span><select value={deploymentForm.instrument_id} onChange={event => setDeploymentForm({ ...deploymentForm, instrument_id: event.target.value })}>
              <option value="">选择永续合约</option>
              {instruments.map(instrument => <option key={text(instrument.id)} value={text(instrument.id)}>{text(instrument.display_label || instrument.provider_symbol)}</option>)}
            </select></label>
            <label><span>周期</span><select value={deploymentForm.interval} onChange={event => setDeploymentForm({ ...deploymentForm, interval: event.target.value })}>
              {['1h', '4h', '1d'].map(value => <option key={value} value={value}>{value}</option>)}
            </select></label>
            <label><span>目标仓位幅度（0.25 至 1）</span><input type="number" inputMode="decimal" min="0.25" max="1" step="0.05" value={deploymentForm.target_exposure} onChange={event => setDeploymentForm({ ...deploymentForm, target_exposure: event.target.value })} /></label>
          </div>
          {deploymentError && <p className="quant-error" role="alert">{deploymentError}</p>}
          <button className="quant-primary-button" type="submit" disabled={!enabled || createDeployment.isPending || !instruments.length}>{createDeployment.isPending ? '创建中…' : '新建部署（默认暂停）'}</button>
          <p className="quant-muted">部署创建后处于暂停状态，手动恢复才会按收盘边界生成信号；暂停会立即作废该部署的生效中信号。</p>
        </form>
        <div className="quant-run-list">
          {deployments.map(deployment => <article key={deployment.id}>
            <button className="quant-run-main" onClick={() => undefined} aria-pressed={false}>
              <b>{deployment.strategy_key || '策略未知'} · {deployment.instrument_symbol || `#${deployment.instrument_id}`} · {deployment.interval}</b>
              <span>目标幅度 {formatPaperNumber(deployment.target_exposure, 2)} · 仓位 ±{formatPaperNumber(deployment.target_exposure, 2)}</span>
              <small>
                {formatPaperTime(deployment.last_run?.created_at)} · {deployment.last_run ? `${deployment.last_run.status}${deployment.last_run.reason ? `：${deployment.last_run.reason}` : ''}` : '尚未运行'} · <i className={`quant-status ${deployment.status === 'active' ? 'active' : 'done'}`}>{deployment.status === 'active' ? '运行中' : '已暂停'}</i>
              </small>
            </button>
            <div className="quant-run-actions">
              <button onClick={() => deploymentStatus.mutate({ id: deployment.id, action: deployment.status === 'active' ? 'pause' : 'resume' })} disabled={deploymentStatus.isPending}>{deployment.status === 'active' ? '暂停' : '恢复'}</button>
            </div>
          </article>)}
          {!deployments.length && <p className="quant-empty">还没有策略部署。</p>}
        </div>
        {generate.error && <p className="quant-error" role="alert">手动生成失败：{wrapError(generate.error)}（冷却期内会返回 429）</p>}
      </section>

      <section className="quant-card" aria-label="信号列表">
        <header><div><p className="crypto-eyebrow">SIGNALS · 目标仓位 <PaperBadge /></p><h3>信号</h3></div><small>信号是期望仓位，不是订单</small></header>
        {signalsQuery.error && <p className="quant-error" role="alert">信号暂时无法读取：{wrapError(signalsQuery.error)}</p>}
        <div className="quant-trade-table">
          <div className="quant-trade-head"><span>生成时间</span><span>决策边界</span><span>目标仓位</span><span>状态</span><span>剩余有效期</span><span>原因</span></div>
          {signals.map(signal => <div className="quant-trade-row" key={signal.id}>
            <span>{formatPaperTime(signal.generated_at)}</span>
            <span>{formatPaperTime(signal.decision_time)} · {signal.interval}</span>
            <span>{formatPaperNumber(Number(signal.target_exposure) * 100, 0)}%</span>
            <span><i className={`quant-status ${signalStatusClass(signal.status)}`}>{signalStatusLabel(signal.status)}</i></span>
            <span>{signal.status === 'generated' ? formatExpiry(signal.expires_in_seconds) : '—'}</span>
            <span>{signal.rejected_reason || signal.consumed_reason || signal.reason || '—'}</span>
          </div>)}
          {!signals.length && <p className="quant-empty">暂无信号。恢复部署后按收盘边界自动生成，或手动触发一次。</p>}
        </div>
      </section>

      <section className="quant-card" aria-label="虚拟订单与成交">
        <header><div><p className="crypto-eyebrow">ORDERS · FILLS <PaperBadge /></p><h3>虚拟订单与成交</h3></div></header>
        <div className="quant-trade-table">
          <div className="quant-trade-head"><span>时间</span><span>标的</span><span>方向</span><span>数量</span><span>成交价</span><span>费用</span><span>状态</span></div>
          {orders.map(order => <div className="quant-trade-row" key={order.id}>
            <span>{formatPaperTime(order.created_at)}</span>
            <span>{order.instrument_symbol || `#${order.client_order_id}`}</span>
            <span>{order.side === 'buy' ? '买入' : '卖出'}</span>
            <span>{formatPaperNumber(order.filled_quantity, 4)} / {formatPaperNumber(order.intended_quantity, 4)}</span>
            <span>{order.avg_fill_price ? formatPaperNumber(order.avg_fill_price, 2) : '—'}</span>
            <span>{formatPaperNumber(order.fee, 4)}</span>
            <span>{order.status}{order.reject_reason ? `：${order.reject_reason}` : ''}{order.signal_id ? ` · 信号 #${order.signal_id}` : ''}</span>
          </div>)}
          {!orders.length && <p className="quant-empty">暂无虚拟订单。</p>}
        </div>
        {!!orders.length && <div className="paper-fills-detail">
          {orders.slice(0, 5).map(order => order.fills.length ? <details key={`fills-${order.id}`}>
            <summary>订单 {order.client_order_id} 的 {order.fills.length} 笔成交</summary>
            {order.fills.map(fill => <p key={fill.id}>{formatPaperTime(fill.fill_time)} · {fill.side === 'buy' ? '买入' : '卖出'} {formatPaperNumber(fill.quantity, 4)} @ {formatPaperNumber(fill.price, 2)} · 费用 {formatPaperNumber(fill.fee, 4)} · 已实现 {formatPaperNumber(fill.realized_pnl, 4)}</p>)}
          </details> : null)}
        </div>}
      </section>

      <section className="quant-card" aria-label="对账历史">
        <header><div><p className="crypto-eyebrow">RECONCILIATION <PaperBadge /></p><h3>对账历史</h3></div>
          <div className="quant-run-actions"><button onClick={() => reconcile.mutate()} disabled={reconcile.isPending}>立即对账</button></div>
        </header>
        {reconcile.error && <p className="quant-error" role="alert">对账失败：{wrapError(reconcile.error)}</p>}
        {reconciliations.map(row => <p className="quant-muted" key={text(row.id)}>
          {formatPaperTime(text(row.created_at))} · {text(row.status) === 'ok' ? '账实一致' : text(row.status) === 'repaired' ? '发现偏差并已修复' : '存在未解释偏差'} · {text(row.fill_count)} 笔成交 / {text(row.funding_count)} 笔资金费 · 台账现金 {formatPaperNumber(text(row.cash_from_ledger))}
        </p>)}
        {!reconciliations.length && <p className="quant-empty">还没有对账记录。</p>}
        <p className="quant-muted">对账从成交+资金费台账重建持仓与现金，与缓存不一致时自动修复并留档；这是模拟盘跨重启安全性的核心演练。</p>
      </section>
    </>}
  </div>
}

export default QuantPaper
export const QuantPaperPage = QuantPaper
