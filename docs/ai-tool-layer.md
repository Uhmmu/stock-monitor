# AI Tool Adapter Layer

## Scope and architecture

The AI Tool layer is a vendor-neutral, read-only boundary over Research Data Gateway v1. It does not call an LLM, implement chat, prompts, memory, an agent loop, MCP, external search, synchronization, or paid discovery. It never queries ORM models, Redis, or data volumes directly.

```text
PostgreSQL / Redis / persisted files
                 |
        ResearchGateway service
                 |
     explicit AI Tool adapters (44)
                 |
     Registry -> Policy -> Executor
                 |
      debug API / future orchestrator
```

Adapters receive a request-scoped `ResearchGateway`, validated arguments, and an authenticated `ToolExecutionContext`. Aggregate adapters call Gateway methods directly and preserve partial successes. No adapter calls another adapter.

## Registry and execution

`ToolRegistry` uses explicit startup registration from `catalog.py`; there is no module scanning, dynamic import, user registration, or third-party Python loading. Registration rejects duplicate names, schema mismatches, invalid semantic versions, non-snake-case names, short descriptions, and non-read-only definitions. `export_openai_tools()` emits ordinary JSON function definitions and does not import or call the OpenAI SDK.

`ToolExecutor` performs: call ID creation, lookup, enable/allow/deny checks, Pydantic validation/defaulting, private-data policy, date-span policy, call budget, canonical cache lookup, timeout, adapter execution, deterministic compression, envelope size check, audit, and stable result/error conversion. `execute_many()` limits calls and concurrency, preserves input order, isolates failures, deduplicates identical calls within a batch, and enforces a cumulative output budget. Recursive calls are not supported.

## Tools and Gateway sources

All definitions are version `1.0.0`, require authentication, are read-only, return `ToolExecutionResult`, and only read already persisted data.

| Domain | Tools | ResearchGateway methods |
| --- | --- | --- |
| system | `list_research_capabilities` | `capabilities` |
| portfolio | `get_portfolio_summary`, `get_portfolio_positions`, `get_position_detail`, `get_trade_history`, `get_portfolio_risk_analysis` | `portfolio_summary`, `portfolio_positions`, `portfolio_position`, `trades`, `portfolio_analysis` |
| company | `get_company_profile`, `get_company_snapshot`, `get_company_peers` | `company_profile`; snapshot also uses `portfolio_position`, `price_latest`, `valuation`, `technical`; `peers` |
| market | `get_latest_price`, `get_price_history`, `compare_price_performance`, `get_market_context` | `price_latest`, `price_history`, `market_context`; comparison derives return/drawdown/volatility in memory |
| news | `get_latest_news`, `search_news`, `get_news_detail`, `get_news_archives` | `news`, `news_detail`, `archives` |
| SEC | `get_sec_filings`, `get_sec_filing_detail`, `get_sec_events`, `get_sec_financial_facts`, `get_insider_trades`, `get_institutional_holdings` | `sec_filings`, `sec_filing`, `sec_events`, `sec_periods`, `insider_trades`, `institutional_holdings` |
| ownership | `get_company_ownership_activity`, `get_congress_trades`, `get_tracked_figures`, `get_figure_positions`, `get_public_figure_activity` | ownership aggregate uses financial/SEC methods; `congress_trades`, `tracked_figures`, `figure_positions`, `public_figure_activity` |
| financials | `get_financial_summary`, `get_financial_statements`, `compare_financial_metrics`, `get_financial_trends` | `financial_summary`, `financial_statements`; comparisons/trends deterministically reshape whitelisted metrics |
| valuation | `get_latest_valuation`, `get_valuation_history`, `compare_valuations` | `valuation`, `valuation_history` |
| technical | `get_technical_analysis`, `get_technical_levels`, `compare_technical_signals`, `get_technical_chart_reference` | `technical`; chart tool returns the controlled Research API URL, never file paths or bytes |
| calendar | `get_calendar_events`, `get_calendar_event_detail` | `calendar_events`, `calendar_event` |
| discovery | `get_discovery_runs`, `get_discovery_run`, `get_discovery_candidates` | `discovery_runs`, `discovery_run`, `discovery_candidates` |

Gateway v1 was extended with read-only routes for persisted portfolio analysis runs, the current user's last-good discovery market context, public official transaction disclosures, tracked figures, figure positions, and aggregated public-figure activity. No table or migration was added.

