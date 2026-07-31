import { ReactNode, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

export function ChatDialog({ open, title, children, onClose, className = '' }: {
  open: boolean
  title: string
  children: ReactNode
  onClose: () => void
  className?: string
}) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const element = panel.current
    const focusable = () => Array.from(element?.querySelectorAll<HTMLElement>('button,[href],input,textarea,select,[tabindex]:not([tabindex="-1"])') || [])
    focusable()[0]?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab') return
      const values = focusable()
      if (!values.length) return
      const first = values[0]
      const last = values[values.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => { document.removeEventListener('keydown', onKeyDown); previous?.focus() }
  }, [open, onClose])
  if (!open) return null
  return createPortal(<div className={`ai-dialog-root ${className}`}>
    <button className="ai-dialog-scrim" onClick={onClose} aria-label="关闭弹层"/>
    <div className="ai-dialog-panel" ref={panel} role="dialog" aria-modal="true" aria-labelledby="ai-dialog-title">
      <div className="ai-dialog-heading"><h2 id="ai-dialog-title">{title}</h2><button onClick={onClose} aria-label="关闭">×</button></div>
      {children}
    </div>
  </div>, document.body)
}
