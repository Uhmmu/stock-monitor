import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, getToken } from './api'

/**
 * The browser only sees the server's normalized market contract.  Provider
 * fields are intentionally optional because delayed/fallback providers do not
 * expose the same quote depth as the primary feed.
 */
export type RealtimeMarketSession = 'pre_market' | 'regular' | 'after_hours' | 'closed' | 'unknown' | string

export type RealtimeQuote = {
  symbol: string
  currency: string | null
  price: number | null
  bid: number | null
  ask: number | null
  bid_size: number | null
  ask_size: number | null
  last_trade_price: number | null
  last_trade_size: number | null
  open: number | null
  high: number | null
  low: number | null
  previous_close: number | null
  volume: number | null
  vwap: number | null
  change: number | null
  change_percent: number | null
  timestamp: string | null
  received_at: string | null
  provider: string | null
  feed: string | null
  delayed_seconds: number | null
  market_session: RealtimeMarketSession
  is_delayed: boolean | null
  is_stale: boolean | null
  age_seconds: number | null
  reference_price: number | null
  reference_provider: string | null
  reference_feed: string | null
  alternate_quotes: RealtimeQuote[]
}

export type RealtimeProviderHealth = {
  provider: string
  channel?: 'market' | 'news' | string
  label?: string | null
  connected: boolean | null
  status: string | null
  feed: string | null
  last_message_at: string | null
  last_success_at: string | null
  last_error: string | null
  subscriptions: string[]
  message_rate: number | null
  reconnect_count: number | null
  delayed: boolean | null
  articles_fetched?: number | null
  rate_limit_state?: string | null
}

export type RealtimeStreamStatus = 'idle' | 'loading' | 'connecting' | 'connected' | 'fallback' | 'error'

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null

const first = (record: Record<string, unknown>, keys: string[]): unknown => {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return record[key]
  }
  return null
}

const numberValue = (value: unknown): number | null => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

const stringValue = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value : null

const booleanValue = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null

const normalizeSymbol = (value: unknown): string => typeof value === 'string' ? value.trim().toUpperCase() : ''

const sessionValue = (value: unknown): RealtimeMarketSession => {
  if (typeof value !== 'string' || !value.trim()) return 'unknown'
  const normalized = value.trim().toLowerCase().replace(/[- ]/g, '_')
  if (normalized === 'premarket') return 'pre_market'
  if (normalized === 'afterhours' || normalized === 'postmarket') return 'after_hours'
  return normalized
}

const emptyQuote = (symbol: string): RealtimeQuote => ({
  symbol,
  currency: null,
  price: null,
  bid: null,
  ask: null,
  bid_size: null,
  ask_size: null,
  last_trade_price: null,
  last_trade_size: null,
  open: null,
  high: null,
  low: null,
  previous_close: null,
  volume: null,
  vwap: null,
  change: null,
  change_percent: null,
  timestamp: null,
  received_at: null,
  provider: null,
  feed: null,
  delayed_seconds: null,
  market_session: 'unknown',
  is_delayed: null,
  is_stale: null,
  age_seconds: null,
  reference_price: null,
  reference_provider: null,
  reference_feed: null,
  alternate_quotes: [],
})

