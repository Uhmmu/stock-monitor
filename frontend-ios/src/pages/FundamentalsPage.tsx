import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { api } from '@shared/api'
import { formatDateTime, formatPercent } from '@shared/format'
import type { FinancialStatement, Fundamentals, SecEvent, SecFinancial, SecHoldings, SecInsider, ValuationMetric, ValuationSnapshot, WatchItem } from '@shared/types'
import { IOSPage, LoadingState, SectionHeader, StateView, StatusPill } from '../components'

type Module = 'valuation' | 'financials' | 'sec'
type SecView = 'events' | 'financials' | 'insider' | 'holdings'
const percentLabels = new Set(['毛利率 %', '净利率 %', '营业利润率 %', 'ROE %', 'ROA %', '营收增速 YoY %', 'EPS增速 YoY %'])
const statementLabels: Record<string, string> = { revenue: '营收', gross_profit: '毛利润', operating_income: '营业利润', net_income: '净利润', eps: '每股收益', ebitda: 'EBITDA', cash: '现金及等价物', inventory: '存货', current_assets: '流动资产', total_assets: '总资产', total_debt: '总债务', shareholders_equity: '股东权益', operating_cash_flow: '经营现金流', capital_expenditure: '资本开支', free_cash_flow: '自由现金流', financing_cash_flow: '融资现金流', investing_cash_flow: '投资现金流' }
const statementGroups = [
  ['利润表', 'income_statement', ['revenue', 'gross_profit', 'operating_income', 'net_income', 'eps', 'ebitda']],
  ['资产负债表', 'balance_sheet', ['cash', 'inventory', 'current_assets', 'total_assets', 'total_debt', 'shareholders_equity']],
  ['现金流量表', 'cash_flow', ['operating_cash_flow', 'capital_expenditure', 'free_cash_flow', 'financing_cash_flow', 'investing_cash_flow']],
] as const

export function FundamentalsPage() {
  const [module, setModule] = useState<Module>('valuation')
  const [ticker, setTicker] = useState('')
  const watchlist = useQuery({ queryKey: ['ios-watchlist'], queryFn: () => api<WatchItem[]>('/watchlist'), staleTime: 60_000 })
  const current = ticker || watchlist.data?.[0]?.ticker || ''
  return <IOSPage className="fundamentals-page">
    <section className="large-title"><span>RESEARCH</span><h1>基本面</h1><p>估值、财报与 SEC 官方披露。</p></section>
    <div className="security-picker"><span>当前证券</span><select value={current} onChange={event => setTicker(event.target.value)} aria-label="选择证券">{watchlist.data?.map(item => <option key={item.id} value={item.ticker}>{item.ticker}</option>)}</select></div>
    <div className="segmented-control fundamentals-segments" role="tablist">{([['valuation', '估值'], ['financials', '财务报表'], ['sec', 'SEC']] as [Module, string][]).map(([key, label]) => <button role="tab" aria-selected={module === key} className={module === key ? 'active' : ''} key={key} onClick={() => setModule(key)}>{label}</button>)}</div>
    {!current ? <StateView title="还没有可分析证券" message="请先在自选股中添加证券。"/> : module === 'valuation' ? <ValuationView ticker={current}/> : module === 'financials' ? <FinancialStatementsView ticker={current}/> : <SecView ticker={current}/>}
  </IOSPage>
}

