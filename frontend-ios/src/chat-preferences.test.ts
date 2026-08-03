import { afterEach, describe, expect, it } from 'vitest'
import type { AIConfig } from '@shared/types'
import { CHAT_PREFERENCE_KEY, loadChatPreference, newestChatPreference, saveChatPreference, validateChatPreference } from './chat-preferences'

const storage = new Map<string, string>()
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  clear: () => storage.clear(),
} })

const config = { default_model: 'default', models: [{ id: 'default', label: 'Default', family: 'other', is_default: true, available: true }, { id: 'a', label: 'A', family: 'other', is_default: false, available: true }], web_search: { default_mode: 'off', available_modes: ['off', 'search'] } } as AIConfig

afterEach(() => localStorage.clear())

describe('mobile chat preferences', () => {
  it('uses the same persisted preference contract as desktop', () => {
    saveChatPreference('a', 'search')
    expect(loadChatPreference()?.model).toBe('a')
    expect(localStorage.getItem(CHAT_PREFERENCE_KEY)).toContain('search')
  })

  it('validates removed choices against current configuration', () => {
    expect(validateChatPreference({ model: 'removed', web_access_mode: 'deep_high', updated_at: '' }, config)).toEqual({ model: 'default', web_access_mode: 'off' })
  })

  it('uses the most recently updated local or server preference', () => {
    const older = { model: 'a', web_access_mode: 'off' as const, updated_at: '2026-08-01T00:00:00Z' }
    const newer = { model: 'default', web_access_mode: 'search' as const, updated_at: '2026-08-02T00:00:00Z' }
    expect(newestChatPreference(older, newer)).toEqual(newer)
  })
})
