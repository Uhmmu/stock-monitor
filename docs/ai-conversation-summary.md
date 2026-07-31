# AI Conversation Summary

Conversation summaries compress one `ai_conversations` history. They are not
long-term memory and never cross conversations. The current text remains in
`ai_conversations.summary`; versioned records live in
`ai_conversation_summary_snapshots`.

Each snapshot records owner, version, message range, structured summary,
provider/model/prompt version, bounded usage and safe failure metadata. The
unique `(conversation_id, version)` constraint and single pending lookup make
submission idempotent.

The incremental service loads the last completed snapshot and only messages
after `through_message_id`. On success it marks the prior version superseded and
atomically advances `current_summary_snapshot_id`.
Each job is bounded to the next 500 completed messages rather than rereading the
entire conversation.

Automatic enqueue happens after an answer is persisted and triggers on the
configured total-message, unsummarized-message, character, or context-ratio
threshold. Celery task `app.tasks.celery_app.summarize_ai_conversation` performs
provider work without blocking SSE. Manual refresh is available at
`POST /api/ai/v1/conversations/{id}/summary/refresh`.

The versioned prompt treats messages, tool/web/SEC text, and pasted content as
untrusted. It forbids new facts, hidden reasoning, credentials, full tool
results and web pages. Calls have no tools or web access. Pydantic validates the
fixed JSON schema before persistence.

Timeouts, invalid JSON and provider errors use the finite
`AI_SUMMARY_MAX_RETRIES` budget, then fail only the pending snapshot. A
previous completed snapshot stays current; otherwise chat falls back to bounded
recent messages. A stale pending task is retryable after five minutes.

The history loader supplies the latest summary as context, then only recent
unsummarized messages. The current user message remains last. Assistant
messages record which snapshot was used for transparent inspection.

The service emits content-free audit fields and aggregate trigger, success,
failure, compression, token, and estimated context-saving metrics. All
`AI_SUMMARY_*` settings are documented in `.env.example`. Verify migration
round trips, first/incremental snapshots, invalid output, concurrency, history
fallback, compileall, and normal chat regression.
