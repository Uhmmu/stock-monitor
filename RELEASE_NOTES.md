# Release Notes

## v0.3.0 — Multi-user workspace and deeper research metrics

This release turns Stock Monitor from a single-user monitoring dashboard into a multi-user research workspace.

### Highlights

- **Multi-user authentication**
  - Username/password login with JWT sessions.
  - Self-service registration requests.
  - Admin approval and user management.
  - Separate administrator and regular-user permissions.

- **Trading Journal**
  - Create, edit and delete personal trade journal entries.
  - Record ticker, date, direction, quantity, price, notes, strategy tags and review content.
  - Attach images and structured trade rows.
  - Generate an AI-assisted summary for a journal entry.

- **Computed financial indicators**
  - Added annual financial-statement normalization using yfinance.
  - Added deterministic ROIC calculation using NOPAT and invested capital.
  - Added Piotroski F-Score with partial-result reporting such as `6/8` when some signals are unavailable.
  - Added Altman Z-Score with industry applicability warnings.
  - Added explicit missing-field, formula-version, source and warning metadata.

- **Cross-model research view**
  - Combines valuation, growth and financial-health models.
  - Shows model weights, peer comparisons, DCF scenarios and model conflicts.
  - Keeps AI explanations separate from deterministic numeric calculations.

### Data quality behavior

Missing financial fields are no longer silently treated as zero or as a failed signal. The UI distinguishes between available, partial, insufficient and not-applicable results, so users can tell the difference between weak company fundamentals and incomplete source coverage.

### Upgrade notes

1. Back up PostgreSQL before upgrading.
2. Copy `.env.example` values into your deployment configuration and set a strong `JWT_SECRET` and `ADMIN_INIT_PASSWORD`.
3. Run the database migration through the API container.
4. Rebuild all backend roles (`api`, `worker`, `sec-worker`, `beat`) and the frontend image.
5. Refresh the cross-model snapshot after deployment so the new annual-statement calculations are populated.

### Verification

- Backend cross-model tests pass.
- Frontend TypeScript check and production Vite build pass.
- Production containers and `/api/health` endpoint verified after deployment.

