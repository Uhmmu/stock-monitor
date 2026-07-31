import { BlockFrame } from '../components/BlockFrame'
import { formatCurrency, formatDate, toNumber } from '../format'
import type { RichBlockProps, ValuationRangeData } from '../types'

export function ValuationRangeBlock({ block, citations, onCitation }: RichBlockProps<ValuationRangeData>) {
  const entries = [
    ['悲观', block.data.bear_value ?? block.data.lower_bound, 'bear'],
    ['基准', block.data.base_value, 'base'],
    ['乐观', block.data.bull_value ?? block.data.upper_bound, 'bull'],
  ] as const
  const numeric = [...entries.map(([, value]) => toNumber(value)), toNumber(block.data.current_price)].filter((value): value is number => value != null)
  const min = Math.min(...numeric)
  const max = Math.max(...numeric)
  const span = max > min ? max - min : Math.abs(max || 1)
  const position = (value: typeof block.data.current_price) => {
    const number = toNumber(value)
    return number == null ? 0 : Math.min(Math.max(((number - min) / span) * 100, 0), 100)
  }
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <div className="ai-rich-valuation">
      <div className="ai-rich-valuation-current">
        <span>当前价格</span>
        <strong>{formatCurrency(block.data.current_price, block.data.currency)}</strong>
        {block.data.current_position_label && <small>{block.data.current_position_label}</small>}
      </div>
      <div className="ai-rich-range-track" aria-label="估值区间">
        <i/>
        {entries.map(([label, value, tone]) => toNumber(value) != null && <span key={label} className={tone} style={{ left: `${position(value)}%` }} title={`${label} ${formatCurrency(value, block.data.currency)}`}/>)}
        {toNumber(block.data.current_price) != null && <b style={{ left: `${position(block.data.current_price)}%` }} title="当前价格"/>}
      </div>
      <div className="ai-rich-valuation-scenarios">
        {entries.map(([label, value, tone]) => <div key={label} className={tone}><span>{label}</span><strong>{formatCurrency(value, block.data.currency)}</strong></div>)}
      </div>
      <p>{block.data.model_name || '内部估值情景'}{block.data.valuation_date ? ` · ${formatDate(block.data.valuation_date)}` : ''}</p>
      <small>估值情景用于研究比较，不构成收益保证。</small>
    </div>
  </BlockFrame>
}
