# Options analytics

The Options module is a research and sentiment data layer, not an execution or recommendation system.

## Sources and universe

- yfinance is the primary option-chain source. The provider checks the runtime schema and treats missing fields as unavailable.
- Finnhub supplies only the existing underlying quote and security metadata fallback. The project does not claim a Finnhub options endpoint.
- The maintained universe is bounded to SPY/QQQ/IWM, the 11 first-level sector ETFs already registered by Industry Pulse, a small liquid secondary-proxy set, and enabled watchlist securities with a valid Yahoo symbol. It never scans the full security universe.
- ETF-to-sector and stock-to-industry links reuse `IndustryPulseNode`, `IndustryPulseInstrument`, and `ETF_REGISTRY`. Watchlist display groups remain supplementary user organization, not sector authority.

## Refresh and retention

Celery performs a cheap database-backed due check and queues a bounded refresh at most every six hours. Each symbol is isolated, retried with a timeout, and protected by the existing Redis plus durable-run pattern. The worker reads at most two relevant expirations per symbol. A watchlist addition queues the same single-symbol path.

Filtered contracts are cached for 12 hours for detail views; they are not an unlimited contract ledger. One aggregate row per symbol and market date is retained for 365 days by default. Daily uniqueness makes repeated jobs idempotent.

## Metrics and quality

The deterministic layer produces call/put volume, open interest, put/call ratios, total volume/OI and volume-to-OI turnover, representative multi-sample ATM IV, near/next-term IV, IV change, strike distributions, largest OI strikes/concentration, and downside/upside skew. Bias is reported as `CALL_HEAVY`, `SLIGHT_CALL_HEAVY`, `BALANCED`, `SLIGHT_PUT_HEAVY`, `PUT_HEAVY`, or `MIXED`; it is a call/put volume and OI description, not a directional recommendation. Skew uses a clearly labelled moneyness proxy because Yahoo does not provide reliable complete Greeks.

IV calculations reject missing or non-finite values, zero IV, unreasonable IV, stale trades, very wide spreads, and extreme moneyness. Every result includes coverage, sample size, warnings, and HIGH/MEDIUM/LOW quality. `NO_OPTIONS`, `NO_VALID_EXPIRATION`, `PROVIDER_ERROR`, `STALE_DATA`, `INSUFFICIENT_LIQUIDITY`, and `INSUFFICIENT_HISTORY` remain explicit; missing values are never rendered as zero.

Activity is explainable trading activity, not a predicted return or buy/sell score. When enough observed snapshots exist, `activity_score` is an empirical self-history percentile (60 observations when at least 30 prior points exist, otherwise 20 observations when at least 10 exist). Changes use 1/5/20 observed snapshots; rolling averages use 7/20/30/60 observed snapshots, so weekends and missing calendar dates do not create fake zeros. Percentiles, z-scores, and anomaly labels remain `INSUFFICIENT_HISTORY`/`N/A` until their minimum samples are available. A z-score of 2/3 is `HIGH`/`EXTREME`; anomaly direction is separate from the one-step trend.

With only two stored snapshots, most historical comparisons are intentionally unavailable. The API still returns current IV/skew, OI concentration, quality, and explicit sample/warning metadata; it does not manufacture a percentile or regime.

## Consumers

Authenticated `/api/options` endpoints serve the Market, Sector, Watchlist, common detail, history, filtered-chain, and ranking views. Chat tools and Report Center consume the same persisted aggregate service and never request raw database access or insert a complete chain into model context.

AI/report consumers receive the same persisted aggregate `OptionsState` (activity, bias, risk_pricing, positioning, and historical_regime), with raw chains excluded and history capped. Risk pricing is limited to IV, skew, term structure, sample quality, and historical comparisons. This module intentionally does not implement the final Mood score, option premium/expected-move pricing, Greeks, dealer/participant positioning, OI-change flow, or intraday tape inference.
