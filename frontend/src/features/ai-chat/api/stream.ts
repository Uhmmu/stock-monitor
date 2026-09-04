import { getToken } from '../../../api'
import type { AIErrorPayload, AIStreamEvent, MessageCreateRequest } from './types'

const KNOWN_EVENTS = new Set([
  'conversation.started', 'message.created', 'response.started', 'context.ready',
  'model.switched', 'tool.planning',
  'tool.started', 'tool.completed', 'tool.failed', 'response.delta', 'response.reset', 'citation.map',
  'response.block.created', 'response.block.completed', 'response.rich_content.completed',
  'message.persisted', 'response.completed', 'error',
  'deep_search.created', 'deep_search.queued', 'deep_search.started', 'deep_search.progress',
  'deep_search.completed', 'deep_search.failed', 'deep_search.cancelled', 'deep_search.cost',
])
const TERMINAL_EVENTS = new Set(['response.completed', 'error'])

export class AIAPIError extends Error {
  code: string
  retryable: boolean
  status: number
  constructor(message: string, code = 'AI_NETWORK_ERROR', status = 0, retryable = false) {
    super(message)
    this.name = 'AIAPIError'
    this.code = code
    this.status = status
    this.retryable = retryable
  }
}

export async function* parseSSEChunks(chunks: AsyncIterable<Uint8Array | string>): AsyncGenerator<AIStreamEvent> {
  const decoder = new TextDecoder()
  let buffer = ''
  const parseBlock = (block: string): AIStreamEvent | null => {
    let eventName = 'message'
    const dataLines: string[] = []
    for (const rawLine of block.split(/\r?\n/)) {
      const line = rawLine.replace(/\r$/, '')
      if (!line || line.startsWith(':')) continue
      const index = line.indexOf(':')
      const field = index < 0 ? line : line.slice(0, index)
      const value = index < 0 ? '' : line.slice(index + 1).replace(/^ /, '')
      if (field === 'event') eventName = value
      if (field === 'data') dataLines.push(value)
    }
    if (!KNOWN_EVENTS.has(eventName) || !dataLines.length) {
      return null
    }
    try {
      const data: unknown = JSON.parse(dataLines.join('\n'))
      if (!data || typeof data !== 'object' || Array.isArray(data)) return null
      return { type: eventName, data } as AIStreamEvent
    } catch {
      return null
    }
  }

  for await (const chunk of chunks) {
    buffer += typeof chunk === 'string' ? chunk : decoder.decode(chunk, { stream: true })
    buffer = buffer.replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const event = parseBlock(block)
      if (event) yield event
      boundary = buffer.indexOf('\n\n')
    }
  }
  buffer += decoder.decode()
  const trailing = parseBlock(buffer.trim())
  if (trailing) yield trailing
}

async function* responseChunks(response: Response): AsyncGenerator<Uint8Array> {
  if (!response.body) throw new AIAPIError('浏览器无法读取流式回答。', 'AI_STREAM_UNAVAILABLE', response.status)
  const reader = response.body.getReader()
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      if (value) yield value
    }
  } finally {
    reader.releaseLock()
  }
}

async function parseFailedResponse(response: Response): Promise<AIAPIError> {
  let payload: AIErrorPayload | null = null
  try { payload = await response.json() as AIErrorPayload } catch { /* safe fallback below */ }
  if (response.status === 401) {
    localStorage.removeItem('auth_token')
    sessionStorage.removeItem('auth_token')
    window.dispatchEvent(new Event('auth:logout'))
    return new AIAPIError('登录状态已过期，请重新登录。', 'AI_AUTH_EXPIRED', 401)
  }
  return new AIAPIError(
    payload?.error?.message || '模型服务暂时不可用，请稍后重试。',
    payload?.error?.code || 'AI_REQUEST_FAILED',
    response.status,
    Boolean(payload?.error?.retryable),
  )
}

async function* streamEndpoint(path: string, body: unknown, signal: AbortSignal): AsyncGenerator<AIStreamEvent> {
  const token = getToken()
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw await parseFailedResponse(response)
  let terminal = false
  for await (const event of parseSSEChunks(responseChunks(response))) {
    if (terminal) break
    yield event
    if (TERMINAL_EVENTS.has(event.type)) terminal = true
  }
  if (!terminal && !signal.aborted) throw new AIAPIError('回答连接已中断，已保留服务端状态。', 'AI_STREAM_INTERRUPTED', response.status, true)
}

export function streamMessage(conversationId: number, body: MessageCreateRequest, signal: AbortSignal) {
  return streamEndpoint(`/ai/v1/conversations/${conversationId}/messages`, { ...body, stream: true }, signal)
}

export function streamRegenerate(conversationId: number, messageId: number, body: { model?: string | null; web_access_mode?: import('./types').WebAccessMode; deep_search_confirmed?: boolean }, signal: AbortSignal) {
  return streamEndpoint(`/ai/v1/conversations/${conversationId}/messages/${messageId}/regenerate`, { ...body, stream: true }, signal)
}
