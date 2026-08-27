import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { api } from './api'
import QuantBacktests from './QuantBacktests'
import './crypto-research.css'

// ---------------------------------------------------------------------------
// types (mirroring the authenticated /api/crypto read endpoints)
// ---------------------------------------------------------------------------

export type CryptoInstrumentSummary = {
  id: number
  venue: string
  market: string
  provider_symbol: string
  kind: string
  status: string
  display_label: string
  base_asset_symbol: string
  quote_asset_symbol: string
}

export type CryptoSearchResponse = {
  query: string
  instruments: CryptoInstrumentSummary[]
  assets: { id: number; slug: string; symbol: string; display_name: string; display_label: string; asset_kind: string }[]
  note: string
}

export type CryptoInstrumentDetail = CryptoInstrumentSummary & {
  filters: Record<string, unknown>
  provider_mappings: { provider: string; provider_id: string; method: string; verified_at: string | null }[]
  base_asset: { id: number; slug: string; symbol: string; display_name: string }
  quote_asset: { id?: number; slug: string; symbol: string; display_name: string }
  settlement_asset: { id?: number; slug: string; symbol: string } | null
}

export type CryptoFundamentalsLatest = {
  market_cap: string | null
  fully_diluted_valuation: string | null
  circulating_supply: string | null
  total_supply: string | null
  max_supply: string | null
  market_cap_rank: number | null
  provider_timestamp: string | null
  fetched_at: string | null
  source: string | null
  coverage: number | string | null
  freshness_status: string | null
}

export type CryptoFundamentals = {
  asset_id: number
  provider_mapping: {
    provider: string
    provider_id: string
    method?: string | null
    verified_at?: string | null
  } | null
  reference: {
    canonical_name?: string | null
    symbol?: string | null
    categories?: string[]
    website_urls?: string[]
    contract_references?: Record<string, string>
  } | null
  latest: CryptoFundamentalsLatest | null
  freshness: {
    status?: string | null
    provider_timestamp?: string | null
    fetched_at?: string | null
    source?: string | null
    coverage?: number | string | null
  } | null
  warnings: string[]
}

export type CryptoNewsItem = {
  news_id: number | string
  title: string
  summary: string | null
  ai_summary: string | null
  url: string | null
  provider: string | null
  source: string | null
  published_at: string | null
  found_at: string | null
  association: {
    scope_type: string
    confidence: number | string | null
    evidence_method?: string | null
    evidence: unknown
  } | null
}

export type CryptoNewsResponse = {
  items: CryptoNewsItem[]
  warnings: string[]
}

export type CryptoLatest = {
  instrument_id: number
  display_label: string
  source: 'ticker_cache' | 'closed_candle_fallback' | 'unavailable'
  stale: boolean
  age_seconds: number | null
  warning: string | null
  provider: string
  symbol: string
  last_price: string | null
  bid_price: string | null
  ask_price: string | null
  high_price_24h: string | null
  low_price_24h: string | null
  base_volume_24h: string | null
  quote_volume_24h: string | null
  event_time_ms: number | null
  received_at: string | null
}

export type CryptoCandleRow = {
  open_time_ms: number
  close_time_ms: number
  open: string
  high: string
  low: string
  close: string
  base_volume: string
  quote_volume: string
  taker_buy_base_volume: string | null
  trades: number | null
  final: boolean
  provider: string
  feed: string
  price_type: string
}

export type CryptoCandlesResponse = {
  instrument_id: number
  interval: string
  items: CryptoCandleRow[]
  coverage: {
    earliest_open_ms: number | null
    latest_open_ms: number | null
    candle_count: number
    expected_count: number
    missing_count: number
  }
  limit: number
}

export type CryptoTechnical = {
  status: 'ready' | 'insufficient' | 'invalid'
  version: string
  parameter_set_version?: string
  interval?: string
  candle_count?: number
  minimum_required?: number
  reason?: string
  data_through_ms?: number
  input_hash?: string
  last?: {
    close: string
    rsi: number | null
    atr: number | null
    macd: number | null
    macd_signal: number | null
    macd_histogram: number | null
    bollinger_upper: number | null
    bollinger_middle: number | null
    bollinger_lower: number | null
  }
  series?: { time_ms: number[]; close: string[] } & Record<string, unknown>
  omissions?: string[]
  note?: string
}

export type CryptoDerivativeMetric = {
  observed_at: string
  mark_price: string | null
  index_price: string | null
  basis_rate: string | null
  open_interest_base: string | null
  open_interest_usd: string | null
  long_short_ratio: string | null
  taker_buy_sell_ratio: string | null
  taker_buy_volume: string | null
  taker_sell_volume: string | null
  futures_volume_base: string | null
  provider: string
  quality: string
}

