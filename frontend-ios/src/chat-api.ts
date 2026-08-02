import { api, getToken, post } from '@shared/api'
import type { AIConfig, AIMessage, Conversation, ConversationPage, MessagePage, WebAccessMode } from '@shared/types'

export const getAIConfig = () => api<AIConfig>('/ai/v1/config')
export const listConversations = () => api<ConversationPage>('/ai/v1/conversations?status=active&page=1&limit=40')
export const createConversation = (model: string | null, web_access_mode: WebAccessMode) => post<Conversation>('/ai/v1/conversations', { model, web_access_mode })
export const getMessages = (id: number) => api<MessagePage>(`/ai/v1/conversations/${id}/messages?page=1&limit=80&rich_content=true`)
export const stopGeneration = (id: number) => post<{ stopped: boolean }>(`/ai/v1/conversations/${id}/stop`, {})

export type MobileStreamEvent = { type: string; data: Record<string, unknown> }

export async function streamChatMessage(conversationId: number, body: { message: string; model: string | null; web_access_mode: WebAccessMode; deep_search_confirmed: boolean }, signal: AbortSignal, onEvent: (event: MobileStreamEvent) => void) {
  const token = getToken()
  const response = await fetch(`/api/ai/v1/conversations/${conversationId}/messages`, { method: 'POST', signal, headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify({ ...body, stream: true }) })
  if (!response.ok) {
    let message = '模型服务暂时不可用。'
    try { const payload = await response.json() as { error?: { message?: string } }; message = payload.error?.message || message } catch { /* safe fallback */ }
    throw new Error(message)
  }
  if (!response.body) throw new Error('当前浏览器无法读取流式回答。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const parse = (block: string): MobileStreamEvent | null => {
    let type = ''
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) type = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!type || !data.length) return null
    try { const value = JSON.parse(data.join('\n')); return value && typeof value === 'object' ? { type, data: value as Record<string, unknown> } : null } catch { return null }
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) { const event = parse(buffer.slice(0, boundary)); if (event) onEvent(event); buffer = buffer.slice(boundary + 2); boundary = buffer.indexOf('\n\n') }
    }
    buffer += decoder.decode()
    if (buffer.trim()) { const event = parse(buffer.trim()); if (event) onEvent(event) }
  } finally { reader.releaseLock() }
}

export function temporaryMessage(id: string, conversationId: number, role: 'user' | 'assistant', content: string): AIMessage {
  return { id, conversation_id: conversationId, role, status: role === 'user' ? 'completed' : 'streaming', content, model: null, citations: [], error_message_safe: null, created_at: new Date().toISOString() }
}
