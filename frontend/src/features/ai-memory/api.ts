import { api, patch, post } from '../../api'
import type { DecisionDraftPreview, DecisionFilters, DecisionPage, DecisionReview, InvestmentDecision, Memory, MemoryDetail, MemoryPage, MemorySettings, MessageMemoryUsage } from './types'

export const memoryKeys = {
  all:['ai-memories'] as const,
  candidates:(conversationId:number)=>['ai-memory-candidates',conversationId] as const,
  settings:['ai-memory-settings'] as const,
  decisions:['ai-investment-decisions'] as const,
}

export function listMemories(status?:string, conversationId?:number) {
  const query = new URLSearchParams({limit:'100'})
  if(status) query.set('status',status)
  if(conversationId) query.set('source_conversation_id',String(conversationId))
  return api<MemoryPage>(`/ai/v1/memories?${query}`)
}
export function listMemoryCandidates(conversationId:number) {
  return api<MemoryPage>(`/ai/v1/memory-candidates?conversation_id=${conversationId}&limit=20`)
}
export function createMemory(body:Record<string,unknown>) { return post<Memory>('/ai/v1/memories',body) }
export function updateMemory(id:number,body:Record<string,unknown>) { return patch<Memory>(`/ai/v1/memories/${id}`,body) }
export function getMemory(id:number) { return api<MemoryDetail>(`/ai/v1/memories/${id}`) }
export function confirmMemory(id:number) { return post<Memory>(`/ai/v1/memories/${id}/confirm`,{}) }
export function rejectMemory(id:number) { return post<Memory>(`/ai/v1/memories/${id}/reject`,{}) }
export function archiveMemory(id:number) { return post<Memory>(`/ai/v1/memories/${id}/archive`,{}) }
export function restoreMemory(id:number) { return post<Memory>(`/ai/v1/memories/${id}/restore`,{}) }
export function deleteMemory(id:number) { return api<void>(`/ai/v1/memories/${id}`,{method:'DELETE'}) }
export function extractMessageMemories(messageId:number) { return post<MemoryPage>(`/ai/v1/messages/${messageId}/memory-candidates`,{}) }
export function getMemorySettings() { return api<MemorySettings>('/ai/v1/memory-settings') }
export function updateMemorySettings(body:Partial<MemorySettings>) { return patch<MemorySettings>('/ai/v1/memory-settings',body) }

export function listDecisions(filters:DecisionFilters|string={},conversationId?:number) {
  const values:DecisionFilters=typeof filters==='string'?{status:filters,conversationId}:filters
  const query = new URLSearchParams({limit:'100'})
  if(values.status) query.set('status',values.status)
  if(values.symbol) query.set('symbol',values.symbol)
  if(values.decisionType) query.set('decision_type',values.decisionType)
  if(values.search) query.set('search',values.search)
  if(values.timeHorizon) query.set('time_horizon',values.timeHorizon)
  if(values.reviewDue!==undefined) query.set('review_due',String(values.reviewDue))
  if(values.minConfidence!==undefined) query.set('min_confidence',String(values.minConfidence))
  if(values.decisionDateFrom) query.set('decision_date_from',values.decisionDateFrom)
  if(values.decisionDateTo) query.set('decision_date_to',values.decisionDateTo)
  if(values.portfolioId) query.set('portfolio_id',String(values.portfolioId))
  if(values.conversationId) query.set('source_conversation_id',String(values.conversationId))
  return api<DecisionPage>(`/ai/v1/investment-decisions?${query}`)
}
export function getDecision(id:number) { return api<InvestmentDecision>(`/ai/v1/investment-decisions/${id}`) }
export function createDecision(body:Record<string,unknown>) { return post<InvestmentDecision>('/ai/v1/investment-decisions',body) }
export function decisionFromMessage(messageId:number) { return post<DecisionDraftPreview>(`/ai/v1/messages/${messageId}/investment-decision-draft`,{}) }
export function resolveDecision(candidate:Record<string,unknown>,resolution:'standalone'|'keep_both'|'replace_existing'|'merge',conflictIds:number[]) { return post<InvestmentDecision>('/ai/v1/investment-decisions/resolve',{candidate,resolution,conflict_ids:conflictIds}) }
export function updateDecision(id:number,body:Record<string,unknown>) { return patch<InvestmentDecision>(`/ai/v1/investment-decisions/${id}`,body) }
export function confirmDecision(id:number) { return post<InvestmentDecision>(`/ai/v1/investment-decisions/${id}/confirm`,{}) }
export function executeDecision(id:number,executionStatus:'executed'|'partially_executed'='executed',tradeId?:number) { return post<InvestmentDecision>(`/ai/v1/investment-decisions/${id}/execute`,{execution_status:executionStatus,trade_id:tradeId??null}) }
export function transitionDecision(id:number,action:'cancel'|'invalidate'|'close'|'archive') { return post<InvestmentDecision>(`/ai/v1/investment-decisions/${id}/${action}`,{}) }
export function deleteDecision(id:number) { return api<void>(`/ai/v1/investment-decisions/${id}`,{method:'DELETE'}) }
export function createReviewDraft(id:number) { return post<DecisionReview>(`/ai/v1/investment-decisions/${id}/review-draft?web_access_mode=off`,{}) }
export function createDecisionReview(id:number,body:Record<string,unknown>) { return post<DecisionReview>(`/ai/v1/investment-decisions/${id}/reviews`,body) }
export function getMessageMemoryUsage(messageId:number) { return api<MessageMemoryUsage>(`/ai/v1/messages/${messageId}/memory-usage`) }
