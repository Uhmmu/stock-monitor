"""Provider priority, fallback, freshness and cross-provider divergence."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings

from .contracts import (
    IntradayBar,
    ProviderError,
    ProviderHealth,
    QuoteDivergence,
    RealtimeQuote,
    RealtimeQuoteEnvelope,
)
from .providers import AlpacaRealtimeProvider, ProviderRegistry, RealtimeMarketDataProvider, TiingoRealtimeProvider
from .session import is_quote_stale

logger = logging.getLogger(__name__)


def configured_provider_order(settings: Settings | None = None) -> tuple[str, ...]:
    value = settings or get_settings()
    raw = str(getattr(value, "realtime_provider_order", "alpaca,tiingo,finnhub,yfinance") or "")
    names = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return tuple(dict.fromkeys(names))


def _price_difference(primary: RealtimeQuote, reference: RealtimeQuote, threshold_pct: float) -> QuoteDivergence | None:
    if primary.price is None or reference.price is None or primary.price <= 0 or reference.price <= 0:
        return None
    absolute = abs(primary.price - reference.price)
    percentage = absolute / primary.price * 100
    timestamp_difference = abs((primary.timestamp - reference.timestamp).total_seconds())
    return QuoteDivergence(
        symbol=primary.symbol,
        primary_provider=primary.provider,
        reference_provider=reference.provider,
        primary_price=primary.price,
        reference_price=reference.price,
        absolute_difference=absolute,
        percentage_difference=percentage,
        timestamp_difference_seconds=timestamp_difference,
        warning=percentage >= max(0.0, threshold_pct),
    )


def calculate_divergence(
    primary: RealtimeQuote,
    reference: RealtimeQuote,
    *,
    warn_pct: float | None = None,
) -> QuoteDivergence | None:
    threshold = warn_pct
    if threshold is None:
        threshold = float(getattr(get_settings(), "realtime_price_divergence_warn_pct", 0.5))
    return _price_difference(primary, reference, threshold)


class ProviderRouter:
    """Route quote/history reads while isolating individual provider failures."""

    def __init__(
        self,
        providers: ProviderRegistry | Iterable[RealtimeMarketDataProvider] = (),
        *,
        order: Iterable[str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.registry = providers if isinstance(providers, ProviderRegistry) else ProviderRegistry(providers)
        self.order = tuple(name.strip().lower() for name in (order or configured_provider_order(self.settings)) if name.strip())
        self.last_errors: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ProviderRouter":
        value = settings or get_settings()
        providers: list[RealtimeMarketDataProvider] = []
        if bool(getattr(value, "alpaca_market_data_enabled", False)):
            providers.append(AlpacaRealtimeProvider(settings=value))
        if bool(getattr(value, "tiingo_market_data_enabled", False)):
            providers.append(TiingoRealtimeProvider(settings=value))
        return cls(providers, settings=value)

    def _provider_order(self) -> list[RealtimeMarketDataProvider]:
        providers: list[RealtimeMarketDataProvider] = []
        for name in self.order:
            provider = self.registry.get(name)
            if provider is not None:
                providers.append(provider)
        # Providers registered by a caller but absent from configuration remain
        # usable as an explicit test/fallback provider after configured entries.
        seen = {provider.name for provider in providers}
        providers.extend(provider for provider in self.registry.values() if provider.name not in seen)
        return providers

    async def get_quote(
        self,
        symbol: str,
        *,
        stale_after_seconds: float | None = None,
        divergence_warn_pct: float | None = None,
    ) -> RealtimeQuoteEnvelope:
        stale_threshold = float(
            stale_after_seconds
            if stale_after_seconds is not None
            else getattr(self.settings, "realtime_stale_seconds", 45)
        )
        candidates: list[RealtimeQuote] = []
        self.last_errors = {}
        for provider in self._provider_order():
            try:
                quote = await provider.get_quote(symbol)
                if quote.symbol != symbol.strip().upper():
                    # Do not silently attach another symbol to this request.
                    self.last_errors[provider.name] = "provider_symbol_mismatch"
                    continue
                candidates.append(quote)
            except ProviderError as exc:
                self.last_errors[provider.name] = str(exc)
            except Exception as exc:  # provider isolation boundary
                self.last_errors[provider.name] = f"{type(exc).__name__}"

        if not candidates:
            detail = ", ".join(f"{name}:{error}" for name, error in self.last_errors.items()) or "no providers configured"
            raise ProviderError(f"no realtime quote available for {symbol}: {detail}", provider="router")

        fresh = [quote for quote in candidates if not is_quote_stale(quote, max_age_seconds=stale_threshold)]
        authoritative = fresh[0] if fresh else candidates[0]
        alternates = tuple(quote for quote in candidates if quote is not authoritative)
        # Tiingo reference data is useful even when Alpaca is primary.  The
        # first alternate is enough for a deterministic warning; all alternates
        # remain in the envelope for provenance and diagnostics.
        divergence = calculate_divergence(
            authoritative,
            alternates[0],
            warn_pct=divergence_warn_pct,
        ) if alternates else None
        return RealtimeQuoteEnvelope(
            symbol=authoritative.symbol,
            authoritative_quote=authoritative,
            alternate_quotes=alternates,
            divergence=divergence,
            stale=is_quote_stale(authoritative, max_age_seconds=stale_threshold),
        )

    async def get_quotes(
        self,
        symbols: list[str],
        *,
        stale_after_seconds: float | None = None,
        divergence_warn_pct: float | None = None,
    ) -> list[RealtimeQuoteEnvelope]:
        output: list[RealtimeQuoteEnvelope] = []
        for symbol in dict.fromkeys(value.strip().upper() for value in symbols if value.strip()):
            try:
                output.append(await self.get_quote(symbol, stale_after_seconds=stale_after_seconds, divergence_warn_pct=divergence_warn_pct))
            except ProviderError:
                continue
        return output

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "1m",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[IntradayBar]:
        self.last_errors = {}
        for provider in self._provider_order():
            try:
                rows = await provider.get_intraday_bars(symbol, interval, start, end)
                if rows:
                    return rows
            except ProviderError as exc:
                self.last_errors[provider.name] = str(exc)
            except Exception as exc:
                self.last_errors[provider.name] = type(exc).__name__
        return []

    async def health(self) -> list[ProviderHealth]:
        rows: list[ProviderHealth] = []
        for provider in self._provider_order():
            try:
                rows.append(await provider.health_check())
            except Exception as exc:
                rows.append(ProviderHealth(provider=provider.name, connected=False, last_error=type(exc).__name__))
        return rows

    async def aclose(self) -> None:
        for provider in self.registry.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result


async def route_quote(
    symbol: str,
    providers: ProviderRegistry | Iterable[RealtimeMarketDataProvider],
    *,
    order: Iterable[str] | None = None,
    settings: Settings | None = None,
) -> RealtimeQuoteEnvelope:
    return await ProviderRouter(providers, order=order, settings=settings).get_quote(symbol)


RealtimeProviderRouter = ProviderRouter
