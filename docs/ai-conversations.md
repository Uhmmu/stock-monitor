# AI Conversations

Long conversations now use versioned incremental summaries documented in
[`ai-conversation-summary.md`](ai-conversation-summary.md). Context can include
the latest conversation-local summary, recent unsummarized messages, relevant
confirmed memories and relevant active decisions. These three record types stay
separate and are independently disableable.

## Architecture and transaction boundary

`app.ai.conversations` owns user isolation, persistence, bounded history, lifecycle transitions, and process-local cancellation. The existing `AIOrchestrator` remains the stateless model/tool/citation core.

```text
Conversation API -> ConversationService -> bounded ProviderMessage history
                                      -> AIOrchestrator
                                      -> terminal persistence transaction
```

Provider calls never run inside a database transaction. The service first commits the user message and pending assistant placeholder, releases the transaction during generation, then uses a short terminal transaction for content, citations, tool summaries, usage, and counters. Streaming deltas are accumulated in memory and are not written per token.

## Data model and migration

Alembic revision `0037_ai_conversations` adds:

- `ai_conversations`: title, active context, response preferences, counts, timestamps, archive/soft-delete state, and reserved summary fields.
- `ai_messages`: user/assistant content, lifecycle, regeneration lineage, usage, provider metadata, and safe errors.
- `ai_message_citations`: independently recoverable, bounded source metadata.
- `ai_tool_call_records`: safe execution summaries/counts, never full tool results.

Revision `0041_ai_rich_content` adds nullable versioned JSONB rich content to
assistant messages while retaining complete fallback Markdown in `content`.
See [`ai-rich-content.md`](ai-rich-content.md).

IDs follow the project's integer convention. Every child row repeats `user_id` for ownership filtering. Physical conversation deletion cascades; normal API deletion is soft.

## State machines

Conversation states are `active`, `archived`, and `deleted`. Assistant messages go from `pending` to `streaming`, then `completed`, `partial`, `failed`, or `cancelled`. Only pending/streaming rows may be finalized, preventing stop/completion races. Cancelled answers retain partial text.

## API

All routes use the existing Bearer token. Missing and foreign resources have the same 404 appearance.

```text
POST   /api/ai/v1/conversations
GET    /api/ai/v1/conversations?status=active|archived|deleted&page=1&limit=30
GET    /api/ai/v1/conversations/{conversation_id}
PATCH  /api/ai/v1/conversations/{conversation_id}
DELETE /api/ai/v1/conversations/{conversation_id}
POST   /api/ai/v1/conversations/{conversation_id}/restore
POST   /api/ai/v1/conversations/{conversation_id}/archive
GET    /api/ai/v1/conversations/{conversation_id}/messages?rich_content=true
POST   /api/ai/v1/conversations/{conversation_id}/messages
GET    /api/ai/v1/conversations/{conversation_id}/messages/{message_id}?rich_content=true
POST   /api/ai/v1/conversations/{conversation_id}/stop
GET    /api/ai/v1/conversations/{conversation_id}/active-generation
POST   /api/ai/v1/conversations/{conversation_id}/messages/{message_id}/regenerate
```

Creation accepts an optional first message and reuses the normal non-stream service. Message pagination returns the most recent page in ascending display order; higher pages retrieve older windows. Conversation ordering is stable by last-message time, creation time, and ID.

## SSE and persistence

Streaming message/regenerate requests emit:

```text
conversation.started -> message.created -> response.started -> context.ready
tool.started / tool.completed / tool.failed -> response.delta -> citation.map
response.block.created / response.block.completed
-> response.rich_content.completed
message.persisted -> response.completed | error
```

`message.persisted` comes only after the terminal commit. Exactly one completion/error event terminates a stream. SSE contains no hidden reasoning, full tool results, arguments, system prompts, or credentials.

## History and regenerate

The loader reads only prior user/assistant rows with usable content. Empty failed/cancelled placeholders, tool/citation rows, deleted messages, and system prompts are excluded. Defaults are 16 messages and 60,000 characters with hard clamps. Incomplete prior answers are labelled before provider use.

Regenerate is intentionally linear and limited to the latest user turn. It creates a new assistant row, increments `generation_index`, links `regenerated_from_message_id`, and keeps the old answer. Later history uses only the newest usable assistant generation for that user turn, while the message API still returns every saved version. The lineage fields leave room for a later branch selector.

## Stop and runtime limitation

`ConversationRuntimeRegistry` is async-lock protected and permits one active generation per conversation. Stop cancels the registered request task, waits briefly for terminal persistence, and always unregisters.

The registry is explicitly `single_process`. Config/health report the mode and `distributed_cancellation=false`. Multiple API workers or hosts require a Redis-backed implementation; this phase does not claim distributed stop.

## Configuration and retention

`.env.example` documents feature, history, runtime, checkpoint, restore/soft-delete, and page-limit settings. Missing values use safe defaults. Partial checkpointing is off. No hard-delete scheduler is exposed; the repository has a physical-delete primitive for a later explicit retention job.

## Security, privacy, and audit

- Every repository read contains resource ID plus `user_id`.
- Client schemas reject user/provider/history/system/tool-result injection.
- Audits contain IDs, lengths, counts, status, and timings—not full content.
- Citation URLs allow HTTP(S); absolute/traversal locators are removed.
- Tool persistence stores bounded safe summaries plus validated, recursively bounded and redacted normalized arguments with a canonical hash. These persistence-only arguments are excluded from message responses and SSE; complete tool results are never stored.
- API keys, hidden reasoning, full research bodies, memory, embeddings, and vectors are never stored.

## Testing and migration

```bash
PYTHONPATH=backend pytest -q backend/tests/ai_conversations backend/tests/ai
python -m compileall -q backend/app
```

Migration verification is upgrade `0037`, downgrade `0036`, then upgrade `0037`. Production validation must use PostgreSQL. Older migrations have SQLite-incompatible constraint alterations, so isolated SQLite testing stamps a schema at `0036` before exercising this revision.

```bash
curl -N -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/api/ai/v1/conversations/$CONVERSATION_ID/messages" \
  -d '{"message":"结合我的持仓、估值和最近新闻分析 MSFT","stream":true}'
```

Long-term/cross-conversation memory, RAG, embeddings, semantic search, WebSockets, background generation, distributed cancellation, and write tools remain unimplemented.