/** Normalize both the typed backend quote and tolerant provider-shaped fixtures. */
export function normalizeRealtimeQuote(input: unknown, fallbackSymbol = ''): RealtimeQuote | null {
  const record = asRecord(input)
  if (!record) return null
  // The realtime API returns a provider-neutral envelope so provenance and
  // divergence can travel with the authoritative quote.  Unwrap it here so
  // views never need to know the envelope shape.
  const authoritative = asRecord(record.authoritative_quote)
  if (authoritative) {
    const primary = normalizeRealtimeQuote(authoritative, fallbackSymbol || normalizeSymbol(record.symbol))
    if (!primary) return null
    const alternateRaw = Array.isArray(record.alternate_quotes) ? record.alternate_quotes : []
    const alternates = alternateRaw.map(item => normalizeRealtimeQuote(item, primary.symbol)).filter((item): item is RealtimeQuote => item !== null)
    return {
      ...primary,
      is_stale: booleanValue(first(record, ['stale', 'is_stale'])) ?? primary.is_stale,
      age_seconds: numberValue(first(record, ['age_seconds', 'age'])) ?? primary.age_seconds,
      alternate_quotes: alternates,
    }
  }
  const symbol = normalizeSymbol(first(record, ['symbol', 'ticker', 'ticker_symbol'])) || normalizeSymbol(fallbackSymbol)
  if (!symbol) return null
  const previousClose = numberValue(first(record, ['previous_close', 'prev_close', 'previousClose', 'prevClose']))
  const price = numberValue(first(record, ['price', 'last_price', 'last', 'last_trade_price', 'tngoLast', 'lqRefPrice']))
  const change = numberValue(first(record, ['change', 'price_change'])) ?? (price != null && previousClose != null ? price - previousClose : null)
  const changePercent = numberValue(first(record, ['change_percent', 'change_pct', 'price_change_percent'])) ?? (change != null && previousClose ? change / previousClose * 100 : null)
  const alternateRaw = first(record, ['alternate_quotes', 'alternates', 'references'])
  const alternateQuotes = Array.isArray(alternateRaw)
    ? alternateRaw.map(item => normalizeRealtimeQuote(item, symbol)).filter((item): item is RealtimeQuote => item !== null)
    : []
  const reference = asRecord(first(record, ['reference_price', 'reference']))
  const referencePrice = numberValue(reference ? first(reference, ['price', 'last_price', 'tngoLast', 'lqRefPrice']) : null) ?? numberValue(first(record, ['reference_price_value']))
  const referenceProvider = stringValue(reference ? first(reference, ['provider', 'source']) : null) ?? stringValue(first(record, ['reference_provider']))
  const referenceFeed = stringValue(reference ? first(reference, ['feed', 'mode']) : null) ?? stringValue(first(record, ['reference_feed']))
  const quote = {
    ...emptyQuote(symbol),
    currency: stringValue(first(record, ['currency', 'currency_code'])),
    price,
    bid: numberValue(first(record, ['bid', 'bid_price', 'lqBidPrice'])),
    ask: numberValue(first(record, ['ask', 'ask_price', 'lqAskPrice'])),
    bid_size: numberValue(first(record, ['bid_size', 'bidSize', 'lqBidSize'])),
    ask_size: numberValue(first(record, ['ask_size', 'askSize', 'lqAskSize'])),
    last_trade_price: numberValue(first(record, ['last_trade_price', 'lastTradePrice'])) ?? price,
    last_trade_size: numberValue(first(record, ['last_trade_size', 'lastTradeSize'])),
    open: numberValue(first(record, ['open', 'open_price', 'day_open'])),
    high: numberValue(first(record, ['high', 'day_high'])),
    low: numberValue(first(record, ['low', 'day_low'])),
    previous_close: previousClose,
    volume: numberValue(first(record, ['volume', 'day_volume', 'total_volume'])),
    vwap: numberValue(first(record, ['vwap', 'day_vwap'])),
    change,
    change_percent: changePercent,
    timestamp: stringValue(first(record, ['timestamp', 'market_timestamp', 'market_time', 'time'])),
    received_at: stringValue(first(record, ['received_at', 'fetched_at', 'persisted_at'])),
    provider: stringValue(first(record, ['provider', 'source', 'source_provider'])),
    feed: stringValue(first(record, ['feed', 'market_data_feed', 'mode'])),
    delayed_seconds: numberValue(first(record, ['delayed_seconds', 'delay_seconds', 'latency_seconds'])),
    market_session: sessionValue(first(record, ['market_session', 'session'])),
    is_delayed: booleanValue(first(record, ['is_delayed', 'delayed'])),
    is_stale: booleanValue(first(record, ['is_stale', 'stale'])),
    age_seconds: numberValue(first(record, ['age_seconds', 'age'])),
    reference_price: referencePrice,
    reference_provider: referenceProvider,
    reference_feed: referenceFeed,
    alternate_quotes: alternateQuotes,
  }
  return quote
}

