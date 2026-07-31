# AI Long-Term User Memory

Long-term memory is stable, user-owned context reusable across conversations. It
is separate from conversation summaries and time-stamped decisions. Version one
uses SQL filters and keyword scoring only—no vector store or embeddings.

Types are a closed allow-list covering investment style, risk/portfolio
constraints, valuation/market/research/communication preferences, goals,
projects, symbol interests and recurring workflows. Scopes are `global`,
`portfolio`, `symbol`, `project`, and `page_context`.

States are `proposed`, `active`, `rejected`, `stale`, `expired`, `archived`, and
soft-deleted. Inferred candidates stay proposed until confirmed. Explicit
“记住…” and manual UI actions are controlled writes; the model has no write
tool. Every lifecycle change is recorded in `ai_memory_events`.

Candidate extraction rejects short-lived market facts, common prompt injection
forms, credentials/account identifiers and sensitive personal categories.
Sensitive storage defaults off. If enabled, a sensitive entry is still first a
proposal and requires another explicit confirmation.

Duplicates use a normalized SHA-256 signature scoped by owner/type/scope.
Comparable changed constraints link to the prior memory; confirming the
replacement archives the old record so conflicts are not injected together.
Risk constraints default to annual reconfirmation, symbol interests to six
months, project context to a year and recurring workflows to 90 days. Stale and
expired records remain visible but are excluded from answers.

`RelevantMemoryRetriever` performs one user-scoped query, structured scope
filtering, keyword/importance ranking and item/character limits. Current user
instructions remain higher priority.

Because Exa queries are model-authored, saved memory and decisions are omitted
from all web-enabled turns. Offline chat records exact usage in
`ai_message_memory_usage`; the message action discloses used memories and their
last confirmation dates.

`/ai-memory` exposes per-user switches, active/proposed/stale/expired/archive
sections, editing, reconfirmation, history and forgetting. Chat provides
candidate confirmation, “记住这条”, and per-answer usage management.

The `/api/ai/v1` API includes `memory-settings`, `memories` CRUD and lifecycle
actions, `memory-candidates`, message extraction, explicit forget, and
`messages/{id}/memory-usage`. Listing supports lifecycle/type/scope/source/date
filters and cursor pagination. `AI_MEMORY_*` environment defaults and limits
are documented in `.env.example`.

Read-only model tools are
`get_relevant_user_memories`, `list_user_memories`, and `get_user_memory`.
The tools expose active memory only. Every query includes `user_id`; missing
and unauthorized records both return 404.
