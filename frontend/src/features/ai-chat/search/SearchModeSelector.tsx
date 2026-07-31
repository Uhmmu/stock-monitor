import { useEffect, useRef, useState } from 'react'
import type { WebAccessMode, WebSearchConfig } from './types'
import { SearchModeDescription } from './SearchModeDescription'
import { SEARCH_MODE_COPY } from './searchModes'

export function SearchModeSelector({ mode, config, disabled, onMode }: { mode: WebAccessMode; config: WebSearchConfig; disabled?: boolean; onMode: (mode: WebAccessMode) => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const pointer = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', pointer)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', pointer); document.removeEventListener('keydown', key) }
  }, [open])
  const modes: WebAccessMode[] = config.available_modes.includes('off') ? config.available_modes : ['off', ...config.available_modes]
  return <div className="ai-search-mode-picker" ref={root}>
    <button type="button" className="ai-search-mode-trigger" disabled={disabled} onClick={() => setOpen(value => !value)} aria-haspopup="listbox" aria-expanded={open} aria-label={`联网模式：${SEARCH_MODE_COPY[mode].label}`}><span aria-hidden="true">◎</span><b>{SEARCH_MODE_COPY[mode].label}</b><i aria-hidden="true">⌃</i></button>
    {open && <div className="ai-search-mode-menu" role="listbox" aria-label="选择联网模式">
      <div className="ai-model-menu-heading"><b>联网模式</b><span>费用以 Exa 实际响应为准</span></div>
      {modes.map(value => <button key={value} type="button" role="option" aria-selected={value === mode} className={value === mode ? 'selected' : ''} onClick={() => { onMode(value); setOpen(false) }}><span className="ai-search-radio" aria-hidden="true">{value === mode ? '●' : '○'}</span><SearchModeDescription mode={value} config={config}/><i aria-hidden="true">{value === mode ? '✓' : ''}</i></button>)}
    </div>}
  </div>
}
