import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, LineSeries, createChart } from 'lightweight-charts'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { Sheet } from './Sheet'
import { api } from './api'
import { chartThemeTokens, getResolvedTheme, subscribeTheme } from './theme'
import type { ThemeMode } from './theme'

// Historical P/E：P/E = 收盘价 ÷ 当时已公开的最近四季摊薄 EPS（SEC XBRL point-in-time）。
// 亏损区间 P/E 记 N/M（null），曲线断开且不参与统计。

type PePoint = { date: string; price: number; eps_ttm: number; pe: number | null }

type PeHistory = {
  ticker: string
  metric: string
  range: string
  status: 'ok' | 'insufficient_history' | 'syncing' | 'no_eps_data'
  current: { price: number | null; eps_ttm: number | null; pe: number | null; pe_status: string; as_of_date: string | null }
  statistics: {
    mean: number; median: number; p25: number; p75: number
    percentile: number | null; vs_median_pct: number | null; valid_points: number
  } | null
  history: { first_date: string | null; last_date: string | null; years_available: number | null } | null
  series: PePoint[]
}

const RANGES: { key: '3y' | '5y' | '10y' | 'max'; label: string }[] = [
  { key: '3y', label: '3Y' }, { key: '5y', label: '5Y' }, { key: '10y', label: '10Y' }, { key: 'max', label: 'MAX' },
]

function percentileBand(p: number | null): string | null {
  if (p == null) return null
  if (p <= 20) return '历史低位'
  if (p <= 40) return '低于历史区间'
  if (p <= 60) return '接近历史中位'
  if (p <= 80) return '高于历史区间'
  return '历史高位'
}

const fmtX = (v: number | null | undefined, digits = 1) => (v == null ? 'N/M' : `${v.toFixed(digits)}x`)
const fmtPct = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)

function PeChart({ data, statistics }: { data: PeHistory; statistics: NonNullable<PeHistory['statistics']> }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [hovered, setHovered] = useState<PePoint | null>(null)
  const [theme, setTheme] = useState<ThemeMode>(() => getResolvedTheme())
  useEffect(() => subscribeTheme(setTheme), [])

  const byDate = useMemo(() => {
    const map = new Map<string, PePoint>()
    for (const row of data.series) map.set(row.date, row)
    return map
  }, [data])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let chart: IChartApi | null = null
    let observer: ResizeObserver | null = null
    try {
      const tokens = chartThemeTokens()
      chart = createChart(host, {
        width: Math.max(host.clientWidth, 1),
        height: host.clientWidth < 600 ? 250 : 320,
        layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: tokens.text, fontFamily: 'inherit', fontSize: 11 },
        grid: { vertLines: { color: tokens.grid }, horzLines: { color: tokens.grid } },
        rightPriceScale: { borderVisible: false, scaleMargins: { top: .08, bottom: .1 } },
        timeScale: { borderVisible: false, timeVisible: false, secondsVisible: false, rightOffset: 1, fixLeftEdge: true, fixRightEdge: true },
        crosshair: { vertLine: { labelVisible: true }, horzLine: { labelVisible: true } },
        localization: {
          locale: 'zh-CN',
          priceFormatter: (price: number) => `${price >= 100 ? price.toFixed(0) : price.toFixed(1)}x`,
        },
      })
      const series = chart.addSeries(LineSeries, {
        color: tokens.accent, lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
        crosshairMarkerVisible: true, title: '',
      })
      // 亏损区间用 whitespace 点断线，绝不画成负 P/E
      series.setData(data.series.map(row => (
        row.pe == null ? { time: row.date as Time } : { time: row.date as Time, value: row.pe }
      )))

      const first = data.series[0]?.date
      const last = data.series[data.series.length - 1]?.date
      const ref = (color: string, width: 1 | 2, value: number): ISeriesApi<'Line'> => {
        const line = chart!.addSeries(LineSeries, {
          color, lineWidth: width, lineStyle: 2, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, title: '',
        })
        line.setData(first && last ? [{ time: first as Time, value }, { time: last as Time, value }] : [])
        return line
      }
      if (first && last) {
        ref(tokens.zeroLine, 2, statistics.median)
        ref(tokens.textStrong, 1, statistics.p25)
        ref(tokens.textStrong, 1, statistics.p75)
      }
      chart.timeScale().fitContent()

      chart.subscribeCrosshairMove(param => {
        const time = param.time as string | undefined
        setHovered(time ? byDate.get(time) ?? null : null)
      })

      observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
        const width = entries[0]?.contentRect.width
        if (width) chart?.applyOptions({ width, height: width < 600 ? 250 : 320 })
      })
      observer?.observe(host)
    } catch (error) {
      console.error('Historical P/E chart render failed', error)
    }
    return () => {
      observer?.disconnect()
      chart?.remove()
      chart = null
    }
  }, [data, statistics, byDate, theme])

  const point = hovered ?? data.series[data.series.length - 1] ?? null
  return (
    <div className="pe-chart">
      <div className="pe-chart-canvas" ref={hostRef} role="img" aria-label="历史市盈率曲线" />
      <div className="pe-chart-tooltip">
        {point ? (
          <>
            <span className="pe-tooltip-date">{point.date}</span>
            <span>价格 <b>{point.price.toFixed(2)}</b></span>
            <span>TTM EPS <b>{point.eps_ttm.toFixed(2)}</b></span>
            <span>P/E <b>{point.pe == null ? 'N/M' : `${point.pe.toFixed(2)}x`}</b></span>
          </>
        ) : <span>该区间没有可显示的交易日</span>}
      </div>
      <div className="pe-chart-legend">
        <i style={{ borderTop: '2px solid' }} />P/E
        <i className="pe-legend-median" />中位 {fmtX(statistics.median)}
        <i className="pe-legend-quartile" />P25 {fmtX(statistics.p25)} / P75 {fmtX(statistics.p75)}
      </div>
    </div>
  )
}

