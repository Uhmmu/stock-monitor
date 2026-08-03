import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AIAPIError,
  conversationKeys,
  createConversation,
  stopGeneration,
  streamMessage,
  streamRegenerate,
  type AIMessage,
  type AIStreamEvent,
  type ConversationCreateRequest,
  type MessageCreateRequest,
  type ToolActivity,
  type WebAccessMode,
} from '../api'

export type StreamState = 'idle' | 'creating_conversation' | 'connecting' | 'streaming' | 'stopping' | 'completed' | 'partial' | 'failed' | 'cancelled'

const now = () => new Date().toISOString()
const temporaryMessage = (id: string, conversationId: number, role: 'user' | 'assistant', content: string, status: AIMessage['status'], parent: number | null = null, generation = 1): AIMessage => ({
  id, conversation_id: conversationId, role, status, content, content_format: role === 'user' ? 'plain_text' : 'markdown',
  content_schema_version: null, content_parts: null, rich_block_skeletons: [],
  parent_message_id: parent, reply_to_message_id: parent, regenerated_from_message_id: null, generation_index: generation,
  model: null, input_tokens: 0, output_tokens: 0, total_tokens: 0, tool_call_count: 0, citation_count: 0,
  web_access_mode: 'off', external_search_call_count: 0, deep_search_run_id: null, external_search_cost_usd: null,
  error_code: null, error_message_safe: null, has_partial_content: false, citations: [], tool_calls: [],
  created_at: now(), started_at: null, completed_at: null, cancelled_at: null, updated_at: now(),
})

function friendlyError(error: unknown): string {
  if (error instanceof AIAPIError) {
    const messages: Record<string, string> = {
      AI_PROVIDER_UNAVAILABLE: '模型服务暂时不可用，请稍后重试。',
      AI_PROVIDER_RATE_LIMITED: '模型服务当前请求较多，请稍后重试。',
      AI_CONVERSATION_BUSY: '当前会话正在生成另一条回答。',
      AI_CONVERSATION_NOT_FOUND: '该会话不存在或已不可访问。',
      AI_CONVERSATION_DELETED: '该会话已被删除。',
      AI_CONTEXT_TOO_LARGE: '当前问题与历史上下文过长，请精简后重试。',
      AI_TOOL_BUDGET_EXCEEDED: '研究数据读取已达到本轮上限，已保留可用内容。',
      WEB_SEARCH_PROVIDER_NOT_CONFIGURED: '联网搜索尚未配置，请切换为不联网后重试。',
      WEB_SEARCH_BUDGET_EXCEEDED: '本轮联网搜索预算已用完。',
      DEEP_SEARCH_BUDGET_EXCEEDED: 'Deep Search 预算或今日额度已用完。',
      DEEP_SEARCH_CONFIRMATION_REQUIRED: '该 Deep Search 档位需要先确认参考费用。',
    }
    return messages[error.code] || error.message || '模型服务暂时不可用，请稍后重试。'
  }
  return '网络连接异常，请稍后重试。'
}