const isQuoteLike = (value: unknown): boolean => {
  const record = asRecord(value)
  return !!record && !!(first(record, ['symbol', 'ticker', 'ticker_symbol']))
}

/** Extract quotes from all supported response envelopes without exposing provider JSON to views. */
export function normalizeRealtimeQuotes(payload: unknown, requestedSymbols: string[] = []): RealtimeQuote[] {
  const requested = requestedSymbols.map(normalizeSymbol).filter(Boolean)
  const record = asRecord(payload)
  if (record?.authoritative_quote) {
    const quote = normalizeRealtimeQuote(record, requested[0] || '')
    return quote ? [quote] : []
  }
  // SSE handlers may wrap the same envelope one additional time as
  // ``{event, data:{quotes:[...]}}``.  Peel that transport wrapper before
  // interpreting quote maps so a key such as ``quotes`` is never mistaken for
  // a ticker symbol.
  const transportData = record ? asRecord(record.data) : null
  if (transportData && !isQuoteLike(transportData) && (Array.isArray(transportData.quotes) || Array.isArray(transportData.items) || Array.isArray(transportData.results))) {
    return normalizeRealtimeQuotes(transportData, requested)
  }
  let candidates: unknown[] = []
  if (Array.isArray(payload)) candidates = payload
  else if (record) {
    const nested = first(record, ['quotes', 'items', 'data', 'results'])
    if (Array.isArray(nested)) candidates = nested
    else if (isQuoteLike(nested)) candidates = [nested]
    else if (asRecord(nested)) {
      const nestedRecord = asRecord(nested) || {}
      candidates = Object.entries(nestedRecord).map(([key, value]) => {
        if (isQuoteLike(value) || asRecord(value)?.authoritative_quote) return value
        return { ...(asRecord(value) || {}), symbol: key }
      })
    }
    else {
      candidates = Object.entries(record)
        .filter(([key, value]) => requested.includes(normalizeSymbol(key)) || isQuoteLike(value))
        .map(([key, value]) => isQuoteLike(value) ? value : { ...(asRecord(value) || {}), symbol: key })
    }
  }
  const normalized = candidates.map(item => normalizeRealtimeQuote(item)).filter((item): item is RealtimeQuote => item !== null)
  const bySymbol = new Map<string, RealtimeQuote>()
  for (const quote of normalized) bySymbol.set(quote.symbol, quote)
  return requested.length ? requested.map(symbol => bySymbol.get(symbol)).filter((item): item is RealtimeQuote => item !== undefined) : [...bySymbol.values()]
}

export function quoteMap(quotes: RealtimeQuote[]): Record<string, RealtimeQuote> {
  return quotes.reduce<Record<string, RealtimeQuote>>((map, quote) => {
    map[quote.symbol] = quote
    return map
  }, {})
}

export function quoteTimestamp(quote: RealtimeQuote): number {
  const timestamp = quote.timestamp || quote.received_at
  if (!timestamp) return 0
  const parsed = Date.parse(timestamp)
  return Number.isFinite(parsed) ? parsed : 0
}

export function isQuoteNewer(next: RealtimeQuote, current: RealtimeQuote | undefined): boolean {
  if (!current) return true
  const nextTimestamp = quoteTimestamp(next)
  const currentTimestamp = quoteTimestamp(current)
  return nextTimestamp >= currentTimestamp
}

