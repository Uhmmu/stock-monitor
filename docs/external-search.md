# Exa external search

Long-term memory and investment-decision context are not sent to Exa. The first
privacy firewall omits those private context blocks from web-enabled turns
entirely because external tool queries are model-authored.

This document describes the server-side public-web boundary used by AI chat. It does not cover the separate Perplexity opportunity-discovery pipeline.

## Search and Agent are separate

| Product mode | Exa endpoint | Exa control | Final chat answer |
|---|---|---|---|
| `off` | none | none | stock-monitor model using internal tools only |
| `search` | `POST /search` | Search `type=auto` by default | stock-monitor model |
| `deep_minimal` … `deep_xhigh` | `POST /agent/runs` | fixed Agent `effort` | Exa research returned as one untrusted tool result, then stock-monitor model |

Exa Search types `deep-lite`, `deep`, and `deep-reasoning` remain supported by the provider contract for future experiments. They are not the five product Deep modes and are never shown in the UI. Agent `auto` is supported by Exa but intentionally absent from the stock-monitor enum and UI.

## Current official contract

The implementation was checked against the current Exa reference on 2026-07-30:

- Search: `POST https://api.exa.ai/search`.
- Agent create: `POST https://api.exa.ai/agent/runs` with top-level `query`, fixed `effort`, optional `outputSchema`, `systemPrompt`, and non-sensitive `metadata`.
- Agent status: `GET /agent/runs/{id}`.
- Agent events: `GET /agent/runs/{id}/events`; replay accepts `Last-Event-ID` with `Accept: text/event-stream`.
- Agent cancel: `POST /agent/runs/{id}/cancel`.
- Authentication: one `x-api-key` header. Exa also documents Bearer auth, but stock-monitor sends only the documented primary header used in its examples.
- Run states: `queued`, `running`, `completed`, `failed`, `cancelled`; stop reasons include `schema_satisfied`, `budget_reached`, `error`, and `cancelled`.

The current Search response calls its type field `resolvedSearchType` and marks it deprecated/possibly empty. The parser records it when non-empty and otherwise preserves the requested type; no policy decision depends on that response field.

