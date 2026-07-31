# Stateless AI Orchestrator

The conversation layer may prepend a completed conversation summary and bounded
confirmed memory/decision context. These are data, not system instructions; the
current user message has priority. Exact use is persisted for disclosure. Saved
private memory is omitted from web-enabled and Deep Search turns.

> The Orchestrator remains the stateless model/tool/citation core. User-owned history, message lifecycle, persistence, regenerate, and stop live in the separate Conversation layer documented in `docs/ai-conversations.md`. Its only boundary extensions are bounded prior `ProviderMessage` input, a conversation ID for tool audit context, and safe terminal tool summaries.

## Scope and architecture

The third-stage backend adds a stateless, provider-neutral research assistant at `/api/ai/v1`. It does not create conversation/message tables, persist prompts or answers, remember users, search the public web, invoke Perplexity/MCP, or expose write tools.

```text
authenticated request
  -> request/context validation
  -> deterministic tool selection
  -> provider registry + provider adapter
  -> bounded model/tool loop
  -> existing ToolExecutor
  -> compressed untrusted tool messages
  -> citation validation/optional repair
  -> deterministic rich-content composition
  -> JSON or SSE response
```

The Research Data Gateway remains the only business-data boundary. The AI Tool Layer adapts Gateway operations into 44 bounded, read-only semantic tools. The Orchestrator never imports ORM models, reads Redis/files, calls the Gateway directly, refreshes upstream data, or executes adapters. It obtains all business evidence through `ToolExecutor` with the authenticated user's `ToolExecutionContext`.

## Provider protocol

`app.ai.providers` defines internal Pydantic messages, tool calls/definitions, requests, responses, usage, and stream events. `BaseModelProvider` exposes `create_response`, `stream_response`, `supports_tools`, and `supports_streaming`; Orchestrator code contains no OpenAI SDK types.

`ProviderRegistry` uses explicit in-process registration, rejects duplicate names, and never dynamically imports a client-selected provider. `MockProvider` supplies deterministic unit/integration responses. The production registry contains `OpenAICompatibleProvider` only.

The OpenAI-compatible adapter uses `httpx.AsyncClient` against server-configured `/chat/completions`. It translates assistant tool calls and tool-result messages in both directions, reconstructs streamed tool arguments, parses usage, enforces bounded connect/request timeouts, and retries only transport failures, 429, and 5xx with limited exponential backoff. It does not retry 400/401/403, log request bodies or authorization, or expose upstream authentication bodies. Upstream 401/403 becomes a stable server-configuration error.

## Context and prompt

System prompt version is `AI_SYSTEM_PROMPT_VERSION = 4`. Fixed context contains the prompt, current date/timezone, optional page context, active symbols/portfolio ID, and the current user message. It does not prefetch portfolio, news, SEC, valuation, technical, or financial data by default. Tool capabilities are read from the cached registry.

User text always remains in a `user` message. Tool data always remains in a `tool` message prefixed as untrusted research data and serialized as bounded JSON. News/SEC text, existing AI opinions, discovery output, public-figure descriptions, and user-authored text cannot change the system prompt, tool allowlist, provider, model, configuration, or later tool policy. URLs, code, and instructions in tool output are never executed.

The prompt requires Chinese-first answers, explicit dates/freshness/gaps, separation of facts/inference/judgment, `[S1]` citations for load-bearing facts, no fabricated real-time claims, no guaranteed returns, and no business-data mutation. Hidden reasoning and chain-of-thought are never requested or streamed.

## Tool selection

`ToolSelector` performs centralized Chinese/English rule matching without another model call. It maps portfolio, news, SEC, valuation, technical, financial, calendar, ownership, discovery, market, and company terms/page contexts to preferred semantic tools. `get_company_snapshot`, `get_company_profile`, and `get_latest_price` are considered baseline context when eligible.

Client `allowed_tools` can only narrow the server registry; `denied_tools` always wins. Unknown names are rejected. Disabled registry tools are absent. The configured normal maximum is 18 and the hard maximum is 30; normal requests therefore expose a relevant subset rather than all 44 definitions.

## Tool-calling loop

The loop supports direct answers, multiple tool calls in one round, multiple model rounds, existing `ToolExecutor.execute_many()` concurrency, structured tool failures, and a final no-tools answer round. It preserves `tool_call_id` pairing and records safe status metadata for clients.

Identical calls use a SHA-256 signature of tool name plus canonical sorted JSON arguments. Duplicate calls in later rounds reuse the first result and do not execute again. Disallowed/unknown model tool names are returned as structured tool errors and never executed. Provider schema errors, empty responses, timeouts, tool failures, length limits, and exhausted budgets map to stable outcomes; an empty model response receives one bounded retry.

Default/hard limits are:

| Limit | Default | Hard maximum |
| --- | ---: | ---: |
| Model rounds | 5 | 6 |
| Total unique tool calls | 12 | 12 |
| Calls per model round | 6 | 6 |
| Parallel tool calls | 4 | 4 |
| Context characters | 180,000 | 200,000 |
| Total tool-result characters | 80,000 | 80,000 |
| Answer characters | 30,000 | 30,000 |
| Total duration | 120s | 120s |
| Citation repairs | 1 | 1 |

Every research model uses the same configured budgets and the same system prompt. Tool results use the Tool Layer's existing compression first, then a deterministic valid-JSON envelope budget. Summary, freshness, warnings, sources, and core data are retained; raw payloads, audit/cache fields, user IDs, credentials, absolute paths, and full upstream response bodies are excluded.

Because this stage has no chat history, `ContextTrimmer` primarily trims tool data. It first removes bulky `data` fields, then—only if required—drops complete older assistant/tool groups while retaining the latest pair. System/current user messages and assistant-tool/tool-result pairs are preserved. Data is reduced structurally, never by producing truncated invalid JSON.