const parseProviderHealth = (provider: string, input: unknown, channel: 'market' | 'news' | string = 'market'): RealtimeProviderHealth => {
  const record = asRecord(input) || {}
  const statusValue = stringValue(first(record, ['status', 'state', 'health']))
  const lastSuccess = stringValue(first(record, ['last_success_at', 'last_successful_at', 'last_success']))
  const connected = booleanValue(first(record, ['connected', 'is_connected'])) ?? (lastSuccess ? true : null)
  return {
    provider,
    channel,
    label: stringValue(first(record, ['label', 'name', 'display_name'])),
    connected,
    status: statusValue,
    feed: stringValue(first(record, ['feed', 'mode'])),
    last_message_at: stringValue(first(record, ['last_message_at', 'last_update_at', 'last_received_at', 'last_fetch', 'updated_at'])),
    last_success_at: lastSuccess,
    last_error: stringValue(first(record, ['last_error', 'error', 'error_message'])),
    subscriptions: Array.isArray(record.subscriptions) ? record.subscriptions.filter((item): item is string => typeof item === 'string') : [],
    message_rate: numberValue(first(record, ['message_rate', 'messages_per_second'])),
    reconnect_count: numberValue(first(record, ['reconnect_count', 'reconnects'])),
    delayed: booleanValue(first(record, ['delayed', 'is_delayed'])),
    articles_fetched: numberValue(first(record, ['articles_fetched', 'article_count'])),
    rate_limit_state: stringValue(first(record, ['rate_limit_state', 'quota_state'])),
  }
}

export function normalizeProviderHealth(payload: unknown): RealtimeProviderHealth[] {
  const record = asRecord(payload)
  const raw = record ? first(record, ['providers', 'items', 'data']) : payload
  if (Array.isArray(raw)) {
    return raw.map(item => {
      const value = asRecord(item) || {}
      const provider = stringValue(first(value, ['provider', 'name']))?.trim().toLowerCase() || 'unknown'
      return parseProviderHealth(provider, value, 'market')
    }).filter(item => item.provider !== 'unknown')
  }
  const rawRecord = asRecord(raw)
  if (rawRecord) {
    return Object.entries(rawRecord).map(([provider, value]) => parseProviderHealth(provider.toLowerCase(), value, 'market'))
  }
  if (record) {
    const flattened: RealtimeProviderHealth[] = []
    for (const sectionKey of ['market_data', 'news']) {
      const section = asRecord(record[sectionKey])
      if (!section) continue
      const channel = sectionKey === 'news' ? 'news' : 'market'
      for (const [provider, value] of Object.entries(section)) flattened.push(parseProviderHealth(provider.toLowerCase(), value, channel))
    }
    if (flattened.length) return flattened
    return Object.entries(record)
      .filter(([key]) => !['generated_at', 'updated_at', 'status', 'redis_available'].includes(key))
      .map(([provider, value]) => parseProviderHealth(provider.toLowerCase(), value, 'market'))
  }
  return []
}

type StreamEnvelope = { event: string; data: unknown }

/** Parse a complete SSE event payload. Exported for deterministic Vitest coverage. */
export function parseSSEEvent(event: string, data: string): StreamEnvelope | null {
  if (!data.trim()) return null
  try {
    return { event: event || 'message', data: JSON.parse(data) }
  } catch {
    return { event: event || 'message', data }
  }
}

type RealtimeHookResult = {
  quotes: Record<string, RealtimeQuote>
  streamStatus: RealtimeStreamStatus
  streamError: Error | null
  lastUpdateAt: string | null
  query: UseQueryResult<unknown, Error>
}

const STREAM_RETRY_BASE_MS = 1_000
const STREAM_RETRY_MAX_MS = 30_000

/**
 * Read realtime quotes through the server.  The stream is preferred; REST is
 * fetched once initially and only retried at a conservative 30s cadence while
 * the stream is unavailable. No provider credentials ever reach the browser.
 */
