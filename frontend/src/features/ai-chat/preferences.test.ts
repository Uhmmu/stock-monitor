import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AIConfig } from './api'
import { CHAT_PREFERENCE_KEY, loadChatPreference, newestChatPreference, saveChatPreference, validateChatPreference } from './preferences'

const storage = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  clear: () => storage.clear(),
} })

const config = {
  default_model: 'model-default',
  models: [
    { id: 'model-default', label: 'Default', family: 'other', is_default: true, available: true },
    { id: 'model-a', label: 'A', family: 'other', is_default: false, available: true },
  ],
  web_search: { default_mode: 'off', available_modes: ['off', 'search'] },
} as AIConfig

afterEach(() => { localStorage.clear(); vi.useRealTimers() })

describe('chat preferences', () => {
  it('persists the last model and web mode', () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-08-04T00:00:00Z'))
    saveChatPreference('model-a', 'search')
    expect(loadChatPreference()).toEqual({ model: 'model-a', web_access_mode: 'search', updated_at: '2026-08-04T00:00:00.000Z' })
    expect(localStorage.getItem(CHAT_PREFERENCE_KEY)).toContain('model-a')
  })

  it('falls back when a remembered choice is no longer available', () => {
    expect(validateChatPreference({ model: 'removed', web_access_mode: 'deep_high', updated_at: '' }, config)).toEqual({ model: 'model-default', web_access_mode: 'off' })
  })

  it('uses the most recently updated local or server preference', () => {
    const older = { model: 'model-a', web_access_mode: 'off' as const, updated_at: '2026-08-01T00:00:00Z' }
    const newer = { model: 'model-default', web_access_mode: 'search' as const, updated_at: '2026-08-02T00:00:00Z' }
    expect(newestChatPreference(older, newer)).toEqual(newer)
  })
})
