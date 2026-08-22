import type { PropsWithChildren } from 'react'
import type { Citation } from '../../api'
import type { RichBlock } from '../types'
import { appHref } from '../../../../appRoute'

const freshnessText = {
  fresh: '较新',
  aging: '待更新',
  stale: '已过期',
  unknown: '时间未知',
}

function navigate(target: string) {
  if (!target.startsWith('/') || target.startsWith('//')) return
  window.history.pushState({}, '', appHref(target))
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function BlockFrame({ block, citations, onCitation, children, tone }: PropsWithChildren<{
  block: RichBlock<unknown>
  citations: Citation[]
  onCitation: (key: string) => void
  tone?: string
}>) {
  const known = new Set(citations.map(citation => citation.key))
  const keys = block.citation_keys.filter(key => known.has(key))
  const target = block.interaction?.navigation_target
  return <section className={`ai-rich-block ${tone ? `tone-${tone}` : ''}`} aria-label={block.title || block.block_type}>
    {(block.title || block.subtitle || block.freshness) && <header className="ai-rich-block-header">
      <div>
        {block.title && <h3>{block.title}</h3>}
        {block.subtitle && <p>{block.subtitle}</p>}
      </div>
      {block.freshness && <span className={`ai-rich-freshness ${block.freshness.status}`} title={block.freshness.label || undefined}>
        {block.freshness.label || freshnessText[block.freshness.status]}
      </span>}
    </header>}
    <div className="ai-rich-block-body">{children}</div>
    {(keys.length > 0 || block.warnings.length > 0 || target) && <footer className="ai-rich-block-footer">
      <div className="ai-rich-block-citations" aria-label="此组件的信息来源">
        {keys.map(key => <button key={key} onClick={() => onCitation(key)}>{key}</button>)}
      </div>
      {block.warnings.length > 0 && <details><summary>数据提示</summary><ul>{block.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul></details>}
      {target && target.startsWith('/') && !target.startsWith('//') && <button className="ai-rich-navigation" onClick={() => navigate(target)}>打开详情 <span aria-hidden="true">↗</span></button>}
    </footer>}
  </section>
}
