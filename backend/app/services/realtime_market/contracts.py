"""Typed contracts for the realtime market-data boundary.

The rest of the application must only consume these values.  Provider payloads
are intentionally kept out of the contracts so a change in Alpaca or Tiingo's
wire format cannot leak into portfolio or alerting code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None, *, fallback: datetime | None = None) -> datetime:
    """Return an aware UTC datetime without ever treating a provider timestamp
    as the receive time.

    Naive provider timestamps are interpreted as UTC.  Provider adapters should
    parse timezone-bearing values whenever possible; this fallback keeps the
    contract deterministic for test fixtures and legacy APIs.
    """

    value = value or fallback or utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class MarketSession(StrEnum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTERHOURS = "afterhours"
    CLOSED = "closed"
    UNKNOWN = "unknown"


_SESSION_ALIASES = {
    "pre_market": MarketSession.PREMARKET.value,
    "pre-market": MarketSession.PREMARKET.value,
    "premarket": MarketSession.PREMARKET.value,
    "regular": MarketSession.REGULAR.value,
    "regular_market": MarketSession.REGULAR.value,
    "after_hours": MarketSession.AFTERHOURS.value,
    "after-hours": MarketSession.AFTERHOURS.value,
    "afterhours": MarketSession.AFTERHOURS.value,
    "post_market": MarketSession.AFTERHOURS.value,
    "post-market": MarketSession.AFTERHOURS.value,
    "closed": MarketSession.CLOSED.value,
    "unknown": MarketSession.UNKNOWN.value,
}


def normalize_market_session(value: str | MarketSession | None) -> str:
    return _SESSION_ALIASES.get(str(value or "unknown").strip().lower(), MarketSession.UNKNOWN.value)


@dataclass(frozen=True, slots=True)
class RealtimeQuote:
    """Provider-neutral quote/trade snapshot.

    ``timestamp`` is the market timestamp from the provider.  ``received_at``
    is when this process received/accepted the message.  They are deliberately
    separate so stale and delayed data cannot be presented as current data.
    """

    symbol: str
    price: float | None
    timestamp: datetime
    received_at: datetime
    provider: str
    feed: str | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_trade_price: float | None = None
    last_trade_size: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume: int | float | None = None
    vwap: float | None = None
    market_session: str = MarketSession.UNKNOWN.value
    delayed_seconds: int | None = None
    is_delayed: bool | None = None
    exchange: str | None = None
    currency: str | None = None
    source_role: str = "primary"
    source_id: str | None = None
    raw_payload: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))
        object.__setattr__(self, "market_session", normalize_market_session(self.market_session))
        if self.price is not None and self.price <= 0:
            raise ValueError("quote price must be positive when present")

    @property
    def provider_timestamp(self) -> datetime:
        return self.timestamp

    @property
    def delayed(self) -> bool:
        return bool(self.is_delayed or (self.delayed_seconds is not None and self.delayed_seconds > 0))

    @property
    def change(self) -> float | None:
        if self.price is None or self.previous_close is None:
            return None
        return self.price - self.previous_close

    @property
    def change_pct(self) -> float | None:
        if self.price is None or self.previous_close in (None, 0):
            return None
        return (self.price - self.previous_close) / self.previous_close * 100

    # Existing price_snapshot naming is exposed as read-only aliases.  This
    # lets callers migrate without copying values or changing semantics.
    @property
    def open_price(self) -> float | None:
        return self.open

    @property
    def day_high(self) -> float | None:
        return self.high

    @property
    def day_low(self) -> float | None:
        return self.low

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("timestamp", "received_at"):
            value[key] = value[key].isoformat()
        value["market_session"] = str(self.market_session)
        return value


@dataclass(frozen=True, slots=True)
class IntradayBar:
    symbol: str
    timestamp: datetime
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: int | float | None = None
    vwap: float | None = None
    trade_count: int | None = None
    provider: str = "aggregated"
    feed: str | None = None
    market_session: str = MarketSession.UNKNOWN.value
    received_at: datetime = field(default_factory=utc_now)
    source_id: str | None = None
    is_partial: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))
        object.__setattr__(self, "market_session", normalize_market_session(self.market_session))
        if self.interval not in {"1m", "5m", "15m"}:
            raise ValueError("interval must be one of 1m, 5m, or 15m")
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low do not contain open and close")

    @property
    def end(self) -> datetime:
        from datetime import timedelta

        minutes = int(self.interval[:-1])
        return self.timestamp + timedelta(minutes=minutes)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat()
        value["received_at"] = self.received_at.isoformat()
        value["market_session"] = str(self.market_session)
        return value


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    connected: bool = False
    last_message_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    error_code: str | None = None
    subscriptions: tuple[str, ...] = ()
    message_rate: float = 0.0
    reconnect_count: int = 0
    stale: bool = False
    capability_limited: bool = False
    auth_type: str | None = None
    environment: str | None = None
    market_data_endpoint: str | None = None
    feed: str | None = None
    stream_endpoint: str | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("last_message_at", "last_success_at", "updated_at"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        value["subscriptions"] = list(self.subscriptions)
        return value


@dataclass(frozen=True, slots=True)
class QuoteDivergence:
    symbol: str
    primary_provider: str
    reference_provider: str
    primary_price: float
    reference_price: float
    absolute_difference: float
    percentage_difference: float
    timestamp_difference_seconds: float | None
    warning: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RealtimeQuoteEnvelope:
    symbol: str
    authoritative_quote: RealtimeQuote
    alternate_quotes: tuple[RealtimeQuote, ...] = ()
    divergence: QuoteDivergence | None = None
    stale: bool = False

    @property
    def quote(self) -> RealtimeQuote:
        return self.authoritative_quote

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "authoritative_quote": self.authoritative_quote.to_dict(),
            "alternate_quotes": [quote.to_dict() for quote in self.alternate_quotes],
            "divergence": self.divergence.to_dict() if self.divergence else None,
            "stale": self.stale,
        }


class ProviderError(RuntimeError):
    """A provider failure that can be isolated by the routing layer."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        retry_after: float | None = None,
        capability_limited: bool = False,
        transient: bool = True,
    ) -> None:
        # Never include request headers or URLs containing credentials here.
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retry_after = retry_after
        self.capability_limited = capability_limited
        self.transient = transient


def finite_number(value: Any, *, positive: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if positive and number <= 0:
        return None
    return number


def parse_provider_timestamp(value: Any) -> datetime | None:
    """Parse ISO-8601, epoch seconds, and epoch milliseconds safely."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, UTC)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def trading_date_for(moment: datetime | None, timezone: str = "America/New_York") -> date | None:
    if moment is None:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ensure_utc(moment).astimezone(ZoneInfo(timezone)).date()
    except Exception:
        return ensure_utc(moment).date()
