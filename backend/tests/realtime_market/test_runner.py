import asyncio
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.services.realtime_market.contracts import RealtimeQuote
from app.services.realtime_market.runner import MarketStreamRuntime, _eligible_symbol
from app.services.realtime_market.stream import ExponentialJitterBackoff, StreamingSupervisor


class MemoryState:
    def __init__(self):
        self.quotes = []
        self.published = []
        self.health = []

    def set_quote(self, envelope):
        self.quotes.append(envelope)
        return True

    def set_bar(self, bar, *, publish=True):
        if publish:
            self.publish("bar_update", bar.to_dict())
        return True

    def set_health(self, value):
        self.health.append(value)
        return True

    def publish(self, event, payload):
        self.published.append((event, payload))
        return True


class Provider:
    name = "alpaca"


def quote(symbol, timestamp, price):
    return RealtimeQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        received_at=timestamp,
        provider="alpaca",
        feed="iex",
    )


def test_runner_uses_canonical_symbol_validation_for_provider_subscriptions():
    assert _eligible_symbol("MSFT")
    assert _eligible_symbol("BRK.B")
    assert _eligible_symbol("1578.T")
    assert _eligible_symbol("SPX=F")
    assert not _eligible_symbol("not a symbol")


def test_runner_ignores_older_quotes_for_latest_state_and_backfill_cursor():
    state = MemoryState()
    runtime = MarketStreamRuntime(
        settings=Settings(realtime_provider_order="alpaca", realtime_stale_seconds=120),
        providers=[Provider()],
        state=state,
    )
    persisted = []

    async def capture(bar, *, backfill=False):
        persisted.append((bar, backfill))

    runtime.persist_bar = capture
    base = datetime.now(UTC).replace(second=59, microsecond=0)
    asyncio.run(runtime.on_message("alpaca", quote("MSFT", base, 100)))
    asyncio.run(runtime.on_message("alpaca", quote("MSFT", base + timedelta(seconds=2), 101)))
    asyncio.run(runtime.on_message("alpaca", quote("MSFT", base - timedelta(seconds=1), 99)))

    assert runtime.latest["MSFT"]["alpaca"].price == 101
    assert runtime.last_valid["MSFT"] == base + timedelta(seconds=2)
    assert len(state.quotes) == 2
    assert len(persisted) == 1
    assert persisted[0][0].timestamp == base.replace(second=0)


def test_supervisor_backoffs_after_clean_stream_disconnect():
    supervisor = StreamingSupervisor(
        Provider(),
        backoff=ExponentialJitterBackoff(initial=0.001, maximum=0.001, jitter=0),
    )
    calls = 0

    async def run_once():
        nonlocal calls
        calls += 1
        if calls == 2:
            supervisor._stop.set()

    supervisor.run_once = run_once
    asyncio.run(supervisor.run())

    assert calls == 2
    assert supervisor.reconnect_count == 1
    assert supervisor.last_error == "stream disconnected"
