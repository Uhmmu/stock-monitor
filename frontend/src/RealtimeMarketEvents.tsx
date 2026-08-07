import type { RealtimeBar, RealtimeMarketEvent } from './realtime'

const eventLabels: Record<string, string> = {
  day_high_breakout: '突破日高',
  day_low_breakdown: '跌破日低',
  rapid_move: '快速波动',
  price_crosses_vwap: '跨越 VWAP',
  percentage_move: '日内大幅波动',
  price_crosses_ma20: '穿越 MA20',
  bollinger_upper_breakout: '突破布林上轨',
  bollinger_lower_breakdown: '跌破布林下轨',
  rsi_cross: 'RSI 穿越阈值',
  macd_crossover: 'MACD 交叉',
  '5m_volume_spike': '5 分钟放量',
  '15m_volume_spike': '15 分钟放量',
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

const providerLabels: Record<string, string> = {
  alpaca: 'Alpaca',
  tiingo: 'Tiingo',
  finnhub: 'Finnhub',
  aggregated: '聚合行情',
}

const finite = (value: number | null): value is number => value != null && Number.isFinite(value)

const numberText = (value: number | null, digits = 2): string => finite(value)
  ? value.toLocaleString('zh-CN', { maximumFractionDigits: digits })
  : '数据不足'

const volumeText = (value: number | null): string => finite(value)
  ? value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
  : '数据不足'

const providerText = (value: string | null): string => value
  ? providerLabels[value.toLowerCase()] || value
  : '数据不足'

const timeText = (value: string | null): string => {
  if (!value) return '时间不足'
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString('zh-CN', { timeZoneName: 'short' }) : '时间格式未知'
}

function eventMessage(event: RealtimeMarketEvent): string {
  const value = numberText(event.value)
  const threshold = numberText(event.threshold)
  const direction = typeof event.metadata.direction === 'string' ? event.metadata.direction : null
  switch (event.event_type) {
    case 'day_high_breakout': return `价格 ${value} 突破前高 ${threshold}`
    case 'day_low_breakdown': return `价格 ${value} 跌破前低 ${threshold}`
    case 'price_crosses_vwap': return `价格 ${value} ${direction === 'above' ? '上穿' : direction === 'below' ? '下穿' : '跨越'} VWAP ${threshold}`
    case 'rapid_move':
    case 'percentage_move': return `区间涨跌 ${finite(event.value) ? `${event.value >= 0 ? '+' : ''}${event.value.toFixed(2)}%` : value}，阈值 ${finite(event.threshold) ? `${event.threshold.toFixed(2)}%` : threshold}`
    case 'price_crosses_ma20': return `价格 ${value} ${direction === 'above' ? '上穿' : direction === 'below' ? '下穿' : '跨越'} MA20 ${threshold}`
    case 'rsi_cross': return `RSI ${value} ${direction === 'above' ? '上穿' : direction === 'below' ? '下穿' : '跨越'} ${threshold}`
    case 'macd_crossover': return `MACD ${direction === 'bullish' ? '金叉' : direction === 'bearish' ? '死叉' : '交叉'}，值 ${value}`
    case '5m_volume_spike':
    case '15m_volume_spike': return `相对同时间基准 ${finite(event.value) ? `${event.value.toFixed(2)}×` : value}，阈值 ${finite(event.threshold) ? `${event.threshold.toFixed(2)}×` : threshold}`
    default: return `当前值 ${value} · 触发阈值 ${threshold}`
  }
}

function severityClass(severity: string): string {
  const value = severity.toLowerCase()
  return value === 'high' || value === 'warning' ? 'high' : value === 'notice' ? 'notice' : 'info'
}

export function RealtimeBarSummary({ bar }: { bar?: RealtimeBar }) {
  return <section className={`realtime-bar-summary${bar ? '' : ' unavailable'}`} aria-label="最新盘中 bar">
    <div className="realtime-bar-summary-heading"><div><small>INTRADAY BAR</small><b>最新 1 分钟行情</b></div><span>{bar ? `${bar.interval} · ${sessionLabels[bar.market_session] || bar.market_session}` : '等待行情流'}</span></div>
    {bar ? <dl>
      <div><dt>收盘</dt><dd>{numberText(bar.close)}</dd></div>
      <div><dt>高 / 低</dt><dd>{numberText(bar.high)} / {numberText(bar.low)}</dd></div>
      <div><dt>VWAP</dt><dd>{numberText(bar.vwap)}</dd></div>
      <div><dt>成交量</dt><dd>{volumeText(bar.volume)}</dd></div>
    </dl> : <p>尚未收到 bar_update；有数据后会显示 1 分钟 OHLC、VWAP 和成交量。</p>}
    {bar && <small className="realtime-bar-summary-meta">{providerText(bar.provider)}{bar.feed ? ` · ${bar.feed}` : ''} · 行情时点 {timeText(bar.timestamp || bar.received_at)}{bar.is_partial ? ' · 当前 bar 尚未收盘' : ''}{bar.is_backfill ? ' · 重连补齐' : ''}</small>}
  </section>
}

export function RealtimeMarketEventList({
  events,
  title = '盘中事件',
  subtitle = '来自服务端实时事件流与已入库事件',
  compact = false,
}: {
  events: RealtimeMarketEvent[]
  title?: string
  subtitle?: string
  compact?: boolean
}) {
  const visible = events.slice(0, compact ? 5 : 8)
  return <section className={`realtime-events${compact ? ' compact' : ''}`} aria-label={title}>
    <div className="realtime-events-heading"><div><small>MARKET EVENTS</small><h3>{title}</h3></div><span>{subtitle}</span></div>
    {visible.length ? <div className="realtime-events-list">{visible.map((event, index) => <article key={`${event.id ?? `${event.symbol}-${event.event_type}-${event.timestamp}`}-${index}`} className={`realtime-event ${severityClass(event.severity)}`}>
      <div className="realtime-event-topline"><b>{event.symbol}</b><strong>{eventLabels[event.event_type] || event.event_type}</strong><em>{event.severity === 'high' ? '高' : event.severity === 'warning' ? '警示' : event.severity === 'notice' ? '提示' : '信息'}</em></div>
      <p>{eventMessage(event)}</p>
      <small className="realtime-event-meta">{timeText(event.timestamp)} · {sessionLabels[event.market_session] || event.market_session} · {providerText(event.provider)}{event.feed ? ` · ${event.feed}` : ''}</small>
    </article>)}</div> : <div className="realtime-events-empty">暂未发现已确认的盘中事件；缺少基准数据时不会猜测或生成事件。</div>}
  </section>
}
