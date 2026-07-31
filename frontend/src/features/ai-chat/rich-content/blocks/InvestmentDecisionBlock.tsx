import { BlockFrame } from '../components/BlockFrame'
import { formatDate } from '../format'
import type { InvestmentDecisionData, RichBlockProps } from '../types'

export function InvestmentDecisionBlock({ block, citations, onCitation }: RichBlockProps<InvestmentDecisionData>) {
  return <BlockFrame block={block} citations={citations} onCitation={onCitation} tone={block.data.review_due ? 'risk' : 'decision'}>
    <article className="ai-rich-decision">
      <div className="ai-rich-decision-meta">
        <span>{block.data.decision_type}</span>
        <span>{block.data.status}</span>
        {block.data.review_due && <em>待复盘</em>}
      </div>
      <h4>{block.data.title}</h4>
      {block.data.symbols.length > 0 && <div className="ai-rich-symbols">{block.data.symbols.map(symbol => <span key={symbol}>{symbol}</span>)}</div>}
      {block.data.action && <section><b>行动计划</b><p>{block.data.action}</p></section>}
      {block.data.thesis_summary && <section><b>投资逻辑</b><p>{block.data.thesis_summary}</p></section>}
      <div className="ai-rich-decision-columns">
        {block.data.invalidation_conditions.length > 0 && <section><b>失效条件</b><ul>{block.data.invalidation_conditions.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></section>}
        {block.data.risks.length > 0 && <section><b>主要风险</b><ul>{block.data.risks.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></section>}
      </div>
      <footer>
        <span>决策 {formatDate(block.data.decision_date)}</span>
        {block.data.target_review_at && <span>复盘 {formatDate(block.data.target_review_at, true)}</span>}
      </footer>
    </article>
  </BlockFrame>
}
