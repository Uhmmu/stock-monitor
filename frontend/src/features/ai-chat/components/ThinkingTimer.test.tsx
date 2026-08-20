import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ThinkingTimer } from './ThinkingTimer'

describe('thinking timer', () => {
  it('renders the label with a zero-second elapsed state', () => {
    const html = renderToStaticMarkup(<ThinkingTimer startedAt={new Date().toISOString()} label="正在生成"/>)
    expect(html).toContain('正在生成 · 0s')
  })

  it('shows the already-elapsed waiting time from the start timestamp', () => {
    const startedAt = new Date(Date.now() - 65000).toISOString()
    const html = renderToStaticMarkup(<ThinkingTimer startedAt={startedAt} label="正在生成"/>)
    expect(html).toContain('正在生成 · 1m05s')
  })

  it('falls back to zero when the start timestamp is missing', () => {
    const html = renderToStaticMarkup(<ThinkingTimer startedAt={null} label="准备中…"/>)
    expect(html).toContain('准备中… · 0s')
  })
})
