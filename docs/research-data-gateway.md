# Research Data Gateway

## Architecture and scope

`/api/research/v1` is a read-only adapter over the project's existing PostgreSQL records and controlled file volumes. It does not migrate or duplicate business data, perform upstream API calls, invoke an LLM, implement chat/tool calling/RAG, or become a new write authority.

The boundary is:

```text
existing models/services and controlled volumes
                 ↓
ResearchRepository (ORM queries and pagination)
                 ↓
ResearchGateway (authorization, adapters, sources, freshness, warnings)
                 ↓
authenticated /api/research/v1 routes
```

Routers only parse HTTP parameters. ORM entities never cross the service boundary. Provider JSON is allow-listed or bounded by depth, item count, key count, and string size; complete raw provider/model payloads are excluded.

## Domains and endpoints

| Domain | Endpoints | Existing authority |
|---|---|---|
| Capabilities | `GET /capabilities` | Runtime registry |
| Portfolio | `GET /portfolio/summary`, `/positions`, `/positions/{symbol}`, `/trades`, `/analysis` | portfolio, trade, and persisted `portfolio_analysis_runs`; cached pricing/FX aggregation |
| News | `GET /news`, `/news/{news_id}`, `/news/archives` | `news_items`, `daily_news_archives`, `weekly_news_archives` |
| SEC | `GET /sec/filings`, `/sec/filings/{id}`, `/sec/events`, `/sec/financial-periods`, `/sec/insider-trades`, `/sec/institutional-holdings` | SEC tables already persisted by the application |
| Companies | `GET /companies/{symbol}/profile`, `/financials/summary`, `/financial-statements`, `/valuation`, `/valuation/history`, `/peers` | company/security/profile, financial, valuation, and peer tables |
| Market/technical | `GET /companies/{symbol}/price/latest`, `/prices/history`, `/technical`, `/technical/chart` | persisted price/history/technical records and validated chart volume |
| Calendar | `GET /calendar/events`, `/calendar/events/{id}` | reconciled calendar events and source evidence |
| Discovery | `GET /discovery/runs`, `/discovery/runs/{id}`, `/discovery/runs/{id}/candidates` | current user's persisted discovery runs and normalized child records |
| Market context | `GET /market/context` | current user's most recent persisted discovery market context; no refresh |
| Ownership | `GET /ownership/congress-trades`, `/ownership/figures`, `/ownership/figures/{id}/positions`, `/ownership/figures/{id}/activity` | persisted public disclosures, tracked figures, and figure positions |

All paths above are relative to `/api/research/v1`.

## Response contract

Every JSON endpoint returns:

```json
{
  "data": {},
  "sources": [{"source_id": "valuation_snapshot:100", "source_type": "valuation_snapshot", "title": "MSFT valuation", "authority": "derived"}],
  "freshness": {"as_of": "2026-07-29T12:00:00Z", "status": "fresh", "age_seconds": 120, "ttl_seconds": 129600, "reason": "latest daily valuation snapshot"},
  "warnings": [],
  "meta": {"request_id": "uuid", "generated_at": "2026-07-29T12:02:00Z", "symbols": ["MSFT"], "data_version": "v1"}
}
```

Times are timezone-aware ISO 8601. Missing values are `null`. Monetary fields name their currency or unit; percentages use `_percent` or an explicit `unit`. Enums are stable English protocol values.

## Sources and freshness

`source_id` is deterministic from the existing record type and primary key. `locator` uses an internal `research://` identifier and never an absolute server path. SEC records use `official`; provider/company records use `primary` or `secondary`; calculations use `derived`; user-owned portfolios and trades use `user`.

Freshness TTLs are centralized in `app/research/freshness.py`. Price snapshots use 5 minutes, news 6 hours, valuations 36 hours, technical analysis 24 hours, financial statements 120 days, and portfolio positions 10 minutes. SEC filings have no expiry because an old filing remains an authoritative historical record. Financial responses expose both report period and ingestion time so callers do not confuse a recent sync with a recent fiscal period.

## Errors

Gateway-generated errors use `{request_id, error: {code, message, field, context}}`. Stable codes include `RESEARCH_NOT_FOUND`, `INVALID_SYMBOL`, `INVALID_DATE_RANGE`, `INVALID_PARAMETER`, `FORBIDDEN_RESOURCE`, `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, `FILE_NOT_FOUND`, `FILE_ACCESS_DENIED`, `DATA_INCOMPLETE`, and `INTERNAL_RESEARCH_ERROR`. Database details, Redis URLs, credentials, and filesystem paths are not returned.

## Authorization and audit boundary

All routes reuse bearer authentication. Clients cannot submit a `user_id`. Portfolio selection is constrained by `portfolios.user_id`; discovery runs and candidates are constrained by `stock_discovery_runs.user_id`. An inaccessible private record deliberately returns the same 404 surface as a missing record.

Audit logs include request ID, authenticated user ID, endpoint, bounded query filters, status, duration, and error code. They exclude authorization headers, secrets, article/filing bodies, raw payloads, and transaction content. The request ID is also returned in `X-Request-ID` and `meta.request_id`.

## File safety

Chart access accepts a symbol, never a path. The service resolves the database record, resolves the stored path against `technical_chart_dir`, verifies it remains inside that root, allows only WebP/PNG/JPEG, enforces a size ceiling, and returns stable errors for missing or denied files. The same `resolve_safe_file` primitive is available for future archive/EDGAR readers. News archive v1 reads PostgreSQL content, so it does not need a volume fallback.

## Limits and current exclusions

Page size is capped at 100. Daily prices are capped at 2,500 rows and ten years per request; calendar queries are capped at two years. Financial/valuation provider JSON is deliberately summarized. Phase v1 does not expose full SEC/news documents, arbitrary archive files, Redis internals, standalone live market-index/FX endpoints, or raw discovery model responses. Public-figure data is persisted disclosure data and does not infer political positions. Missing persisted data produces an empty result with a warning or a stable not-found error; it never triggers a third-party fetch.

## AI tool integration

The implemented AI Tool layer calls `ResearchGateway` methods directly for in-process use. Tools preserve the envelope so citations can use `sources`, recency decisions can use `freshness`, and audit correlation can use request IDs. They do not import ORM models or read volumes directly.

## Examples

Set `TOKEN` to a valid bearer token and `BASE_URL` to the deployment URL:

```bash
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/capabilities"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/portfolio/summary"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/news?symbol=MSFT&limit=10"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/sec/filings?symbol=MSFT&form_type=10-Q"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/companies/MSFT/financials/summary"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/companies/MSFT/valuation"
curl -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/research/v1/companies/MSFT/technical"
```
## Relationship to the AI Tool layer

The Research Data Gateway remains the authoritative read boundary and is intentionally separate from the AI Tool Adapter layer documented in [`ai-tool-layer.md`](./ai-tool-layer.md). The Tool layer consumes request-scoped `ResearchGateway` service methods, adds semantic aggregation, strict model-facing arguments, policy/budget/timeout controls, deterministic compression, caching, and tool-call audit. It does not move repository access into adapters or turn Research routes into one-to-one model tools.
