import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.services.realtime_market import (
    ProviderHealth,
    ProviderRouter,
    RealtimeQuote,
    calculate_divergence,
    is_quote_stale,
    market_session_at,
)
from app.services.realtime_market.contracts import ProviderError


def make_quote(provider: str, price: float, *, received_at: datetime | None = None) -> RealtimeQuote:
    moment = datetime(2026, 8, 7, 14, 32, tzinfo=UTC)
    return RealtimeQuote(
        symbol="NVDA", price=price, timestamp=moment,
        received_at=received_at or moment, provider=provider, feed="iex",
    )


class FakeProvider:
    def __init__(self, name: str, quote: RealtimeQuote | None = None, error: Exception | None = None):
        self.name = name
        self.quote = quote
        self.error = error

    async def get_quote(self, symbol: str):
        if self.error:
            raise self.error
        return self.quote

    async def get_quotes(self, symbols):
        return [self.quote] if self.quote else []

    async def get_intraday_bars(self, symbol, interval="1m", start=None, end=None):
        return []

    async def health_check(self):
        return ProviderHealth(provider=self.name, connected=self.error is None)


def test_router_fallback_and_reference_divergence():
    primary = FakeProvider("alpaca", error=ProviderError("down", provider="alpaca"))
    tiingo = FakeProvider("tiingo", make_quote("tiingo", 100.8))
    router = ProviderRouter([primary, tiingo], order=["alpaca", "tiingo"], settings=type("S", (), {"realtime_stale_seconds": 60, "realtime_price_divergence_warn_pct": .5})())
    envelope = asyncio.run(router.get_quote("NVDA"))
    assert envelope.authoritative_quote.provider == "tiingo"
    assert envelope.alternate_quotes == ()
    assert envelope.divergence is None


def test_router_keeps_alternate_and_flags_large_divergence():
    primary = FakeProvider("alpaca", make_quote("alpaca", 100.0))
    tiingo = FakeProvider("tiingo", make_quote("tiingo", 101.0))
    router = ProviderRouter([primary, tiingo], order=["alpaca", "tiingo"], settings=type("S", (), {"realtime_stale_seconds": 60, "realtime_price_divergence_warn_pct": .5})())
    envelope = asyncio.run(router.get_quote("NVDA"))
    assert envelope.authoritative_quote.provider == "alpaca"
    assert envelope.divergence is not None and envelope.divergence.warning is True


def test_stale_quote_and_market_session_are_utc_based():
    now = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
    quote = make_quote("alpaca", 100, received_at=now - timedelta(seconds=61))
    assert is_quote_stale(quote, now=now, max_age_seconds=60)
    assert market_session_at(datetime(2026, 8, 7, 12, 0, tzinfo=UTC)) == "premarket"
    assert market_session_at(datetime(2026, 8, 7, 15, 0, tzinfo=UTC)) == "regular"
    assert market_session_at(datetime(2026, 8, 7, 22, 0, tzinfo=UTC)) == "afterhours"


def test_divergence_uses_primary_denominator_and_timestamp_difference():
    primary = make_quote("alpaca", 100)
    reference = replace(primary, provider="tiingo", price=101, timestamp=primary.timestamp + timedelta(seconds=3))
    value = calculate_divergence(primary, reference, warn_pct=.5)
    assert value is not None
    assert value.absolute_difference == 1
    assert value.percentage_difference == 1
    assert value.timestamp_difference_seconds == 3
    assert value.warning
