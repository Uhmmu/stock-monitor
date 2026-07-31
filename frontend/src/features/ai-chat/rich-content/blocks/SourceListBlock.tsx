import { formatDate } from '../format'
import type { RichBlockProps, SourceListData } from '../types'
import { safePublicUrl } from '../validation'

const originText = {
  internal: '站内数据',
  web: '公开网络',
  deep_search: '深度研究',
  unknown: '来源',
}

export function SourceListBlock({ block, onCitation }: RichBlockProps<SourceListData>) {
  return <details className="ai-rich-sources" open={!block.data.collapsed}>
    <summary>
      <span>信息来源</span>
      <small>{block.data.sources.length} 项</small>
    </summary>
    <ol>{block.data.sources.map(source => {
      const url = safePublicUrl(source.url)
      return <li key={`${source.citation_key}-${source.source_id}`}>
        <button onClick={() => onCitation(source.citation_key)}>{source.citation_key}</button>
        <div>
          {url ? <a href={url} target="_blank" rel="noreferrer noopener">{source.title}</a> : <span>{source.title}</span>}
          <small>
            {originText[source.origin]}
            {source.provider ? ` · ${source.provider}` : ''}
            {source.published_at ? ` · ${formatDate(source.published_at)}` : ''}
          </small>
        </div>
      </li>
    })}</ol>
  </details>
}
