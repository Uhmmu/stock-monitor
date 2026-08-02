# Unified investment ledger

## Boundary

`backend/app/services/portfolio/investment_ledger.py` is the portfolio-domain
read boundary for account facts. Portfolio routes, position details, health,
Research Gateway, AI Tools, and exports should consume its DTOs instead of
joining IBKR typed records independently.

The evidence remains in the existing IBKR tables. The ledger does not copy the
15k+ Flex rows and never performs provider IO.

## Authority order

For matched securities, IBKR Flex is authoritative for quantity, average cost,
cost basis, executions, cash, dividends, fees/taxes, lots, and realized P&L.
The project market-data layer remains authoritative for current and historical
prices. A dated IBKR report mark is only an explicit fallback.

Unmatched securities and non-broker portfolios retain manual/journal support.
The model is source-explicit (`manual`, `journal`, `import`, `ibkr_flex`, and
future broker values) rather than IBKR-only.

## Manual fact governance

Migration `0046_unified_investment_ledger` adds source, authority, status,
supersession, sync-run, source-record, confidence, and match-method fields to
`trade_transactions`.

Matched manual rows are never physically deleted. Exact date/side/quantity/
price matches link to an IBKR trade. Account-level replacements retain a match
method. Pre-coverage rows without lot/prior-position evidence become
`historical_unverified`. Both statuses are excluded from current accounting and
hidden from the default transaction feed, but remain queryable for audit.

IBKR-managed quantities, costs, executions, and fees cannot be edited through
manual Portfolio APIs. Notes and investment-decision features remain separate
user-owned context.

## Portfolio APIs

- `GET /api/portfolio/summary`: account overview and enriched positions.
- `GET /api/portfolio/performance?range=1M|3M|6M|YTD|1Y|ALL`: NAV,
  contributions, investment value, TWR, and drawdown.
- `GET /api/portfolio/attribution`: persisted position attribution.
- `GET /api/portfolio/positions/{symbol}`: personal position summary, personal
  performance curve, timeline, lots, and completed trades.
- `GET /api/portfolio/transactions`: unified executions, dividends, fees,
  taxes, and account cash activity. Superseded manual rows are opt-in.
- `GET /api/portfolio/completed-trades`: completed FIFO round trips.
- `GET /api/portfolio/open-lots`: broker tax lots and unmatched manual lots.

Returns distinguish IBKR facts, project market data, and project-derived
calculations. Missing history remains missing; current holdings are never used
to backfill a historical curve.

## Return conventions

Account performance prefers IBKR daily NAV. Daily return removes external net
cash flow before measuring investment performance; deposits are not profit and
sale proceeds are not income. Cumulative return compounds daily returns. Simple
cumulative return is shown separately. Position total P&L is:

`unrealized + gross realized + gross dividends - commissions - taxes`

The UI labels the method and completeness. Historical performance is exposed to
portfolio health as a separate account-history section and does not alter the
existing fundamental/valuation/SEC objective score.

## Propagation

Successful Flex sync reconciles positions, governs manual records, rebuilds
analytics, updates account cash, bumps the private portfolio generation, and
clears private AI Tool caches. The IBKR frontend invalidates summary,
performance, health, attribution, transactions, lots, completed trades, and
position-detail query families when the sync reaches `completed`.

## Migration and rollback

Before production migration, create and verify a PostgreSQL backup. Upgrade all
backend roles because they share the backend image. Rollback order:

1. Restore the pre-deployment backend/frontend images.
2. Run `alembic downgrade 0045_ibkr_account_analytics` if the application code
   has also been rolled back.
3. If accounting data needs exact point-in-time restoration, restore the
   verified database backup instead of manually editing authority fields.

The downgrade removes only the new governance columns and indexes. It does not
delete IBKR evidence tables or manual transactions.

## Known gaps

- Benchmark history remains a separate project-price comparison and is not yet
  merged point-by-point into every IBKR performance row.
- Position daily curves depend on persisted IBKR position-performance coverage;
  missing days are not interpolated.
- Industry and currency P&L attribution are shown only where persisted typed
  inputs support them; no values are inferred from names.
- Orders remain IBKR diagnostic context. Executions are the investment facts.
