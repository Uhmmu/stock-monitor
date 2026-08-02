import { describe, expect, it } from 'vitest'
import { initialNavigation, navigationReducer } from './navigation'

describe('iOS navigation stack', () => {
  it('clears details when switching root tabs', () => {
    const detail = navigationReducer(initialNavigation, { type: 'push', route: { kind: 'stock', id: 'AAPL' } })
    expect(navigationReducer(detail, { type: 'tab', tab: 'chat' })).toEqual({ tab: 'chat', stack: [] })
  })
  it('returns through details one level at a time', () => {
    const first = navigationReducer(initialNavigation, { type: 'push', route: { kind: 'reports' } })
    const second = navigationReducer(first, { type: 'push', route: { kind: 'stock', id: 'NVDA' } })
    expect(navigationReducer(second, { type: 'back' }).stack).toEqual([{ kind: 'reports' }])
  })
})
