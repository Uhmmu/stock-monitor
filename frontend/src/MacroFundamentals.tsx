import { Component, type ErrorInfo, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, LineSeries, createChart, type IChartApi, type Time } from 'lightweight-charts'
import { api, post } from './api'
import { Sheet } from './Sheet'
import { chartThemeTokens, getResolvedTheme, subscribeTheme, type ThemeMode } from './theme'

type ValuePoint = { observation_date: string; value: number | null; last_fetched_at?: string | null; is_derived?: boolean }
type Freshness = { status: string; label_zh: string; age_days?: number; last_fetched_at?: string | null }
type MacroCard = {
  series_key: string; display_name_zh: string; display_name_en: string; description_zh: string; unit: string; frequency: string; category: string
  latest: ValuePoint | null; previous: ValuePoint | null; trend: { direction: string; strength: string }
  current_impact: { label: string; label_zh: string }; freshness: Freshness; data_status: string
  sparkline?: ValuePoint[]
}
type SummaryDriver = {
  series_key: string; display_name_zh?: string | null; observation_date: string | null; effect: string; reason: string; unit?: string | null
  current_value?: number | null; current_observation_date?: string | null; previous_value?: number | null; previous_observation_date?: string | null; comparison_label_zh?: string | null
}
type Summary = { state: string; label_zh: string; tone: string; confidence: number; drivers: SummaryDriver[]; disclaimer: string }
type Overview = {
  source: { provider: string; name: string; enabled: boolean; configured: boolean; status: string; status_label_zh: string }
  last_sync_at: string | null; last_attempt_status: string | null; last_successful_sync_at: string | null; last_full_success_at: string | null; latest_observation_date: string | null; latest_fetched_at: string | null
  usage: { used: number; daily_limit: number; reserved_requests: number; remaining: number; automatic_remaining: number; automatic_usable_limit: number; usage_date_utc: string }
  summaries: Record<string, Summary>; cards: MacroCard[]; curve_analysis: { state: string; label_zh: string; spread_10y_2y?: number | null; spread_10y_3m?: number | null; reason_codes?: string[] }
  integrity: { raw_series_count: number; available_series_count: number; missing_series_keys: string[]; errors: Record<string, unknown> }
  disclaimer: string
}
type SeriesDetail = MacroCard & {
  display_name_en: string; observations: ValuePoint[]; derived_series: Record<string, ValuePoint[]>; interpretation: {
    why_it_matters: string; rising_interpretation: string; falling_interpretation: string; bullish_scenarios: string[]; bearish_scenarios: string[]; context_notes: string[]; affected_assets: Record<string, string>
  }; source_attribution: string; disclaimer: string
}
type YieldCurve = { maturities: string[]; curves: { label: string; observation_date: string; points: { maturity: string; value: number | null }[] }[]; analysis: Overview['curve_analysis'] }
type SyncStatus = { source: Overview['source']; usage: Overview['usage']; last_successful_sync_at: string | null; next_scheduled_sync: string; runs: { id: number; status: string; started_at: string; finished_at: string | null; api_requests_used: number; successful_series_count: number; failed_series_count: number; trigger_type: string }[] }

