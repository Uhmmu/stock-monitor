// Apple 风格流体交互物理引擎:弹簧、速度追踪、动量投影、橡皮筋。
// 全部基于「阻尼比 + 响应」这套设计师友好参数,天然可打断、速度感知。

export type SpringConfig = { damping: number; response: number }

// 常用预设(阻尼比 damping / 响应 response 秒)
export const SPRINGS = {
  move: { damping: 1.0, response: 0.4 },     // 位移/重定位(如 PiP)
  rotate: { damping: 0.8, response: 0.4 },   // 旋转
  drawer: { damping: 0.8, response: 0.3 },   // 抽屉/弹窗
  snappy: { damping: 0.9, response: 0.28 },  // 快速吸附
} as const

const REST_DELTA = 0.15   // 位置静止阈值(px)
const REST_SPEED = 0.15   // 速度静止阈值(px/ms)

// 弹簧驱动器:始终从「当前呈现值」运动到 target,可随时改 target 与注入速度。
// 用半隐式欧拉 + 子步长积分,保证高刚度下数值稳定。
export class Spring {
  value: number
  velocity = 0            // px/ms
  target: number
  private k: number       // 刚度
  private c: number       // 阻尼
  constructor(initial: number, cfg: SpringConfig = SPRINGS.move) {
    this.value = initial
    this.target = initial
    const w = (2 * Math.PI) / cfg.response      // 无阻尼角频率 (rad/s)
    this.k = w * w
    this.c = 2 * cfg.damping * w
  }
  setConfig(cfg: SpringConfig) {
    const w = (2 * Math.PI) / cfg.response
    this.k = w * w
    this.c = 2 * cfg.damping * w
  }
  // dt 毫秒。子步长 ≤4ms 保证稳定。返回是否仍在运动。
  step(dtMs: number): boolean {
    let remaining = Math.min(dtMs, 64) / 1000   // 转秒,并夹住长帧
    let v = this.velocity * 1000                // 转 px/s 参与积分
    let x = this.value
    const sub = 0.004
    while (remaining > 0) {
      const h = Math.min(sub, remaining)
      const a = -this.k * (x - this.target) - this.c * v
      v += a * h
      x += v * h
      remaining -= h
    }
    this.value = x
    this.velocity = v / 1000
    if (Math.abs(x - this.target) < REST_DELTA && Math.abs(this.velocity) < REST_SPEED) {
      this.value = this.target
      this.velocity = 0
      return false
    }
    return true
  }
}

// 用 rAF 持续推进弹簧,每帧把当前值交给 onFrame。可随时 stop 中途抓取。
export function animateSpring(
  spring: Spring,
  onFrame: (value: number) => void,
  onRest?: () => void,
): () => void {
  let last = performance.now()
  let raf = 0
  let alive = true
  const tick = (now: number) => {
    if (!alive) return
    const dt = now - last
    last = now
    const moving = spring.step(dt)
    onFrame(spring.value)
    if (moving) raf = requestAnimationFrame(tick)
    else onRest?.()
  }
  raf = requestAnimationFrame(tick)
  return () => { alive = false; cancelAnimationFrame(raf) }
}

// 速度追踪:记录最近的位置/时间戳,释放时算出真实手势速度(px/ms)。
export class VelocityTracker {
  private samples: { t: number; v: number }[] = []
  private readonly window = 100  // 只看最近 100ms
  reset(v: number) { this.samples = [{ t: performance.now(), v }] }
  add(v: number) {
    const t = performance.now()
    this.samples.push({ t, v })
    while (this.samples.length > 2 && t - this.samples[0].t > this.window) this.samples.shift()
  }
  // 用窗口内首尾差分求速度,比逐帧差分更抗抖动
  velocity(): number {
    if (this.samples.length < 2) return 0
    const first = this.samples[0]
    const last = this.samples[this.samples.length - 1]
    const dt = last.t - first.t
    return dt > 0 ? (last.v - first.v) / dt : 0
  }
}

// 动量投影:按释放速度预测惯性最终停点(Apple decelerationRate ≈ 0.998)。
// velocity 单位 px/ms。
export function projectMomentum(position: number, velocity: number, decelerationRate = 0.998): number {
  return position + (velocity * decelerationRate) / (1 - decelerationRate)
}

// 橡皮筋阻力:超出边界时按渐进阻力压缩位移,而非硬停。
// overshoot 为越界量(px),dimension 为容器该轴尺寸。
export function rubberband(overshoot: number, dimension: number, c = 0.55): number {
  const sign = Math.sign(overshoot)
  const o = Math.abs(overshoot)
  return sign * (o * dimension * c) / (dimension + c * o)
}

// 把值夹在 [min,max] 内,越界部分走橡皮筋。
export function clampRubber(value: number, min: number, max: number, dimension: number): number {
  if (value < min) return min + rubberband(value - min, dimension)
  if (value > max) return max + rubberband(value - max, dimension)
  return value
}

// 用户是否请求减弱动态。rAF 弹簧是 JS 驱动,CSS 媒体查询管不到,
// 组件需读这个值把弹簧降级为直接吸附/交叉淡入(skill §14)。
export function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches
}

// 触感反馈:仅在"落定"这类因果明确的时刻调用(skill §13)。
// 桌面/不支持的设备静默降级为无操作。
export function haptic(pattern: number | number[] = 8): void {
  if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
    try { navigator.vibrate(pattern) } catch { /* 某些浏览器需用户手势,忽略 */ }
  }
}
