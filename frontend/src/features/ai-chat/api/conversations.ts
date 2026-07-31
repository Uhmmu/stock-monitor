import { api, patch, post } from '../../../api'
import type {
  AIMessage,
  AIConfig,
  Conversation,
  ConversationCreateRequest,
  ConversationPage,
  ConversationStatus,
  ConversationUpdateRequest,
  MessagePage,
  DeepSearchRun,
} from './types'

export function getAIConfig() {
  return api<AIConfig>('/ai/v1/config')
}

export const conversationKeys = {
  all: ['ai-conversations'] as const,
  list: (status: ConversationStatus, page: number) => ['ai-conversations', status, page] as const,
  detail: (id: number) => ['ai-conversation', id] as const,
  messages: (id: number) => ['ai-conversation-messages', id] as const,
}

export function listConversations(status: ConversationStatus, page = 1, limit = 30) {
  return api<ConversationPage>(`/ai/v1/conversations?status=${status}&page=${page}&limit=${limit}`)
}

export function getConversation(id: number) {
  return api<Conversation>(`/ai/v1/conversations/${id}`)
}

export function createConversation(body: ConversationCreateRequest) {
  return post<Conversation>('/ai/v1/conversations', body)
}

export function updateConversation(id: number, body: ConversationUpdateRequest) {
  return patch<Conversation>(`/ai/v1/conversations/${id}`, body)
}

export function archiveConversation(id: number) {
  return post<Conversation>(`/ai/v1/conversations/${id}/archive`, {})
}

export function restoreConversation(id: number) {
  return post<Conversation>(`/ai/v1/conversations/${id}/restore`, {})
}

export function deleteConversation(id: number) {
  return api<void>(`/ai/v1/conversations/${id}`, { method: 'DELETE' })
}

export function getMessages(id: number, page = 1, limit = 80) {
  return api<MessagePage>(`/ai/v1/conversations/${id}/messages?page=${page}&limit=${limit}&rich_content=true`)
}

export function getMessage(conversationId: number, messageId: number) {
  return api<AIMessage>(`/ai/v1/conversations/${conversationId}/messages/${messageId}?rich_content=true`)
}

export function stopGeneration(id: number) {
  return post<{ stopped: boolean; assistant_message_id: number | null }>(`/ai/v1/conversations/${id}/stop`, {})
}

export function getActiveGeneration(id: number) {
  return api<{ active: boolean; assistant_message_id: number | null; runtime_mode: string }>(`/ai/v1/conversations/${id}/active-generation`)
}

export function getDeepSearchRun(runId: string) {
  return api<DeepSearchRun>(`/external-search/v1/deep-runs/${encodeURIComponent(runId)}`)
}

export function getActiveDeepSearchRun(conversationId: number) {
  return api<DeepSearchRun | null>(`/external-search/v1/conversations/${conversationId}/active-deep-run`)
}

export function cancelDeepSearchRun(runId: string) {
  return post<DeepSearchRun>(`/external-search/v1/deep-runs/${encodeURIComponent(runId)}/cancel`, {})
}
