import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'

import { normalizeProviderHealth, normalizeRealtimeQuote, normalizeRealtimeQuotes, parseSSEEvent } from './realtime'
import { RealtimeQuoteCard } from './RealtimeMarketCard'

describe('realtime market contract normalization', () => {
  it('normalizes a typed quote and derives change without filling missing fields', () => {
    const quote = normalizeRealtimeQuote({
      symbol: 'nvda',
      price: 182.36,
      previous_close: 179.24,
      provider: 'alpaca',
      feed: 'iex',
      is_delayed: false,
      timestamp: '2026-08-07T14:32:00Z',
    })
    expect(quote?.symbol).toBe('NVDA')
    expect(quote?.change).toBeCloseTo(3.12, 2)
    expect(quote?.change_percent).toBeCloseTo(1.7407, 3)
    expect(quote?.bid).toBeNull()
    expect(quote?.provider).toBe('alpaca')
  })

  it('accepts provider aliases and reference prices', () => {
    const quote = normalizeRealtimeQuote({
      ticker: 'MSFT',
      last_trade_price: 418.22,
      prevClose: 415.30,
      day_high: 421.04,
      reference: { price: 418.36, provider: 'tiingo', feed: 'consolidated' },
    })
    expect(quote?.price).toBe(418.22)
    expect(quote?.previous_close).toBe(415.3)
    expect(quote?.high).toBe(421.04)
    expect(quote?.reference_price).toBe(418.36)
    expect(quote?.reference_provider).toBe('tiingo')
  })

  it('reads array and symbol-map response envelopes', () => {
    expect(normalizeRealtimeQuotes({ quotes: [{ symbol: 'AAPL', price: 1 }] }, ['AAPL'])).toHaveLength(1)
    expect(normalizeRealtimeQuotes({ AAPL: { price: 2 } }, ['AAPL'])[0]?.symbol).toBe('AAPL')
    const envelope = normalizeRealtimeQuotes({ quotes: { MSFT: { authoritative_quote: { symbol: 'MSFT', price: 418 }, stale: false } } }, ['MSFT'])
    expect(envelope[0]).toMatchObject({ symbol: 'MSFT', price: 418, is_stale: false })
    expect(normalizeRealtimeQuotes({ data: { quotes: [{ symbol: 'AAPL', price: 3 }] } }, ['AAPL'])[0]?.price).toBe(3)
  })
})

describe('realtime SSE parser and provider health', () => {
  it('parses JSON and keeps non-JSON heartbeat payloads safe', () => {
    expect(parseSSEEvent('quote_update', '{"symbol":"MSFT"}')).toEqual({ event: 'quote_update', data: { symbol: 'MSFT' } })
    expect(parseSSEEvent('', 'ping')?.data).toBe('ping')
    expect(parseSSEEvent('', '')).toBeNull()
  })

  it('normalizes provider status without exposing credentials', () => {
    const rows = normalizeProviderHealth({ providers: [{ provider: 'alpaca', connected: true, feed: 'iex', subscriptions: ['MSFT'] }] })
    expect(rows[0]).toMatchObject({ provider: 'alpaca', connected: true, feed: 'iex', subscriptions: ['MSFT'] })
    expect(JSON.stringify(rows)).not.toContain('secret')
    const sections = normalizeProviderHealth({ market_data: { tiingo: { connected: false, last_error: '403' } }, news: { tiingo: { last_success: '2026-08-07T00:00:00Z' } } })
    expect(sections.map(row => row.provider)).toEqual(['tiingo', 'tiingo'])
  })

  it('does not label delayed data as realtime', () => {
    const quote = normalizeRealtimeQuote({ symbol: 'MSFT', price: 418, is_delayed: true, provider: 'alpaca', feed: 'delayed_sip' })!
    const html = renderToStaticMarkup(createElement(RealtimeQuoteCard, { symbol: 'MSFT', quote, streamStatus: 'connected' }))
    expect(html).toContain('延迟数据')
    expect(html).not.toContain('>实时<')
    expect(html).toContain('数据不足')
  })
})