Primary references: [Search](https://exa.ai/docs/reference/search), [Agent overview](https://exa.ai/docs/reference/agent-api/overview), [create a run](https://exa.ai/docs/reference/agent-api/create-a-run), [get a run](https://exa.ai/docs/reference/agent-api/get-a-run), [cancel a run](https://exa.ai/docs/reference/agent-api/cancel-a-run), and [list run events](https://exa.ai/docs/reference/agent-api/list-run-events).

## Normal Search contract

Normal chat search defaults to eight results, `type=auto`, content moderation, and `contents.highlights=true`. Inputs use strict internal schemas and are converted to the current camelCase Exa fields. Retired fields such as `neural`, `useAutoprompt`, `tokensNum`, and `livecrawl` are not sent.

Freshness is an internal product policy:

| Mode | `contents.maxAgeHours` | Local cache | Limits |
|---|---:|---:|---|
| `balanced` | omitted | 15 minutes | up to 10 results |
| `fresh` | `1` | 3 minutes | up to 10 results |
| `live` | `0` | disabled | up to 5 results and once per answer |
| `cached` | `-1` | 1 hour | up to 10 results |

`maxAgeHours` is Exa crawl-cache age, not publication time. `published_at` and `retrieved_at` remain separate. Text mode is supported by the provider, but normal semantic tools request highlights. Text is capped at 15,000 characters and should be used only by a future explicitly bounded tool.

Registered semantic tools are:

- `search_web`
- `search_latest_news_web`
- `search_official_company_sources`
- `search_financial_reports_web`
- `search_publications_web`

The selector exposes at most three relevant normal-web tools. Company-domain filters come from the stored company profile; a model cannot declare a domain to be official. Stored SEC, financial, valuation, portfolio, and synchronized-news tools remain preferred.

## Provider lifecycle and failures

`ExaExternalSearchProvider` owns one pooled `httpx.AsyncClient` per application process and closes it at application shutdown. Search uses a finite timeout and a global in-process rate limiter. Agent create, status, event replay, and cancel share a separate concurrency semaphore. Individual Agent JSON requests have a bounded timeout; a long-running run is represented by its ID and polled instead of holding one HTTP request indefinitely.

Network failures, 429, and selected 5xx responses receive at most two retries with jitter and bounded exponential backoff. `Retry-After` is honored up to the local cap. Invalid/auth/payment/forbidden requests are not retried. A paid Agent create is never automatically retried; the local idempotency row is retained to prevent an accidental second charge.

Errors are translated to stable `WEB_SEARCH_*` or `DEEP_SEARCH_*` codes. Provider authentication bodies, request payloads, tracebacks, and credentials are never returned to the browser.

## Security and privacy

The only remote host requested by this subsystem is the configured server-side Exa API Base. Search result URLs are metadata; stock-monitor does not fetch them.

Before a URL becomes a result or citation, it is parsed and normalized. Only HTTP(S) is accepted. User info, fragments, tracking parameters, overlong values, invalid IDNA/ports, loopback/private/link-local IPs, cloud metadata hosts, `.local`/`.internal`, and known service names are rejected. Public locators never reuse internal filesystem paths.

Before a query is sent, `ExternalQueryPrivacyFilter` removes credentials, email, labeled user/conversation/message identifiers, UUIDs, internal addresses, local paths, and labeled portfolio quantities, cost basis, P&L, and balances. The Deep tool never adds portfolio positions, transaction history, account metadata, or chat history. It may append public ticker symbols selected by the model from the public question. The `include_internal_context` argument is intentionally not used to serialize private context.

Production query logging is off. External audit and tool-call persistence record a SHA-256 fingerprint and length instead of query text. The durable run stores `query_hash` and an optional short sanitized preview only when `EXA_QUERY_LOGGING_ENABLED=true`. It never stores an API key, full Provider response, webpage body, hidden reasoning, or raw SSE event.

All tool output is prefixed as untrusted research data and is sent only in a tool-role message. System instructions explicitly forbid following webpage or Agent-output instructions, revealing secrets, changing tool policy, executing code, visiting suggested URLs, or performing writes.

## Domains and citations

Every accepted result is mapped to the existing source format using `web:<sha256(normalized_url)>`, `source_type=web_search`, `provider=exa`, title, dates, URL, and authority metadata. Deep grounding uses `source_type=deep_research`. The common Citation Builder deduplicates source IDs and assigns the existing `[S1]`, `[S2]` sequence; there are no separate web citation numbers.

Authority tiers are `official`, `trusted_media`, `specialist`, `general_web`, and `unknown`. They are evidence metadata, not truth scores. Government, regulator, exchange, and stored company domains can be marked official. Trusted media and forced blocked domains are centralized server configuration. Conflicting safe sources are retained.

## Cache, limits, budgets, and metrics

Normal responses are cached in process by the fully sanitized provider request. Errors and empty responses are not cached. Agent results are durable per user and conversation and are never reused across users.

Per answer, the executor allows at most three normal Search calls, one live call, and one Agent tool call. Agent concurrency and active-run caps are enforced before creation. The per-request dollar cap is checked against the current fixed effort estimate; optional user daily Agent cost and High/X-High run counts are enforced from durable SQL rows. Optional normal-Search daily dollar accounting uses Redis; if Redis is unavailable, normal Search retains its per-answer limits, while High/X-High continue to fail safely against SQL limits.

The admin-only metrics endpoint is `GET /api/external-search/v1/metrics`. Audit and metrics contain no query or page content. Exa's response cost replaces the estimate when supplied; otherwise `cost_estimated=true` remains visible.

## Configuration and deployment

All settings are listed in `.env.example`. The safe default is `EXA_ENABLED=false`, `EXA_DEFAULT_WEB_ACCESS_MODE=off`, and no key. A missing key must not prevent API, worker, beat, or internal AI startup. The public AI config returns only enabled modes, labels, confirmation flags, and reference base prices; it does not expose the key, API Base, domain policy, or budget implementation.

Backend changes require rebuilding `api`, `worker`, `sec-worker`, and `beat`; UI changes also require rebuilding `frontend`. Apply Alembic migration `0039_external_search` before switching containers. Back up PostgreSQL and source, verify the current non-Git VPS deployment state, and keep X-High disabled during an initial production canary if the account budget is uncertain.

## Testing

```bash
PYTHONPATH=backend pytest -q backend/tests/external_search
PYTHONPATH=backend pytest -q backend/tests
cd frontend && npm test && npm run build
python -m compileall -q backend/app backend/alembic/versions
git diff --check
```

No test should make a live Exa call. Provider tests use `httpx.MockTransport`, and Deep lifecycle tests use the mock provider and an isolated database.

## Deliberately not implemented

There is no Exa MCP, Websets, Monitors, x402, contact enrichment, arbitrary URL fetcher, crawler, vector store, webpage archive, Research Gateway write-back, model replacement, Exa access to stock-monitor tools, or trading action.