Private-data tools are portfolio summary/positions/detail/trades/risk, company snapshot (because it may include the user's position), market context (stored against a user-owned run), and all discovery tools. Cache keys for these tools always contain the authenticated user ID. A body-provided `user_id`, `caller`, path, URL, SQL, or any unknown argument is rejected.

## Arguments and result modes

All argument models use `extra="forbid"` and whitespace stripping. Symbols use the existing Gateway normalizer, uppercase automatically, reject path/control characters, deduplicate in order, and are capped at 20 (10 for comparisons). Queries are capped at 500 characters. Lists, form/event types, financial metric names, sort fields, intervals, limits, and date ranges are bounded; only persisted daily prices (`1d`) are supported. Financial metrics use a fixed whitelist.

Result modes are:

- `compact`: at most 10 list items and normally 8,000 characters.
- `standard`: at most 30 items and normally 24,000 characters.
- `detailed`: at most 100 items and normally 60,000 characters; it still excludes raw provider/model payloads, full SEC/news bodies, and image bytes.

The hard envelope limit is 80,000 characters. Environment values are clamped to safe constants. Token counts are explicitly approximate: ASCII is estimated at four characters per token and non-ASCII conservatively at one token per character. They are only budget/audit signals, not billing values.

Compression recursively removes null/empty values and blocked raw fields, bounds nesting, truncates known long text fields, applies stable list limits, and progressively reduces nested collections/strings while preserving valid JSON. It never slices serialized JSON. Truncation adds `TOOL_RESULT_TRUNCATED`, preserves original/returned counts, and sets `stats.truncated=true`. Sources are merged, deduplicated by `source_id`, stably sorted, and stripped of unsafe absolute/traversal locators. Original `freshness` and warnings remain attached.

## Policy, timeout, concurrency, cache, audit

Stable errors include `TOOL_NOT_ALLOWED`, `TOOL_DISABLED`, `TOOL_CALL_LIMIT_EXCEEDED`, `TOOL_OUTPUT_BUDGET_EXCEEDED`, `TOOL_ARGUMENTS_INVALID`, `TOOL_TIMEOUT`, `TOOL_RESULT_TOO_LARGE`, `TOOL_PRIVATE_DATA_DENIED`, `TOOL_EXECUTION_FAILED`, and `TOOL_NOT_FOUND`. Tracebacks are logged server-side but never returned.

Default timeout is 15 seconds and hard maximum is 30. Internal batches allow at most 12 calls and four-way concurrency; the debug batch endpoint accepts at most eight. A semaphore prevents unbounded task creation. A child failure does not cancel siblings.

The optional cache is a bounded (256 entry), maximum-ten-minute in-process optimization fallback—not a fact source. Public keys use normalized arguments; private keys additionally use authenticated `user_id`. Errors are never cached, original freshness is never rewritten, and TTLs are domain-specific (price 60 seconds, user data 30 seconds, news/calendar/discovery 2 minutes, valuation/technical 5 minutes, slow-changing company/SEC/financial/ownership data 10 minutes).

Each execution logs only bounded normalized arguments and metadata: call/request/user/caller, tool/version, status, duration, cache hit, result mode, item counts, output estimates, truncation, source types, warning codes, and error code. Tokens, keys, full transactions, article/SEC bodies, results, and discovery raw responses are excluded. Lightweight bounded in-memory counters track calls/status, cache hits, truncations, and recent durations.

## Debug API

All routes require normal JWT authentication. Production can independently disable the entire layer, debug API, or batch API; disabled debug endpoints return 404.

```text
GET  /api/ai-tools/v1/tools?domain=news&enabled_only=true&include_schema=false
GET  /api/ai-tools/v1/tools/{tool_name}
POST /api/ai-tools/v1/execute
POST /api/ai-tools/v1/execute-batch
GET  /api/ai-tools/v1/openai-schema?domain=news&tools=get_latest_news
```

Examples:

```bash
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/ai-tools/v1/tools"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/ai-tools/v1/tools/get_latest_news"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/ai-tools/v1/openai-schema"
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$BASE_URL/api/ai-tools/v1/execute" \
  -d '{"tool":"get_company_snapshot","arguments":{"symbol":"MSFT","result_mode":"standard"}}'
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$BASE_URL/api/ai-tools/v1/execute-batch" \
  -d '{"calls":[{"tool":"get_position_detail","arguments":{"symbol":"MSFT"}},{"tool":"get_latest_news","arguments":{"symbol":"MSFT","days":30,"limit":10}},{"tool":"get_sec_filings","arguments":{"symbol":"MSFT","form_types":["10-Q","8-K"],"limit":10}}]}'
```

## Configuration

`.env.example` documents `AI_TOOLS_ENABLED`, debug/batch switches, timeout/call/concurrency limits, the three result budgets, hard budget, cache, and audit switches. Real `.env` files are not modified or logged.

## AI Orchestrator integration

The stateless third-stage AI Orchestrator calls this layer, but the AI Tool Layer does not depend on model providers, prompts, or orchestration. The Orchestrator selects an authenticated allowlist, exports matching schemas, routes model-originated arguments through `ToolExecutor`, and returns compressed `ToolExecutionResult` evidence to the model as untrusted tool-role data. It never bypasses this layer for Gateway internals, databases, caches, or files. See [AI Orchestrator](ai-orchestrator.md).

Still intentionally absent from this Tool Layer: provider protocol logic, prompts, chat/session/message/memory storage, MCP, RAG/embedding/vector storage, external search, automatic refresh, and business-data mutation.
