import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { citationMarkdown, normalizeMarkdownEmphasis, normalizeMarkdownTables, SafeMarkdown } from './SafeMarkdown'

describe('safe assistant markdown', () => {
  it('links citations outside code but preserves fenced and inline code', () => {
    const source = '事实 [S1]\n\n`const x = "[S2]"`\n\n```ts\n[S3]\n```'
    const transformed = citationMarkdown(source)
    expect(transformed).toContain('[S1](#citation-S1)')
    expect(transformed).toContain('`const x = "[S2]"`')
    expect(transformed).toContain('```ts\n[S3]\n```')
  })

  it('does not render javascript URLs or raw script HTML', () => {
    const html = renderToStaticMarkup(<SafeMarkdown content={'[危险](javascript:alert(1))\n<script>alert(2)</script>'} citations={[]} onCitation={() => undefined}/>)
    expect(html).not.toContain('javascript:')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('alert(2)')
  })

  it('renders an accessible citation action', () => {
    const html = renderToStaticMarkup(<SafeMarkdown content={'证据 [S1]'} citations={[{ key: 'S1', source_id: 'n:1', title: 'News', source_type: 'news', symbol: null, provider: null, authority: null, published_at: null, retrieved_at: null, locator: null, url: null }]} onCitation={() => undefined}/>)
    expect(html).toContain('aria-label="查看引用 S1"')
    expect(html).toContain('[S1]')
  })

  it('renders GFM tables as card entries instead of raw table markup', () => {
    const content = '| 指标 | NVDA | AVGO |\n| --- | ---: | ---: |\n| ROIC | 145.75% | 20.36% |'
    const html = renderToStaticMarkup(<SafeMarkdown content={content} citations={[]} onCitation={() => undefined}/>)
    expect(html).not.toContain('<table>')
    expect(html).toContain('ai-md-table-row')
    expect(html).toContain('ai-md-table-row-head')
    expect(html).toContain('<small>NVDA</small>')
    expect(html).toContain('<small>AVGO</small>')
    expect(html).toContain('>145.75%</span>')
    expect(html).toContain('>20.36%</span>')
  })

  it('renders two-column tables as label/value card rows', () => {
    const content = '| 指标 | 数值 |\n| --- | --- |\n| P/E | 28.4 |\n| P/B | 11.2 |'
    const html = renderToStaticMarkup(<SafeMarkdown content={content} citations={[]} onCitation={() => undefined}/>)
    expect(html).toContain('ai-md-table kv')
    expect(html).toContain('ai-md-table-key')
    expect(html).toContain('<span class="ai-md-table-key">P/E</span>')
    expect(html).toContain('<span class="ai-md-table-value">28.4</span>')
    expect(html).not.toContain('<table>')
  })

  it('repairs compact single-line model tables before rendering', () => {
    const content = '| 指标 | NVDA | AVGO | 解读 | |---|---:|---:|---| | 参考股价 | $190.24 | $370.68 | 截至 2026-07-29 | | ROIC | 145.75% | 20.36% | NVDA 更高 |'
    const normalized = normalizeMarkdownTables(content)
    expect(normalized.split('\n')).toHaveLength(4)
    const html = renderToStaticMarkup(<SafeMarkdown content={content} citations={[]} onCitation={() => undefined}/>)
    expect(html).not.toContain('<table>')
    expect(html).toContain('<small>解读</small>')
    expect(html).toContain('NVDA 更高')
  })

  it('does not rewrite compact table-like text inside fenced code', () => {
    const content = '```md\n| A | B | |---|---| | 1 | 2 |\n```'
    expect(normalizeMarkdownTables(content)).toBe(content)
  })

  it('renders punctuation-ended bold labels followed immediately by Chinese text', () => {
    const content = '**需要跟踪（两边有✳）：**资本开支增速、Azure 毛利率、数据中心产能利用率。'
    const html = renderToStaticMarkup(<SafeMarkdown content={content} citations={[]} onCitation={() => undefined}/>)
    expect(html).toContain('<strong>需要跟踪（两边有✳）：</strong>')
    expect(html).not.toContain('**需要跟踪')
  })

  it('does not normalize bold-like text inside inline or fenced code', () => {
    const content = '`**标签：**正文`\n\n```md\n**标签：**正文\n```'
    expect(normalizeMarkdownEmphasis(content)).toBe(content)
  })
})
