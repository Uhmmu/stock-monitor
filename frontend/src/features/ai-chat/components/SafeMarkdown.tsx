import { Children, isValidElement, ReactElement, ReactNode, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import type { Citation } from '../api'

function textOf(value: ReactNode): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(textOf).join('')
  if (isValidElement<{ children?: ReactNode }>(value)) return textOf(value.props.children)
  return ''
}

function hostChildren(value: ReactNode): ReactElement<{ children?: ReactNode }>[] {
  return Children.toArray(value).filter(
    (child): child is ReactElement<{ children?: ReactNode }> => isValidElement(child)
  )
}

function tagName(element: ReactElement): string {
  return typeof element.type === 'string' ? element.type : ''
}

type ParsedMarkdownTable = {
  headers: string[]
  rows: ReactNode[][]
}

/** Extract header labels and row cell nodes from react-markdown's table tree. */
function parseMarkdownTable(children: ReactNode): ParsedMarkdownTable | null {
  let headers: string[] | null = null
  const rows: ReactNode[][] = []
  for (const section of hostChildren(children)) {
    const sectionTag = tagName(section)
    if (sectionTag !== 'thead' && sectionTag !== 'tbody' && sectionTag !== 'tfoot') continue
    for (const row of hostChildren(section.props.children)) {
      if (tagName(row) !== 'tr') continue
      const cells = hostChildren(row.props.children).map(cell => cell.props.children)
      if (sectionTag === 'thead') headers = cells.map(textOf)
      else rows.push(cells)
    }
  }
  if (!headers || headers.length < 2 || rows.length === 0) return null
  return { headers, rows }
}

/** Chat tables render as entry cards (valuation-card style), not raw grids. */
function MarkdownTable({ children }: { children: ReactNode }) {
  const parsed = parseMarkdownTable(children)
  if (!parsed) return <div className="ai-table-scroll"><table>{children}</table></div>
  if (parsed.headers.length === 2) {
    return <div className="ai-md-table kv" role="list">
      {parsed.rows.map((row, index) => <div className="ai-md-table-row" role="listitem" key={index}>
        <span className="ai-md-table-key">{row[0] ?? ''}</span>
        <span className="ai-md-table-value">{row[1] ?? ''}</span>
      </div>)}
    </div>
  }
  return <div className="ai-md-table" role="list">
    {parsed.rows.map((row, index) => <div className="ai-md-table-row" role="listitem" key={index}>
      <div className="ai-md-table-row-head">{row[0] ?? ''}</div>
      <div className="ai-md-table-row-body">
        {parsed.headers.slice(1).map((header, columnIndex) => <div className="ai-md-table-cell" key={columnIndex}>
          {header && <small>{header}</small>}
          <span>{row[columnIndex + 1] ?? ''}</span>
        </div>)}
      </div>
    </div>)}
  </div>
}

const tableDivider = /\|\s*(?::?-{3,}:?\s*\|){2,}/
const strongPunctuationBoundary = /\*\*([^*\n]*\p{P})\*\*(?=[\p{L}\p{N}])/gu

/** Restore row breaks when a model collapses a valid GFM table onto one line. */
export function normalizeMarkdownTables(value: string): string {
  let fenced = false
  return value.split('\n').map(line => {
    if (/^\s*```/.test(line)) { fenced = !fenced; return line }
    if (fenced || !tableDivider.test(line)) return line
    return line.replace(/\|\s+\|/g, '|\n|')
  }).join('\n')
}

/**
 * CommonMark treats a closing ** after punctuation as ambiguous when the next
 * character is a letter or number (for example `**需要跟踪：**资本`). An HTML
 * zero-width-space entity makes the delimiter unambiguous without adding a
 * visible gap to Chinese text. Code spans and fenced code remain untouched.
 */
export function normalizeMarkdownEmphasis(value: string): string {
  let fenced = false
  return value.split('\n').map(line => {
    if (/^\s*```/.test(line)) { fenced = !fenced; return line }
    if (fenced) return line
    return line.split(/(`+[^`]*`+)/g).map((part, index) => index % 2 ? part : part.replace(strongPunctuationBoundary, '**$1**&#8203;')).join('')
  }).join('\n')
}

export function citationMarkdown(value: string): string {
  let fenced = false
  return normalizeMarkdownEmphasis(normalizeMarkdownTables(value)).split('\n').map(line => {
    if (/^\s*```/.test(line)) { fenced = !fenced; return line }
    if (fenced) return line
    return line.split(/(`+[^`]*`+)/g).map((part, index) => index % 2 ? part : part.replace(/\[S(\d+)\]/g, '[S$1](#citation-S$1)')).join('')
  }).join('\n')
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(textOf(children).replace(/\n$/, ''))
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }
  return <div className="ai-code-block"><button onClick={copy} aria-label="复制代码">{copied ? '已复制' : '复制'}</button><pre>{children}</pre></div>
}

export function SafeMarkdown({ content, citations, onCitation }: {
  content: string
  citations: Citation[]
  onCitation: (key: string) => void
}) {
  const map = new Map(citations.map(item => [item.key, item]))
  return <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    rehypePlugins={[rehypeSanitize]}
    components={{
      a: ({ href, children }) => {
        if (href?.startsWith('#citation-')) {
          const key = href.slice('#citation-'.length)
          return <button className={`ai-citation-badge${map.has(key) ? '' : ' missing'}`} onClick={() => onCitation(key)} aria-label={`查看引用 ${key}`}>[{key}]</button>
        }
        if (!href?.startsWith('http://') && !href?.startsWith('https://')) return <span>{children}</span>
        return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
      },
      pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
      table: ({ children }) => <MarkdownTable>{children}</MarkdownTable>,
    }}
  >{citationMarkdown(content)}</ReactMarkdown>
}
