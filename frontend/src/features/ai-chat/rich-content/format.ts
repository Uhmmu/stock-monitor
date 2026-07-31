import type { Numeric } from './types'

export function toNumber(value: Numeric | null | undefined): number | null {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function formatNumber(
  value: Numeric | null | undefined,
  maximumFractionDigits = 2,
): string {
  const number = toNumber(value)
  if (number == null) return '数据不足'
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits,
    notation: Math.abs(number) >= 1_000_000 ? 'compact' : 'standard',
  }).format(number)
}

export function formatCurrency(
  value: Numeric | null | undefined,
  currency?: string | null,
): string {
  const number = toNumber(value)
  if (number == null) return '数据不足'
  if (currency && /^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat('zh-CN', {
        style: 'currency',
        currency,
        maximumFractionDigits: 2,
      }).format(number)
    } catch {
      // Fall through to a stable plain-number representation.
    }
  }
  return `${currency && currency !== '—' ? `${currency} ` : ''}${formatNumber(number)}`
}

export function formatPercent(value: Numeric | null | undefined): string {
  const number = toNumber(value)
  return number == null ? '数据不足' : `${number > 0 ? '+' : ''}${formatNumber(number)}%`
}

export function formatDate(value?: string | null, includeTime = false): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 24)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date)
}

export function formatCell(value: unknown, type: string): string {
  if (value == null || value === '') return '—'
  if (type === 'percent') return formatPercent(value as Numeric)
  if (type === 'currency' || type === 'number' || type === 'score') {
    return formatNumber(value as Numeric)
  }
  if (type === 'date') return formatDate(String(value))
  if (typeof value === 'object') return '—'
  return String(value)
}
