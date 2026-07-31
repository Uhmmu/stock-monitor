import { BlockFrame } from '../components/BlockFrame'
import type { MetricGridData, RichBlockProps } from '../types'

export function MetricGridBlock({ block, citations, onCitation }: RichBlockProps<MetricGridData>) {
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <dl className={`ai-rich-metric-grid columns-${Math.min(Math.max(block.data.columns, 1), 4)}`}>
      {block.data.metrics.map(metric => <div key={metric.key} className={`trend-${metric.trend}`}>
        <dt>{metric.label}</dt>
        <dd>{metric.display_value || '数据不足'}</dd>
        {metric.secondary_text && <small>{metric.secondary_text}</small>}
      </div>)}
    </dl>
  </BlockFrame>
}
