import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, patch, post } from '@shared/api'
import { formatDateTime, formatMoney } from '@shared/format'
import { GlassCard, IOSPage, LoadingState, NavigationBar, SectionHeader, StateView, StatusPill } from '../components'

type JournalRow = {
  security_id?: number | null
  ticker: string
  direction: string
  quantity: number | null
  price: number | null
  fee: number | null
  strategy: string
  result: string
}

type JournalLog = {
  id: number
  trade_date: string
  ticker: string | null
  direction: string | null
  quantity: number | null
  price: number | null
  note: string | null
  content: string | null
  table_rows: JournalRow[]
  photo_urls: string[]
  ai_summary: string | null
  ai_summary_model: string | null
  status: 'draft' | 'published' | string
  source_type: 'manual' | 'ibkr_sync' | string
  objective_facts: Record<string, unknown>
  created_at: string
}

type JournalForm = {
  trade_date: string
  ticker: string
  direction: string
  quantity: string
  price: string
  note: string
  content: string
}

type TradeLogPayload = {
  trade_date: string
  ticker: string | null
  direction: string | null
  quantity: number | null
  price: number | null
  note: string | null
  content: string | null
  table_rows: JournalRow[]
  photo_urls: string[]
}

export type JournalPageProps = {
  back?: () => void
  initialMode?: 'list' | 'new'
  initialLogId?: number | null
}

const fieldStyle: CSSProperties = { display: 'grid', gap: '.35rem', color: 'var(--secondary)', fontSize: '.72rem' }
const inputStyle: CSSProperties = { width: '100%', minHeight: '2.8rem', padding: '0 .75rem', border: '1px solid var(--separator)', borderRadius: '12px', color: 'var(--text)', background: 'rgba(118,118,128,.07)', outline: 'none' }
const textareaStyle: CSSProperties = { ...inputStyle, minHeight: '6.5rem', padding: '.7rem .75rem', resize: 'vertical', lineHeight: 1.5 }