export function useRealtimeQuotes(symbols: string[], enabled = true): RealtimeHookResult {
  const normalizedSymbols = useMemo(() => [...new Set(symbols.map(normalizeSymbol).filter(Boolean))].sort(), [symbols.join(',')])
  const symbolParam = normalizedSymbols.join(',')
  const queryClient = useQueryClient()
  const [streamStatus, setStreamStatus] = useState<RealtimeStreamStatus>(normalizedSymbols.length ? 'loading' : 'idle')
  const [streamError, setStreamError] = useState<Error | null>(null)
  const [streamQuotes, setStreamQuotes] = useState<Record<string, RealtimeQuote>>({})
  const [lastUpdateAt, setLastUpdateAt] = useState<string | null>(null)
  const query = useQuery({
    queryKey: ['market-realtime', normalizedSymbols],
    queryFn: () => api<unknown>(`/market/realtime?symbols=${encodeURIComponent(symbolParam)}`),
    enabled: enabled && normalizedSymbols.length > 0,
    staleTime: 15_000,
    refetchInterval: enabled && normalizedSymbols.length && (streamStatus === 'error' || streamStatus === 'fallback') ? 30_000 : false,
    refetchIntervalInBackground: false,
  })

  useEffect(() => {
    if (!enabled || !normalizedSymbols.length) {
      setStreamStatus('idle')
      setStreamQuotes({})
      return
    }
    const controller = new AbortController()
    let retry = 0
    let reconnectTimer: number | undefined
    let stopped = false

    const applyPayload = (payload: unknown) => {
      const quotes = normalizeRealtimeQuotes(payload, normalizedSymbols)
      if (!quotes.length) return
      setStreamQuotes(previous => {
        const next = { ...previous }
        for (const quote of quotes) {
          if (isQuoteNewer(quote, next[quote.symbol])) next[quote.symbol] = quote
        }
        return next
      })
      queryClient.setQueryData(['market-realtime', normalizedSymbols], (current: unknown) => {
        const merged = quoteMap(normalizeRealtimeQuotes(current, normalizedSymbols))
        for (const quote of quotes) if (isQuoteNewer(quote, merged[quote.symbol])) merged[quote.symbol] = quote
        return Object.values(merged)
      })
      setLastUpdateAt(new Date().toISOString())
    }

    const connect = async () => {
      if (stopped) return
      setStreamStatus(retry ? 'fallback' : 'connecting')
      try {
        const token = getToken()
        const headers: Record<string, string> = { Accept: 'text/event-stream' }
        if (token) headers.Authorization = `Bearer ${token}`
        const response = await fetch(`/api/market/realtime/stream?symbols=${encodeURIComponent(symbolParam)}`, { headers, signal: controller.signal })
        if (!response.ok || !response.body) throw new Error(`Realtime stream unavailable (${response.status})`)
        retry = 0
        setStreamError(null)
        setStreamStatus('connected')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let event = ''
        let dataLines: string[] = []
        const flush = () => {
          const parsed = parseSSEEvent(event, dataLines.join('\n'))
          event = ''
          dataLines = []
          if (parsed) applyPayload(parsed.data)
        }
        while (!stopped) {
          const chunk = await reader.read()
          if (chunk.done) break
          buffer += decoder.decode(chunk.value, { stream: true })
          const lines = buffer.split(/\r?\n/)
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (!line) { flush(); continue }
            if (line.startsWith(':')) continue
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
          }
        }
        if (!stopped) throw new Error('Realtime stream closed')
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === 'AbortError')) return
        const normalizedError = error instanceof Error ? error : new Error('Realtime stream failed')
        setStreamError(normalizedError)
        setStreamStatus('fallback')
        const delay = Math.min(STREAM_RETRY_MAX_MS, STREAM_RETRY_BASE_MS * 2 ** retry) + Math.round(Math.random() * 500)
        retry += 1
        reconnectTimer = window.setTimeout(connect, delay)
      }
    }
    connect()
    return () => {
      stopped = true
      controller.abort()
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
    }
  }, [enabled, normalizedSymbols, symbolParam, queryClient])

  const restQuotes = normalizeRealtimeQuotes(query.data, normalizedSymbols)
  const quotes = useMemo(() => {
    const merged = quoteMap(restQuotes)
    for (const quote of Object.values(streamQuotes)) if (isQuoteNewer(quote, merged[quote.symbol])) merged[quote.symbol] = quote
    return merged
  }, [query.data, normalizedSymbols, streamQuotes])
  return { quotes, streamStatus, streamError, lastUpdateAt, query }
}

export function useRealtimeProviderHealth(enabled = true) {
  return useQuery({
    queryKey: ['market-provider-health'],
    queryFn: () => api<unknown>('/market/providers/status'),
    enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    select: normalizeProviderHealth,
  })
}
