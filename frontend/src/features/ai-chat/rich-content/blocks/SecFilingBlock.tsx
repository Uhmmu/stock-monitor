import { BlockFrame } from '../components/BlockFrame'
import { formatDate } from '../format'
import type { RichBlockProps, SecFilingData } from '../types'
import { safePublicUrl } from '../validation'

export function SecFilingBlock({ block, citations, onCitation }: RichBlockProps<SecFilingData>) {
  const officialUrl = safePublicUrl(block.data.official_url)
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <article className="ai-rich-sec">
      <div className="ai-rich-sec-meta">
        <strong>{block.data.form_type}</strong>
        <span>{block.data.symbol}</span>
        <time>提交 {formatDate(block.data.filed_at)}</time>
        {block.data.report_period && <time>报告期 {formatDate(block.data.report_period)}</time>}
      </div>
      {block.data.title && <h4>{block.data.title}</h4>}
      {block.data.summary && <p>{block.data.summary}</p>}
      {block.data.key_changes.length > 0 && <section><b>关键变化</b><ul>{block.data.key_changes.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></section>}
      {block.data.risk_changes.length > 0 && <section className="risks"><b>风险变化</b><ul>{block.data.risk_changes.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></section>}
      {officialUrl && <a href={officialUrl} target="_blank" rel="noreferrer noopener">打开 SEC 官方文件 ↗</a>}
    </article>
  </BlockFrame>
}