function todayKey() {
  const date = new Date()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function emptyForm(): JournalForm {
  return { trade_date: todayKey(), ticker: '', direction: '', quantity: '', price: '', note: '', content: '' }
}

function formFromLog(log: JournalLog): JournalForm {
  return {
    trade_date: log.trade_date,
    ticker: log.ticker || '',
    direction: log.direction || '',
    quantity: log.quantity == null ? '' : String(log.quantity),
    price: log.price == null ? '' : String(log.price),
    note: log.note || '',
    content: log.content || '',
  }
}

function numberOrNull(value: string) {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function factValue(facts: Record<string, unknown>, key: string) {
  const value = facts[key]
  if (value == null || value === '') return '数据不足'
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString('zh-CN', { maximumFractionDigits: 6 })
  return String(value)
}

function JournalCard({ log, onEdit }: { log: JournalLog; onEdit: (log: JournalLog) => void }) {
  const isDraft = log.status === 'draft'
  const facts = log.objective_facts || {}
  return <article className="activity-card" style={{ display: 'block' }}>
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '.7rem' }}>
      <div style={{ minWidth: 0, display: 'grid', gap: '.3rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '.45rem' }}>
          <StatusPill tone={isDraft ? 'warning' : 'positive'}>{isDraft ? '待写复盘' : '已完成'}</StatusPill>
          <strong>{log.ticker || '未填写标的'}</strong>
        </div>
        <small>{log.direction || '交易记录'} · {log.source_type === 'ibkr_sync' ? 'IBKR 自动草稿' : formatDateTime(log.created_at)}</small>
      </div>
      <time style={{ flex: '0 0 auto', color: 'var(--blue)', fontSize: '.72rem', fontWeight: 700 }}>{log.trade_date}</time>
    </div>

    {log.source_type === 'ibkr_sync' && <div style={{ display: 'grid', gap: '.28rem', marginTop: '.8rem', padding: '.7rem', borderRadius: '12px', color: 'var(--secondary)', background: 'rgba(255,159,10,.08)', fontSize: '.72rem', lineHeight: 1.45 }}>
      <strong style={{ color: 'var(--orange)' }}>券商事实已填好</strong>
      <span>仓位 {factValue(facts, 'quantity_before')} → {factValue(facts, 'quantity_after')}</span>
      <span>成交价 {factValue(facts, 'execution_price')} · 手续费 {factValue(facts, 'commission')}</span>
    </div>}
    {log.note && <p style={{ margin: '.75rem 0 0', fontSize: '.8rem', lineHeight: 1.55 }}>{log.note}</p>}
    {log.content && <p style={{ margin: '.55rem 0 0', color: 'var(--secondary)', fontSize: '.77rem', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{log.content}</p>}
    {log.table_rows.length > 0 && <div style={{ display: 'grid', gap: '.3rem', marginTop: '.7rem', paddingTop: '.65rem', borderTop: '1px solid var(--separator)', color: 'var(--secondary)', fontSize: '.7rem' }}>
      {log.table_rows.slice(0, 4).map((row, index) => <span key={`${log.id}-${index}`}>{row.ticker || '—'} · {row.direction || '数据不足'} · {row.quantity == null ? '数量不足' : row.quantity} @ {row.price == null ? '价格不足' : row.price}</span>)}
      {log.table_rows.length > 4 && <span>还有 {log.table_rows.length - 4} 条交易明细</span>}
    </div>}
    {log.ai_summary && <div style={{ marginTop: '.7rem', padding: '.7rem', borderRadius: '12px', color: 'var(--secondary)', background: 'var(--blue-soft)', fontSize: '.75rem', lineHeight: 1.55 }}>
      <strong style={{ display: 'block', marginBottom: '.25rem', color: 'var(--blue)' }}>AI 复盘摘要{log.ai_summary_model ? ` · ${log.ai_summary_model}` : ''}</strong>
      <span>{log.ai_summary}</span>
    </div>}
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '.55rem', marginTop: '.85rem' }}>
      <button className="primary-button" style={{ minHeight: '2.5rem', padding: '0 .85rem', fontSize: '.75rem' }} onClick={() => onEdit(log)}>{isDraft ? '填写复盘' : '编辑日志'}</button>
    </div>
  </article>
}

export function JournalPage({ back, initialMode = 'list', initialLogId = null }: JournalPageProps) {
  const client = useQueryClient()
  const logs = useQuery({ queryKey: ['ios-trade-logs'], queryFn: () => api<JournalLog[]>('/trade-logs') })
  const [editorOpen, setEditorOpen] = useState(initialMode === 'new')
  const [editing, setEditing] = useState<JournalLog | null>(null)
  const [form, setForm] = useState<JournalForm>(emptyForm)
  const initialLogOpened = useRef(false)

  const closeEditor = () => {
    setEditorOpen(false)
    setEditing(null)
    setForm(emptyForm())
  }
  const openNew = () => {
    setEditing(null)
    setForm(emptyForm())
    setEditorOpen(true)
  }
  const openEdit = (log: JournalLog) => {
    setEditing(log)
    setForm(formFromLog(log))
    setEditorOpen(true)
  }

  useEffect(() => {
    if (initialLogId == null || !logs.data || initialLogOpened.current) return
    initialLogOpened.current = true
    const log = logs.data.find((item) => item.id === initialLogId)
    if (log) openEdit(log)
  }, [initialLogId, logs.data])

  const payload = (): TradeLogPayload => ({
    trade_date: form.trade_date,
    ticker: form.ticker.trim().toUpperCase() || null,
    direction: form.direction || null,
    quantity: numberOrNull(form.quantity),
    price: numberOrNull(form.price),
    note: form.note.trim() || null,
    content: form.content.trim() || null,
    table_rows: editing?.table_rows || [],
    photo_urls: editing?.photo_urls || [],
  })
  const save = useMutation({
    mutationFn: () => editing ? patch<JournalLog>(`/trade-logs/${editing.id}`, payload()) : post<JournalLog>('/trade-logs', payload()),
    onSuccess: () => {
      closeEditor()
      void client.invalidateQueries({ queryKey: ['ios-trade-logs'] })
    },
  })

  const drafts = (logs.data || []).filter((log) => log.status === 'draft')
  const published = (logs.data || []).filter((log) => log.status !== 'draft')
  const editorTitle = editing ? (editing.status === 'draft' ? '填写交易复盘' : '编辑交易日志') : '新建交易日志'
  const brokerFactsReadonly = editing?.source_type === 'ibkr_sync'

  return <>
    {back && <NavigationBar title="交易日志" eyebrow="TRADING JOURNAL" back={back}/>}
    <IOSPage className={back ? 'detail-page' : ''}>
      <section className="large-title">
        <span>TRADING JOURNAL</span>
        <h1>交易日志</h1>
        <p>把执行、背景与复盘留在同一条记录里。</p>
      </section>

      <SectionHeader title="我的日志" caption={`${logs.data?.length ?? 0} 条记录`} action={<button className="primary-button" style={{ minHeight: '2.65rem', padding: '0 .9rem', fontSize: '.76rem' }} onClick={editorOpen ? closeEditor : openNew}>{editorOpen ? '关闭编辑' : '新建日志'}</button>}/>

      {editorOpen && <div style={{ marginBottom: '1rem' }}><GlassCard className="market-card">
        <div className="market-card-heading">
          <div><span>{editing ? 'EDIT ENTRY' : 'NEW ENTRY'}</span><strong>{editorTitle}</strong></div>
          {brokerFactsReadonly && <StatusPill tone="warning">IBKR 事实只读</StatusPill>}
        </div>
        <form onSubmit={(event) => { event.preventDefault(); save.mutate() }} style={{ display: 'grid', gap: '.8rem', marginTop: '1rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '.65rem' }}>
            <label style={fieldStyle}>日期<input style={inputStyle} type="date" value={form.trade_date} onChange={(event) => setForm({ ...form, trade_date: event.target.value })} required readOnly={brokerFactsReadonly}/></label>
            <label style={fieldStyle}>标的<input style={inputStyle} value={form.ticker} onChange={(event) => setForm({ ...form, ticker: event.target.value })} placeholder="例如 AAPL" readOnly={brokerFactsReadonly}/></label>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: '.65rem' }}>
            <label style={fieldStyle}>方向<select style={inputStyle} value={form.direction} onChange={(event) => setForm({ ...form, direction: event.target.value })} disabled={brokerFactsReadonly}><option value="">选择方向</option><option value="买入">买入</option><option value="卖出">卖出</option><option value="调整">调整</option><option value="观望">观望</option></select></label>
            <label style={fieldStyle}>数量<input style={inputStyle} type="number" inputMode="decimal" min="0" step="any" value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} placeholder="数据不足" readOnly={brokerFactsReadonly}/></label>
          </div>
          <label style={fieldStyle}>成交价<input style={inputStyle} type="number" inputMode="decimal" min="0" step="any" value={form.price} onChange={(event) => setForm({ ...form, price: event.target.value })} placeholder="数据不足" readOnly={brokerFactsReadonly}/></label>
          <label style={fieldStyle}>简短备注<input style={inputStyle} value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} placeholder="一句话记录当天最重要的交易背景"/></label>
          <label style={fieldStyle}>文字记录<textarea style={textareaStyle} value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} placeholder="记录交易计划、执行、情绪、复盘和明天要验证的条件"/></label>
          {brokerFactsReadonly && <div style={{ padding: '.75rem', borderRadius: '12px', color: 'var(--secondary)', background: 'rgba(255,159,10,.08)', fontSize: '.72rem', lineHeight: 1.5 }}>
            IBKR 成交、费用、汇率和仓位变化是只读证据；这里只补充主观复盘，不会反向修改持仓。
          </div>}
          {save.error && <p style={{ margin: 0, color: 'var(--red)', fontSize: '.74rem', lineHeight: 1.45 }}>保存失败，当前记录未改变。请稍后重试。</p>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '.55rem' }}>
            <button type="button" className="text-button" onClick={closeEditor}>取消</button>
            <button type="submit" className="primary-button" style={{ minHeight: '2.75rem', padding: '0 1rem', fontSize: '.78rem' }} disabled={save.isPending}>{save.isPending ? '保存中…' : '保存日志'}</button>
          </div>
        </form>
      </GlassCard></div>}

      {logs.isLoading && <LoadingState rows={5}/>}
      {logs.isError && <StateView title="交易日志读取失败" message="请检查网络后重试；没有可用数据时不会补写记录。" retry={() => { void logs.refetch() }}/>}
      {!logs.isLoading && !logs.isError && <>
        <SectionHeader title="待写草稿" caption="IBKR 同步的客观事实不会被编辑覆盖"/>
        {drafts.length ? <div className="activity-list">{drafts.map((log) => <JournalCard key={log.id} log={log} onEdit={openEdit}/>)}</div> : <StateView title="暂无草稿" message="同步 IBKR 持仓变化后，待写复盘会显示在这里。"/>}

        <SectionHeader title="已完成记录" caption={published.length ? `${published.length} 条可继续编辑` : '你的交易计划与复盘会保存在这里'}/>
        {published.length ? <div className="activity-list">{published.map((log) => <JournalCard key={log.id} log={log} onEdit={openEdit}/>)}</div> : <StateView title="暂无记录" message="点击上方“新建日志”，留下第一条交易复盘。"/>}
      </>}
    </IOSPage>
  </>
}
