import { useEffect, useState } from 'react'
import { getResolvedTheme, subscribeTheme, toggleTheme, type ThemeMode } from './theme'

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4.25" />
      <path d="M12 2.75v2.1M12 19.15v2.1M2.75 12h2.1M19.15 12h2.1M5.34 5.34l1.48 1.48M17.18 17.18l1.48 1.48M18.66 5.34l-1.48 1.48M6.82 17.18l-1.48 1.48" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.2 14.35A7.85 7.85 0 0 1 9.65 3.8 8.7 8.7 0 1 0 20.2 14.35Z" />
    </svg>
  )
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const [theme, setTheme] = useState<ThemeMode>(() => getResolvedTheme())

  useEffect(() => subscribeTheme(setTheme), [])

  const next = theme === 'dark' ? 'light' : 'dark'
  const label = theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'

  return (
    <button
      type="button"
      className={`theme-toggle ${theme}${className ? ` ${className}` : ''}`}
      onClick={() => setTheme(toggleTheme())}
      aria-label={label}
      title={label}
      aria-pressed={theme === 'dark'}
      data-theme-next={next}
    >
      <span className="theme-toggle-track" aria-hidden="true">
        <span className="theme-toggle-thumb">
          {theme === 'dark' ? <MoonIcon /> : <SunIcon />}
        </span>
        <i className="theme-toggle-glyph sun"><SunIcon /></i>
        <i className="theme-toggle-glyph moon"><MoonIcon /></i>
      </span>
    </button>
  )
}
