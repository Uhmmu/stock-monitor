import { describe, expect, it } from 'vitest'
import { providerValuesDiffer } from './financialComparison'

describe('providerValuesDiffer',()=>{
  it('marks material provider differences without flagging rounding noise or missing data',()=>{
    expect(providerValuesDiffer(100,102)).toBe(true)
    expect(providerValuesDiffer(100,100.5)).toBe(false)
    expect(providerValuesDiffer(100,null)).toBe(false)
  })
})