export function useAIStream({ conversationId, onConversationCreated }: {
  conversationId: number | null
  onConversationCreated: (id: number) => void
}) {
  const client = useQueryClient()
  const [state, setState] = useState<StreamState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [localMessages, setLocalMessages] = useState<AIMessage[]>([])
  const [activities, setActivities] = useState<Record<string, ToolActivity[]>>({})
  const [deepRunId, setDeepRunId] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  const activeConversation = useRef<number | null>(null)
  const activeAssistant = useRef<string | number | null>(null)
  const busy = useRef(false)
  const delta = useRef('')
  const deltaTimer = useRef<number | null>(null)

  const flushDelta = useCallback(() => {
    if (deltaTimer.current != null) window.clearTimeout(deltaTimer.current)
    deltaTimer.current = null
    const value = delta.current
    delta.current = ''
    const id = activeAssistant.current
    if (!value || id == null) return
    setLocalMessages(items => items.map(item => item.id === id ? { ...item, content: item.content + value, status: 'streaming', updated_at: now() } : item))
  }, [])

  const scheduleDelta = useCallback((value: string) => {
    delta.current += value
    if (deltaTimer.current == null) deltaTimer.current = window.setTimeout(flushDelta, 32)
  }, [flushDelta])

  const updateActivity = useCallback((event: AIStreamEvent) => {
    if (!event.type.startsWith('tool.') || activeAssistant.current == null) return
    const data = event.data as { tool_call_id: string; display_name?: string; returned_item_count?: number | null; summary?: string | null }
    const key = String(activeAssistant.current)
    const status = event.type === 'tool.started' ? 'running' : event.type === 'tool.failed' ? 'failed' : 'completed'
    setActivities(values => {
      const items = values[key] || []
      const next: ToolActivity = { tool_call_id: data.tool_call_id, display_name: data.display_name || '读取研究数据', status, returned_item_count: data.returned_item_count, summary: data.summary }
      return { ...values, [key]: items.some(item => item.tool_call_id === next.tool_call_id) ? items.map(item => item.tool_call_id === next.tool_call_id ? next : item) : [...items, next] }
    })
  }, [])

  const consume = useCallback(async (source: AsyncIterable<AIStreamEvent>, signal: AbortSignal) => {
    let terminal = false
    for await (const event of source) {
      if (signal.aborted || terminal) break
      updateActivity(event)
      if (event.type === 'conversation.started') {
        activeConversation.current = event.data.conversation_id
        activeAssistant.current = event.data.assistant_message_id
      } else if (event.type === 'message.created') {
        activeAssistant.current = event.data.assistant_message.id
        setLocalMessages(items => {
          const withoutTemps = items.filter(item => !String(item.id).startsWith('temp-'))
          const ids = new Set(withoutTemps.map(item => String(item.id)))
          return [...withoutTemps, ...[event.data.user_message, event.data.assistant_message].filter(item => !ids.has(String(item.id)))]
        })
      } else if (event.type === 'response.started') {
        setState('streaming')
      } else if (event.type === 'response.delta') {
        scheduleDelta(event.data.delta)
      } else if (event.type === 'response.reset') {
        flushDelta()
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === id ? { ...item, content: '' } : item))
      } else if (event.type === 'citation.map' && activeAssistant.current != null) {
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === id ? { ...item, citations: event.data.citations, citation_count: event.data.citations.length } : item))
      } else if (event.type === 'response.block.created' && activeAssistant.current != null) {
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => {
          if (item.id !== id) return item
          const skeletons = item.rich_block_skeletons || []
          return skeletons.some(block => block.block_id === event.data.block_id)
            ? item
            : { ...item, rich_block_skeletons: [...skeletons, event.data] }
        }))
      } else if (event.type === 'response.rich_content.completed' && activeAssistant.current != null) {
        flushDelta()
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === id ? {
          ...item,
          content: event.data.fallback_markdown,
          content_format: 'rich_markdown',
          content_schema_version: event.data.schema_version,
          content_parts: event.data,
          rich_block_skeletons: [],
        } : item))
      } else if (event.type.startsWith('deep_search.')) {
        const data = event.data as { run_id?: string | null }
        if (data.run_id) setDeepRunId(data.run_id)
      } else if (event.type === 'message.persisted' && activeAssistant.current != null) {
        flushDelta()
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === id ? { ...item, status: event.data.status } : item))
      } else if (event.type === 'response.completed') {
        flushDelta()
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === id ? {
          ...item,
          content: event.data.answer || item.content,
          content_format: event.data.rich_content ? 'rich_markdown' : item.content_format,
          content_schema_version: event.data.rich_content?.schema_version ?? item.content_schema_version,
          content_parts: event.data.rich_content ?? item.content_parts,
          rich_block_skeletons: [],
          status: event.data.status,
        } : item))
        setState(event.data.status === 'partial' ? 'partial' : 'completed')
        terminal = true
      } else if (event.type === 'error') {
        flushDelta()
        const id = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === id ? { ...item, status: item.content ? 'partial' : 'failed', error_code: event.data.code, error_message_safe: event.data.message } : item))
        setError(friendlyError(new AIAPIError(event.data.message, event.data.code, 0, event.data.retryable)))
        setState('failed')
        terminal = true
      }
    }
  }, [flushDelta, scheduleDelta, updateActivity])

  const finalizeRequest = useCallback(async (id: number) => {
    await Promise.all([
      client.invalidateQueries({ queryKey: conversationKeys.messages(id) }),
      client.invalidateQueries({ queryKey: conversationKeys.detail(id) }),
      client.invalidateQueries({ queryKey: conversationKeys.all }),
    ])
  }, [client])

  const run = useCallback(async (id: number, source: (signal: AbortSignal) => AsyncIterable<AIStreamEvent>) => {
    controller.current = new AbortController()
    activeConversation.current = id
    setState('connecting')
    setError(null)
    try {
      await consume(source(controller.current.signal), controller.current.signal)
    } catch (caught) {
      if (!controller.current.signal.aborted) {
        setError(friendlyError(caught))
        setState('failed')
        const assistantId = activeAssistant.current
        setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, status: item.content ? 'partial' : 'failed' } : item))
      }
    } finally {
      await finalizeRequest(id)
      busy.current = false
      controller.current = null
    }
  }, [consume, finalizeRequest])

  const send = useCallback(async (question: string, context: ConversationCreateRequest) => {
    if (busy.current || !question.trim()) return
    busy.current = true
    let id = conversationId
    try {
      if (id == null) {
        setState('creating_conversation')
        const { deep_search_confirmed: _confirmation, ...conversationContext } = context
        const created = await createConversation(conversationContext)
        id = created.id
        onConversationCreated(id)
      }
      const stamp = Date.now()
      const userTemp = temporaryMessage(`temp-user-${stamp}`, id, 'user', question.trim(), 'completed')
      const assistantTemp = temporaryMessage(`temp-assistant-${stamp}`, id, 'assistant', '', 'pending')
      activeAssistant.current = assistantTemp.id
      setLocalMessages(items => [...items, userTemp, assistantTemp])
      await run(id, signal => streamMessage(id!, {
        message: question.trim(),
        active_symbol: context.active_symbol,
        active_symbols: context.active_symbols,
        active_portfolio_id: context.active_portfolio_id,
        page_context: context.page_context,
        model: context.model,
        web_access_mode: context.web_access_mode,
        deep_search_confirmed: Boolean((context as ConversationCreateRequest & { deep_search_confirmed?: boolean }).deep_search_confirmed),
        stream: true,
      }, signal))
    } catch (caught) {
      busy.current = false
      setState('failed')
      setError(friendlyError(caught))
    }
  }, [conversationId, onConversationCreated, run])

  const regenerate = useCallback(async (message: AIMessage, model: string | null, webAccessMode: WebAccessMode = message.web_access_mode, deepSearchConfirmed = false) => {
    if (busy.current || conversationId == null || typeof message.id !== 'number') return
    busy.current = true
    const temp = temporaryMessage(`temp-assistant-${Date.now()}`, conversationId, 'assistant', '', 'pending', message.parent_message_id, message.generation_index + 1)
    activeAssistant.current = temp.id
    setLocalMessages(items => [...items, temp])
    await run(conversationId, signal => streamRegenerate(conversationId, message.id as number, { model, web_access_mode: webAccessMode, deep_search_confirmed: deepSearchConfirmed }, signal))
  }, [conversationId, run])

  const stop = useCallback(async () => {
    const id = activeConversation.current
    if (id == null || state === 'stopping') return
    setState('stopping')
    controller.current?.abort()
    try { await stopGeneration(id) } catch { /* a completed race is harmless */ }
    flushDelta()
    const assistantId = activeAssistant.current
    setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, status: 'cancelled', cancelled_at: now(), has_partial_content: Boolean(item.content) } : item))
    setState('cancelled')
    busy.current = false
    await finalizeRequest(id)
  }, [finalizeRequest, flushDelta, state])

  const clearPersisted = useCallback((serverIds: Set<string>) => {
    setLocalMessages(items => {
      const next = items.filter(item => !serverIds.has(String(item.id)))
      return next.length === items.length ? items : next
    })
  }, [])

  useEffect(() => () => {
    if (!busy.current) return
    const id = activeConversation.current
    controller.current?.abort()
    if (id != null) void stopGeneration(id).catch(() => undefined)
  }, [])

  return { state, error, localMessages, activities, deepRunId, send, regenerate, stop, clearPersisted, setError }
}
