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

export type CryptoInterval = '1h' | '4h' | '1d'

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

export function formatUtcTime(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '未知'
  return new Date(ms).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
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

// ---------------------------------------------------------------------------
// page
// ---------------------------------------------------------------------------

export function CryptoResearchPage({ enabled = true }: { enabled?: boolean }) {
  const [instrumentId, setInstrumentId] = useState<number | null>(() => parseInstrumentFromSearch(window.location.search))
  const [interval, setIntervalState] = useState<CryptoInterval>('1d')
  const [query, setQuery] = useState('')

  useEffect(() => {
    const onPop = () => setInstrumentId(parseInstrumentFromSearch(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const selectInstrument = (id: number) => {
    setInstrumentId(id)
    const search = new URLSearchParams(window.location.search)
    search.set('tab', 'crypto')
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
    queryFn: () => api<CryptoInstrumentSummary & { filters: Record<string, unknown>; provider_mappings: { provider: string; provider_id: string; method: string; verified_at: string | null }[]; base_asset: { slug: string; symbol: string; display_name: string }; quote_asset: { slug: string; symbol: string; display_name: string }; settlement_asset: { slug: string; symbol: string } | null }>(`/crypto/instruments/${instrumentId}`),
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
    queryKey: ['crypto-candles', instrumentId, interval],
    queryFn: () => api<CryptoCandlesResponse>(`/crypto/market/candles?instrument_id=${instrumentId}&interval=${interval}&limit=1000`),
    enabled: enabled && instrumentId !== null,
    staleTime: 60_000,
  })
  const technical = useQuery({
    queryKey: ['crypto-technical', instrumentId, interval],
    queryFn: () => api<CryptoTechnical>(`/crypto/market/technical?instrument_id=${instrumentId}&interval=${interval}`),
    enabled: enabled && instrumentId !== null,
    staleTime: 5 * 60_000,
  })

  const prepared = useMemo(() => prepareCryptoCandles(candles.data?.items ?? []), [candles.data])
  const movingAverages = useMemo(() => {
    const series = technical.data?.series
    if (!series || !Array.isArray(series.time_ms)) return []
    const result: { time: UTCTimestamp; value: number }[][] = []
    for (const key of ['sma20', 'sma50', 'sma200']) {
      const values = series[key] as { time_ms: number; value: number }[] | undefined
      if (!Array.isArray(values)) { result.push([]); continue }
      result.push(values.map(point => ({ time: (point.time_ms / 1000) as UTCTimestamp, value: point.value })))
    }
    return result
  }, [technical.data])

  const options = query.trim().length > 0 && search.data ? search.data.instruments : instruments.data?.items ?? []
  const coverage = candles.data?.coverage
  const technicalLast = technical.data?.status === 'ready' ? technical.data.last : null

  return <div className="crypto-research-page">
    <section className="crypto-hero">
      <div>
        <p className="crypto-eyebrow">CRYPTO RESEARCH · 加密研究</p>
        <h2>链上资产，同样的证据标准</h2>
        <p>使用稳定标识浏览 Binance 现货币对：身份由供应商映射决定，行情只来自已收盘 K 线与短缓存，缺口如实标注。</p>
      </div>
      <div className="crypto-hero-meta">
        <span>数据来源</span>
        <b>Binance 公共接口</b>
        <small>{instruments.data ? `${instruments.data.total} 个已入库交易对` : '等待元数据同步'}</small>
      </div>
    </section>

    {!enabled && <div className="crypto-disabled">演示预览未加载加密数据，连接账户后读取已保存的市场数据。</div>}

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

        <section className="crypto-technical" aria-label="技术指标">
          <header>
            <h3>技术指标</h3>
            <span className="crypto-source-badge">{technicalStatusLabel(technical.data?.status ?? 'invalid')}</span>
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
  </div>
}
