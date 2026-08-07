import { useRealtimeProviderHealth, type RealtimeProviderHealth } from './realtime'

const labels: Record<string, string> = {
  alpaca: 'Alpaca Market Data',
  tiingo: 'Tiingo Market Data',
  tiingo_news: 'Tiingo News',
  finnhub: 'Finnhub',
  yahoo: 'Yahoo Finance',
  yfinance: 'Yahoo Finance',
  marketaux: 'Marketaux',
}

const order = ['alpaca', 'tiingo', 'tiingo_news', 'finnhub', 'yahoo', 'yfinance', 'marketaux']

function statusLabel(row: RealtimeProviderHealth): { text: string; className: string } {
  const status = row.status?.toLowerCase()
  if (row.connected === true || status === 'healthy' || status === 'connected' || status === 'ok') return { text: '正常', className: 'ok' }
  if (status === 'degraded' || status === 'partial' || status === 'stale' || row.delayed === true) return { text: '部分可用', className: 'warn' }
  if (row.connected === false || status === 'failed' || status === 'error' || status === 'unhealthy') return { text: '不可用', className: 'error' }
  return { text: '状态未知', className: 'unknown' }
}

function displayTime(value: string | null): string {
  if (!value) return '数据不足'
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString('zh-CN', { timeZoneName: 'short' }) : '时间格式未知'
}

export function RealtimeProviderHealthPanel() {
  const health = useRealtimeProviderHealth()
  const rows = [...(health.data || [])].sort((a, b) => {
    const ai = order.indexOf(a.provider.toLowerCase())
    const bi = order.indexOf(b.provider.toLowerCase())
    return (ai < 0 ? 100 : ai) - (bi < 0 ? 100 : bi)
  })
  return <section className="realtime-provider-health settings-card" aria-labelledby="realtime-provider-health-title">
    <div className="section-title"><div><p>MARKET DATA DIAGNOSTICS</p><h2 id="realtime-provider-health-title">盘中数据源状态</h2></div><span>{health.isFetching ? '更新中…' : '服务端状态'}</span></div>
    <p className="realtime-provider-health-note">行情浏览器只通过项目 API/SSE 读取；Alpaca、Tiingo 的密钥不会返回前端。延迟或参考行情会明确标注，不会伪装为实时。</p>
    {health.isError && <div className="realtime-provider-health-error">数据源状态暂时读取失败；不影响现有行情页面。</div>}
    {health.isLoading && !rows.length && <div className="realtime-provider-health-loading">正在读取数据源健康状态…</div>}
    <div className="realtime-provider-health-grid">
      {rows.map((row, index) => {
        const status = statusLabel(row)
        const name = row.label || labels[row.provider.toLowerCase()] || row.provider
        return <article key={`${row.channel || 'market'}-${row.provider}-${row.feed || 'default'}-${row.last_success_at || row.last_message_at || index}`} className={`realtime-provider-health-row ${status.className}`}>
          <div className="realtime-provider-health-title"><span className="realtime-provider-health-dot"/><div><b>{name}</b><small>{row.feed || (row.channel === 'news' || row.provider.toLowerCase().includes('news') ? '新闻' : '行情')}</small></div><em>{status.text}</em></div>
          <dl>
            <div><dt>最后消息</dt><dd>{displayTime(row.last_message_at || row.last_success_at)}</dd></div>
            <div><dt>订阅</dt><dd>{row.subscriptions.length ? row.subscriptions.slice(0, 3).join(', ') : '数据不足'}</dd></div>
            <div><dt>错误</dt><dd>{row.last_error || '无'}</dd></div>
          </dl>
        </article>
      })}
      {!health.isLoading && !rows.length && !health.isError && <div className="realtime-provider-health-empty">后端尚未返回 provider 状态；行情仍会按现有数据源安全退化。</div>}
    </div>
  </section>
}