function ValuationView({ ticker }: { ticker: string }) {
  const fundamentals = useQuery({ queryKey: ['ios-fundamentals', ticker], queryFn: () => api<Fundamentals>(`/fundamentals?ticker=${encodeURIComponent(ticker)}`), staleTime: 60_000 })
  const valuation = useQuery({ queryKey: ['ios-valuation', ticker], queryFn: () => api<ValuationSnapshot>(`/cross-model?ticker=${encodeURIComponent(ticker)}`), staleTime: 60_000, retry: false })
  if (fundamentals.isLoading || valuation.isLoading) return <LoadingState rows={7}/>
  const snapshot = valuation.data
  const quote = snapshot?.dcf_scenarios.current ?? snapshot?.consensus.current
  return <div className="mobile-valuation">
    <section className="valuation-hero"><div><span>{snapshot?.classification.industry || snapshot?.classification.sector || '行业待同步'}</span><h2>{snapshot?.company || ticker}</h2><p>{snapshot?.classification.focus || '基于已存财务、同行与市场数据进行多模型估值。'}</p></div>{snapshot?.model_conflict && <StatusPill tone="warning">模型有分歧</StatusPill>}</section>
    {snapshot ? <>
      <SectionHeader title="估值区间" caption={`快照 ${snapshot.snapshot_date}`}/>
      <div className="valuation-range"><Scenario label="保守" value={snapshot.dcf_scenarios.bear} current={quote}/><Scenario label="基准" value={snapshot.dcf_scenarios.base || snapshot.consensus.value} current={quote} primary/><Scenario label="乐观" value={snapshot.dcf_scenarios.bull} current={quote}/></div>
      <div className="valuation-context"><span>当前价格 <b>{moneyLike(quote)}</b></span><span>反向 DCF 隐含增长 <b>{snapshot.reverse_dcf.implied_fcf_growth == null ? '数据不足' : `${snapshot.reverse_dcf.implied_fcf_growth.toFixed(1)}${snapshot.reverse_dcf.unit || '%'}`}</b></span></div>
      <SectionHeader title="模型判断" caption="逐个模型保留分歧，不强行合并"/>
      <div className="model-signal-list">{snapshot.model_signals.map(signal => <article key={signal.key}><div><strong>{signal.label}</strong><span>{'★'.repeat(Math.max(0, signal.stars))}{'☆'.repeat(Math.max(0, 5 - signal.stars))}</span></div><b>{signal.verdict}</b><p>{signal.detail}</p></article>)}</div>
      <SectionHeader title="核心估值指标" caption="本地值优先，并显示同行位置"/>
      <MetricGroup rows={snapshot.valuation}/>
      {snapshot.ai_opinion && <details className="valuation-opinion"><summary>查看 AI 估值解读</summary><div><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{snapshot.ai_opinion}</ReactMarkdown></div><small>{snapshot.ai_model || 'AI'} · 生成于 {formatDateTime(snapshot.generated_at)}</small></details>}
    </> : <StateView title="估值快照尚未生成" message="桌面端可触发今日估值刷新；已有数据不会被臆测补齐。"/>}
    <SectionHeader title="实时基本面" caption={fundamentals.data ? `查询于 ${formatDateTime(fundamentals.data.as_of)}` : undefined}/>
    <div className="fundamental-metric-grid">{fundamentals.data?.metrics.map(metric => <div key={metric.label}><span>{metric.label}</span><strong>{formatFundamental(metric.label, metric.value)}</strong><small>{metric.source || '数据不足'}</small></div>)}</div>
    {fundamentals.isError && <StateView title="基本面暂不可用" message="实时数据源没有返回有效指标。"/>}
  </div>
}

function Scenario({ label, value, current, primary = false }: { label: string; value: number | null; current: number | null | undefined; primary?: boolean }) {
  const delta = value != null && current ? (value - current) / current * 100 : null
  return <div className={primary ? 'primary' : ''}><span>{label}</span><strong>{moneyLike(value)}</strong><small className={(delta || 0) >= 0 ? 'gain' : 'loss'}>{delta == null ? '数据不足' : formatPercent(delta)}</small></div>
}

function MetricGroup({ rows }: { rows: ValuationMetric[] }) {
  return <div className="valuation-metric-list">{rows.map(metric => <article key={metric.key}><div><strong>{metric.label}</strong><b>{metric.display || formatMetricValue(metric.value, metric.unit)}</b></div><p>{metric.explanation}</p><footer><span>{metric.peer_median == null ? '同行数据不足' : `同行中位数 ${formatMetricValue(metric.peer_median, metric.unit)}`}</span>{metric.comparison && <em>{metric.comparison}</em>}</footer></article>)}</div>
}

