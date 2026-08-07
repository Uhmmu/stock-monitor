export type ThemeMode = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'stock-monitor-theme'
export const THEME_EVENT = 'themechange'

const LIGHT_THEME_COLOR = '#f5f5f7'
const DARK_THEME_COLOR = '#000000'

function readStoredTheme(): ThemeMode | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY)
    return value === 'dark' || value === 'light' ? value : null
  } catch {
    return null
  }
}

export function getSystemTheme(): ThemeMode {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function getPreferredTheme(): ThemeMode {
  return readStoredTheme() ?? getSystemTheme()
}

export function getResolvedTheme(): ThemeMode {
  if (typeof document === 'undefined') return 'light'
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr === 'dark' || attr === 'light') return attr
  return getPreferredTheme()
}

function syncMeta(theme: ThemeMode) {
  if (typeof document === 'undefined') return
  const themeColor = theme === 'dark' ? DARK_THEME_COLOR : LIGHT_THEME_COLOR
  const colorScheme = theme === 'dark' ? 'dark' : 'light'
  document.documentElement.style.colorScheme = colorScheme

  const setMeta = (selector: string, content: string, attr = 'content') => {
    const node = document.querySelector(selector)
    if (node) node.setAttribute(attr, content)
  }
  setMeta('meta[name="color-scheme"]', colorScheme)
  setMeta('meta[name="theme-color"]', themeColor)
  setMeta('meta[name="msapplication-TileColor"]', themeColor)
  setMeta(
    'meta[name="apple-mobile-web-app-status-bar-style"]',
    theme === 'dark' ? 'black-translucent' : 'default',
  )
}

export function applyTheme(theme: ThemeMode, { persist = true }: { persist?: boolean } = {}) {
  if (typeof document === 'undefined') return theme
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  root.dataset.theme = theme
  syncMeta(theme)
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      /* ignore quota / private mode */
    }
  }
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { theme } }))
  return theme
}

export function toggleTheme(): ThemeMode {
  return applyTheme(getResolvedTheme() === 'dark' ? 'light' : 'dark')
}

export function initTheme() {
  return applyTheme(getPreferredTheme(), { persist: Boolean(readStoredTheme()) })
}

export function subscribeTheme(listener: (theme: ThemeMode) => void) {
  const onTheme = (event: Event) => {
    const detail = (event as CustomEvent<{ theme?: ThemeMode }>).detail
    listener(detail?.theme === 'dark' || detail?.theme === 'light' ? detail.theme : getResolvedTheme())
  }
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY) {
      const next = getPreferredTheme()
      if (next !== getResolvedTheme()) applyTheme(next, { persist: false })
    }
  }
  const onSystemTheme = () => {
    // A manual choice wins over the OS preference until the user clears it.
    if (readStoredTheme() === null && getSystemTheme() !== getResolvedTheme()) {
      applyTheme(getSystemTheme(), { persist: false })
    }
  }
  const media = typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null
  window.addEventListener(THEME_EVENT, onTheme)
  window.addEventListener('storage', onStorage)
  media?.addEventListener?.('change', onSystemTheme)
  // Safari versions that predate MediaQueryList.addEventListener.
  media?.addListener?.(onSystemTheme)
  return () => {
    window.removeEventListener(THEME_EVENT, onTheme)
    window.removeEventListener('storage', onStorage)
    media?.removeEventListener?.('change', onSystemTheme)
    media?.removeListener?.(onSystemTheme)
  }
}

export function cssVar(name: string, fallback = '') {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** Chart palette derived from current CSS tokens so lightweight-charts track theme. */
export function chartThemeTokens() {
  const dark = getResolvedTheme() === 'dark'
  return {
    theme: dark ? 'dark' as const : 'light' as const,
    text: cssVar('--ink-4', dark ? '#98989d' : '#718096'),
    textStrong: cssVar('--ink-3', dark ? '#aeaeb2' : '#6e6e73'),
    grid: cssVar('--chart-grid', dark ? 'rgba(84,84,88,.28)' : 'rgba(100,116,139,.09)'),
    border: cssVar('--line', dark ? 'rgba(84,84,88,.55)' : 'rgba(100,116,139,.2)'),
    background: cssVar('--chart-bg', dark ? '#10131d' : '#10131d'),
    crosshair: cssVar('--chart-crosshair', dark ? 'rgba(235,235,245,.28)' : 'rgba(232,233,242,.35)'),
    crosshairLabel: cssVar('--chart-crosshair-label', dark ? '#3a3a3c' : '#323848'),
    paneSeparator: cssVar('--chart-pane-separator', dark ? 'rgba(84,84,88,.45)' : 'rgba(137,144,167,.14)'),
    zeroLine: cssVar('--chart-zero', dark ? 'rgba(235,235,245,.28)' : 'rgba(82,96,116,.9)'),
    accent: cssVar('--accent', dark ? '#0a84ff' : '#0071e3'),
    accentSoft: cssVar('--chart-accent-soft', dark ? 'rgba(10,132,255,.28)' : 'rgba(57,123,216,.24)'),
    accentFaint: cssVar('--chart-accent-faint', dark ? 'rgba(10,132,255,.04)' : 'rgba(57,123,216,.025)'),
    down: cssVar('--down', dark ? '#ff453a' : '#ff3b30'),
    downSoft: cssVar('--chart-down-soft', dark ? 'rgba(255,69,58,.08)' : 'rgba(209,96,109,.04)'),
    downFill: cssVar('--chart-down-fill', dark ? 'rgba(255,69,58,.32)' : 'rgba(209,96,109,.30)'),
    candleUp: cssVar('--chart-candle-up', '#53c7a2'),
    candleDown: cssVar('--chart-candle-down', '#ef7186'),
    priceLine: cssVar('--chart-price-line', dark ? 'rgba(245,245,247,.42)' : 'rgba(243,244,250,.42)'),
  }
}