function PeBody({ ticker, range }: { ticker: string; range: '3y' | '5y' | '10y' | 'max' }) {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['pe-history', ticker, range],
    queryFn: () => api<PeHistory>(`/valuation/history?ticker=${ticker}&range=${range}&metric=pe`),
    enabled: !!ticker,
    staleTime: 10 * 60_000,
    retry: 1,
  })

  if (query.isLoading) {
    return <div className="pe-state"><span className="pe-spinner" aria-hidden="true" />正在读取历史估值数据…</div>
  }
  if (query.isError) {
    return (
      <div className="pe-state">
        <p>历史估值数据暂时无法读取。</p>
        <button type="button" className="pe-retry" onClick={() => query.refetch()}>重试</button>
      </div>
    )
  }
  const data = query.data
  if (!data) return null

  if (data.status === 'syncing' || data.status === 'no_eps_data') {
    return (
      <div className="pe-state">
        <p>正在首次采集该股票的 SEC 财报事实（point-in-time EPS），通常几分钟内完成。</p>
        <button type="button" className="pe-retry" onClick={() => client.invalidateQueries({ queryKey: ['pe-history', ticker] })}>刷新</button>
      </div>
    )
  }
  if (data.status === 'insufficient_history' || !data.statistics) {
    return (
      <div className="pe-state">
        <p>SEC 财报历史不足四季，暂时无法构建 TTM EPS 与历史 P/E。</p>
        {data.history?.first_date && <small>价格数据自 {data.history.first_date} 起可用。</small>}
      </div>
    )
  }

  const { current, statistics } = data
  const band = percentileBand(statistics.percentile)
  const validPePoints = data.series.some(row => row.pe != null)
  return (
    <div className="pe-history">
      <div className="pe-hero">
        <div className="pe-hero-main">
          <span>Current P/E</span>
          <strong className={current.pe == null ? 'pe-nm' : ''}>{fmtX(current.pe)}</strong>
          <small>
            截至 {current.as_of_date ?? '—'}
            {current.price != null && <> · 收盘 {current.price.toFixed(2)}</>}
            {current.eps_ttm != null && <> · TTM EPS {current.eps_ttm.toFixed(2)}</>}
          </small>
          {current.pe_status === 'negative_ttm' && <em>TTM 亏损，P/E 记为 N/M（Not Meaningful）</em>}
        </div>
        <dl className="pe-hero-stats">
          <div><dt>Median</dt><dd>{fmtX(statistics.median)}</dd></div>
          <div><dt>Mean</dt><dd>{fmtX(statistics.mean)}</dd></div>
          <div><dt>Percentile</dt><dd>{statistics.percentile == null ? '—' : `${Math.round(statistics.percentile)}%`}{band && <em>{band}</em>}</dd></div>
          <div><dt>vs Median</dt><dd>{fmtPct(statistics.vs_median_pct)}</dd></div>
          <div><dt>P25–P75</dt><dd>{fmtX(statistics.p25)}–{fmtX(statistics.p75)}</dd></div>
        </dl>
      </div>

      {validPePoints ? (
        <PeChart data={data} statistics={statistics} />
      ) : (
        <div className="pe-state"><p>该区间 TTM 持续为负，没有有效的正 P/E 数据点；下方统计为空。</p></div>
      )}

      <p className="pe-footnote">
        {statistics.valid_points} 个有效交易日{data.history?.years_available != null && <> · 共 {data.history.years_available} 年历史可用（{data.history.first_date} 起）</>}。
        P/E = 收盘价 ÷ 当时已公开的最近四个连续财季摊薄 EPS（SEC XBRL，按财报实际披露日生效，无未来数据泄露）；价格与 EPS 均已按拆股调整到当前股本，亏损区间计为 N/M 且不参与统计。
        历史分位只说明相对自身历史的位置，不构成高估/低估或买卖结论。
      </p>
    </div>
  )
}

export function HistoricalPeSheet({ ticker, onClose }: { ticker: string | null; onClose: () => void }) {
  const [range, setRange] = useState<'3y' | '5y' | '10y' | 'max'>('5y')
  useEffect(() => { setRange('5y') }, [ticker])
  return (
    <Sheet open={!!ticker} onClose={onClose} title={ticker ? `${ticker} 历史市盈率` : undefined} size="wide">
      <div className="pe-history-toolbar">
        <div className="segmented compact" role="tablist" aria-label="时间范围">
          {RANGES.map(item => (
            <button
              key={item.key} type="button" role="tab" aria-selected={range === item.key}
              className={range === item.key ? 'active' : ''} onClick={() => setRange(item.key)}
            >{item.label}</button>
          ))}
        </div>
      </div>
      {ticker && <PeBody key={`${ticker}:${range}`} ticker={ticker} range={range} />}
    </Sheet>
  )
}
