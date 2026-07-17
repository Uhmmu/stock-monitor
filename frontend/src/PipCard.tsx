import { ReactNode, useCallback, useEffect, useRef } from 'react'
import {
  Spring, SPRINGS, animateSpring, VelocityTracker,
  projectMomentum, clampRubber, prefersReducedMotion, haptic,
} from './motion'

// Apple 画中画式可拖拽浮卡:
// · 双轴 1:1 跟随指针(保留抓取偏移,不吸附中心)
// · 越界橡皮筋回弹
// · 释放接管速度 → 动量投影预测落点 → 吸附到最近的左/右边缘
// · 全程可打断
const MARGIN = 16      // 距视口边距
const THRESHOLD = 8    // 拖拽起始阈值(hysteresis)

export function PipCard({ children }: { children: ReactNode }) {
  const el = useRef<HTMLDivElement>(null)
  const sx = useRef<Spring | null>(null)
  const sy = useRef<Spring | null>(null)
  const stopX = useRef<(() => void) | null>(null)
  const stopY = useRef<(() => void) | null>(null)
  const tx = useRef(new VelocityTracker())
  const ty = useRef(new VelocityTracker())
  const grab = useRef({ x: 0, y: 0 })     // 抓取时指针相对卡片左上角偏移
  const start = useRef({ x: 0, y: 0 })
  const pos = useRef({ x: 0, y: 0 })      // 当前左上角坐标
  const moved = useRef(false)
  const dragging = useRef(false)

  const bounds = useCallback(() => {
    const w = el.current?.offsetWidth ?? 0
    const h = el.current?.offsetHeight ?? 0
    return {
      minX: MARGIN, maxX: window.innerWidth - w - MARGIN,
      minY: MARGIN, maxY: window.innerHeight - h - MARGIN,
    }
  }, [])

  const draw = useCallback(() => {
    if (el.current) el.current.style.transform =
      `translate3d(${pos.current.x}px,${pos.current.y}px,0)`
  }, [])

  // 初始定位到右下角
  useEffect(() => {
    const b = bounds()
    pos.current = { x: b.maxX, y: b.maxY }
    sx.current = new Spring(b.maxX, SPRINGS.move)
    sy.current = new Spring(b.maxY, SPRINGS.move)
    draw()
    const onResize = () => {
      const nb = bounds()
      pos.current.x = Math.min(Math.max(pos.current.x, nb.minX), nb.maxX)
      pos.current.y = Math.min(Math.max(pos.current.y, nb.minY), nb.maxY)
      draw()
    }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); stopX.current?.(); stopY.current?.() }
  }, [bounds, draw])

  const onPointerDown = (e: React.PointerEvent) => {
    stopX.current?.(); stopY.current?.()          // 打断动画,就地抓住
    dragging.current = true
    moved.current = false
    start.current = { x: e.clientX, y: e.clientY }
    grab.current = { x: e.clientX - pos.current.x, y: e.clientY - pos.current.y }
    tx.current.reset(pos.current.x)
    ty.current.reset(pos.current.y)
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return
    if (!moved.current) {
      const d = Math.hypot(e.clientX - start.current.x, e.clientY - start.current.y)
      if (d < THRESHOLD) return                    // 阈值前不动,区分点击
      moved.current = true
      el.current?.classList.add('dragging')
    }
    const b = bounds()
    // 保留抓取偏移;越界走橡皮筋
    pos.current.x = clampRubber(e.clientX - grab.current.x, b.minX, b.maxX, window.innerWidth)
    pos.current.y = clampRubber(e.clientY - grab.current.y, b.minY, b.maxY, window.innerHeight)
    tx.current.add(pos.current.x)
    ty.current.add(pos.current.y)
    draw()
  }

  const settle = useCallback((axis: 'x' | 'y', target: number, v: number) => {
    const s = (axis === 'x' ? sx : sy).current!
    const stopper = axis === 'x' ? stopX : stopY
    stopper.current?.()
    // 减弱动态:不跑吸附弹簧,直接落到目标边缘。skill §14
    if (prefersReducedMotion()) {
      s.value = target; s.velocity = 0
      pos.current[axis] = target; draw()
      return
    }
    s.value = pos.current[axis]
    s.target = target
    s.velocity = v                                 // 速度接管
    const onFrame = (val: number) => { pos.current[axis] = val; draw() }
    stopper.current = animateSpring(s, onFrame)
  }, [draw])

  const onPointerUp = () => {
    if (!dragging.current) return
    dragging.current = false
    el.current?.classList.remove('dragging')
    if (!moved.current) return                      // 视为点击,不做物理
    const b = bounds()
    const vx = tx.current.velocity()
    const vy = ty.current.velocity()
    // 先按动量投影预测水平落点,再吸附到最近的左/右边缘
    const projX = projectMomentum(pos.current.x, vx)
    const mid = (b.minX + b.maxX) / 2
    haptic(6)                                       // 吸附到边缘的落定触感(§13)
    settle('x', projX < mid ? b.minX : b.maxX, vx)
    // 纵向:投影落点夹回边界内
    const projY = Math.min(Math.max(projectMomentum(pos.current.y, vy), b.minY), b.maxY)
    settle('y', projY, vy)
  }

  return (
    <div
      className="pip-card"
      ref={el}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {children}
    </div>
  )
}