export type CryptoFundingEvent = {
  funding_time: string
  funding_rate: string
  mark_price: string | null
  provider: string
  quality: string
}

export type CryptoDerivativesHistory = {
  instrument_id: number
  interval: string
  metrics: CryptoDerivativeMetric[]
  funding_rates: CryptoFundingEvent[]
  coverage: Record<string, unknown>
  definitions: Record<string, { metric_name: string; definition: string; scope: string; unit: string }>
}

export type CryptoRegime = {
  state: 'INSUFFICIENT_DATA' | 'BALANCED' | 'LEVERAGE_BUILDUP' | 'DELEVERAGING' | 'LONG_CROWDING' | 'SHORT_CROWDING'
  version: string
  threshold_hash: string
  input_hash: string
  as_of: string
  valid_until: string
  stale: boolean
  confidence: string
  coverage: string
  features: Record<string, string | null>
  sample_counts: Record<string, number>
  evidence: string[]
  omissions: string[]
  warnings: string[]
  note: string
}

export type CryptoInterval = '1h' | '4h' | '1d'
export type CryptoPriceType = 'trade' | 'mark' | 'index'

// ---------------------------------------------------------------------------
// pure helpers (exported for tests)
// ---------------------------------------------------------------------------

export function parseInstrumentFromSearch(search: string): number | null {
  const value = new URLSearchParams(search).get('instrument')
  if (value === null || value === '') return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

export function cryptoIntervalLabel(interval: CryptoInterval): string {
  return interval === '1h' ? '1 小时' : interval === '4h' ? '4 小时' : '1 天'
}

export function formatCryptoAge(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '未知'
  if (seconds < 60) return `${Math.round(seconds)} 秒前`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时前`
  return `${Math.round(seconds / 86400)} 天前`
}

export function formatCryptoNumber(value: string | null | undefined, maxDigits = 4): string {
  if (value === null || value === undefined || value === '') return '数据不足'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '数据不足'
  return parsed.toLocaleString('en-US', { maximumFractionDigits: maxDigits })
}

export function formatCryptoCoverage(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '覆盖未知'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '覆盖未知'
  const percent = parsed <= 1 ? parsed * 100 : parsed
  return `${Math.max(0, Math.min(100, percent)).toFixed(1)}%`
}

export function cryptoFreshnessLabel(status: string | null | undefined): string {
  if (status === 'fresh') return '新鲜'
  if (status === 'stale') return '可能偏旧'
  if (status === 'expired') return '已过期'
  if (status === 'unknown') return '新鲜度未知'
  return status ? status : '新鲜度未知'
}

export function safeCryptoUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

export function formatCryptoEvidence(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function formatUtcTime(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '未知'
  return new Date(ms).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}

export function formatUtcIso(value: string | null | undefined): string {
  if (!value) return '未知'
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? '未知' : time.toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}

export function formatCryptoRate(value: string | null | undefined, digits = 3): string {
  if (value === null || value === undefined || value === '') return '数据不足'
  const rate = Number(value)
  return Number.isFinite(rate) ? `${(rate * 100).toFixed(digits)}%` : '数据不足'
}

export function regimeLabel(state: CryptoRegime['state']): string {
  return ({
    INSUFFICIENT_DATA: '数据不足', BALANCED: '未触发联合阈值', LEVERAGE_BUILDUP: '杠杆累积',
    DELEVERAGING: '去杠杆', LONG_CROWDING: '多头拥挤', SHORT_CROWDING: '空头拥挤',
  } as const)[state]
}

export function sparklineSegments(values: (string | null)[]): string[] {
  const parsed = values.map(value => value === null ? null : Number(value))
  const finite = parsed.filter((value): value is number => value !== null && Number.isFinite(value))
  if (finite.length < 2) return []
  const min = Math.min(...finite)
  const span = Math.max(Math.max(...finite) - min, Number.EPSILON)
  const segments: string[] = []
  let points: string[] = []
  parsed.forEach((value, index) => {
    if (value === null || !Number.isFinite(value)) {
      if (points.length > 1) segments.push(points.join(' '))
      points = []
      return
    }
    points.push(`${(index / Math.max(1, parsed.length - 1) * 100).toFixed(2)},${(30 - (value - min) / span * 26).toFixed(2)}`)
  })
  if (points.length > 1) segments.push(points.join(' '))
  return segments
}

export function latestDerivativeValue(
  items: CryptoDerivativeMetric[],
  key: 'open_interest_usd' | 'basis_rate' | 'taker_buy_sell_ratio',
): string | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (items[index][key] !== null) return items[index][key]
  }
  return null
}

export type PreparedCryptoChart = {
  candles: { time: UTCTimestamp; open: number; high: number; low: number; close: number }[]
  volume: { time: UTCTimestamp; value: number }[]
  rejected: number
}

/** Validate and chronologicalize provider candles; never fabricate bars. */
export function prepareCryptoCandles(items: CryptoCandleRow[]): PreparedCryptoChart {
  const candles: PreparedCryptoChart['candles'] = []
  const volume: PreparedCryptoChart['volume'] = []
  let rejected = 0
  for (const item of items) {
    const open = Number(item.open)
    const high = Number(item.high)
    const low = Number(item.low)
    const close = Number(item.close)
    const baseVolume = Number(item.base_volume)
    const time = item.open_time_ms / 1000
    const valid =
      [open, high, low, close].every(value => Number.isFinite(value)) &&
      high >= Math.max(open, close) &&
      low <= Math.min(open, close) &&
      Number.isFinite(baseVolume) &&
      Number.isFinite(time)
    if (!valid || !item.final) {
      rejected += 1
      continue
    }
    candles.push({ time: time as UTCTimestamp, open, high, low, close })
    volume.push({ time: time as UTCTimestamp, value: baseVolume })
  }
  candles.sort((a, b) => a.time - b.time)
  volume.sort((a, b) => a.time - b.time)
  return { candles, volume, rejected }
}

export function technicalStatusLabel(status: CryptoTechnical['status']): string {
  if (status === 'ready') return '指标就绪'
  if (status === 'insufficient') return '数据不足'
  return '不可用'
}

export function latestSourceLabel(source: CryptoLatest['source']): string {
  if (source === 'ticker_cache') return '实时缓存'
  if (source === 'closed_candle_fallback') return '已收盘 K 线回退'
  return '暂无数据'
}

// ---------------------------------------------------------------------------
// chart component
// ---------------------------------------------------------------------------

function CryptoCandleChart({ prepared, movingAverages }: { prepared: PreparedCryptoChart; movingAverages: { time: UTCTimestamp; value: number }[][] }) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const maRefs = useRef<ISeriesApi<'Line'>[]>([])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const chart = createChart(host, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: getComputedStyle(host).color,
        fontFamily: 'inherit',
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: 'rgba(120,120,128,0.12)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true },
      handleScale: !prefersReducedMotion,
      handleScroll: !prefersReducedMotion,
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#30d158',
      downColor: '#ff453a',
      borderVisible: false,
      wickUpColor: '#30d158',
      wickDownColor: '#ff453a',
    })
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      color: 'rgba(100,116,139,0.45)',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    chartRef.current = chart
    seriesRef.current = candles
    volumeRef.current = volume
    maRefs.current = ['#d9a7ff', '#64d2ff', '#ffd60a'].map(color =>
      chart.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
    )
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      volumeRef.current = null
      maRefs.current = []
    }
  }, [])

  useEffect(() => {
    seriesRef.current?.setData(prepared.candles)
    volumeRef.current?.setData(prepared.volume)
    maRefs.current.forEach((series, index) => {
      series.setData(movingAverages[index] ?? [])
    })
    chartRef.current?.timeScale().scrollToRealTime()
  }, [prepared, movingAverages])

  if (prepared.candles.length === 0) {
    return <div className="crypto-chart-empty">暂无已收盘 K 线，等待采集任务完成后展示。</div>
  }
  return <div className="crypto-chart-host" ref={hostRef} role="img" aria-label="加密货币 K 线图" />
}

function DerivativeSparkline({ values, label }: { values: (string | null)[]; label: string }) {
  const segments = sparklineSegments(values)
  if (segments.length === 0) return <div className="crypto-sparkline-empty">数据不足</div>
  return <svg className="crypto-sparkline" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label={label}>
    {segments.map((points, index) => <polyline key={index} points={points}/>) }
  </svg>
}

// ---------------------------------------------------------------------------
// page
// ---------------------------------------------------------------------------

export function CryptoResearchPage({ enabled = true }: { enabled?: boolean }) {
  const [instrumentId, setInstrumentId] = useState<number | null>(() => parseInstrumentFromSearch(window.location.search))
  const [interval, setIntervalState] = useState<CryptoInterval>('1d')
  const [priceType, setPriceType] = useState<CryptoPriceType>('trade')
  const [query, setQuery] = useState('')
  const [view, setView] = useState<'market' | 'quant'>('market')

  useEffect(() => {
    const onPop = () => setInstrumentId(parseInstrumentFromSearch(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const selectInstrument = (id: number) => {
    setInstrumentId(id)
    // dedicated /crypto route: instrument selection stays in the query string
    const search = new URLSearchParams(window.location.search)
    search.delete('tab')
    search.set('instrument', String(id))
    window.history.replaceState({}, '', `${window.location.pathname}?${search.toString()}`)
  }

  const search = useQuery({
    queryKey: ['crypto-search', query],
    queryFn: () => api<CryptoSearchResponse>(`/crypto/search?q=${encodeURIComponent(query)}`),
    enabled: enabled && query.trim().length > 0,
    staleTime: 60_000,
  })
  const instruments = useQuery({
    queryKey: ['crypto-instruments'],
    queryFn: () => api<{ items: CryptoInstrumentSummary[]; total: number }>(`/crypto/instruments?limit=50`),
    enabled,
    staleTime: 5 * 60_000,
  })
  const detail = useQuery({
    queryKey: ['crypto-instrument', instrumentId],
    queryFn: () => api<CryptoInstrumentDetail>(`/crypto/instruments/${instrumentId}`),
    enabled: enabled && instrumentId !== null,
    staleTime: 5 * 60_000,
  })
  const latest = useQuery({
    queryKey: ['crypto-latest', instrumentId],
    queryFn: () => api<CryptoLatest>(`/crypto/market/latest?instrument_id=${instrumentId}`),
    enabled: enabled && instrumentId !== null,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const candles = useQuery({
    queryKey: ['crypto-candles', instrumentId, interval, priceType],
    queryFn: () => api<CryptoCandlesResponse>(`/crypto/market/candles?instrument_id=${instrumentId}&interval=${interval}&price_type=${priceType}&limit=1000`),
    enabled: enabled && instrumentId !== null,
    staleTime: 60_000,
  })
  const technical = useQuery({
    queryKey: ['crypto-technical', instrumentId, interval],
    queryFn: () => api<CryptoTechnical>(`/crypto/market/technical?instrument_id=${instrumentId}&interval=${interval}`),
    enabled: enabled && instrumentId !== null,
    staleTime: 5 * 60_000,
  })
  const derivatives = useQuery({
    queryKey: ['crypto-derivatives', instrumentId],
    queryFn: () => api<CryptoDerivativesHistory>(`/crypto/derivatives?instrument_id=${instrumentId}&hours=168`),
    enabled: enabled && instrumentId !== null && detail.data?.kind === 'perpetual',
    staleTime: 5 * 60_000,
  })
  const regime = useQuery({
    queryKey: ['crypto-regime', instrumentId],
    queryFn: () => api<CryptoRegime>(`/crypto/derivatives/regime?instrument_id=${instrumentId}`),
    enabled: enabled && instrumentId !== null && detail.data?.kind === 'perpetual',
    staleTime: 5 * 60_000,
  })
  const assetId = detail.data?.base_asset.id ?? null
  const fundamentals = useQuery({
    queryKey: ['crypto-fundamentals', assetId],
    queryFn: () => api<CryptoFundamentals>(`/crypto/fundamentals?asset_id=${assetId}`),
    enabled: enabled && assetId !== null,
    staleTime: 15 * 60_000,
  })
  const news = useQuery({
    queryKey: ['crypto-news', assetId, instrumentId],
    queryFn: () => api<CryptoNewsResponse>(`/crypto/news?asset_id=${assetId}&instrument_id=${instrumentId}&limit=20`),
    enabled: enabled && assetId !== null && instrumentId !== null,
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (detail.data?.kind !== 'perpetual' && priceType !== 'trade') setPriceType('trade')
  }, [detail.data?.kind, priceType])

  const prepared = useMemo(() => prepareCryptoCandles(candles.data?.items ?? []), [candles.data])
  const movingAverages = useMemo(() => {
    if (priceType !== 'trade') return []
    const series = technical.data?.series
    if (!series || !Array.isArray(series.time_ms)) return []
    const result: { time: UTCTimestamp; value: number }[][] = []
    for (const key of ['sma20', 'sma50', 'sma200']) {
      const values = series[key] as { time_ms: number; value: number }[] | undefined
      if (!Array.isArray(values)) { result.push([]); continue }
      result.push(values.map(point => ({ time: (point.time_ms / 1000) as UTCTimestamp, value: point.value })))
    }
    return result
  }, [technical.data, priceType])

  const options = query.trim().length > 0 && search.data ? search.data.instruments : instruments.data?.items ?? []
  const coverage = candles.data?.coverage
  const technicalLast = technical.data?.status === 'ready' ? technical.data.last : null
  const fundamentalLatest = fundamentals.data?.latest
  const fundamentalFreshness = fundamentals.data?.freshness
  const fundamentalStatus = fundamentalLatest?.freshness_status ?? fundamentalFreshness?.status ?? null
  const newsItems = news.data?.items ?? []

  return <div className="crypto-research-page">
    <section className="crypto-hero">
      <div>
        <p className="crypto-eyebrow">CRYPTO RESEARCH · 加密研究</p>
        <h2>交易型加密研究，证据优先</h2>
        <p>专属 Crypto 研究面板：现货、永续合约、技术指标、市场基本面、新闻与衍生品证据都在这里，和 Stock 工作区保持分离。</p>
      </div>
      <div className="crypto-hero-meta">
        <span>数据来源</span>
        <b>Binance 公共接口</b>
        <small>{instruments.data ? `${instruments.data.total} 个已入库交易对` : '等待元数据同步'}</small>
      </div>
    </section>

    <div className="crypto-view-segment" role="tablist" aria-label="Crypto 研究模块">
      <button role="tab" aria-selected={view === 'market'} className={view === 'market' ? 'active' : ''} onClick={() => setView('market')}>市场研究 <small>Market Research</small></button>
      <button role="tab" aria-selected={view === 'quant'} className={view === 'quant' ? 'active' : ''} onClick={() => setView('quant')}>量化回测 <small>Quant Backtest</small></button>
    </div>

    {!enabled && <div className="crypto-disabled">演示预览未加载加密数据，连接账户后读取已保存的市场数据。</div>}

    {view === 'quant' ? <QuantBacktests enabled={enabled} /> : <>
    <section className="crypto-search" aria-label="加密标的搜索">
      <label>
        <span>搜索标的</span>
        <input
          value={query}
          onChange={event => setQuery(event.target.value)}
          placeholder="如 BTCUSDT、BTC"
          aria-label="搜索加密标的"
        />
      </label>
      <div className="crypto-instrument-grid">
        {options.length === 0 && <p className="crypto-empty-hint">{search.isLoading || instruments.isLoading ? '正在读取标的…' : '暂无匹配的标的；等待元数据同步或调整关键词。'}</p>}
        {options.map(instrument => (
          <button
            key={`${instrument.id}-${instrument.kind}`}
            className={`crypto-instrument-card${instrumentId === instrument.id ? ' selected' : ''}`}
            onClick={() => selectInstrument(instrument.id)}
            aria-pressed={instrumentId === instrument.id}
          >
            <b>{instrument.display_label}</b>
            <small>{instrument.status === 'trading' ? '交易中' : instrument.status === 'delisted' ? '已退市' : '暂停'}</small>
          </button>
        ))}
      </div>
      {query.trim().length > 0 && search.data && search.data.assets.length > 0 && (
        <p className="crypto-asset-hints">
          资产提示（非身份）：{search.data.assets.map(asset => asset.display_label).join(' · ')}
        </p>
      )}
    </section>

    {instrumentId !== null && (
      <>
        <section className="crypto-overview" aria-label="最新行情">
          <header>
            <h3>{detail.data?.display_label ?? latest.data?.display_label ?? `交易对 #${instrumentId}`}</h3>
            {latest.data && (
              <span className={`crypto-source-badge${latest.data.stale ? ' stale' : ''}`}>
                {latestSourceLabel(latest.data.source)}
                {latest.data.stale ? ' · 数据偏旧' : ''} · {formatCryptoAge(latest.data.age_seconds)}
              </span>
            )}
          </header>
          {latest.data?.warning && <p className="crypto-warning" role="status">{latest.data.warning}</p>}
          {latest.isLoading && <p className="crypto-loading">正在读取最新行情…</p>}
          {latest.data && (
            <dl className="crypto-metrics">
              <div><dt>最新价</dt><dd>{formatCryptoNumber(latest.data.last_price, 6)}</dd></div>
              <div><dt>买一 / 卖一</dt><dd>{latest.data.bid_price && latest.data.ask_price ? `${formatCryptoNumber(latest.data.bid_price, 2)} / ${formatCryptoNumber(latest.data.ask_price, 2)}` : '数据不足'}</dd></div>
              <div><dt>24h 最高 / 最低</dt><dd>{latest.data.high_price_24h && latest.data.low_price_24h ? `${formatCryptoNumber(latest.data.high_price_24h, 2)} / ${formatCryptoNumber(latest.data.low_price_24h, 2)}` : '数据不足'}</dd></div>
              <div><dt>24h 成交量</dt><dd>{formatCryptoNumber(latest.data.base_volume_24h, 2)}</dd></div>
              <div><dt>行情时间</dt><dd>{formatUtcTime(latest.data.event_time_ms)}</dd></div>
            </dl>
          )}
        </section>

        <section className="crypto-fundamentals" aria-label="市场基本面">
          <header>
            <div><p className="crypto-eyebrow">COINGECKO REFERENCE</p><h3>市场基本面</h3></div>
            <span className={`crypto-source-badge${fundamentalStatus === 'stale' || fundamentalStatus === 'expired' ? ' stale' : ''}`}>
              {cryptoFreshnessLabel(fundamentalStatus)}
            </span>
          </header>
          {fundamentals.isLoading && <p className="crypto-loading">正在读取已持久化基本面…</p>}
          {fundamentals.isError && <p className="crypto-warning" role="status">基本面暂时不可用；现货、技术与衍生品研究仍可继续。</p>}
          {fundamentals.data && (
            <>
              {fundamentals.data.provider_mapping && (
                <p className="crypto-fundamentals-reference">
                  映射：{fundamentals.data.provider_mapping.provider}:{fundamentals.data.provider_mapping.provider_id}
                  {fundamentals.data.provider_mapping.method ? ` · ${fundamentals.data.provider_mapping.method}` : ''}
                  {fundamentals.data.reference?.canonical_name ? ` · ${fundamentals.data.reference.canonical_name}` : ''}
                </p>
              )}
              <dl className="crypto-metrics compact">
                <div><dt>市值</dt><dd>{formatCryptoNumber(fundamentalLatest?.market_cap, 0)}</dd></div>
                <div><dt>FDV</dt><dd>{formatCryptoNumber(fundamentalLatest?.fully_diluted_valuation, 0)}</dd></div>
                <div><dt>市值排名</dt><dd>{fundamentalLatest?.market_cap_rank ?? '数据不足'}</dd></div>
                <div><dt>流通供应量</dt><dd>{formatCryptoNumber(fundamentalLatest?.circulating_supply, 4)}</dd></div>
                <div><dt>总供应量</dt><dd>{formatCryptoNumber(fundamentalLatest?.total_supply, 4)}</dd></div>
                <div><dt>最大供应量</dt><dd>{formatCryptoNumber(fundamentalLatest?.max_supply, 4)}</dd></div>
              </dl>
              <footer className="crypto-coverage">
                <span>来源 {fundamentalLatest?.source ?? fundamentalFreshness?.source ?? fundamentals.data.provider_mapping?.provider ?? 'CoinGecko'}</span>
                <span>供应商时间 {formatUtcIso(fundamentalLatest?.provider_timestamp ?? fundamentalFreshness?.provider_timestamp)}</span>
                <span>读取时间 {formatUtcIso(fundamentalLatest?.fetched_at ?? fundamentalFreshness?.fetched_at)}</span>
                <span>覆盖 {formatCryptoCoverage(fundamentalLatest?.coverage ?? fundamentalFreshness?.coverage)}</span>
              </footer>
              {fundamentals.data.warnings.map((warning, index) => <p className="crypto-warning" role="status" key={`${warning}-${index}`}>{warning}</p>)}
            </>
          )}
        </section>

        <section className="crypto-news" aria-label="加密新闻">
          <header>
            <div><p className="crypto-eyebrow">CRYPTO NEWS</p><h3>关联新闻</h3></div>
            <span className="crypto-source-badge">{news.data ? `${newsItems.length} 条已保存` : '仅读取已保存新闻'}</span>
          </header>
          {news.isLoading && <p className="crypto-loading">正在读取已持久化新闻…</p>}
          {news.isError && <p className="crypto-warning" role="status">新闻暂时不可用；市场、技术与衍生品研究仍可继续。</p>}
          {news.data && newsItems.length === 0 && <p className="crypto-empty-hint">暂无高置信度关联新闻；不以 ticker-only 匹配补造结果。</p>}
          {newsItems.length > 0 && (
            <div className="crypto-news-list">
              {newsItems.map(item => {
                const href = safeCryptoUrl(item.url)
                const summary = item.ai_summary || item.summary
                const evidence = formatCryptoEvidence(item.association?.evidence)
                return <article className="crypto-news-item" key={String(item.news_id)}>
                  <h4>{href ? <a href={href} target="_blank" rel="noreferrer noopener">{item.title}</a> : <span>{item.title}</span>}</h4>
                  {summary && <p>{summary}</p>}
                  <div className="crypto-news-meta">
                    <span>{item.source || item.provider || '来源未知'}</span>
                    <span>发布 {formatUtcIso(item.published_at)}</span>
                    <span>发现 {formatUtcIso(item.found_at)}</span>
                    {item.association && <span>{item.association.scope_type} · 置信度 {formatCryptoCoverage(item.association.confidence)}</span>}
                  </div>
                  {evidence && <small className="crypto-news-evidence">证据：{evidence}</small>}
                </article>
              })}
            </div>
          )}
          {news.data?.warnings.map((warning, index) => <p className="crypto-warning" role="status" key={`${warning}-${index}`}>{warning}</p>)}
        </section>

        <section className="crypto-chart-section" aria-label="历史 K 线">
          <header>
            <h3>历史 K 线（UTC）</h3>
            <div className="segmented compact" role="tablist" aria-label="K 线周期">
              {(['1h', '4h', '1d'] as CryptoInterval[]).map(value => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={interval === value}
                  className={interval === value ? 'active' : ''}
                  onClick={() => setIntervalState(value)}
                >
                  {cryptoIntervalLabel(value)}
                </button>
              ))}
            </div>
            {detail.data?.kind === 'perpetual' && <div className="segmented compact" role="tablist" aria-label="价格类型">
              {(['trade', 'mark', 'index'] as CryptoPriceType[]).map(value => <button
                key={value} role="tab" aria-selected={priceType === value}
                className={priceType === value ? 'active' : ''} onClick={() => setPriceType(value)}
              >{value === 'trade' ? '成交价' : value === 'mark' ? '标记价' : '指数价'}</button>)}
            </div>}
          </header>
          <CryptoCandleChart prepared={prepared} movingAverages={movingAverages} />
          <footer className="crypto-coverage">
            {candles.isLoading && <span>正在读取 K 线…</span>}
            {coverage && (
              <>
                <span>{coverage.candle_count} 根已收盘 K 线</span>
                <span>{formatUtcTime(coverage.earliest_open_ms)} → {formatUtcTime(coverage.latest_open_ms)}</span>
                <span className={coverage.missing_count > 0 ? ' crypto-gap' : ''}>
                  {coverage.missing_count > 0 ? `覆盖缺口 ${coverage.missing_count} 根` : '区间内无缺口'}
                </span>
              </>
            )}
            {prepared.rejected > 0 && <span className="crypto-gap">已忽略 {prepared.rejected} 根无效/未收盘数据</span>}
          </footer>
        </section>

        {detail.data?.kind === 'perpetual' && <section className="crypto-derivatives" aria-label="衍生品研究">
          <header>
            <div><p className="crypto-eyebrow">USD-M DERIVATIVES</p><h3>衍生品研究</h3></div>
            {regime.data && <span className={`crypto-regime-badge state-${regime.data.state.toLowerCase()}`}>{regimeLabel(regime.data.state)}</span>}
          </header>
          {(derivatives.isLoading || regime.isLoading) && <p className="crypto-loading">正在读取已持久化衍生品证据…</p>}
          {(derivatives.isError || regime.isError) && <p className="crypto-warning" role="status">衍生品证据读取失败；没有用旧值或推断值替代。</p>}
          {regime.data && <div className="crypto-regime-summary">
            <div><span>Regime v1</span><strong>{regimeLabel(regime.data.state)}</strong><small>置信度 {Math.round(Number(regime.data.confidence) * 100)}% · 仅表示覆盖与规则一致度</small></div>
            <div><span>覆盖率</span><strong>{Math.round(Number(regime.data.coverage) * 100)}%</strong><small>有效至 {formatUtcIso(regime.data.valid_until)}{regime.data.stale ? ' · 已过期' : ''}</small></div>
          </div>}
          {regime.data?.note && <p className="crypto-regime-note">{regime.data.note}</p>}
          {regime.data && regime.data.evidence.length > 0 && <ul className="crypto-evidence-list">{regime.data.evidence.map(item => <li key={item}>{item.replaceAll('_', ' ')}</li>)}</ul>}
          {regime.data && regime.data.omissions.length > 0 && <p className="crypto-warning" role="status">缺口：{regime.data.omissions.join(' · ')}</p>}
          {derivatives.data && <div className="crypto-derivative-grid">
            <article><span>资金费率</span><strong>{formatCryptoRate(derivatives.data.funding_rates.at(-1)?.funding_rate)}</strong><DerivativeSparkline label="资金费率历史" values={derivatives.data.funding_rates.map(row => row.funding_rate)}/><small>{derivatives.data.funding_rates.length} 个实际结算事件</small></article>
            <article><span>未平仓量</span><strong>{formatCryptoNumber(latestDerivativeValue(derivatives.data.metrics, 'open_interest_usd'), 0)}</strong><DerivativeSparkline label="未平仓量历史" values={derivatives.data.metrics.map(row => row.open_interest_usd)}/><small>USD 名义值；缺失不补值</small></article>
            <article><span>标记/指数基差</span><strong>{formatCryptoRate(latestDerivativeValue(derivatives.data.metrics, 'basis_rate'))}</strong><DerivativeSparkline label="基差历史" values={derivatives.data.metrics.map(row => row.basis_rate)}/><small>仅同时间标记价与指数价</small></article>
            <article><span>Taker 买卖比</span><strong>{formatCryptoNumber(latestDerivativeValue(derivatives.data.metrics, 'taker_buy_sell_ratio'), 3)}</strong><DerivativeSparkline label="Taker 买卖比历史" values={derivatives.data.metrics.map(row => row.taker_buy_sell_ratio)}/><small>买方成交量 / 卖方成交量</small></article>
          </div>}
          {derivatives.data && <footer className="crypto-coverage"><span>{derivatives.data.metrics.length} 个 1h 指标点</span><span>{derivatives.data.funding_rates.length} 个资金费率事件</span><span>来源 Binance USD-M 公共接口</span></footer>}
        </section>}

        <section className="crypto-technical" aria-label="技术指标">
          <header>
            <h3>技术指标</h3>
            <span className="crypto-source-badge">成交价 · {technicalStatusLabel(technical.data?.status ?? 'invalid')}</span>
          </header>
          {technical.isLoading && <p className="crypto-loading">正在计算指标…</p>}
          {technical.data?.status === 'insufficient' && <p className="crypto-warning" role="status">{technical.data.reason}</p>}
          {technicalLast && (
            <>
              <dl className="crypto-metrics compact">
                <div><dt>RSI (14)</dt><dd>{technicalLast.rsi !== null ? technicalLast.rsi.toFixed(2) : '数据不足'}</dd></div>
                <div><dt>ATR (14)</dt><dd>{technicalLast.atr !== null ? technicalLast.atr.toFixed(4) : '数据不足'}</dd></div>
                <div><dt>MACD</dt><dd>{technicalLast.macd !== null ? technicalLast.macd.toFixed(4) : '数据不足'}</dd></div>
                <div><dt>布林带中轨</dt><dd>{technicalLast.bollinger_middle !== null ? technicalLast.bollinger_middle.toFixed(4) : '数据不足'}</dd></div>
                <div><dt>布林带上轨</dt><dd>{technicalLast.bollinger_upper !== null ? technicalLast.bollinger_upper.toFixed(4) : '数据不足'}</dd></div>
                <div><dt>布林带下轨</dt><dd>{technicalLast.bollinger_lower !== null ? technicalLast.bollinger_lower.toFixed(4) : '数据不足'}</dd></div>
              </dl>
              <p className="crypto-technical-note">
                参数集 {technical.data?.parameter_set_version} · 数据截至 {formatUtcTime(technical.data?.data_through_ms ?? null)}
                {technical.data?.input_hash ? ` · 输入 ${technical.data.input_hash.slice(0, 10)}` : ''}
              </p>
            </>
          )}
        </section>

        {detail.data && (
          <section className="crypto-identity-evidence" aria-label="身份证据">
            <h3>身份与来源</h3>
            <p>
              {detail.data.base_asset.display_name}（{detail.data.base_asset.slug}） / {detail.data.quote_asset.display_name}（{detail.data.quote_asset.slug}）
              {detail.data.settlement_asset ? ` · 结算 ${detail.data.settlement_asset.slug}` : ''}
            </p>
            <ul>
              {detail.data.provider_mappings.map(mapping => (
                <li key={`${mapping.provider}-${mapping.provider_id}`}>
                  {mapping.provider}:{mapping.provider_id} · {mapping.method}
                  {mapping.verified_at ? ' · 已验证' : ' · 未验证'}
                </li>
              ))}
              {detail.data.provider_mappings.length === 0 && <li>暂无供应商映射证据</li>}
            </ul>
          </section>
        )}
      </>
    )}
    </>}
  </div>
}
