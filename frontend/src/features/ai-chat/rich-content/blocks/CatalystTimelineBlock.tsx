import { BlockFrame } from '../components/BlockFrame'
import { formatDate } from '../format'
import type { CatalystTimelineData, RichBlockProps } from '../types'

const statusText = {
  upcoming: '即将发生',
  ongoing: '进行中',
  completed: '已完成',
  cancelled: '已取消',
  unknown: '状态未知',
}

export function CatalystTimelineBlock({ block, citations, onCitation }: RichBlockProps<CatalystTimelineData>) {
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <ol className="ai-rich-timeline">
      {block.data.events.map(event => <li key={event.event_id} className={`importance-${event.importance}`}>
        <time dateTime={event.starts_at}>{formatDate(event.starts_at, true)}</time>
        <div>
          <header><b>{event.title}</b><span>{statusText[event.status]}</span></header>
          <small>{event.symbol ? `${event.symbol} · ` : ''}{event.event_type}</small>
          {event.summary && <p>{event.summary}</p>}
          {event.citation_keys.length > 0 && <footer>{event.citation_keys.map(key => <button key={key} onClick={() => onCitation(key)}>{key}</button>)}</footer>}
        </div>
      </li>)}
    </ol>
  </BlockFrame>
}
