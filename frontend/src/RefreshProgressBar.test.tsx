import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { REFRESH_BAR_DELAY_MS, RefreshProgressBar, progressVisible } from './RefreshProgressBar'

describe('progressVisible', () => {
  it('stays hidden without fetch activity regardless of elapsed time', () => {
    expect(progressVisible(false, 10_000)).toBe(false)
  })
  it('hides short requests and only shows sustained loading', () => {
    expect(progressVisible(true, REFRESH_BAR_DELAY_MS - 1)).toBe(false)
    expect(progressVisible(true, REFRESH_BAR_DELAY_MS)).toBe(true)
    expect(progressVisible(true, 5_000)).toBe(true)
  })
})

describe('RefreshProgressBar', () => {
  it('renders nothing when no query is in flight', () => {
    const client = new QueryClient()
    const markup = renderToStaticMarkup(<QueryClientProvider client={client}><RefreshProgressBar/></QueryClientProvider>)
    expect(markup).toBe('')
  })
})
