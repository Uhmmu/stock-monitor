import type { RichContentDocument } from '../rich-content/types'

export type ConversationStatus = 'active' | 'archived' | 'deleted'
export type MessageStatus = 'pending' | 'streaming' | 'completed' | 'partial' | 'failed' | 'cancelled'
export type WebAccessMode = 'off' | 'search' | 'deep_minimal' | 'deep_low' | 'deep_medium' | 'deep_high' | 'deep_xhigh'

export type DeepModeConfig = {
  label: string
  estimated_base_cost_usd: number
  confirmation_required: boolean
  enabled: boolean
}

export type WebSearchConfig = {
  enabled: boolean
  configured: boolean
  default_mode: WebAccessMode
  available_modes: WebAccessMode[]
  deep_modes: Record<'minimal' | 'low' | 'medium' | 'high' | 'xhigh', DeepModeConfig>
}

export type AIModelOption = {
  id: string
  label: string
  family: 'claude' | 'gpt' | 'other'
  is_default: boolean
  available: boolean
}

export type AIConfig = {
  enabled: boolean
  streaming: boolean
  default_model: string
  allowed_models: string[]
  models: AIModelOption[]
  max_message_chars: number
  conversations_enabled: boolean
  conversation_runtime_mode: string
  web_search: WebSearchConfig
  rich_content?: {
    enabled: boolean
    schema_version: number
    max_blocks_per_message: number
    blocks: Array<{ block_type: string; version: number }>
  }
}

export type Conversation = {
  id: number
  title: string
  title_source: 'generated' | 'user'
  status: ConversationStatus
  active_symbol: string | null
  active_symbols: string[]
  active_portfolio_id: number | null
  page_context: string | null
  model: string | null
  web_access_mode: WebAccessMode
  message_count: number
  completed_message_count: number
  last_message_preview: string | null
  created_at: string
  updated_at: string
  last_message_at: string | null
  archived_at: string | null
  deleted_at: string | null
}

export type Citation = {
  key: string
  source_id: string
  title: string
  source_type: string
  symbol: string | null
  provider: string | null
  authority: string | null
  published_at: string | null
  retrieved_at: string | null
  market_timestamp?: string | null
  fetched_at?: string | null
  persisted_at?: string | null
  market_session?: string | null
  data_status?: string | null
  provider_role?: string | null
  locator: string | null
  url: string | null
}

export type DeepSearchRun = {
  run_id: string
  conversation_id: number | null
  user_message_id: number | null
  assistant_message_id: number | null
  provider: string
  mode: WebAccessMode
  effort: 'minimal' | 'low' | 'medium' | 'high' | 'xhigh'
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  termination_reason: string | null
  text: string | null
  structured: Record<string, unknown> | unknown[] | null
  sources: Array<{ source_id: string; title: string; url: string; domain: string; authority_tier: string }>
  usage: Record<string, unknown>
  cost_usd: number | null
  cost_estimated: boolean
  error_code: string | null
  error_message_safe: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  last_synced_at: string | null
}

export type ToolCallRecord = {
  id: number
  tool_call_id: string
  tool_name: string
  display_name: string
  status: string
  summary: string | null
  warning_codes: string[]
  returned_item_count: number | null
  cache_hit: boolean
  truncated: boolean
  reused: boolean
  external_provider?: string | null
  external_run_id?: string | null
  cost_usd?: number | null
  cost_estimated?: boolean
  created_at: string
  completed_at: string | null
}