function FinancialStatementsView({ ticker }: { ticker: string }) {
  const [frequency, setFrequency] = useState<'annual' | 'quarterly'>('annual')
  const [period, setPeriod] = useState(0)
  const query = useQuery({ queryKey: ['ios-statements', ticker, frequency], queryFn: () => api<FinancialStatement[]>(`/financial-statements?ticker=${encodeURIComponent(ticker)}&frequency=${frequency}`), staleTime: 60_000 })
  useEffect(() => setPeriod(0), [ticker, frequency])
  const row = query.data?.[period]
  if (query.isLoading) return <LoadingState rows={7}/>
  if (!query.data?.length) return <StateView title="财务报表数据不足" message="系统尚未同步该证券的 Yahoo 三大报表。"/>
  return <div className="mobile-statements"><div className="inline-toggle"><button className={frequency === 'annual' ? 'active' : ''} onClick={() => setFrequency('annual')}>年度</button><button className={frequency === 'quarterly' ? 'active' : ''} onClick={() => setFrequency('quarterly')}>季度</button></div><div className="period-scroll" aria-label="选择报告期">{query.data.map((item, index) => <button className={period === index ? 'active' : ''} key={item.period_end} onClick={() => setPeriod(index)}><b>{frequency === 'annual' ? item.fiscal_year : item.fiscal_period}</b><span>{item.period_end}</span></button>)}</div><p className="result-caption">{row?.source} · {row?.currency || '币种未知'} · 同步于 {formatDateTime(row?.synced_at)}</p>{row && statementGroups.map(([title, key, metrics]) => <section className="statement-mobile-card" key={key}><h2>{title}</h2>{metrics.map(metric => <div key={metric}><span>{statementLabels[metric] || metric}</span><strong>{compactNumber(row[key][metric])}</strong></div>)}</section>)}</div>
}