## Citations

`CitationBuilder` merges all tool-result sources across rounds, deduplicates by `source_id`, and assigns encounter-stable `S1`, `S2`, etc. Unsafe absolute/traversal locators are removed; only HTTP(S) public URLs survive. Tool messages include only server-built citation metadata. The model cannot add sources to the API response.

`CitationValidator` extracts `[S<number>]`, normalizes repeated markers, rejects unknown keys, and removes unused citations from the response. If invalid keys occur, Orchestrator makes at most one no-tools repair call instructing the model to change citations without adding facts. If repair is empty or still invalid, illegal markers are removed and a warning is returned.

## API and protocols

All endpoints require the normal bearer JWT:

```text
POST /api/ai/v1/respond
GET  /api/ai/v1/config
GET  /api/ai/v1/health
GET  /api/ai/v1/metrics   (debug switch)
```

`stream=false` returns `AIRespondResponse` with request/response IDs, answer, completed/partial/error status, only used citations, safe tool-call records, aggregate usage, and warnings. `stream=true` uses the exact same Orchestrator core and emits JSON SSE blocks:

```text
response.started
context.ready
tool.started
tool.completed | tool.failed
response.delta
citation.map
response.block.created
response.block.completed
response.rich_content.completed
response.completed | error
```

Tool status events include a localized display name but not arguments or
results. `response.delta` contains answer text only, never reasoning.
`citation.map` contains server-built citations. Rich block events contain only
the final Composer-validated block document described in
[`ai-rich-content.md`](ai-rich-content.md). Exactly one terminal event is
emitted. `StreamingResponse` sets `text/event-stream`, `Cache-Control:
no-cache`, and `Connection: keep-alive`; downstream work is cancelled when the
generator/client disconnects.

Example non-streaming request:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$BASE_URL/api/ai/v1/respond" \
  -d '{"message":"结合我的持仓、估值和最新新闻，分析 MSFT 是否还适合作为核心仓位","active_symbol":"MSFT","model":"gpt-5.6-sol","stream":false}'
```

Example SSE request:

```bash
curl -N -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$BASE_URL/api/ai/v1/respond" \
  -d '{"message":"分析 NVDA 当前技术支撑、估值和最近 SEC 风险","active_symbol":"NVDA","model":"claude-haiku-4-5-20251001","stream":true}'
```

Health/config calls:

```bash
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/ai/v1/health"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/ai/v1/config"
```

`/config` omits provider URLs, credentials, prompts, paths, and internal policy. `/health` is local/configuration-only and never spends a model request.

## Errors, audit, and metrics

Stable codes include `AI_DISABLED`, `AI_PROVIDER_NOT_FOUND`, `AI_PROVIDER_UNAVAILABLE`, `AI_MODEL_NOT_ALLOWED`, `AI_CONFIGURATION_ERROR`, `AI_REQUEST_INVALID`, `AI_CONTEXT_TOO_LARGE`, `AI_TOOL_SELECTION_FAILED`, `AI_TOOL_LOOP_LIMIT_REACHED`, `AI_TOOL_BUDGET_EXCEEDED`, `AI_PROVIDER_TIMEOUT`, `AI_PROVIDER_RATE_LIMITED`, `AI_PROVIDER_AUTH_FAILED`, `AI_PROVIDER_BAD_RESPONSE`, `AI_STREAM_INTERRUPTED`, `AI_CITATION_VALIDATION_FAILED`, `AI_RESPONSE_EMPTY`, and `AI_INTERNAL_ERROR`. API errors never return tracebacks, keys, authorization, or raw provider bodies.

Audit logs contain request/user IDs, provider/model, mode/page/symbol, message length and short SHA-256 digest, rounds/call counts, token usage, duration, citation counts, status, and error code. They exclude full messages, prompts, holdings, filings/articles, tool results, answers, credentials, and hidden reasoning. Bounded in-memory metrics track request statuses, models, errors, average duration/rounds/tool calls, invalid citations, and repairs.

## Configuration

`.env.example` documents the `AI_*` settings: enable switch; provider/default and allowed models; server-only base/key; request/connect/total timeouts; retry count; model/tool/concurrency/context/result/answer/output-token limits; citation repair and tool-selection limits; streaming/non-streaming/debug switches; and the disabled-by-default lightweight portfolio prefetch switch. Numeric values are clamped to code hard limits. Missing credentials do not prevent application startup; `/respond` returns `AI_CONFIGURATION_ERROR` until configured. Existing server-side `OPENAI_BASE_URL`/`OPENAI_API_KEY` remain a compatibility fallback.

## Testing

Focused tests cover provider registry/mock/HTTP parsing/status mapping/retry/streaming, strict request/context boundaries, multilingual selection, citation safety/validation, direct/single/multi-round calls, deduplication, illegal tools, empty recovery, citation repair, SSE terminal behavior, auth, strict request fields, config/health, and OpenAPI.

```bash
PYTHONPATH=backend pytest -q backend/tests/ai backend/tests/ai_tools
ruff check backend/app/ai backend/tests/ai
python -m compileall -q backend/app/ai
```

## Deliberately absent and next stage

There are no conversation/message/memory tables, RAG/embedding/vector storage, external search, Perplexity/MCP, multi-agent planning, image/voice understanding, background AI jobs, write tools, automatic trading, or frontend chat UI.

A future chat stage can persist sanitized user/assistant messages around `AIOrchestrator.respond/stream`, then pass a separately budgeted recent-history summary into `ContextBuilder`. It should not weaken provider/tool boundaries, store raw tool results, or allow persisted content to enter the system role. Conversation ownership and retention/deletion policy must be enforced before adding any history.
