import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services.realtime_market import (
    IntradayBar,
    ProviderHealth,
    RealtimeQuote,
    RealtimeQuoteEnvelope,
    RealtimeStateStore,
    StreamingSupervisor,
    backfill_missing_bars,
    detect_reconnect_gap,
    health_key,
    quote_key,
)
from app.services.realtime_market.state import REALTIME_UPDATES_CHANNEL


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.published = []

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def publish(self, channel, value):
        self.published.append((channel, value))


def make_quote():
    now = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
    return RealtimeQuote(symbol="MSFT", price=100, timestamp=now, received_at=now, provider="alpaca", feed="iex")


def test_redis_state_uses_fixed_keys_ttl_and_event_channel():
    redis = FakeRedis()
    store = RealtimeStateStore(redis, ttl_seconds=42)
    quote = make_quote()
    assert store.set_quote(quote)
    assert quote_key("msft") in redis.values
    restored = store.get_quote("MSFT")
    assert restored is not None and restored.price == quote.price
    health = ProviderHealth(provider="alpaca", connected=True)
    assert store.set_health(health)
    assert store.get_health("alpaca")["connected"] is True
    assert health_key("alpaca") in redis.values
    assert [channel for channel, _ in redis.published] == [REALTIME_UPDATES_CHANNEL, REALTIME_UPDATES_CHANNEL]
    events = [json.loads(payload)["event"] for _, payload in redis.published]
    assert events == ["quote_update", "provider_status"]


def test_redis_state_keeps_envelope_provenance_while_get_quote_unwraps_authority():
    redis = FakeRedis()
    store = RealtimeStateStore(redis)
    primary = make_quote()
    reference = RealtimeQuote(
        symbol="MSFT", price=100.2, timestamp=primary.timestamp,
        received_at=primary.received_at, provider="tiingo", feed="consolidated",
        source_role="reference",
    )
    envelope = RealtimeQuoteEnvelope(symbol="MSFT", authoritative_quote=primary, alternate_quotes=(reference,))
    assert store.set_quote(envelope)
    raw = json.loads(redis.values[quote_key("MSFT")])
    assert raw["authoritative_quote"]["provider"] == "alpaca"
    assert raw["alternate_quotes"][0]["provider"] == "tiingo"
    assert store.get_quote("MSFT").provider == "alpaca"


def test_reconnect_gap_starts_at_next_minute_and_dedupes_backfill():
    last = datetime(2026, 8, 7, 15, 0, 22, tzinfo=UTC)
    reconnect = datetime(2026, 8, 7, 15, 3, 2, tzinfo=UTC)
    gap = detect_reconnect_gap(last, reconnect, symbol="MSFT")
    assert gap is not None and gap.start == datetime(2026, 8, 7, 15, 1, tzinfo=UTC)


class FakeHistoryProvider:
    name = "tiingo"

    async def get_intraday_bars(self, symbol, interval="1m", start=None, end=None):
        return [
            IntradayBar(symbol=symbol, timestamp=start, interval="1m", open=1, high=2, low=1, close=2, provider=self.name, feed="consolidated"),
            IntradayBar(symbol=symbol, timestamp=start, interval="1m", open=1, high=2, low=1, close=2, provider=self.name, feed="consolidated"),
        ]


def test_backfill_provider_failure_isolated_and_rows_deduped():
    result = asyncio.run(backfill_missing_bars(
        "MSFT", [FakeHistoryProvider()],
        last_valid_market_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=UTC),
        reconnect_at=datetime(2026, 8, 7, 15, 3, tzinfo=UTC),
    ))
    assert result.provider == "tiingo"
    assert result.count == 1


class FakeStream:
    name = "fake"

    def __init__(self):
        self.closed = False
        self.subscribed = []

    async def connect(self):
        return None

    async def subscribe(self, symbols):
        self.subscribed.append(tuple(symbols))

    async def unsubscribe(self, symbols):
        return None

    async def stream(self):
        if False:
            yield make_quote()
        return

    async def close(self):
        self.closed = True

    async def health_check(self):
        return ProviderHealth(provider=self.name, connected=True)


def test_stream_supervisor_stops_provider_without_leaking_disconnect():
    provider = FakeStream()
    supervisor = StreamingSupervisor(provider, symbols=["MSFT", "MSFT"])
    asyncio.run(supervisor.run_once())
    assert supervisor.connected is False
    assert provider.subscribed == [("MSFT",)]
    asyncio.run(supervisor.stop())
    assert provider.closed is True


def test_stream_supervisor_reconnects_connected_but_stale_transport():
    provider = FakeStream()
    supervisor = StreamingSupervisor(provider, stale_after_seconds=30)
    now = datetime.now(UTC)
    supervisor.connected = True
    supervisor.connected_at = now - timedelta(seconds=31)

    assert asyncio.run(supervisor.reconnect_if_stale(now=now)) is True
    assert supervisor.connected is False
    assert supervisor.last_error == "stream stale; reconnect requested"
    assert provider.closed is True


def test_stream_supervisor_allows_new_connection_message_grace_period():
    provider = FakeStream()
    supervisor = StreamingSupervisor(provider, stale_after_seconds=30)
    now = datetime.now(UTC)
    supervisor.connected = True
    supervisor.connected_at = now - timedelta(seconds=29)

    assert asyncio.run(supervisor.reconnect_if_stale(now=now)) is False
    assert supervisor.connected is True
    assert provider.closed is False
