# Exa Agent Deep Search lifecycle

Decision review never starts Deep Search automatically. A user must explicitly
choose an existing Deep mode, and saved long-term memory/decision context is
omitted from that web-enabled turn.

## Product modes and cost display

The UI exposes exactly five Agent efforts:

| UI mode | Provider effort | Purpose | Reference base price | Confirmation |
|---|---|---|---:|---|
| Deep · Minimal | `minimal` | one narrow fact | about $0.012 | no |
| Deep · Low | `low` | small investigation | about $0.025 | no |
| Deep · Medium | `medium` | balanced multi-source research | about $0.10 | no; recommended |
| Deep · High | `high` | complex multi-step research | about $0.50 | configurable, on by default |
| Deep · X-High | `xhigh` | highest-intensity open research | about $1.00 | on by default for every send/regenerate |

These are reference base prices from Exa's current pricing documentation, not maximum charges. Search or other measured components may add cost. The backend replaces an estimate with `costDollars.total` when Exa returns it. See [Exa pricing](https://exa.ai/docs/reference/pricing) and [rate limits](https://exa.ai/docs/reference/rate-limits).

The model never receives an `effort` parameter. `run_deep_web_research` reads the validated message `web_access_mode`, maps it to exactly one effort, and rejects normal Search/off contexts. High/X-High confirmation is validated again server-side before any Agent create request.

## Durable state machine

Migration `0039_external_search` adds `external_search_runs`, `external_search_run_events`, message mode/cost/run links, and external metadata on tool-call records.

Creation follows this order:

1. Validate the user owns the conversation and linked messages.
2. Validate role, enabled effort, confirmation, active-run caps, and cost limits.
3. Sanitize the public query and compute its fingerprint.
4. Reuse an existing idempotent row or create one local `pending` row.
5. Call `POST /agent/runs` exactly once without automatic retry.
6. Save the Provider ID only on the server, update `queued`/`running`, and start detached polling.
7. Poll `GET /agent/runs/{id}` through the bounded Agent semaphore.
8. On a terminal status, save bounded `output.text`, structured JSON, normalized grounding, usage, cost, stop reason, and a safe lifecycle event.
9. Return one untrusted ToolExecutionResult to the selected stock-monitor chat model for a short final synthesis with internal data and unified citations.

The local public ID looks like `dsr_…`; the browser never sees the Provider run ID. All reads and mutations filter by `user_id`. Missing and cross-user run IDs both produce a local 404.

The idempotency key hashes `user_id`, `conversation_id`, `user_message_id`, validated mode, and assistant generation index. Duplicate clicks and transport retries reuse the same row. Regenerate creates a new assistant generation and therefore a new billable run; High/X-High is confirmed again according to configuration.

## Output schemas

Minimal and Low use a shallow bounded object containing an executive summary, up to six confirmed facts, and up to four uncertainties. Medium, High, and X-High use bounded confirmed facts, company impacts, source conflicts, and open questions. Every array has `maxItems`; grounding stays in Exa's dedicated output grounding rather than being duplicated in structured output.

The system prompt asks only for public information, explicit dates, official/filing/IR sources where possible, separation of fact and inference, and material conflicts. It does not include a stock-monitor system prompt, identifiers, private portfolio state, or credentials.

## Chat and browser events

The stable conversation event vocabulary is:

- `deep_search.created`
- `deep_search.queued`
- `deep_search.started`
- `deep_search.progress`
- `deep_search.completed`
- `deep_search.failed`
- `deep_search.cancelled`
- `deep_search.cost`

Raw Exa SSE is never forwarded. Only safe stages, status, reliable source count, local run ID, and estimate/actual cost may be emitted. Provider event parsing and `Last-Event-ID` replay are implemented at the provider boundary; durable local events keep only lifecycle fields required by the UI.

During chat generation, the Deep tool emits the start state before waiting and terminal/cost events after the durable run completes. In parallel, the conversation page polls the user-scoped active-run endpoint while generation is active. This gives progress even if model SSE reconnects or the first active-run check occurred before the row was created.

