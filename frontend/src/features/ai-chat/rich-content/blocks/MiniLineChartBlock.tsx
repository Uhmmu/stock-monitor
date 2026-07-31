import { useMemo, useState } from 'react'
import { BlockFrame } from '../components/BlockFrame'
import { formatNumber, toNumber } from '../format'
import type { MiniLineChartData, RichBlockProps } from '../types'

const colors = ['#1677d2', '#7b61c9', '#d97745', '#3f8f69', '#b34f75']
const width = 620
const height = 190
const padding = { top: 18, right: 16, bottom: 28, left: 52 }

export function MiniLineChartBlock({ block, citations, onCitation }: RichBlockProps<MiniLineChartData>) {
  const [hovered, setHovered] = useState<number | null>(null)
  const chart = useMemo(() => {
    const values = block.data.series.flatMap(series => series.points.map(point => toNumber(point.value))).filter((value): value is number => value != null)
    if (!values.length) return null
    let min = Math.min(...values)
    let max = Math.max(...values)
    if (min === max) {
      const paddingValue = Math.abs(min || 1) * 0.05
      min -= paddingValue
      max += paddingValue
    }
    const longest = Math.max(...block.data.series.map(series => series.points.length), 1)
    const x = (index: number, length: number) => padding.left + (length <= 1 ? 0 : index / (length - 1)) * (width - padding.left - padding.right)
    const y = (value: number) => padding.top + (1 - (value - min) / (max - min)) * (height - padding.top - padding.bottom)
    const paths = block.data.series.map(series => {
      const points = series.points
        .map((point, index) => {
          const value = toNumber(point.value)
          return value == null ? null : { x: x(index, series.points.length), y: y(value), value, label: point.x }
        })
        .filter((point): point is NonNullable<typeof point> => point != null)
      return { series, points, d: points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ') }
    })
    return { min, max, longest, paths }
  }, [block.data.series])

  if (!chart) return <BlockFrame block={block} citations={citations} onCitation={onCitation}><p className="ai-rich-empty">图表数据不足。</p></BlockFrame>
  const reference = block.data.series.reduce((current, series) => series.points.length > current.points.length ? series : current, block.data.series[0])
  const hoverIndex = hovered == null ? null : Math.min(hovered, reference.points.length - 1)
  const hoverX = hoverIndex == null ? null : padding.left + (reference.points.length <= 1 ? 0 : hoverIndex / (reference.points.length - 1)) * (width - padding.left - padding.right)

  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <div className="ai-rich-chart">
      {block.data.show_legend && <div className="ai-rich-chart-legend">{block.data.series.map((series, index) => <span key={series.key}><i style={{ background: colors[index % colors.length] }}/>{series.label}</span>)}</div>}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${block.data.title}，${block.data.series.length} 条序列`}
        onPointerMove={event => {
          if (!block.data.show_tooltip) return
          const rect = event.currentTarget.getBoundingClientRect()
          const relative = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1)
          setHovered(Math.round(relative * Math.max(reference.points.length - 1, 0)))
        }}
        onPointerLeave={() => setHovered(null)}
      >
        {[0, 0.5, 1].map(ratio => {
          const y = padding.top + ratio * (height - padding.top - padding.bottom)
          const value = chart.max - ratio * (chart.max - chart.min)
          return <g key={ratio}><line x1={padding.left} x2={width - padding.right} y1={y} y2={y}/><text x={padding.left - 8} y={y + 4}>{formatNumber(value)}</text></g>
        })}
        {chart.paths.map((item, index) => <path key={item.series.key} d={item.d} style={{ stroke: colors[index % colors.length] }}/>)}
        {hoverX != null && <line className="hover-line" x1={hoverX} x2={hoverX} y1={padding.top} y2={height - padding.bottom}/>}
        <rect className="chart-hit-area" x={padding.left} y={padding.top} width={width - padding.left - padding.right} height={height - padding.top - padding.bottom}/>
      </svg>
      {hoverIndex != null && <div className="ai-rich-chart-tooltip" role="status">
        <b>{reference.points[hoverIndex]?.x}</b>
        {block.data.series.map(series => {
          const pointIndex = reference.points.length <= 1 ? 0 : Math.round(hoverIndex * Math.max(series.points.length - 1, 0) / Math.max(reference.points.length - 1, 1))
          return <span key={series.key}>{series.label}<strong>{formatNumber(series.points[pointIndex]?.value)}</strong></span>
        })}
      </div>}
    </div>
  </BlockFrame>
}
