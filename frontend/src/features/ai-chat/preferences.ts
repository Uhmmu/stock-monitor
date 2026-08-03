import type { AIConfig, WebAccessMode } from './api'

export const CHAT_PREFERENCE_KEY = 'stock-monitor:ai-chat-preference:v1'

export type ChatPreference = {
  model: string
  web_access_mode: WebAccessMode
  updated_at: string
}

export function loadChatPreference(): ChatPreference | null {
  try {
    const value = JSON.parse(localStorage.getItem(CHAT_PREFERENCE_KEY) || 'null') as Partial<ChatPreference> | null
    if (!value || typeof value.model !== 'string' || typeof value.web_access_mode !== 'string') return null
    return { model: value.model, web_access_mode: value.web_access_mode as WebAccessMode, updated_at: typeof value.updated_at === 'string' ? value.updated_at : '' }
  } catch {
    return null
  }
}

export function saveChatPreference(model: string, webAccessMode: WebAccessMode): void {
  if (!model) return
  try {
    localStorage.setItem(CHAT_PREFERENCE_KEY, JSON.stringify({ model, web_access_mode: webAccessMode, updated_at: new Date().toISOString() }))
  } catch {
    // Storage can be denied in private/restricted contexts; Chat still works.
  }
}

export function newestChatPreference(...preferences: Array<ChatPreference | null>): ChatPreference | null {
  return preferences.reduce<ChatPreference | null>((newest, preference) => {
    if (!preference) return newest
    if (!newest) return preference
    const preferenceTime = Date.parse(preference.updated_at) || 0
    const newestTime = Date.parse(newest.updated_at) || 0
    return preferenceTime > newestTime ? preference : newest
  }, null)
}

export function validateChatPreference(preference: ChatPreference | null, config: AIConfig): Pick<ChatPreference, 'model' | 'web_access_mode'> {
  const availableModels = new Set(config.models.filter(item => item.available).map(item => item.id))
  const availableModes = new Set(config.web_search.available_modes)
  const defaultModel = availableModels.has(config.default_model) ? config.default_model : config.models.find(item => item.available)?.id || ''
  return {
    model: preference?.model && availableModels.has(preference.model) ? preference.model : defaultModel,
    web_access_mode: preference?.web_access_mode && availableModes.has(preference.web_access_mode) ? preference.web_access_mode : config.web_search.default_mode,
  }
}
