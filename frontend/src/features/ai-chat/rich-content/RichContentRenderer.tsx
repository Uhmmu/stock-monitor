import type { Citation } from '../api'
import { SafeMarkdown } from '../components/SafeMarkdown'
import { RichBlockErrorBoundary } from './components/RichBlockErrorBoundary'
import { getRichBlockRegistration } from './registry'
import { validateRichContentDocument } from './validation'

function Fallback({ content, citations, onCitation, notice }: {
  content: string
  citations: Citation[]
  onCitation: (key: string) => void
  notice?: string
}) {
  return <div className="ai-rich-block-fallback">
    {notice && <p>{notice}</p>}
    <SafeMarkdown content={content} citations={citations} onCitation={onCitation}/>
  </div>
}

export function RichContentRenderer({ document, fallbackMarkdown, citations, onCitation }: {
  document: unknown
  fallbackMarkdown: string
  citations: Citation[]
  onCitation: (key: string) => void
}) {
  const validated = validateRichContentDocument(document)
  if (!validated) {
    return <Fallback content={fallbackMarkdown} citations={citations} onCitation={onCitation}/>
  }
  return <div className="ai-rich-document" data-schema-version={validated.schema_version}>
    {validated.warnings.length > 0 && <details className="ai-rich-document-warnings">
      <summary>本回答有数据提示</summary>
      <ul>{validated.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>
    </details>}
    {validated.parts.map(part => {
      if (part.type === 'markdown') {
        return <div className="ai-rich-markdown" key={part.part_id}>
          <SafeMarkdown content={part.content} citations={citations} onCitation={onCitation}/>
        </div>
      }
      const registration = getRichBlockRegistration(part.block.block_type, part.block.block_version)
      if (!registration) {
        return <Fallback
          key={part.part_id}
          content={part.block.fallback_markdown}
          citations={citations}
          onCitation={onCitation}
          notice="当前客户端暂不支持这个组件版本，已显示文本内容。"
        />
      }
      if (!registration.validate(part.block.data)) {
        return <Fallback
          key={part.part_id}
          content={part.block.fallback_markdown}
          citations={citations}
          onCitation={onCitation}
          notice="该组件数据未通过本地校验，已安全降级为文本。"
        />
      }
      const Component = registration.component
      return <RichBlockErrorBoundary key={part.part_id} block={part.block} citations={citations} onCitation={onCitation}>
        <Component block={part.block} citations={citations} onCitation={onCitation}/>
      </RichBlockErrorBoundary>
    })}
  </div>
}
