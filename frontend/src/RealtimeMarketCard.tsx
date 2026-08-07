import type { RealtimeQuote, RealtimeStreamStatus } from './realtime'

const providerLabels: Record<string, string> = {
  alpaca: 'Alpaca',
  tiingo: 'Tiingo',
  finnhub: 'Finnhub',
  yahoo: 'Yahoo Finance',
  yfinance: 'Yahoo Finance',
}

const sessionLabels: Record<string, string> = {
  pre_market: '盘前',
  premarket: '盘前',
  regular: '常规交易',
  after_hours: '盘后',
  afterhours: '盘后',
  closed: '已休市',
  unknown: '阶段未知',
}

const numberText = (value: number | null, digits = 2): string => value == null || !Number.isFinite(value)
  ? '数据不足'
  : value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })

const volumeText = (value: number | null): string => value == null || !Number.isFinite(value)
  ? '数据不足'
  : value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })

const providerText = (provider: string | null): string => provider ? providerLabels[provider.toLowerCase()] || provider : '数据不足'

function elapsedText(value: string | null): string {
  if (!value) return '时间不足'
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) return '时间格式未知'
  const seconds = Math.max(0, Math.floor((Date.now() - parsed) / 1000))
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  return `${Math.floor(seconds / 3600)} 小时前`
}

function freshnessLabel(quote: RealtimeQuote, streamStatus: RealtimeStreamStatus): { text: string; className: string } {
  if (quote.is_stale === true || (quote.age_seconds != null && quote.age_seconds > 120)) return { text: '数据可能过期', className: 'stale' }
  if (quote.is_delayed === true || (quote.delayed_seconds != null && quote.delayed_seconds > 0)) return { text: '延迟数据', className: 'delayed' }
  if (quote.is_delayed === false && streamStatus === 'connected') return { text: '实时', className: 'live' }
  if (quote.is_delayed === false) return { text: '准实时', className: 'live' }
  return { text: streamStatus === 'connected' ? '时效未知' : '等待行情流', className: 'unknown' }
}

export function RealtimeQuoteProvenance({ quote, streamStatus, lastUpdateAt }: { quote: RealtimeQuote; streamStatus: RealtimeStreamStatus; lastUpdateAt?: string | null }) {
  const freshness = freshnessLabel(quote, streamStatus)
  const reference = quote.reference_price != null
    ? { price: quote.reference_price, provider: quote.reference_provider, feed: quote.reference_feed }
    : quote.alternate_quotes.find(item => item.provider && item.provider !== quote.provider && item.price != null)
  return <div className="realtime-quote-provenance">
    <div><span>Primary</span><b>{providerText(quote.provider)}{quote.feed ? ` · ${quote.feed}` : ''}</b><em className={freshness.className}>{freshness.text}</em></div>
    {reference && <div><span>Reference</span><b>{providerText(reference.provider)}{reference.feed ? ` · ${reference.feed}` : ''} · {numberText(reference.price)}</b></div>}
    <small>行情时点 {quote.timestamp ? new Date(quote.timestamp).toLocaleString('zh-CN', { timeZoneName: 'short' }) : '数据不足'} · 收到 {elapsedText(quote.received_at || lastUpdateAt || null)}</small>
  </div>
}

/** A compact quote card reused by stock details and portfolio position cards. */
export function RealtimeQuoteCard({
  symbol,
  quote,
  streamStatus,
  lastUpdateAt,
  compact = false,
}: {
  symbol: string
  quote?: RealtimeQuote
  streamStatus: RealtimeStreamStatus
  lastUpdateAt?: string | null
  compact?: boolean
}) {
  if (!quote) {
    const statusText = streamStatus === 'error' || streamStatus === 'fallback' ? '实时行情暂不可用，已安全退化到现有行情快照。' : streamStatus === 'connecting' || streamStatus === 'loading' ? '正在建立服务端实时行情流…' : '实时行情数据不足。'
    return <article className={`realtime-quote-card${compact ? ' compact' : ''} unavailable`} aria-label={`${symbol} 实时行情`}>
      <div className="realtime-quote-card-heading"><div><span>REALTIME QUOTE</span><b>{symbol}</b></div><em className="unknown">数据不足</em></div>
      <p>{statusText}</p>
      <small>浏览器只连接项目服务端，不会直接访问 Alpaca 或 Tiingo。</small>
    </article>
  }
  const freshness = freshnessLabel(quote, streamStatus)
  const tone = quote.change_percent == null ? '' : quote.change_percent > 0 ? 'positive' : quote.change_percent < 0 ? 'negative' : ''
  const signedChange = quote.change == null ? '数据不足' : `${quote.change >= 0 ? '+' : ''}${numberText(quote.change)}`
  return <article className={`realtime-quote-card${compact ? ' compact' : ''}`} aria-label={`${symbol} 实时行情`}>
    <header className="realtime-quote-card-heading">
      <div><span>REALTIME QUOTE</span><b>{quote.symbol || symbol}</b></div>
      <em className={freshness.className}>{freshness.text}</em>
    </header>
    <div className="realtime-quote-price-row">
      <strong>{numberText(quote.price)}</strong>
      <div className={tone}><b>{signedChange}</b><span>{quote.change_percent == null ? '数据不足' : `${quote.change_percent >= 0 ? '+' : ''}${quote.change_percent.toFixed(2)}%`}</span></div>
      <span className="realtime-session">{sessionLabels[quote.market_session] || quote.market_session || '阶段未知'}</span>
    </div>
    <dl className="realtime-quote-metrics">
      <div><dt>开盘</dt><dd>{numberText(quote.open)}</dd></div>
      <div><dt>最高</dt><dd>{numberText(quote.high)}</dd></div>
      <div><dt>最低</dt><dd>{numberText(quote.low)}</dd></div>
      <div><dt>前收</dt><dd>{numberText(quote.previous_close)}</dd></div>
      <div><dt>VWAP</dt><dd>{numberText(quote.vwap)}</dd></div>
      <div><dt>成交量</dt><dd>{volumeText(quote.volume)}</dd></div>
    </dl>
    <RealtimeQuoteProvenance quote={quote} streamStatus={streamStatus} lastUpdateAt={lastUpdateAt}/>
  </article>
}