const summaryLabels: Record<string, string> = { growth: '增长', inflation: '通胀', labor: '就业', policy: '政策', yield_curve: '收益率曲线', consumer: '消费', composite: '综合环境' }
const categoryLabels: Record<string, string> = { growth: '增长与产出', inflation: '通胀', labor: '就业', rates: '利率', consumer: '消费与工业' }
const unitLabels: Record<string, string> = { percent: '%', percentage_points: '个百分点', persons: '人', index: '指数', currency: '（原始单位）', currency_per_capita: '（原始单位/人）' }
const displayDate = (value: string | null | undefined) => value ? new Date(value).toLocaleDateString('zh-CN') : '—'
const displayDateTime = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN') : '—'
const formatValue = (value: number | null | undefined, unit?: string) => {
  if (value == null || Number.isNaN(value)) return '数据不足'
  if (unit === 'persons') return `${Math.round(value).toLocaleString('en-US')} 人`
  if (unit === 'percent' || unit === 'percentage_points') return `${value >= 0 ? '+' : ''}${value.toFixed(2)}${unit === 'percent' ? '%' : ' 个百分点'}`
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`
  if (Math.abs(value) >= 1_000) return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
  return value.toLocaleString('en-US', { maximumFractionDigits: 3 })
}
const directionLabel: Record<string, string> = { rising: '上升', falling: '下降', stable: '稳定', mixed: '混合', insufficient_data: '数据不足' }
const toneClass = (tone: string) => tone === 'positive' ? 'positive' : tone === 'negative' ? 'negative' : tone === 'mixed' ? 'macro-mixed' : ''

function Sparkline({ values, color = '#397bd8', height = 42 }: { values: (number | null)[]; color?: string; height?: number }) {
  const points = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (points.length < 2) return <div className="macro-no-chart">历史数据不足</div>
  const min = Math.min(...points); const max = Math.max(...points); const span = max - min || 1
  const coords = points.map((value, index) => `${(index / Math.max(points.length - 1, 1)) * 100},${height - 5 - ((value - min) / span) * (height - 12)}`).join(' ')
  return <svg className="macro-sparkline" viewBox={`0 0 100 ${height}`} role="img" aria-label="历史趋势"><polyline points={coords} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke"/><title>{points.map(value => value.toFixed(2)).join('，')}</title></svg>
}

function MacroHistoryChart({ detail, range, mode }: { detail: SeriesDetail; range: string; mode: string }) {
  const days: Record<string, number | null> = { '1y': 365, '3y': 365 * 3, '5y': 365 * 5, '10y': 365 * 10, all: null }
  const raw = (mode === 'raw' ? detail.observations : detail.derived_series?.[mode] || detail.observations) || []
  const cutoff = useMemo(() => days[range] == null ? null : Date.now() - days[range]! * 86_400_000, [range])
  const chartHostRef = useRef<HTMLDivElement>(null)
  const [theme,setTheme]=useState<ThemeMode>(()=>getResolvedTheme())
  useEffect(()=>subscribeTheme(setTheme),[])
  const chartRows = useMemo(() => {
    const rows = raw.filter(row => {
      if (!row || typeof row.observation_date !== 'string') return false
      const observedAt = new Date(row.observation_date).getTime()
      return Number.isFinite(observedAt) && (!cutoff || observedAt >= cutoff)
    })
    return rows
      .filter((row): row is ValuePoint & { value: number } => typeof row.value === 'number' && Number.isFinite(row.value))
      .sort((left, right) => left.observation_date.localeCompare(right.observation_date))
  }, [raw, cutoff])
  useEffect(() => {
    const host = chartHostRef.current
    if (!host || chartRows.length < 2) return
    let chart: IChartApi | null = null
    let observer: ResizeObserver | null = null
    try {
      const tokens = chartThemeTokens()
      chart = createChart(host, {
        width: Math.max(host.clientWidth, 1),
        height: host.clientWidth < 600 ? 250 : 320,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: tokens.text,
          fontFamily: 'inherit',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: tokens.grid },
          horzLines: { color: tokens.grid },
        },
        rightPriceScale: { borderVisible: false, scaleMargins: { top: .08, bottom: .1 } },
        timeScale: { borderVisible: false, timeVisible: false, secondsVisible: false, rightOffset: 1, fixLeftEdge: true, fixRightEdge: true },
        crosshair: { vertLine: { labelVisible: true }, horzLine: { labelVisible: true } },
        localization: { locale: 'zh-CN' },
      })
      const series = chart.addSeries(LineSeries, {
        color: tokens.accent,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: true,
        // Keep the series name out of the right endpoint; the detail header identifies it.
        title: '',
      })
      const lineData = chartRows.map(row => ({ time: row.observation_date as Time, value: row.value }))
      series.setData(lineData)

      // Preserve the old zero baseline without adding another endpoint label.
      const zero = chart.addSeries(LineSeries, {
        color: tokens.zeroLine,
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        title: '',
      })
      zero.setData(lineData.map(row => ({ time: row.time, value: 0 })))
      chart.timeScale().fitContent()

      observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
        const width = entries[0]?.contentRect.width
        if (width) chart?.applyOptions({ width, height: width < 600 ? 250 : 320 })
      })
      observer?.observe(host)
    } catch (error) {
      console.error('Macro history chart render failed', error)
    }
    return () => {
      observer?.disconnect()
      chart?.remove()
      chart = null
    }
  }, [chartRows, theme])

  if (chartRows.length < 2) return <div className="macro-chart-empty">这个范围内的历史数据不足，系统不会用直线填补缺失日期。</div>
  return <div className="macro-history-chart"><div className="macro-history-canvas" ref={chartHostRef} role="img" aria-label={`宏观指标历史图：${detail.display_name_zh}`}/><div className="macro-chart-axis"><span>{chartRows[0]?.observation_date}</span><span>{chartRows[chartRows.length - 1]?.observation_date}</span></div></div>
}

class MacroDetailErrorBoundary extends Component<{ children: ReactNode; resetKey: string | null; onClose: () => void }, { hasError: boolean }> {
  state = { hasError: false }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true }
  }

  componentDidUpdate(previousProps: Readonly<{ children: ReactNode; resetKey: string | null; onClose: () => void }>) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.hasError) this.setState({ hasError: false })
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Macro detail render failed', error, info)
  }

  render() {
    if (this.state.hasError) {
      return <div className="macro-detail-error" role="alert"><b>指标详情暂时无法显示</b><span>历史数据已经保留，当前弹窗内容出现异常。</span><button className="macro-outline-btn" onClick={this.props.onClose}>关闭弹窗</button></div>
    }
    return this.props.children
  }
}

function MacroStatusBanner({ overview }: { overview: Overview }) {
  const source = overview.source
  if (!source.configured) return <div className="macro-status-banner macro-status-unconfigured"><span className="macro-status-dot"/><div><b>Alpha Vantage 宏观数据源未配置</b><p>管理员可在服务器环境变量中配置 Key；页面不会直接访问 Alpha Vantage。</p></div></div>
  const partial = source.status === 'partial_failure' || source.status === 'failed' || source.status === 'stale'
  const attemptLabel:Record<string,string>={success:'成功',partial_success:'部分成功',failed:'失败',running:'进行中'}
  return <div className={`macro-status-banner ${partial ? 'macro-status-warning' : ''}`}><span className="macro-status-dot"/><div><b>数据源：Alpha Vantage 宏观经济接口 · {source.status_label_zh}</b><p>最后完整同步 {displayDateTime(overview.last_full_success_at||overview.last_successful_sync_at)} · 最新观察 {displayDate(overview.latest_observation_date)}</p>{overview.last_sync_at&&overview.last_attempt_status!=='success'&&<small>最近同步尝试 {displayDateTime(overview.last_sync_at)} · {attemptLabel[overview.last_attempt_status||'']||overview.last_attempt_status}</small>}</div><span className="macro-quota">今日项目侧调用 {overview.usage.used} / {overview.usage.daily_limit}<small>自动同步可用 {overview.usage.automatic_remaining} 次 · 预留 {overview.usage.reserved_requests} 次</small></span></div>
}

function SummaryStrip({ summaries, selectedKey, onSelect }: { summaries: Overview['summaries']; selectedKey: string | null; onSelect: (key: string, summary: Summary) => void }) {
  return <><p className="macro-rule-note">增长、通胀、就业与政策均由已存 Alpha Vantage 序列按本地确定性规则推导，不是 AI 生成；点击可查看指标、观察日期与判断原因。</p><div className="macro-summary-strip">{Object.entries(summaries).map(([key, summary]) => <button type="button" key={key} className={`macro-summary-chip ${toneClass(summary.tone)}`} aria-expanded={selectedKey === key} aria-label={`${summaryLabels[key] || key}：${summary.label_zh}，查看判断依据`} onClick={() => onSelect(key, summary)}><span>{summaryLabels[key] || key}</span><strong>{summary.label_zh}</strong><small>规则推导 · 置信度 {Math.round(summary.confidence * 100)}%</small><i aria-hidden="true">查看依据</i></button>)}</div></>
}

function SummaryEvidence({ categoryKey, summary }: { categoryKey: string; summary: Summary }) {
  return <article className="macro-summary-detail"><header><p className="eyebrow">{summaryLabels[categoryKey] || categoryKey} · DETERMINISTIC RULE</p><h2>{summary.label_zh}</h2><p>置信度 {Math.round(summary.confidence * 100)}%。这是规则化摘要，不是 AI 生成的投资结论。</p></header><section className="macro-summary-conclusion"><span>推断结论</span><b>{summary.label_zh}</b><p>{summary.drivers.length > 0 ? `以下 ${summary.drivers.length} 条已存数据证据触发了当前规则。` : '当前没有足够的可用指标形成更具体的判断。'}</p></section>{summary.drivers.length > 0 && <ol>{summary.drivers.map((driver, index) => <li key={`${driver.series_key}-${index}`}><div className="macro-evidence-heading"><span>{String(index + 1).padStart(2, '0')}</span><div><b>{driver.display_name_zh || driver.series_key}</b><small>{driver.observation_date ? `规则观察日 ${displayDate(driver.observation_date)}` : '综合规则'}</small></div></div>{driver.current_value != null && <dl><div><dt>本期</dt><dd>{formatValue(driver.current_value, driver.unit || undefined)}</dd><small>{displayDate(driver.current_observation_date || driver.observation_date)}</small></div><div><dt>{driver.comparison_label_zh || '对比期'}</dt><dd>{formatValue(driver.previous_value, driver.unit || undefined)}</dd><small>{displayDate(driver.previous_observation_date)}</small></div></dl>}<p><span>判断原因</span>{driver.reason}</p></li>)}</ol>}<footer><b>解读边界</b><p>{summary.disclaimer}</p></footer></article>
}

function YieldCurvePanel({ curve }: { curve?: YieldCurve }) {
  const current = curve?.curves.find(item => item.label === 'current')
  if (!current) return <div className="macro-empty-panel">收益率曲线需要五个期限在同一观察日期都有可用数据。</div>
  const max = Math.max(...current.points.map(point => point.value || 0), 1); const min = Math.min(...current.points.map(point => point.value || 0), 0); const span = max - min || 1
  const coords = current.points.map((point, index) => `${(index / 4) * 100},${108 - ((point.value! - min) / span) * 90}`).join(' ')
  return <div className="macro-curve-panel"><div className="macro-panel-heading"><div><p>RATES</p><h3>美国国债收益率曲线</h3></div><span>{displayDate(current.observation_date)} · {curve!.analysis.label_zh}</span></div><svg viewBox="0 0 100 120" preserveAspectRatio="none" className="macro-curve-chart"><polyline points={coords} className="macro-chart-line"/><line x1="0" x2="100" y1="108" y2="108" className="macro-axis-line"/></svg><div className="macro-curve-labels">{current.points.map(point => <span key={point.maturity}><b>{point.maturity}</b><small>{point.value == null ? '—' : `${point.value.toFixed(2)}%`}</small></span>)}</div><p className="macro-derived-note">收益率曲线状态为规则推导：同时参考当前利差、20/60 个有效交易日前利差，以及短端/长端变化方向。</p></div>
}

function MacroDetail({ selectedKey, onClose }: { selectedKey: string | null; onClose: () => void }) {
  const detail = useQuery({ queryKey: ['us-macro-series', selectedKey], queryFn: () => api<SeriesDetail>(`/fundamentals/macro/us/series/${selectedKey}`), enabled: !!selectedKey, staleTime: 10 * 60_000 })
  const explanation = useQuery({ queryKey: ['us-macro-explanation', selectedKey], queryFn: () => api<SeriesDetail & { limitations: string[]; current_system_judgment: { label_zh: string; reason: string; confidence: string }; market_impact: { asset: string; stance: string; reason: string }[] }>(`/fundamentals/macro/us/series/${selectedKey}/explanation`), enabled: !!selectedKey && detail.isSuccess, staleTime: 10 * 60_000 })
  const [range, setRange] = useState('5y')
  const [mode, setMode] = useState('raw')

  useEffect(() => {
    setRange('5y')
    setMode('raw')
  }, [selectedKey])

  const modes = detail.data ? [
    { key: 'raw', label: detail.data.unit === 'index' ? '指数水平' : '原始值' },
    ...Object.keys(detail.data.derived_series || {}).map(key => ({
      key,
      label: key.includes('yoy') ? '同比' : key.includes('mom') ? '环比' : key.includes('annualized') ? '三个月年化' : key.includes('change') ? '月度变化' : '推导值',
    })),
  ] : []

  return (
    <Sheet open={!!selectedKey} onClose={onClose} title={detail.data?.display_name_zh || '宏观指标详情'}>
      <MacroDetailErrorBoundary resetKey={selectedKey} onClose={onClose}>
        {detail.isLoading && <div className="macro-loading">正在读取历史数据…</div>}
        {detail.isError && <div className="macro-empty-panel">指标详情暂不可用，请稍后重试。</div>}
        {detail.data && (
          <article className="macro-detail">
            <header className="macro-detail-header">
              <p className="eyebrow">{detail.data.display_name_en} · {detail.data.frequency}</p>
              <h2>{detail.data.display_name_zh}</h2>
              <p>{detail.data.description_zh}</p>
            </header>

            <div className="macro-detail-facts" aria-label="指标摘要">
              <div><span>最新值</span><b>{formatValue(detail.data.latest?.value, detail.data.unit)}</b><small>{displayDate(detail.data.latest?.observation_date)}</small></div>
              <div><span>前值</span><b>{formatValue(detail.data.previous?.value, detail.data.unit)}</b><small>{displayDate(detail.data.previous?.observation_date)}</small></div>
              <div><span>趋势</span><b>{directionLabel[detail.data.trend?.direction || 'insufficient_data'] || detail.data.trend?.direction || '数据不足'}</b><small>{detail.data.freshness?.label_zh || '数据不足'}</small></div>
            </div>

            <div className="macro-chart-toolbar" aria-label="历史数据筛选">
              <div className="macro-chart-control-group">
                <span>显示</span>
                {modes.map(item => <button type="button" key={item.key} className={mode === item.key ? 'active' : ''} onClick={() => setMode(item.key)}>{item.label}</button>)}
              </div>
              <div className="macro-chart-control-group">
                <span>范围</span>
                {['1y', '3y', '5y', '10y', 'all'].map(item => <button type="button" key={item} className={range === item ? 'active' : ''} onClick={() => setRange(item)}>{item === 'all' ? '全部' : item}</button>)}
              </div>
            </div>

            <MacroHistoryChart detail={detail.data} range={range} mode={mode}/>
            {explanation.isLoading && <p className="macro-detail-loading">正在读取指标解读…</p>}
            {explanation.data && <>
              <section className="macro-detail-section macro-detail-reading">
                <h3>如何解读</h3>
                <p>{explanation.data.interpretation?.rising_interpretation}</p>
                <p>{explanation.data.interpretation?.falling_interpretation}</p>
              </section>
              <section className="macro-detail-section macro-detail-impact">
                <h3>对市场的可能影响</h3>
                <div className="macro-impact-list">{(explanation.data.market_impact || []).map(item => <div key={item.asset}><b>{item.asset}</b><span>{item.stance}</span><p>{item.reason}</p></div>)}</div>
              </section>
              <section className="macro-detail-section macro-detail-judgment">
                <h3>当前系统判断</h3>
                <div className="macro-judgment"><b>{explanation.data.current_system_judgment?.label_zh || '数据不足'}</b><p>{explanation.data.current_system_judgment?.reason}</p><small>置信度：{explanation.data.current_system_judgment?.confidence || '未知'} · 依据：已存历史序列与确定性规则</small></div>
              </section>
              <section className="macro-detail-section macro-detail-limitations">
                <h3>限制与注意事项</h3>
                <ul>{(explanation.data.limitations || []).map(note => <li key={note}>{note}</li>)}</ul>
              </section>
            </>}
          </article>
        )}
      </MacroDetailErrorBoundary>
    </Sheet>
  )
}

export function MacroFundamentals({ isAdmin = false }: { isAdmin?: boolean }) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null); const [selectedSummary, setSelectedSummary] = useState<{ key: string; summary: Summary } | null>(null)
  const overview = useQuery({ queryKey: ['us-macro-overview'], queryFn: () => api<Overview>('/fundamentals/macro/us/overview'), staleTime: 10 * 60_000, refetchInterval: 15 * 60_000 })
  const curve = useQuery({ queryKey: ['us-macro-yield-curve'], queryFn: () => api<YieldCurve>('/fundamentals/macro/us/yield-curve'), staleTime: 10 * 60_000, enabled: overview.isSuccess })
  if (overview.isLoading) return <div className="macro-page"><div className="macro-loading">正在读取美国宏观数据…</div></div>
  if (overview.isError || !overview.data) return <div className="macro-page"><div className="macro-empty-panel">美国宏观数据暂不可用。后端会继续保留上一次成功同步的数据。</div></div>
  const data = overview.data
  return <div className="macro-page"><div className="macro-page-heading"><div><p className="eyebrow">US MACRO FUNDAMENTALS</p><h2>美国宏观</h2><p>整个市场共用的宏观时间序列。观察日期与系统抓取时间分开显示。</p></div>{isAdmin && <button className="macro-outline-btn" onClick={() => setSelectedKey('us_cpi')}>查看指标说明</button>}</div><MacroStatusBanner overview={data}/><SummaryStrip summaries={data.summaries} selectedKey={selectedSummary?.key || null} onSelect={(key, summary) => setSelectedSummary({ key, summary })}/><section className="macro-core-section"><div className="macro-section-heading"><div><p>CORE INDICATORS</p><h3>核心指标</h3></div><span>{data.integrity.available_series_count}/{data.integrity.raw_series_count} 个原始序列有数据</span></div><div className="macro-card-grid">{data.cards.map(card => <button type="button" className="macro-card" key={card.series_key} onClick={() => setSelectedKey(card.series_key)}><div className="macro-card-top"><span>{categoryLabels[card.category] || card.category}</span><small className={`macro-freshness ${card.freshness.status}`}>{card.freshness.label_zh}</small></div><h4>{card.display_name_zh}</h4><strong>{formatValue(card.latest?.value, card.unit)}</strong><div className="macro-card-meta"><span>观察 {displayDate(card.latest?.observation_date)}</span><span>{card.latest?.value != null && card.previous?.value != null ? `较前值 ${formatValue(card.latest.value - card.previous.value, card.unit === 'percent' ? 'percentage_points' : card.unit)}` : '前值不足'}</span></div><Sparkline values={(card.sparkline || []).map(point => point.value)} color={card.current_impact.label === 'bearish' ? '#be6b71' : '#397bd8'}/><footer><span>影响：{card.current_impact.label_zh}</span><i>ⓘ</i></footer></button>)}</div></section><section className="macro-section-grid macro-secondary-section"><YieldCurvePanel curve={curve.data}/><div className="macro-data-notes"><div className="macro-panel-heading"><div><p>DATA NOTES</p><h3>数据状态</h3></div></div><dl><div><dt>最后成功同步</dt><dd>{displayDateTime(data.last_successful_sync_at)}</dd></div><div><dt>最新观察日期</dt><dd>{displayDate(data.latest_observation_date)}</dd></div><div><dt>自动同步预算</dt><dd>{data.usage.automatic_remaining} / {data.usage.automatic_usable_limit}</dd></div></dl>{data.integrity.missing_series_keys.length > 0 && <p className="macro-warning-text">缺少：{data.integrity.missing_series_keys.join('、')}</p>}<p className="macro-derived-note">数据来自 Alpha Vantage 官方 REST API；其页面标注的底层序列来源由 provider 字段保留。派生指标由本地确定性规则计算。</p></div></section><footer className="macro-disclaimer">{data.disclaimer}</footer><MacroDetail selectedKey={selectedKey} onClose={() => setSelectedKey(null)}/><Sheet open={!!selectedSummary} onClose={() => setSelectedSummary(null)} title="宏观环境判断依据">{selectedSummary && <SummaryEvidence categoryKey={selectedSummary.key} summary={selectedSummary.summary}/>}</Sheet></div>
}

export function MacroDataSourcePanel({ isAdmin = false }: { isAdmin?: boolean }) {
  const client = useQueryClient()
  const status = useQuery({ queryKey: ['us-macro-sync-status'], queryFn: () => api<SyncStatus>('/fundamentals/macro/us/sync-status'), enabled: isAdmin, refetchInterval: 30_000 })
  const test = useMutation({ mutationFn: () => post<{ response_ms: number }>('/admin/integrations/alpha-vantage/test', {}), onSuccess: () => client.invalidateQueries({ queryKey: ['us-macro-sync-status'] }) })
  const sync = useMutation({ mutationFn: () => post<{ status: string }>('/admin/integrations/alpha-vantage/macro/sync', { mode: 'full', series_keys: [], force: false }), onSuccess: () => client.invalidateQueries({ queryKey: ['us-macro-sync-status'] }) })
  if (!isAdmin) return null
  const source = status.data?.source
  return <section className="macro-settings-panel"><div className="section-title"><div><p>DATA SOURCE</p><h2>Alpha Vantage 宏观数据</h2></div><span>{source?.status_label_zh || '读取中'}</span></div><div className="macro-settings-grid"><div><span>Key 状态</span><b>{source?.configured ? '已配置（服务端）' : '未配置'}</b></div><div><span>今日调用</span><b>{status.data ? `${status.data.usage.used} / ${status.data.usage.daily_limit}` : '—'}</b></div><div><span>每日自动保护</span><b>{status.data ? `${status.data.usage.automatic_usable_limit} 次` : '—'}</b></div><div><span>最后成功同步</span><b>{displayDateTime(status.data?.last_successful_sync_at)}</b></div></div><div className="macro-settings-actions"><button onClick={() => test.mutate()} disabled={test.isPending || !source?.configured}>{test.isPending ? '测试中…' : '测试连接'}</button><button onClick={() => sync.mutate()} disabled={sync.isPending || !source?.configured}>{sync.isPending ? '排队中…' : '手动全量同步'}</button>{test.isSuccess && <small>连接成功，响应 {test.data.response_ms}ms</small>}{(test.isError || sync.isError) && <small className="negative">操作失败：请查看同步状态或日志。</small>}</div></section>
}
