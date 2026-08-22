import { describe, expect, it } from 'vitest'
import { appHref, appPath, isAppleDesignPath } from './appRoute'

describe('apple design route context', () => {
  it('keeps legacy routes unchanged and prefixes Apple deep links', () => {
    expect(isAppleDesignPath('/appledesigner')).toBe(false)
    expect(appPath('/appledesign/ai/42')).toBe('/ai/42')
    expect(appHref('/investment-decisions/7', '/appledesign')).toBe('/appledesign/investment-decisions/7')
    expect(appHref('/ai/new', '/')).toBe('/ai/new')
  })
})
