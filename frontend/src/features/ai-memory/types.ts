export type MemoryStatus = 'proposed'|'active'|'rejected'|'stale'|'expired'|'archived'
export type Memory = {
  id:number
  memory_type:string
  scope:string
  scope_key:string|null
  status:MemoryStatus
  title:string|null
  content:string
  structured_value:Record<string,unknown>|unknown[]|null
  origin:string
  confidence:number|null
  importance:number
  source_conversation_id:number|null
  source_message_id:number|null
  source_decision_id:number|null
  effective_from:string|null
  expires_at:string|null
  stale_after:string|null
  last_confirmed_at:string|null
  last_used_at:string|null
  supersedes_memory_id:number|null
  conflict_group:string|null
  created_at:string
  updated_at:string
  confirmed_at:string|null
  archived_at:string|null
}
export type MemoryPage = {items:Memory[];total:number;limit:number;cursor:string|null}
export type MemoryEvent = {
  id:number;event_type:string;before_value:Record<string,unknown>|null
  after_value:Record<string,unknown>|null;conversation_id:number|null
  message_id:number|null;created_at:string
}
export type MemoryDetail = Memory & {events:MemoryEvent[]}
export type MemorySettings = {enabled:boolean;use_in_context:boolean;candidate_extraction_enabled:boolean;max_active_memories:number}

export type Evidence = {
  id:number;source_id:string;source_type:string;origin:string;title:string;symbol:string|null
  provider:string|null;authority:string|null;published_at:string|null;retrieved_at:string|null
  as_of:string|null;url:string|null;locator:string|null;evidence_summary:string
  evidence_role:string;freshness_status:string;created_at:string
}
export type DecisionReview = {
  id:number;review_type:string;status:string;reviewed_at:string|null;data_as_of:string|null
  thesis_status:string;invalidation_status:string;execution_status:string|null;what_changed:string
  supporting_changes:string[];contradicting_changes:string[];lessons:string[];next_action:string|null
  linked_message_id:number|null;linked_conversation_id:number|null;created_at:string;updated_at:string
}
export type InvestmentDecision = {
  id:number;decision_number:number;title:string;decision_type:string;status:string;primary_symbol:string|null;symbols:string[]
  portfolio_id:number|null;decision_date:string;time_horizon:string;target_review_at:string|null;review_due:boolean
  action:string;position_intent:string|null;target_weight:number|null;target_quantity:number|null
  target_price_min:number|null;target_price_max:number|null;thesis:string[];catalysts:string[];risks:string[]
  invalidation_conditions:string[];assumptions:string[];open_questions:string[];structured_conditions:DecisionCondition[];confidence:number|null;priority:number
  source_conversation_id:number|null;source_user_message_id:number|null;source_assistant_message_id:number|null
  supersedes_decision_id:number|null;merged_from_ids:number[];resolution_type:string;related_decision_numbers:number[]
  executed_trade_id:number|null;executed_at:string|null;invalidated_at:string|null;closed_at:string|null
  created_at:string;updated_at:string;evidence:Evidence[];reviews:DecisionReview[];live_context:DecisionLiveContext
}
export type DecisionCondition={category:'catalyst'|'invalidation';description:string;metric:'price'|'event'|'date'|'other';operator:string;threshold:number|null;unit:string|null;event_date:string|null}
export type DecisionLiveCondition={description:string;category:string;metric:string;triggered:boolean|null;current_value?:number;threshold?:number;distance?:number;distance_percent?:number;event_date?:string;days_until?:number}
export type DecisionLiveContext={symbol:string|null;current_price?:number;currency?:string|null;quote_time?:string|null;current_quantity?:number;quantity_to_target?:number;current_weight_percent?:number;target_weight_percent?:number;weight_to_target_percent?:number;conditions:DecisionLiveCondition[];upcoming_events?:{title:string;event_type:string;event_date:string;days_until:number}[]}
export type DecisionDraftPreview={candidate:Record<string,unknown>&{title:string;decision_type:string;symbols:string[];action:string;thesis:string[];catalysts:string[];risks:string[];invalidation_conditions:string[];assumptions:string[];open_questions:string[]};conflicts:InvestmentDecision[];conversation_summary:string}
export type DecisionPage = {items:InvestmentDecision[];total:number;limit:number;cursor:string|null}
export type DecisionFilters = {
  status?:string;symbol?:string;decisionType?:string;search?:string
  timeHorizon?:string;reviewDue?:boolean;minConfidence?:number
  decisionDateFrom?:string;decisionDateTo?:string;portfolioId?:number
  conversationId?:number
}
export type MessageMemoryUsage = {
  memories:Memory[]
  decisions:InvestmentDecision[]
  summary_snapshot:{id:number;version:number;summary_text:string|null;completed_at:string|null}|null
}
