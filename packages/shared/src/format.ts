export function formatMoney(value: number | null | undefined, currency = 'USD') {
  if (value == null || !Number.isFinite(value)) return '数据不足'
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency, maximumFractionDigits: 2 }).format(value)
  } catch {
    return `${currency} ${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  }
}

export function formatPercent(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

export function stockChange(price: number | null, previousClose: number | null) {
  return price != null && previousClose ? ((price - previousClose) / previousClose) * 100 : null
}