export type AIMessage = {
  id: number | string
  conversation_id: number
  role: 'user' | 'assistant'
  status: MessageStatus
  content: string
  content_format: string
  content_schema_version?: number | null
  content_parts?: RichContentDocument | null
  rich_block_skeletons?: Array<{ block_id: string; block_type: string; block_version: number }>
  parent_message_id: number | null
  reply_to_message_id: number | null
  regenerated_from_message_id: number | null
  generation_index: number
  model: string | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  tool_call_count: number
  citation_count: number
  web_access_mode: WebAccessMode
  external_search_call_count: number
  deep_search_run_id: string | null
  external_search_cost_usd: number | null
  error_code: string | null
  error_message_safe: string | null
  has_partial_content: boolean
  citations: Citation[]
  tool_calls: ToolCallRecord[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  updated_at: string
}

export type ConversationPage = { items: Conversation[]; page: number; limit: number; total: number; has_more: boolean }
export type MessagePage = { items: AIMessage[]; page: number; limit: number; total: number; has_more: boolean }

export type ConversationCreateRequest = {
  title?: string
  active_symbol?: string | null
  active_symbols?: string[]
  active_portfolio_id?: number | null
  page_context?: string | null
  model?: string | null
  web_access_mode?: WebAccessMode
  deep_search_confirmed?: boolean
}

export type ConversationUpdateRequest = Partial<ConversationCreateRequest> & { archived?: boolean }

export type MessageCreateRequest = {
  message: string
  active_symbol?: string | null
  active_symbols?: string[]
  active_portfolio_id?: number | null
  page_context?: string | null
  model?: string | null
  stream: boolean
  allowed_tools?: string[] | null
  denied_tools?: string[]
  web_access_mode?: WebAccessMode
  deep_search_confirmed?: boolean
}

export type ToolActivity = {
  tool_call_id: string
  display_name: string
  status: 'planning' | 'running' | 'completed' | 'failed'
  returned_item_count?: number | null
  summary?: string | null
}

export type ModelSwitchNotice = {
  from: string
  to: string
  reason?: string
}

type StreamData = Record<string, unknown>
export type AIStreamEvent =
  | { type: 'conversation.started'; data: { conversation_id: number; user_message_id: number; assistant_message_id: number } }
  | { type: 'message.created'; data: { user_message: AIMessage; assistant_message: AIMessage } }
  | { type: 'response.started'; data: StreamData }
  | { type: 'context.ready'; data: StreamData }
  | { type: 'model.switched'; data: { from: string; to: string; reason?: string } }
  | { type: 'tool.planning'; data: { tool_call_id: string; display_name?: string; tool?: string } }
  | { type: 'tool.started'; data: { tool_call_id: string; display_name?: string; tool?: string } }
  | { type: 'tool.completed'; data: { tool_call_id: string; display_name?: string; status?: string; returned_item_count?: number | null; summary?: string | null } }
  | { type: 'tool.failed'; data: { tool_call_id: string; display_name?: string; status?: string; summary?: string | null } }
  | { type: 'response.delta'; data: { delta: string } }
  | { type: 'response.reset'; data: Record<string, never> }
  | { type: 'citation.map'; data: { citations: Citation[] } }
  | { type: 'response.block.created'; data: { block_id: string; block_type: string; block_version: number } }
  | { type: 'response.block.completed'; data: { part_index: number; part: import('../rich-content/types').RichBlockPart } }
  | { type: 'response.rich_content.completed'; data: RichContentDocument }
  | { type: 'message.persisted'; data: { assistant_message_id: number; status: MessageStatus } }
  | { type: 'deep_search.created'; data: { run_id?: string | null; effort?: string; status: string } }
  | { type: 'deep_search.queued'; data: Record<string, unknown> }
  | { type: 'deep_search.started'; data: { run_id?: string | null; stage?: string; message?: string } }
  | { type: 'deep_search.progress'; data: Record<string, unknown> }
  | { type: 'deep_search.completed'; data: { run_id?: string | null; status: string; source_count?: number } }
  | { type: 'deep_search.failed'; data: { run_id?: string | null; status?: string; message?: string } }
  | { type: 'deep_search.cancelled'; data: { run_id?: string | null; status?: string; message?: string } }
  | { type: 'deep_search.cost'; data: { run_id?: string | null; cost_usd: number; estimated: boolean } }
  | { type: 'response.completed'; data: { status: 'completed' | 'partial'; answer: string; usage?: StreamData; rich_content?: RichContentDocument | null } }
  | { type: 'error'; data: { code: string; message: string; retryable?: boolean } }

export type AIErrorPayload = { request_id?: string; error?: { code?: string; message?: string; retryable?: boolean } }
