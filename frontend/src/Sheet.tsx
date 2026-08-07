import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Spring, SPRINGS, animateSpring, VelocityTracker,
  projectMomentum, rubberband, prefersReducedMotion, haptic,
} from './motion'

// Apple 风格底部弹窗:
// · 从底部沿同一路径进出(空间一致性)
// · 拖拽 1:1 跟随指针,顶部越界橡皮筋
// · 释放接管手势速度(velocity handoff),按动量投影决定关闭 or 回弹
// · 全程可打断:动画途中可再次抓住
// · 背板毛玻璃随展开进度加深,体现前后级层次
export function Sheet({ open, onClose, title, children, size = 'default' }: {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  size?: 'default' | 'wide'
}) {
  const [mounted, setMounted] = useState(open)
  const panelRef = useRef<HTMLDivElement>(null)
  const scrimRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const spring = useRef<Spring | null>(null)
  const stopAnim = useRef<(() => void) | null>(null)
  const height = useRef(0)
  const dragging = useRef(false)
  const startY = useRef(0)
  const startVal = useRef(0)
  const tracker = useRef(new VelocityTracker())
  const pointerId = useRef<number | null>(null)

  // 把弹簧值(translateY: 0=完全展开, height=移出屏幕)映射到 DOM。
  // 背板不透明度随展开进度变化 —— 越靠近展开越暗,拉出层级纵深。
  const apply = useCallback((y: number) => {
    const h = height.current || 1
    const progress = 1 - Math.min(Math.max(y / h, 0), 1)  // 0→1 展开度
    if (panelRef.current) panelRef.current.style.transform = `translate3d(0,${y}px,0)`
    if (scrimRef.current) scrimRef.current.style.opacity = String(progress)
  }, [])

  const runTo = useCallback((target: number, initialV: number, onDone?: () => void) => {
    stopAnim.current?.()
    const s = spring.current!
    // 减弱动态:不跑位移弹簧,直接落位(CSS 侧把背板做成纯淡入)。skill §14
    if (prefersReducedMotion()) {
      s.value = target
      s.velocity = 0
      apply(target)
      onDone?.()
      return
    }
    s.setConfig(Math.abs(initialV) > 0.01 ? SPRINGS.drawer : SPRINGS.sheet)
    s.target = target
    s.velocity = initialV                 // 速度接管:手势速度直接注入弹簧
    stopAnim.current = animateSpring(s, apply, onDone)
  }, [apply])

  // 挂载/卸载:进出沿同一路径。open 时从屏幕外弹入,关闭时弹出后卸载。
  useEffect(() => {
    if (open) {
      setMounted(true)
      requestAnimationFrame(() => {
        const h = panelRef.current?.offsetHeight || window.innerHeight * 0.9
        height.current = h
        if (!spring.current) spring.current = new Spring(h, SPRINGS.drawer)
        spring.current.value = h
        apply(h)
        runTo(0, 0)   // 弹入到完全展开
      })
    } else if (mounted) {
      runTo(height.current, 0, () => setMounted(false))
    }
  }, [open])  // eslint-disable-line react-hooks/exhaustive-deps

  // 仅当内容已滚到顶部时,下拉手势才拖动弹窗(否则让内容自己滚动)。
  const canDrag = () => (scrollRef.current?.scrollTop ?? 0) <= 0

  const onPointerDown = (e: React.PointerEvent) => {
    if (!canDrag()) return
    stopAnim.current?.()                    // 打断进行中的动画,就地抓住
    dragging.current = true
    pointerId.current = e.pointerId
    startY.current = e.clientY
    startVal.current = spring.current?.value ?? 0
    tracker.current.reset(startVal.current)
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return
    const raw = startVal.current + (e.clientY - startY.current)
    // 顶部(y<0)越界:橡皮筋渐进阻力;向下无上限(可拉出关闭)
    const y = raw < 0 ? rubberband(raw, height.current || window.innerHeight) : raw
    tracker.current.add(y)
    apply(y)
    if (spring.current) spring.current.value = y
  }

  const onPointerUp = () => {
    if (!dragging.current) return
    dragging.current = false
    const y = spring.current?.value ?? 0
    const v = tracker.current.velocity()               // px/ms
    const h = height.current || window.innerHeight
    const projected = projectMomentum(y, v)            // 惯性预测停点
    // 投影超过一半高度、或本就拖过一半 → 关闭;否则回弹到展开
    if (projected > h * 0.5 || y > h * 0.6) { haptic(10); runTo(h, v, onClose) }  // 落定触感(§13)
    else runTo(0, v)
  }

  useEffect(() => () => stopAnim.current?.(), [])
  useEffect(() => {
    if (!mounted || !panelRef.current || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      const next = panelRef.current?.offsetHeight
      if (next) height.current = next
    })
    observer.observe(panelRef.current)
    return () => observer.disconnect()
  }, [mounted])
  useEffect(() => {
    if (!mounted) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') runTo(height.current, 0, onClose)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previous
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [mounted, onClose, runTo])
  if (!mounted) return null

  // 挂到 body 下,避免被祖先的 transform/filter/will-change 困住
  // (那会让 position:fixed 相对该祖先定位,弹窗贴到页面内容底部而非视口底部)。
  return createPortal(
    <div className="sheet-root" role="dialog" aria-modal="true">
      <div className="sheet-scrim" ref={scrimRef} onClick={() => runTo(height.current, 0, onClose)} />
      <div className={`sheet-panel${size === 'wide' ? ' sheet-panel-wide' : ''}`} ref={panelRef}>
        <div
          className="sheet-grip-zone"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div className="sheet-grip" />
          {title && <div className="sheet-title">{title}</div>}
        </div>
        <div className="sheet-scroll" ref={scrollRef}>{children}</div>
      </div>
    </div>,
    document.body,
  )
}
