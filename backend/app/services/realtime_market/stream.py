"""Provider-independent streaming supervisor with bounded reconnect backoff."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from .contracts import IntradayBar, ProviderError, ProviderHealth, RealtimeQuote
from .providers import StreamingMarketDataProvider

logger = logging.getLogger(__name__)


class ExponentialJitterBackoff:
    def __init__(self, *, initial: float = 0.5, maximum: float = 30.0, jitter: float = 0.25, rng: random.Random | None = None) -> None:
        self.initial = max(0.01, initial)
        self.maximum = max(self.initial, maximum)
        self.jitter = max(0.0, min(1.0, jitter))
        self.attempt = 0
        self._rng = rng or random.Random()

    def next_delay(self) -> float:
        base = min(self.maximum, self.initial * (2**self.attempt))
        self.attempt += 1
        if self.jitter == 0:
            return base
        return max(0.0, base * (1 - self.jitter + self._rng.random() * 2 * self.jitter))

    def reset(self) -> None:
        self.attempt = 0


Message = RealtimeQuote | IntradayBar
MessageHandler = Callable[[Message], Any]


class StreamingSupervisor:
    """Keep one provider stream isolated from the FastAPI request lifecycle."""

    def __init__(
        self,
        provider: StreamingMarketDataProvider,
        *,
        symbols: Sequence[str] = (),
        on_message: MessageHandler | None = None,
        backoff: ExponentialJitterBackoff | None = None,
        stale_after_seconds: float = 90.0,
    ) -> None:
        self.provider = provider
        self._symbols = {value.strip().upper() for value in symbols if value.strip()}
        self.on_message = on_message
        self.backoff = backoff or ExponentialJitterBackoff()
        self.stale_after_seconds = max(1.0, stale_after_seconds)
        self.reconnect_count = 0
        self.last_message_at: datetime | None = None
        self.last_error: str | None = None
        self.connected = False
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._symbols))

    async def update_subscriptions(self, symbols: Sequence[str]) -> None:
        desired = {value.strip().upper() for value in symbols if value.strip()}
        async with self._lock:
            added = sorted(desired - self._symbols)
            removed = sorted(self._symbols - desired)
            self._symbols = desired
            if not self.connected:
                return
            if added:
                await self.provider.subscribe(added)
            if removed:
                await self.provider.unsubscribe(removed)

    async def stop(self) -> None:
        self._stop.set()
        try:
            await self.provider.close()
        except Exception:
            logger.debug("stream provider close failed", exc_info=True)

    def stale(self, now: datetime | None = None) -> bool:
        if not self.connected or self.last_message_at is None:
            return True
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return (current.astimezone(UTC) - self.last_message_at).total_seconds() > self.stale_after_seconds

    async def _dispatch(self, message: Message) -> None:
        self.last_message_at = datetime.now(UTC)
        if self.on_message is None:
            return
        result = self.on_message(message)
        if inspect.isawaitable(result):
            await result

    async def run_once(self) -> None:
        """Connect, subscribe and consume until the provider disconnects."""

        await self.provider.connect()
        self.connected = True
        self.last_error = None
        self.backoff.reset()
        if self._symbols:
            await self.provider.subscribe(self.symbols)
        try:
            async for message in self.provider.stream():
                await self._dispatch(message)
                if self._stop.is_set():
                    break
        finally:
            self.connected = False
            # A failed websocket object must not be reused on the next retry.
            # Provider close is isolated so one transport's cleanup failure
            # cannot terminate the supervisor or the FastAPI process.
            try:
                await self.provider.close()
            except Exception:
                logger.debug("stream provider cleanup failed", exc_info=True)

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
                if self._stop.is_set():
                    break
                # A provider may close its async iterator without raising (for
                # example on a clean server-side websocket close). Treat that
                # as a disconnect so the supervisor cannot spin in a tight
                # reconnect loop and health exposes the interruption.
                self.reconnect_count += 1
                self.last_error = "stream disconnected"
                await asyncio.sleep(self.backoff.next_delay())
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                self.connected = False
                self.reconnect_count += 1
                self.last_error = str(exc)
                # Authentication/entitlement failures are configuration or
                # capability problems, not transient disconnects.  Stop this
                # provider loop so it cannot hammer an upstream endpoint while
                # other providers continue serving fallback data.
                if not exc.transient or exc.capability_limited or self._stop.is_set():
                    break
                await asyncio.sleep(exc.retry_after if exc.retry_after is not None else self.backoff.next_delay())
            except Exception as exc:
                self.connected = False
                self.reconnect_count += 1
                self.last_error = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
                # Authentication, configuration, and entitlement failures are
                # not healed by a tight reconnect loop. Diagnostics remain in
                # provider health until the service is reconfigured/restarted.
                if isinstance(exc, ProviderError) and not exc.transient:
                    break
                if self._stop.is_set():
                    break
                await asyncio.sleep(self.backoff.next_delay())
        self.connected = False

    async def health_check(self) -> ProviderHealth:
        try:
            health = await self.provider.health_check()  # type: ignore[attr-defined]
        except Exception:
            health = ProviderHealth(provider=getattr(self.provider, "name", "unknown"), connected=False)
        return ProviderHealth(
            provider=health.provider,
            connected=self.connected and health.connected,
            last_message_at=self.last_message_at or health.last_message_at,
            last_success_at=health.last_success_at,
            last_error=self.last_error or health.last_error,
            error_code=health.error_code,
            subscriptions=self.symbols,
            message_rate=health.message_rate,
            reconnect_count=self.reconnect_count + health.reconnect_count,
            stale=self.stale(),
            capability_limited=health.capability_limited,
            auth_type=health.auth_type,
            environment=health.environment,
            market_data_endpoint=health.market_data_endpoint,
            feed=health.feed,
            stream_endpoint=health.stream_endpoint,
        )