function SecView({ ticker }: { ticker: string }) {
  const [view, setView] = useState<SecView>('events')
  const events = useQuery({ queryKey: ['ios-sec-events', ticker], queryFn: () => api<SecEvent[]>(`/sec-events?ticker=${encodeURIComponent(ticker)}`), enabled: view === 'events' })
  const financials = useQuery({ queryKey: ['ios-sec-financials', ticker], queryFn: () => api<SecFinancial[]>(`/sec-financials?ticker=${encodeURIComponent(ticker)}`), enabled: view === 'financials' })
  const insider = useQuery({ queryKey: ['ios-sec-insider', ticker], queryFn: () => api<SecInsider[]>(`/sec-insider?ticker=${encodeURIComponent(ticker)}`), enabled: view === 'insider' })
  const holdings = useQuery({ queryKey: ['ios-sec-holdings', ticker], queryFn: () => api<SecHoldings>(`/sec-13f?ticker=${encodeURIComponent(ticker)}`), enabled: view === 'holdings' })
  const loading = events.isLoading || financials.isLoading || insider.isLoading || holdings.isLoading
  return <div className="mobile-sec"><div className="sec-tabs">{([['events', '重大事件'], ['financials', '财务'], ['insider', '内部人'], ['holdings', '13F']] as [SecView, string][]).map(([key, label]) => <button className={view === key ? 'active' : ''} onClick={() => setView(key)} key={key}>{label}</button>)}</div><p className="result-caption">SEC EDGAR 官方披露 · 数据可能存在申报滞后</p>{loading && <LoadingState rows={6}/>}
    {view === 'events' && <div className="sec-event-list">{events.data?.map(item => <article key={item.id}><header><StatusPill tone={item.priority === 'urgent' ? 'negative' : item.priority === 'important' ? 'warning' : 'neutral'}>{item.form} · Item {item.item_code}</StatusPill><time>{item.filing_date || '日期未知'}</time></header><h2>{item.item_label}</h2>{item.summary_zh ? <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{item.summary_zh}</ReactMarkdown> : <p>{item.summary_status === 'failed' ? item.text?.slice(0, 500) || '数据不足' : 'AI 中文总结生成中…'}</p>}<a href={item.filing_url} target="_blank" rel="noreferrer">查看 SEC 原文 ↗</a></article>)}{!events.isLoading && !events.data?.length && <StateView title="暂无重大事件" message="该证券尚无已解析的结构化事件。"/>}</div>}
    {view === 'financials' && <div className="sec-data-list">{financials.data?.map(item => <article key={`${item.fiscal_year}-${item.fiscal_period}-${item.form}`}><header><strong>{item.fiscal_year} {item.fiscal_period}</strong><span>{item.form} · {item.period_end}</span></header><dl><div><dt>营收</dt><dd>{compactNumber(item.revenue)}</dd></div><div><dt>净利润</dt><dd>{compactNumber(item.net_income)}</dd></div><div><dt>摊薄 EPS</dt><dd>{item.eps_diluted ?? '数据不足'}</dd></div><div><dt>经营现金流</dt><dd>{compactNumber(item.operating_cash_flow)}</dd></div></dl></article>)}</div>}
    {view === 'insider' && <div className="sec-data-list">{insider.data?.map(item => <article key={item.id}><header><strong>{item.insider_name}</strong><span>{item.insider_title || '内部人'} · {item.transaction_date || '日期未知'}</span></header><dl><div><dt>类型</dt><dd>{transactionName(item.transaction_code)}</dd></div><div><dt>股数</dt><dd>{compactNumber(item.shares)}</dd></div><div><dt>价格</dt><dd>{moneyLike(item.price)}</dd></div><div><dt>金额</dt><dd>{compactNumber(item.value)}</dd></div></dl><a href={item.filing_url} target="_blank" rel="noreferrer">查看 Form 4 ↗</a></article>)}</div>}
    {view === 'holdings' && <><p className="result-caption">季度截至 {holdings.data?.report_period || '未知'}；13F 最多滞后约 45 天，仅含申报多头。</p><div className="sec-data-list">{holdings.data?.holdings.map(item => <article key={item.id}><header><strong>{item.manager_name}</strong><span>{item.filing_date || '申报日未知'}</span></header><dl><div><dt>持股数</dt><dd>{compactNumber(item.shares)}</dd></div><div><dt>市值</dt><dd>{compactNumber(item.value_usd)}</dd></div><div><dt>环比</dt><dd>{item.is_new ? '本季新建仓' : compactNumber(item.share_change)}</dd></div></dl></article>)}</div></>}
  </div>
}

function formatFundamental(label: string, value: number | null) { if (value == null) return '—'; if (percentLabels.has(label)) return `${value.toFixed(1)}%`; if (label === '市值(百万)') return `${(value / 1000).toFixed(1)}B`; return value.toLocaleString('en-US', { maximumFractionDigits: 2 }) }
function compactNumber(value: number | null | undefined) { if (value == null) return '数据不足'; const sign = value < 0 ? '−' : ''; const absolute = Math.abs(value); if (absolute >= 1e12) return `${sign}${(absolute / 1e12).toFixed(2)}T`; if (absolute >= 1e9) return `${sign}${(absolute / 1e9).toFixed(2)}B`; if (absolute >= 1e6) return `${sign}${(absolute / 1e6).toFixed(1)}M`; if (absolute >= 1e3) return `${sign}${(absolute / 1e3).toFixed(1)}K`; return value.toLocaleString('en-US', { maximumFractionDigits: 2 }) }
function moneyLike(value: number | null | undefined) { return value == null ? '数据不足' : value.toLocaleString('en-US', { maximumFractionDigits: 2 }) }
function formatMetricValue(value: number | null, unit: string) { return value == null ? '数据不足' : `${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit === '%' ? '%' : unit && unit !== 'number' ? ` ${unit}` : ''}` }
function transactionName(code: string | null) { return ({ P: '公开市场买入', S: '卖出', M: '期权行权', F: '税务代扣', A: '授予', G: '赠予', D: '处置' } as Record<string, string>)[code || ''] || code || '数据不足' }
