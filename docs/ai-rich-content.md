# Rich AI Responses

## Boundary and trust model

Rich responses add a deterministic presentation layer after the normal
model/tool/citation loop. The model never produces component JSON. A successful
read-only `ToolExecutionResult` is passed to an explicit server-side factory,
which may create a bounded `RichBlockCandidate`. The model receives only the
candidate ID, type, and short relevance hint and may place it with
`[[BLOCK:candidate_id]]`.

```text
ToolExecutionResult
  -> deterministic factory (no network, database, Redis, or model call)
  -> validated candidate
  -> model chooses candidate IDs in Markdown
  -> Composer validates placement/citations/limits
  -> RichContentDocument + complete Markdown fallback
  -> SSE and ai_messages persistence
```

Tool raw results and unused candidates are never sent to the browser or stored
with the message. Existing tool access control, user ownership, and citation
boundaries remain unchanged.

## Versioned protocol

`RichContentDocument.schema_version` is currently `1`. It contains ordered
Markdown and block parts plus a complete `fallback_markdown`. Blocks have an
independent `block_type` and `block_version`; both backend and frontend use
explicit registries. Unknown types or versions render the persisted block
fallback instead of failing the message.

Version 1 registers:

- `stock_quote`
- `metric_grid`
- `mini_line_chart`
- `valuation_range`
- `comparison_table`
- `portfolio_allocation`
- `risk_panel`
- `catalyst_timeline`
- `news_cluster`
- `sec_filing`
- `investment_decision`
- `source_list`

Factories live under `backend/app/ai_rich_content/factories`. They accept only a
`ToolExecutionResult` and already-assigned citation metadata. They validate
against strict Pydantic data models before creating a candidate. Missing or
incompatible data skips a component and leaves the ordinary answer intact.

## Composer behavior

`composer.py` treats model output as an untrusted placement proposal. It:

1. recognizes placeholders only outside fenced and inline code;
2. removes malformed, unknown, duplicate, over-limit, or repeated-type tokens;
3. revalidates every selected block through the registry;
4. filters top-level and nested citation keys against server-built citations;
5. applies a small centralized intent allowlist for at most two automatic
   insertions;
6. appends a bounded `source_list` containing only used sources;
7. builds the complete Markdown fallback; and
8. replaces blocks with fallback text if the document exceeds its byte budget.

Defaults are six blocks per message, a hard maximum of ten, 100,000 document
characters, 30,000 characters per block payload, 500 chart points, five chart
series, 100 table rows, and 12 columns. All limits have server configuration and
hard clamps. Composition failures are optional-UI failures: the assistant still
returns Markdown.

## Persistence and compatibility

Alembic revision `0041_ai_rich_content` adds nullable
`ai_messages.content_schema_version` and JSONB `ai_messages.content_parts`.
Existing messages are not backfilled.

- `ai_messages.content` always stores the complete Markdown fallback.
- `content_parts` stores only the final used `RichContentDocument`.
- Regeneration creates and stores a new document with the new assistant version.
- History, summaries, memory extraction, copy, and old clients continue to use
  `content`.

Message read endpoints accept `rich_content=true`. The current frontend sends
that flag. Omitting it or setting it to false returns the existing message
shape without rich fields.

## SSE

After Markdown streaming and citation validation, a rich response may emit:

```text
response.block.created
response.block.completed
response.rich_content.completed
response.completed
```

`response.block.created` contains ID/type/version for a skeleton.
`response.block.completed` contains the final ordered part. The full document is
the data payload of `response.rich_content.completed`. The same object is then
persisted before the single terminal completion. No raw tool data, unused
candidate, prompt, or hidden reasoning is included.

## Frontend runtime

The renderer is under
`frontend/src/features/ai-chat/rich-content`. It performs document and
block-specific runtime validation before looking up an explicit
type/version registration. Each component is wrapped in its own error boundary.
Invalid, unknown, or crashed components use `fallback_markdown`; an invalid
document uses the message-level fallback.

Components use plain React/SVG, safe public HTTP(S) links, existing citation
actions, and bounded arrays. Tables switch to mobile cards, charts have an
accessible label and hover values, and all blocks expose freshness and warning
metadata when present. CSS includes mobile layouts, system dark colors,
reduced-motion/transparency behavior, increased contrast, and touch feedback.
Copying an assistant message always copies the fallback Markdown.

## Configuration and observability

`.env.example` documents all `AI_RICH_CONTENT_*` switches and limits.
`GET /api/ai/v1/config` exposes only enabled/schema/supported versions and the
safe message block limit. Debug AI metrics include counts for compositions,
candidates, used/auto-inserted/degraded blocks, invalid/duplicate placeholders,
and total composition duration. Audit logs contain request ID, counts, versions,
and block types only—never payload values.

## Verification

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/ai_rich_content \
  backend/tests/ai \
  backend/tests/ai_conversations

cd frontend
npm test
npm run build
```

Migration validation is `upgrade 0041 -> downgrade 0040 -> upgrade 0041`.
Because early project migrations contain SQLite-incompatible constraint
operations, an isolated SQLite check starts from a stamped `0040` schema.
Production migration validation must use PostgreSQL.
