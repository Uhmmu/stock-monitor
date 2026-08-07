"""In-memory one-minute OHLCV aggregation with idempotent tick handling."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Iterable

from .contracts import IntradayBar, RealtimeQuote, ensure_utc, normalize_market_session


def minute_bucket(moment: datetime) -> datetime:
    return ensure_utc(moment).replace(second=0, microsecond=0)


@dataclass
class _MinuteAccumulator:
    symbol: str
    timestamp: datetime
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    volume_price_sum: float = 0.0
    trade_count: int = 0
    provider: str = "aggregated"
    feed: str | None = None
    market_session: str = "unknown"
    seen: set[str] = field(default_factory=set)

    def add_quote(self, quote: RealtimeQuote, fingerprint: str) -> bool:
        if fingerprint in self.seen:
            return False
        self.seen.add(fingerprint)
        price = quote.last_trade_price or quote.price
        if price is None and quote.bid is not None and quote.ask is not None:
            price = (quote.bid + quote.ask) / 2
        if price is None or price <= 0:
            return False
        event_time = ensure_utc(quote.timestamp)
        if self.first_timestamp is None or event_time < self.first_timestamp:
            self.first_timestamp = event_time
            self.open = price
        if self.last_timestamp is None or event_time >= self.last_timestamp:
            self.last_timestamp = event_time
            self.close = price
        self.high = price if self.high is None else max(self.high, price)
        self.low = price if self.low is None else min(self.low, price)
        amount = quote.last_trade_size if quote.last_trade_size is not None else quote.volume
        if amount is not None and amount >= 0:
            self.volume = (self.volume or 0.0) + float(amount)
            self.volume_price_sum += price * float(amount)
        self.trade_count += 1
        self.provider = quote.provider
        self.feed = quote.feed or self.feed
        self.market_session = normalize_market_session(quote.market_session)
        return True

    def add_bar(self, bar: IntradayBar) -> bool:
        fingerprint = bar.source_id or _fingerprint(
            bar.symbol,
            bar.timestamp,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
        )
        if fingerprint in self.seen:
            return False
        self.seen.add(fingerprint)
        event_time = ensure_utc(bar.timestamp)
        if self.first_timestamp is None or event_time < self.first_timestamp:
            self.first_timestamp = event_time
            self.open = bar.open
        if self.last_timestamp is None or event_time >= self.last_timestamp:
            self.last_timestamp = event_time
            self.close = bar.close
        self.high = bar.high if self.high is None else max(self.high, bar.high)
        self.low = bar.low if self.low is None else min(self.low, bar.low)
        if bar.volume is not None:
            self.volume = (self.volume or 0.0) + float(bar.volume)
            if bar.vwap is not None:
                self.volume_price_sum += float(bar.vwap) * float(bar.volume)
        if bar.trade_count is not None:
            self.trade_count += bar.trade_count
        self.provider = bar.provider
        self.feed = bar.feed or self.feed
        self.market_session = normalize_market_session(bar.market_session)
        return True

    def build(self, *, received_at: datetime | None = None, is_partial: bool = False) -> IntradayBar | None:
        if None in (self.open, self.high, self.low, self.close):
            return None
        weighted = self.volume_price_sum / self.volume if self.volume and self.volume > 0 else None
        return IntradayBar(
            symbol=self.symbol,
            timestamp=self.timestamp,
            interval="1m",
            open=float(self.open),
            high=float(self.high),
            low=float(self.low),
            close=float(self.close),
            volume=int(self.volume) if self.volume is not None and self.volume.is_integer() else self.volume,
            vwap=weighted,
            trade_count=self.trade_count or None,
            provider=self.provider,
            feed=self.feed,
            market_session=self.market_session,
            received_at=ensure_utc(received_at),
            is_partial=is_partial,
        )


def _fingerprint(symbol: str, timestamp: datetime, *values: object) -> str:
    text = "|".join([symbol, ensure_utc(timestamp).isoformat(), *(str(value) for value in values)])
    return hashlib.sha256(text.encode()).hexdigest()


class MinuteAggregator:
    """Aggregate stream quotes/bars without writing one row per tick.

    A completed minute is emitted exactly once.  Duplicate provider message
    IDs/fingerprints are ignored.  Late events for already-emitted minutes are
    ignored so reconnect/backfill can safely replay data against a unique DB
    constraint; out-of-order events inside the active minute still update the
    high/low and preserve the earliest open/latest close.
    """

    def __init__(self, *, max_symbols: int = 500) -> None:
        self.max_symbols = max(1, max_symbols)
        self._active: dict[str, _MinuteAccumulator] = {}
        self._last_emitted: dict[str, datetime] = {}
        self.duplicates = 0
        self.out_of_order = 0
        self.invalid = 0

    def _ensure_capacity(self, symbol: str) -> None:
        if symbol in self._active or len(self._active) < self.max_symbols:
            return
        oldest = min(self._active.values(), key=lambda item: item.timestamp)
        self._active.pop(oldest.symbol, None)

    def _rotate(self, symbol: str, bucket: datetime, received_at: datetime) -> list[IntradayBar]:
        current = self._active.get(symbol)
        if current is None:
            self._ensure_capacity(symbol)
            self._active[symbol] = _MinuteAccumulator(symbol=symbol, timestamp=bucket)
            return []
        if bucket <= current.timestamp:
            return []
        output: list[IntradayBar] = []
        bar = current.build(received_at=received_at)
        if bar is not None:
            output.append(bar)
            self._last_emitted[symbol] = current.timestamp
        self._active[symbol] = _MinuteAccumulator(symbol=symbol, timestamp=bucket)
        return output

    def add(self, event: RealtimeQuote | IntradayBar, *, received_at: datetime | None = None) -> list[IntradayBar]:
        symbol = event.symbol.strip().upper()
        event_time = ensure_utc(event.timestamp)
        bucket = minute_bucket(event_time)
        received = ensure_utc(received_at or getattr(event, "received_at", None))
        last_emitted = self._last_emitted.get(symbol)
        if last_emitted is not None and bucket <= last_emitted:
            self.out_of_order += 1
            return []
        output = self._rotate(symbol, bucket, received)
        active = self._active[symbol]
        if isinstance(event, RealtimeQuote):
            fingerprint = event.source_id or _fingerprint(symbol, event.timestamp, event.price, event.last_trade_size, event.bid, event.ask)
            accepted = active.add_quote(event, fingerprint)
        elif isinstance(event, IntradayBar):
            accepted = active.add_bar(event)
        else:
            self.invalid += 1
            return output
        if not accepted:
            self.duplicates += 1
        return output

    def add_quote(self, quote: RealtimeQuote) -> list[IntradayBar]:
        return self.add(quote)

    def add_bar(self, bar: IntradayBar) -> list[IntradayBar]:
        return self.add(bar)

    def advance(self, now: datetime | None = None) -> list[IntradayBar]:
        current = ensure_utc(now)
        boundary = minute_bucket(current)
        output: list[IntradayBar] = []
        for symbol, active in list(self._active.items()):
            if active.timestamp < boundary:
                bar = active.build(received_at=current)
                if bar is not None:
                    output.append(bar)
                    self._last_emitted[symbol] = active.timestamp
                self._active.pop(symbol, None)
        return sorted(output, key=lambda bar: (bar.timestamp, bar.symbol))

    def flush(self, *, now: datetime | None = None, force: bool = True) -> list[IntradayBar]:
        current = ensure_utc(now)
        if not force:
            return self.advance(current)
        output: list[IntradayBar] = []
        for symbol, active in list(self._active.items()):
            bar = active.build(received_at=current, is_partial=True)
            if bar is not None:
                output.append(bar)
                self._last_emitted[symbol] = active.timestamp
            self._active.pop(symbol, None)
        return sorted(output, key=lambda bar: (bar.timestamp, bar.symbol))

    def active_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._active))

    def snapshot(self, symbol: str) -> IntradayBar | None:
        active = self._active.get(symbol.strip().upper())
        return active.build(is_partial=True) if active else None


def aggregate_quotes(quotes: Iterable[RealtimeQuote]) -> list[IntradayBar]:
    aggregator = MinuteAggregator()
    output: list[IntradayBar] = []
    for quote in sorted(quotes, key=lambda value: ensure_utc(value.timestamp)):
        output.extend(aggregator.add_quote(quote))
    output.extend(aggregator.flush())
    return output


MinuteBarAggregator = MinuteAggregator
