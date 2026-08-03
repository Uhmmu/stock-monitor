import { KeyboardEvent, useEffect, useRef } from 'react'
import { SearchModeSelector } from '../search/SearchModeSelector'
import type { AIModelOption, WebAccessMode, WebSearchConfig } from '../api'

const MAX_CHARS = 12000

// Kept as a re-export for callers that used the composer module as the model utility.
export { groupModels } from './ModelSelector'

export function MessageComposer({ value, onChange, onSend, onStop, generating, stopping, disabled, webMode = 'off', webSearchConfig, onWebMode, stopLabel = '停止', symbol, pageContext, onRemoveSymbol }: {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  generating: boolean
  stopping: boolean
  disabled?: boolean
  /** @deprecated Model selection is anchored in the Chat header. */
  model?: string
  /** @deprecated Model selection is anchored in the Chat header. */
  models?: AIModelOption[]
  /** @deprecated Model selection is anchored in the Chat header. */
  onModel?: (model: string) => void
  webMode?: WebAccessMode
  webSearchConfig?: WebSearchConfig
  onWebMode?: (mode: WebAccessMode) => void
  stopLabel?: string
  symbol: string | null
  pageContext: string | null
  onRemoveSymbol: () => void
}) {
  const textarea = useRef<HTMLTextAreaElement>(null)
  const composing = useRef(false)

  useEffect(() => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`
  }, [value])

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Escape' && generating) { event.preventDefault(); onStop(); return }
    if (event.key === 'Enter' && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing) {
      event.preventDefault()
      if (value.trim() && value.length <= MAX_CHARS && !generating && !disabled) onSend()
    }
  }
  const contextLabel: Record<string, string> = { company: '公司页', portfolio: '持仓', valuation: '估值页', technical: '技术页', news: '新闻页', calendar: '日历' }
  return <div className="ai-composer-shell">
    {(symbol || pageContext) && <div className="ai-composer-meta">
      <div className="ai-context-chips">
        {symbol && <span>{symbol}<button type="button" onClick={onRemoveSymbol} aria-label={`移除 ${symbol} 上下文`}>×</button></span>}
        {pageContext && <span>{contextLabel[pageContext] || pageContext}</span>}
      </div>
    </div>}
    <div className="ai-composer">
      <label className="sr-only" htmlFor="ai-message-input">输入研究问题</label>
      <textarea
        id="ai-message-input"
        ref={textarea}
        value={value}
        maxLength={MAX_CHARS}
        onChange={event => onChange(event.target.value)}
        onKeyDown={keyDown}
        onCompositionStart={() => { composing.current = true }}
        onCompositionEnd={() => { composing.current = false }}
        placeholder="结合已存研究数据提问…"
        disabled={disabled}
        rows={1}
      />
      {webSearchConfig && onWebMode && <SearchModeSelector mode={webMode} config={webSearchConfig} disabled={generating} onMode={onWebMode}/>} 
      {generating ? <button type="button" className="ai-stop-btn" onClick={onStop} disabled={stopping} aria-label={stopLabel}><i/>{stopping ? '停止中' : stopLabel}</button> : <button type="button" className="ai-send-btn" onClick={onSend} disabled={disabled || !value.trim() || value.length > MAX_CHARS} aria-label="发送消息">↑</button>}
    </div>
    <div className="ai-composer-foot"><span>Enter 发送 · Shift+Enter 换行</span>{value.length >= 10000 && <b className={value.length >= MAX_CHARS ? 'limit' : ''}>{value.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}</b>}</div>
  </div>
}
