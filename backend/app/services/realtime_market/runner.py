"""Standalone realtime market-stream service for Docker Compose.

The process owns upstream WebSockets; FastAPI only reads normalized Redis/DB
state. One provider failure is isolated from the other supervisors.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import PortfolioPosition, WatchlistItem
from app.research.exceptions import ResearchError
from app.research.security import normalize_symbol
from app.services.intraday_market import evaluate_bar_events, event_out, persist_intraday_bar

from .aggregation import MinuteAggregator
from .backfill import BackfillCoordinator
from .contracts import IntradayBar, ProviderHealth, RealtimeQuote, RealtimeQuoteEnvelope
from .providers import AlpacaRealtimeProvider, TiingoRealtimeProvider
from .routing import calculate_divergence, configured_provider_order
from .session import is_market_open, is_quote_stale
from .state import RealtimeStateStore
from .stream import StreamingSupervisor

logger = logging.getLogger(__name__)


def _eligible_symbol(value: str) -> bool:
    try:
        normalize_symbol(value)
    except (ResearchError, AttributeError):
        return False
    return True


def tracked_symbols() -> list[str]:
    with SessionLocal() as db:
        values = set(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        values.update(db.scalars(select(PortfolioPosition.symbol).where(PortfolioPosition.total_quantity > 0)).all())
    return sorted({value.strip().upper() for value in values if _eligible_symbol(value)})


class MarketStreamRuntime:
    def __init__(self, *, settings: Settings | None = None, providers: list[Any] | None = None, state: RealtimeStateStore | None = None) -> None:
        self.settings = settings or get_settings()
        if providers is None:
            providers = []
            if self.settings.alpaca_market_data_enabled:
                providers.append(AlpacaRealtimeProvider(settings=self.settings))
            if self.settings.tiingo_market_data_enabled:
                providers.append(TiingoRealtimeProvider(settings=self.settings))
        self.providers = providers
        self.state = state or RealtimeStateStore(settings=self.settings)
        self.order = configured_provider_order(self.settings)
        self.latest: dict[str, dict[str, RealtimeQuote]] = {}
        self.last_valid: dict[str, datetime] = {}
        self.aggregators = {provider.name: MinuteAggregator() for provider in providers}
        self.supervisors = {
            provider.name: StreamingSupervisor(
                provider, on_message=lambda message, name=provider.name: self.on_message(name, message),
                stale_after_seconds=max(30, self.settings.realtime_stale_seconds * 2),
            )
            for provider in providers
        }
        self.backfill = BackfillCoordinator(providers)
        self.stop_event = asyncio.Event()
        self.metrics = {
            "market_data_messages_total": 0, "market_data_parse_errors": 0,
            "intraday_bars_written": 0, "intraday_backfill_count": 0,
            "market_data_provider_errors": 0,
        }
        self._seen_reconnects = {name: 0 for name in self.supervisors}

    def envelope(self, symbol: str) -> RealtimeQuoteEnvelope | None:
        quotes = self.latest.get(symbol, {})
        ordered = [quotes[name] for name in self.order if name in quotes]
        if not ordered:
            ordered = list(quotes.values())
        if not ordered:
            return None
        fresh = [quote for quote in ordered if not is_quote_stale(quote, max_age_seconds=self.settings.realtime_stale_seconds)]
        authoritative = fresh[0] if fresh else ordered[0]
        alternates = tuple(quote for quote in ordered if quote is not authoritative)
        return RealtimeQuoteEnvelope(
            symbol=symbol, authoritative_quote=authoritative, alternate_quotes=alternates,
            divergence=calculate_divergence(authoritative, alternates[0]) if alternates else None,
            stale=is_quote_stale(authoritative, max_age_seconds=self.settings.realtime_stale_seconds),
        )

    async def on_message(self, provider: str, message: RealtimeQuote | IntradayBar) -> None:
        self.metrics["market_data_messages_total"] += 1
        previous_timestamp = self.last_valid.get(message.symbol)
        if previous_timestamp is None or message.timestamp > previous_timestamp:
            self.last_valid[message.symbol] = message.timestamp
        if isinstance(message, RealtimeQuote):
            provider_quotes = self.latest.setdefault(message.symbol, {})
            previous_quote = provider_quotes.get(provider)
            if previous_quote is None or message.timestamp >= previous_quote.timestamp:
                provider_quotes[provider] = message
                envelope = self.envelope(message.symbol)
                if envelope is not None:
                    self.state.set_quote(envelope)
                    divergence = envelope.divergence
                    if divergence and divergence.warning:
                        logger.warning(
                            "market_data_divergence symbol=%s primary=%s reference=%s difference_pct=%.4f",
                            message.symbol, divergence.primary_provider, divergence.reference_provider,
                            divergence.percentage_difference,
                        )
            for bar in self.aggregators[provider].add_quote(message):
                aggregate = replace(bar, provider=f"{provider}_aggregate")
                await self.persist_bar(aggregate)
            return
        if isinstance(message, IntradayBar):
            self.state.set_bar(message, publish=False)
            await self.persist_bar(message)

    async def persist_bar(self, bar: IntradayBar, *, backfill: bool = False) -> None:
        def write():
            with SessionLocal() as db:
                row, created = persist_intraday_bar(db, bar, is_backfill=backfill)
                events = [event_out(event) for event in evaluate_bar_events(db, row)] if created else []
                db.commit()
                return created, events
        try:
            created, events = await asyncio.to_thread(write)
            if created:
                self.metrics["intraday_bars_written"] += 1
                self.state.publish("bar_update", bar.to_dict())
            for event in events:
                self.state.publish("market_event", event)
        except Exception:
            self.metrics["market_data_provider_errors"] += 1
            logger.exception("intraday_bar_persist_failed symbol=%s provider=%s", bar.symbol, bar.provider)

    async def refresh_subscriptions(self) -> None:
        while not self.stop_event.is_set():
            try:
                symbols = await asyncio.to_thread(tracked_symbols)
                for supervisor in self.supervisors.values():
                    await supervisor.update_subscriptions(symbols)
            except Exception:
                logger.exception("market_subscription_refresh_failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=max(5, self.settings.realtime_subscription_refresh_seconds))
            except TimeoutError:
                pass

    async def flush_aggregates(self) -> None:
        while not self.stop_event.is_set():
            now = datetime.now(UTC)
            for provider, aggregator in self.aggregators.items():
                for bar in aggregator.advance(now):
                    aggregate = replace(bar, provider=f"{provider}_aggregate")
                    await self.persist_bar(aggregate)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=2)
            except TimeoutError:
                pass

    async def health_and_backfill(self) -> None:
        while not self.stop_event.is_set():
            for name, supervisor in self.supervisors.items():
                health = await supervisor.health_check()
                payload = health.to_dict()
                payload.update(self.metrics)
                self.state.set_health(payload)
                # Ping/pong can keep a dead provider socket looking connected
                # after business messages stop. During regular XNYS trading,
                # break stale transports and let the supervisor's normal
                # bounded reconnect loop recover them. Avoid connection churn
                # overnight, on weekends, and on exchange holidays.
                if is_market_open() and await supervisor.reconnect_if_stale():
                    logger.warning("market_stream_stale_reconnect provider=%s", name)
                previous = self._seen_reconnects[name]
                if supervisor.reconnect_count > previous and supervisor.connected:
                    self._seen_reconnects[name] = supervisor.reconnect_count
                    for symbol, last_timestamp in list(self.last_valid.items()):
                        result = await self.backfill.backfill(
                            symbol, last_valid_market_timestamp=last_timestamp,
                            reconnect_at=datetime.now(UTC),
                        )
                        for bar in result.bars:
                            await self.persist_bar(bar, backfill=True)
                        self.metrics["intraday_backfill_count"] += len(result.bars)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=10)
            except TimeoutError:
                pass

    async def seed_rest_state(self, symbols: list[str]) -> None:
        # Bounded startup validation/reference cross-check; stream updates take
        # over immediately and no HTTP request handler performs provider I/O.
        for symbol in symbols:
            quotes = []
            for provider in self.providers:
                try:
                    quotes.append(await provider.get_quote(symbol))
                except Exception as exc:
                    logger.info("market_rest_seed_unavailable provider=%s symbol=%s error=%s", provider.name, symbol, type(exc).__name__)
            for quote in quotes:
                self.latest.setdefault(symbol, {})[quote.provider] = quote
            envelope = self.envelope(symbol)
            if envelope:
                self.state.set_quote(envelope)

    async def run(self) -> None:
        if not self.providers:
            logger.warning("market_stream_disabled no providers configured")
            return
        symbols = await asyncio.to_thread(tracked_symbols)
        # Seed first so providers can exclude symbols that their own REST
        # endpoint rejects before the shared websocket subscriptions begin.
        await self.seed_rest_state(symbols)
        for supervisor in self.supervisors.values():
            await supervisor.update_subscriptions(symbols)
        tasks = [asyncio.create_task(supervisor.run(), name=f"stream-{name}") for name, supervisor in self.supervisors.items()]
        tasks.extend([
            asyncio.create_task(self.refresh_subscriptions(), name="subscription-refresh"),
            asyncio.create_task(self.flush_aggregates(), name="bar-flush"),
            asyncio.create_task(self.health_and_backfill(), name="health-backfill"),
        ])
        await self.stop_event.wait()
        for supervisor in self.supervisors.values():
            await supervisor.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for provider, aggregator in self.aggregators.items():
            for bar in aggregator.flush(now=datetime.now(UTC)):
                aggregate = replace(bar, provider=f"{provider}_aggregate")
                await self.persist_bar(aggregate)

    def stop(self) -> None:
        self.stop_event.set()


async def _main() -> None:
    settings = get_settings()
    if not settings.realtime_stream_enabled:
        logger.warning("market_stream_disabled REALTIME_STREAM_ENABLED=false")
        return
    runtime = MarketStreamRuntime(settings=settings)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, runtime.stop)
        except NotImplementedError:
            pass
    await runtime.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_main())