## Refresh and disconnect recovery

Browser disconnect does not cancel a paid Agent run. The wait is shielded and registered as a detached per-process polling task. The durable row exists before the paid create request and remains the recovery source if the chat stream disappears.

On conversation load, the frontend:

1. Loads persisted messages.
2. Requests `GET /api/external-search/v1/conversations/{conversation_id}/active-deep-run`.
3. Polls every two seconds while the row is `pending`, `queued`, or `running`.
4. Lets the backend synchronize a stale local state from Exa and restart background polling.
5. Loads an assistant-linked completed run by local ID and displays its status, cost, original Exa research, and safe grounding sources even if the final main-model stream was interrupted.

The normal case still uses the stock-monitor model to produce the final response. The recovered Exa text display is explicitly labeled as untrusted Exa research rather than silently presenting it as the final investment answer.

## Cancel and races

The user-facing API is `POST /api/external-search/v1/deep-runs/{local_run_id}/cancel`. The backend checks ownership, calls Exa `POST /agent/runs/{provider_id}/cancel`, applies the returned state, and marks a pending/streaming assistant cancelled. Repeated cancellation of a terminal local row is idempotent.

If cancellation fails because the state changed, the backend fetches the run and accepts Exa's authoritative current state. A completed response therefore wins a completed/cancel race. Cancellation does not promise a refund for work already performed.

Soft-deleting a conversation first stops the normal generation and attempts cancellation of its active runs. Completed Provider runs are not deleted. Local durable rows are tied to conversation ownership and disappear on a future hard cascade delete.

## API surface

```text
POST /api/external-search/v1/deep-runs
GET  /api/external-search/v1/deep-runs/{local_run_id}
GET  /api/external-search/v1/deep-runs/{local_run_id}/events
POST /api/external-search/v1/deep-runs/{local_run_id}/cancel
GET  /api/external-search/v1/conversations/{conversation_id}/active-deep-run
GET  /api/external-search/v1/metrics  # admin only
```

AI chat normally creates runs through the tool rather than the public create endpoint. The endpoint exists for the stable API contract and applies the same validation, privacy, idempotency, and budget rules.

## Operational limits

- One Agent tool call per AI request.
- One idempotent run per user message, mode, and generation.
- One active run per user by default and two globally per deployment database setting.
- Individual create/status/cancel requests are finite; the 900-second setting bounds orchestration, not an unlimited HTTP connection.
- Create is not automatically retried because that could double charge. Poll/status may retry network/5xx failures up to two times.
- Completed output text is capped at 100,000 characters in the run store and compressed again before model context. Assistant answers remain under the existing 30,000-character limit.
- Grounding is normalized and capped at 200 sources. The Tool Layer applies its smaller result-mode/context budget.

## Known limitations

- Detached polling is in-process rather than a Celery recovery scheduler. API startup performs a bounded scan of durable active rows, and any authenticated GET also resumes synchronization. A future periodic stale-run job could cover runs created after a temporary startup/provider failure when no user revisits the conversation.
- If Exa accepts a create request but the network drops before the Provider run ID arrives, stock-monitor retains the failed idempotency row and never retries automatically. Without a Provider ID it cannot safely discover that orphan through the current endpoint contract; operators should reconcile the Exa dashboard rather than resubmit the same generation blindly.
- Provider lifecycle events are normalized, but the UI intentionally shows coarse progress rather than Exa internal reasoning or every source event.
- Metrics are process-local counters; durable run/cost audit lives in PostgreSQL. Cross-process P95/average dashboards require the project's future monitoring stack.
- Normal Search daily cost uses Redis only when a daily cap is configured. Durable Agent budgets use PostgreSQL.

These limitations do not change the core safety guarantees: no duplicate automatic create, no disconnect cancellation, no cross-user reuse, no raw query/event persistence, no hidden reasoning, and no private portfolio context sent to Exa.
