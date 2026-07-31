import { BlockFrame } from '../components/BlockFrame'
import { formatCurrency, formatPercent, toNumber } from '../format'
import type { PortfolioAllocationData, RichBlockProps } from '../types'

export function PortfolioAllocationBlock({ block, citations, onCitation }: RichBlockProps<PortfolioAllocationData>) {
  const max = Math.max(...block.data.items.map(item => toNumber(item.weight_percent) || 0), 1)
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <div className="ai-rich-allocation">
      <div className="ai-rich-allocation-summary">
        <div><span>组合总值</span><strong>{formatCurrency(block.data.total_value, block.data.currency)}</strong></div>
        <div><span>最大持仓</span><strong>{formatPercent(block.data.largest_weight_percent)}</strong></div>
      </div>
      <ol>{block.data.items.map(item => {
        const weight = Math.max(toNumber(item.weight_percent) || 0, 0)
        return <li key={item.key}>
          <div><b>{item.label}</b>{item.category && <small>{item.category}</small>}<strong>{formatPercent(item.weight_percent)}</strong></div>
          <span><i style={{ width: `${Math.min((weight / max) * 100, 100)}%` }}/></span>
          {item.value != null && <small>{formatCurrency(item.value, item.currency || block.data.currency)}</small>}
        </li>
      })}</ol>
    </div>
  </BlockFrame>
}
