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

The deterministic layer produces call/put volume, open interest, put/call ratios, representative ATM IV, near/next-term IV, IV change, strike distributions, major OI levels, and downside/upside skew. Skew uses a clearly labelled moneyness proxy because Yahoo does not provide reliable complete Greeks.

IV calculations reject missing or non-finite values, zero IV, unreasonable IV, stale trades, very wide spreads, and extreme moneyness. Every result includes coverage, sample size, warnings, and HIGH/MEDIUM/LOW quality. `NO_OPTIONS`, `NO_VALID_EXPIRATION`, `PROVIDER_ERROR`, `STALE_DATA`, `INSUFFICIENT_LIQUIDITY`, and `INSUFFICIENT_HISTORY` remain explicit; missing values are never rendered as zero.

Activity is explainable trading activity, not a predicted return or buy/sell score. Historical percentile, rank, z-score, and unusual-activity labels remain unavailable until sufficient daily history exists.

## Consumers

Authenticated `/api/options` endpoints serve the Market, Sector, Watchlist, common detail, history, filtered-chain, and ranking views. Chat tools and Report Center consume the same persisted aggregate service and never request raw database access or insert a complete chain into model context.

Future AI Mood work can consume the stable fields for IV, IV change and term structure, put/call volume and OI, call/put activity, moneyness-proxy skew, activity, quality, coverage, and timestamp alongside News, Social, Price, Volume, Sector, and Institutional evidence. This module intentionally does not implement the final Mood score.
