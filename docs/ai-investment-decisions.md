# AI Investment Decision Memory

An investment decision records what the user decided at a specific time and
why. It is not a preference and is never rewritten as market data changes.
Decisions store action, symbols, horizon, targets, thesis, catalysts, risks,
assumptions, questions and invalidation conditions. Evidence and reviews live
in separate tables.

Every creation path produces `draft`. Only the explicit confirmation API or
“保存为正式决策” action makes it active. Drafts may come from explicit decision
language, an assistant message action with citation metadata, or the manual
editor at `/investment-decisions`. Confirmed core thesis fields are immutable;
material later changes belong in a review.

Evidence stores bounded source metadata and a short factual summary only.
Origins distinguish internal, web, deep search and user statements; roles
distinguish support, contradiction, risk, context and invalidation. Duplicate
decision/source pairs are deduplicated, URLs reuse the safe URL policy, and no
article or SEC body is saved. Freshness is calculated for display without
changing the original record.

The state machine is:

`draft → active → executed | partially_executed | cancelled | invalidated | closed | archived`

Execution is a user-entered journal state, not an order. Optional portfolio and
trade links require ownership validation. Deletion is soft.

Reviews are independent records with thesis/invalidation status, changed facts,
lessons and next action. The default review draft is offline and does not call a
model, Exa, or Deep Search. Fresh tool-backed analysis can be requested through
normal chat. Paid Deep Search requires the user's existing explicit mode choice.
`review_due` is a display-only calculation from `target_review_at` or stale
saved evidence.

The `/api/ai/v1/investment-decisions` APIs cover CRUD, confirmation, manual
execution marking, lifecycle transitions, evidence, reviews and
message-to-draft creation. Lists filter by search text, symbol, state, type,
horizon, date, confidence, review status and portfolio.

The frontend includes draft editing, evidence display, manual execution,
restrained state styling, related portfolio/trade/conversation metadata, and an
editable review confirmation timeline. Read-only tools list decisions, retrieve
a decision/reviews, and filter by symbol. `AI_INVESTMENT_DECISION_*` defaults
are in `.env.example`. Nothing automatically trades or changes portfolio state.
