"""Provider-neutral realtime market data boundary.

The package deliberately has no FastAPI, SQLAlchemy, or Celery imports.  API
and worker layers can compose these contracts with the existing
``price_snapshots``/``intraday_market`` persistence services.
"""

from .aggregation import MinuteBarAggregator, MinuteAggregator, aggregate_quotes, minute_bucket
from .backfill import BackfillCoordinator, BackfillGap, BackfillResult, backfill_missing_bars, detect_reconnect_gap
from .contracts import (
    IntradayBar,
    MarketSession,
    ProviderError,
    ProviderHealth,
    QuoteDivergence,
    RealtimeQuote,
    RealtimeQuoteEnvelope,
    ensure_utc,
    normalize_market_session,
)
from .normalization import (
    normalize_alpaca_bar,
    normalize_alpaca_message,
    normalize_alpaca_quote,
    normalize_alpaca_rest_quotes,
    normalize_alpaca_rest_trades,
    normalize_alpaca_trade,
    normalize_provider_message,
    normalize_tiingo_message,
    normalize_tiingo_quote,
    normalize_tiingo_rest_rows,
)
from .providers import (
    AlpacaMarketDataProvider,
    AlpacaRealtimeProvider,
    ProviderRegistry,
    RealtimeMarketDataProvider,
    StreamingMarketDataProvider,
    TiingoMarketDataProvider,
    TiingoRealtimeProvider,
)
from .routing import ProviderRouter, RealtimeProviderRouter, calculate_divergence, configured_provider_order, route_quote
from .session import canonical_session, is_market_open, is_quote_stale, market_session_at, session_metadata
from .state import (
    INTRADAY_BAR_KEY_PREFIX,
    PROVIDER_HEALTH_KEY_PREFIX,
    PROVIDER_HEALTH_KEY_SUFFIX,
    REALTIME_QUOTE_KEY_PREFIX,
    REALTIME_UPDATES_CHANNEL,
    RealtimeStateStore,
    bar_key,
    health_key,
    quote_key,
)
from .stream import ExponentialJitterBackoff, StreamingSupervisor

__all__ = [
    "AlpacaRealtimeProvider",
    "AlpacaMarketDataProvider",
    "BackfillCoordinator",
    "BackfillGap",
    "BackfillResult",
    "ExponentialJitterBackoff",
    "INTRADAY_BAR_KEY_PREFIX",
    "IntradayBar",
    "MarketSession",
    "MinuteAggregator",
    "MinuteBarAggregator",
    "PROVIDER_HEALTH_KEY_PREFIX",
    "PROVIDER_HEALTH_KEY_SUFFIX",
    "ProviderError",
    "ProviderHealth",
    "ProviderRegistry",
    "ProviderRouter",
    "RealtimeProviderRouter",
    "QuoteDivergence",
    "REALTIME_QUOTE_KEY_PREFIX",
    "REALTIME_UPDATES_CHANNEL",
    "RealtimeMarketDataProvider",
    "RealtimeQuote",
    "RealtimeQuoteEnvelope",
    "RealtimeStateStore",
    "StreamingMarketDataProvider",
    "StreamingSupervisor",
    "TiingoRealtimeProvider",
    "TiingoMarketDataProvider",
    "aggregate_quotes",
    "backfill_missing_bars",
    "bar_key",
    "calculate_divergence",
    "canonical_session",
    "configured_provider_order",
    "detect_reconnect_gap",
    "ensure_utc",
    "health_key",
    "is_market_open",
    "is_quote_stale",
    "market_session_at",
    "minute_bucket",
    "normalize_alpaca_bar",
    "normalize_alpaca_message",
    "normalize_alpaca_quote",
    "normalize_alpaca_rest_quotes",
    "normalize_alpaca_rest_trades",
    "normalize_alpaca_trade",
    "normalize_market_session",
    "normalize_provider_message",
    "normalize_tiingo_message",
    "normalize_tiingo_quote",
    "normalize_tiingo_rest_rows",
    "quote_key",
    "route_quote",
    "session_metadata",
]
