import { BlockFrame } from '../components/BlockFrame'
import { formatDate } from '../format'
import type { NewsClusterData, RichBlockProps } from '../types'
import { safePublicUrl } from '../validation'

export function NewsClusterBlock({ block, citations, onCitation }: RichBlockProps<NewsClusterData>) {
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <article className="ai-rich-news">
      <div className="ai-rich-news-heading">
        <div>
          {block.data.symbol && <span>{block.data.symbol}</span>}
          {block.data.official_source_present && <em>含官方来源</em>}
        </div>
        {block.data.event_date && <time>{formatDate(block.data.event_date, true)}</time>}
      </div>
      <h4>{block.data.headline}</h4>
      <p>{block.data.summary}</p>
      {block.data.disagreement_summary && <aside><b>来源分歧</b><p>{block.data.disagreement_summary}</p></aside>}
      <details>
        <summary>{block.data.source_count} 个相关来源</summary>
        <ul>{block.data.sources.map(source => {
          const url = safePublicUrl(source.url)
          return <li key={source.source_id}>
            {url ? <a href={url} target="_blank" rel="noreferrer noopener">{source.title}</a> : <span>{source.title}</span>}
            <small>{source.provider || source.authority || '来源'}{source.published_at ? ` · ${formatDate(source.published_at)}` : ''}</small>
          </li>
        })}</ul>
      </details>
    </article>
  </BlockFrame>
}
