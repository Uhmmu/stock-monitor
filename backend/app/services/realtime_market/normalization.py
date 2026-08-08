"""Normalize Alpaca and Tiingo wire payloads into realtime contracts.

No business code should inspect an upstream JSON field.  These adapters accept
both REST and stream shapes because Alpaca/Tiingo use slightly different keys
for the same value across endpoints and entitlement tiers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from .contracts import (
    IntradayBar,
    RealtimeQuote,
    ensure_utc,
    finite_number,
    normalize_market_session,
    parse_provider_timestamp,
)
from .session import market_session_at


_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "token",
    "access_token",
    "client_secret",
    "password",
}


def _safe_payload(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Retain useful provider evidence but never persist credentials."""

    if payload is None:
        return None
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if str(key).casefold() in _SENSITIVE_KEYS or "secret" in str(key).casefold():
            continue
        if isinstance(value, Mapping):
            output[str(key)] = _safe_payload(value)
        elif isinstance(value, (list, tuple)):
            output[str(key)] = [
                _safe_payload(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            output[str(key)] = value
    return output


def _received_at(received_at: datetime | None) -> datetime:
    return ensure_utc(received_at)


def _symbol(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().upper()
    return None


def _timestamp(payload: Mapping[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        value = parse_provider_timestamp(payload.get(key))
        if value is not None:
            return value
    return None


def _float(payload: Mapping[str, Any], *keys: str, positive: bool = False) -> float | None:
    for key in keys:
        value = finite_number(payload.get(key), positive=positive)
        if value is not None:
            return value
    return None


def _int(payload: Mapping[str, Any], *keys: str) -> int | None:
    value = _float(payload, *keys)
    return int(value) if value is not None else None


def _session(payload: Mapping[str, Any], timestamp: datetime | None) -> str:
    value = payload.get("market_session") or payload.get("session") or payload.get("m")
    if value:
        return normalize_market_session(str(value))
    return market_session_at(timestamp) if timestamp is not None else "unknown"


def normalize_alpaca_trade(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
    previous_close: float | None = None,
) -> RealtimeQuote | None:
    """Normalize an Alpaca ``t`` message or REST latest-trade object."""

    symbol = _symbol(payload, "S", "symbol", "sym")
    timestamp = _timestamp(payload, "t", "timestamp", "T")
    price = _float(payload, "p", "price", "last", "last_price", positive=True)
    if not symbol or timestamp is None or price is None:
        return None
    size = _float(payload, "s", "size", "last_size")
    return RealtimeQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        received_at=_received_at(received_at),
        provider="alpaca",
        feed=feed or payload.get("feed"),
        last_trade_price=price,
        last_trade_size=size,
        previous_close=previous_close,
        volume=_float(payload, "v", "volume"),
        market_session=_session(payload, timestamp),
        exchange=payload.get("x") or payload.get("exchange"),
        source_id=str(payload.get("i") or payload.get("id") or "") or None,
        raw_payload=_safe_payload(payload),
    )


def normalize_alpaca_quote(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
    previous_close: float | None = None,
) -> RealtimeQuote | None:
    """Normalize an Alpaca ``q`` message or REST latest-quote object."""

    symbol = _symbol(payload, "S", "symbol", "sym")
    timestamp = _timestamp(payload, "t", "timestamp")
    bid = _float(payload, "bp", "bid_price", "bid", positive=True)
    ask = _float(payload, "ap", "ask_price", "ask", positive=True)
    bid_size = _float(payload, "bs", "bid_size")
    ask_size = _float(payload, "as", "ask_size")
    # A quote can have only one side during a thin/entitlement-limited feed;
    # use its available side as the display price, otherwise midpoint.
    price = _float(payload, "p", "price", "mid", "last")
    if price is None and bid is not None and ask is not None:
        price = round((bid + ask) / 2, 10)
    elif price is None:
        price = bid if bid is not None else ask
    if not symbol or timestamp is None or price is None or price <= 0:
        return None
    return RealtimeQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        received_at=_received_at(received_at),
        provider="alpaca",
        feed=feed or payload.get("feed"),
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        previous_close=previous_close,
        market_session=_session(payload, timestamp),
        exchange=payload.get("bx") or payload.get("ax") or payload.get("exchange"),
        source_id=str(payload.get("i") or payload.get("id") or "") or None,
        raw_payload=_safe_payload(payload),
    )


def normalize_alpaca_bar(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
    interval: str = "1m",
) -> IntradayBar | None:
    symbol = _symbol(payload, "S", "symbol", "sym")
    timestamp = _timestamp(payload, "t", "timestamp", "start")
    open_price = _float(payload, "o", "open", positive=True)
    high = _float(payload, "h", "high", positive=True)
    low = _float(payload, "l", "low", positive=True)
    close = _float(payload, "c", "close", positive=True)
    if not symbol or timestamp is None or None in (open_price, high, low, close):
        return None
    return IntradayBar(
        symbol=symbol,
        timestamp=timestamp,
        interval=interval,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=_float(payload, "v", "volume"),
        vwap=_float(payload, "vw", "vwap"),
        trade_count=_int(payload, "n", "trade_count", "trades"),
        provider="alpaca",
        feed=feed or payload.get("feed"),
        market_session=_session(payload, timestamp),
        received_at=_received_at(received_at),
        source_id=str(payload.get("i") or payload.get("id") or "") or None,
    )


def normalize_alpaca_message(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
    previous_close: float | None = None,
) -> RealtimeQuote | IntradayBar | None:
    """Normalize one Alpaca stream message; control/status messages return None."""

    kind = str(payload.get("T") or payload.get("type") or payload.get("message_type") or "").lower()
    if kind in {"t", "trade", "trades", "trade_update"}:
        return normalize_alpaca_trade(payload, received_at=received_at, feed=feed, previous_close=previous_close)
    if kind in {"q", "quote", "quotes"}:
        return normalize_alpaca_quote(payload, received_at=received_at, feed=feed, previous_close=previous_close)
    if kind in {"b", "bar", "bars", "minute_bar"}:
        return normalize_alpaca_bar(payload, received_at=received_at, feed=feed)
    # REST helpers sometimes omit T.  Infer from fields without treating
    # subscription/error messages as market data.
    if any(key in payload for key in ("o", "h", "l", "c", "vw")):
        return normalize_alpaca_bar(payload, received_at=received_at, feed=feed)
    if any(key in payload for key in ("bp", "ap", "bid_price", "ask_price")):
        return normalize_alpaca_quote(payload, received_at=received_at, feed=feed, previous_close=previous_close)
    if any(key in payload for key in ("p", "price", "last")):
        return normalize_alpaca_trade(payload, received_at=received_at, feed=feed, previous_close=previous_close)
    return None


def _tiingo_symbol(payload: Mapping[str, Any]) -> str | None:
    return _symbol(payload, "ticker", "symbol", "S", "Tkr", "code")


def normalize_tiingo_quote(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    mode: str = "consolidated",
    feed: str | None = None,
    previous_close: float | None = None,
) -> RealtimeQuote | None:
    """Normalize Tiingo IEX or consolidated reference-price payloads.

    Tiingo can legally omit IEX bid/ask/last fields when the account lacks an
    entitlement.  We preserve ``None`` and continue using a consolidated
    reference price when available.
    """

    symbol = _tiingo_symbol(payload)
    timestamp = _timestamp(payload, "timestamp", "time", "date", "E", "t")
    price = _float(
        payload,
        "tngoLast",
        "last",
        "lastPrice",
        "last_price",
        "price",
        "lastSalePrice",
        "lqRefPrice",
        "mid",
        "p",
        positive=True,
    )
    bid = _float(payload, "bidPrice", "bid", "bid_price", "b")
    ask = _float(payload, "askPrice", "ask", "ask_price", "a")
    if price is None and bid is not None and ask is not None:
        price = (bid + ask) / 2
    if price is None and bid is not None:
        price = bid
    if price is None and ask is not None:
        price = ask
    if not symbol or timestamp is None or price is None or price <= 0:
        return None
    # Tiingo consolidated fields use dayOpen/dayHigh/dayLow/dayVolume; IEX
    # payloads typically use open/high/low/volume.  Every missing field stays
    # None rather than being inferred from the reference price.
    return RealtimeQuote(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        received_at=_received_at(received_at),
        provider="tiingo",
        feed=feed or mode,
        bid=bid,
        ask=ask,
        bid_size=_float(payload, "bidSize", "bid_size", "bs"),
        ask_size=_float(payload, "askSize", "ask_size", "as"),
        last_trade_price=_float(payload, "last", "lastPrice", "lastSalePrice", "tngoLast", positive=True),
        last_trade_size=_float(payload, "lastSize", "last_size", "size", "s"),
        open=_float(payload, "dayOpen", "open", "o", positive=True),
        high=_float(payload, "dayHigh", "high", "h", positive=True),
        low=_float(payload, "dayLow", "low", "l", positive=True),
        previous_close=_float(payload, "prevClose", "previousClose", "previous_close") or previous_close,
        volume=_float(payload, "dayVolume", "volume", "v"),
        vwap=_float(payload, "vwap", "VWAP", "dayVwap"),
        market_session=_session(payload, timestamp),
        delayed_seconds=_int(payload, "delaySeconds", "delayedSeconds"),
        is_delayed=bool(payload.get("isDelayed")) if payload.get("isDelayed") is not None else None,
        exchange=payload.get("exchange") or payload.get("venue"),
        currency=payload.get("currency"),
        source_role="reference" if mode == "consolidated" else "primary",
        source_id=str(payload.get("id") or payload.get("I") or "") or None,
        raw_payload=_safe_payload(payload),
    )


def normalize_tiingo_message(
    payload: Mapping[str, Any] | list[Any] | tuple[Any, ...],
    *,
    received_at: datetime | None = None,
    mode: str = "consolidated",
    feed: str | None = None,
) -> RealtimeQuote | IntradayBar | None:
    """Normalize Tiingo websocket messages, including array envelopes."""

    if isinstance(payload, (list, tuple)):
        # Tiingo IEX arrays are commonly [message_type, ..., payload].  Find
        # the first mapping with a market value, but never assume indexes for
        # consolidated/reference messages.
        for item in payload:
            if isinstance(item, Mapping):
                value = normalize_tiingo_message(item, received_at=received_at, mode=mode, feed=feed)
                if value is not None:
                    return value
        return None
    if not isinstance(payload, Mapping):
        return None
    kind = str(payload.get("type") or payload.get("messageType") or payload.get("I") or payload.get("T") or "").lower()
    if kind in {"b", "bar", "bars"} or any(key in payload for key in ("open", "high", "low", "close")) and "close" in payload:
        # Tiingo REST historical bars may use date/open/high/low/close.
        normalized = _normalize_tiingo_bar(payload, received_at=received_at, mode=mode, feed=feed)
        if normalized is not None:
            return normalized
    return normalize_tiingo_quote(payload, received_at=received_at, mode=mode, feed=feed)


def _normalize_tiingo_bar(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None,
    mode: str,
    feed: str | None,
) -> IntradayBar | None:
    symbol = _tiingo_symbol(payload)
    timestamp = _timestamp(payload, "timestamp", "date", "time", "t")
    values = {
        "open": _float(payload, "open", "o", positive=True),
        "high": _float(payload, "high", "h", positive=True),
        "low": _float(payload, "low", "l", positive=True),
        "close": _float(payload, "close", "c", positive=True),
    }
    if not symbol or timestamp is None or any(value is None for value in values.values()):
        return None
    return IntradayBar(
        symbol=symbol,
        timestamp=timestamp,
        interval=str(payload.get("interval") or "1m"),
        **values,
        volume=_float(payload, "volume", "v"),
        vwap=_float(payload, "vwap", "vw"),
        trade_count=_int(payload, "tradeCount", "trade_count", "n"),
        provider="tiingo",
        feed=feed or mode,
        market_session=_session(payload, timestamp),
        received_at=_received_at(received_at),
        source_id=str(payload.get("id") or "") or None,
    )


def normalize_provider_message(
    provider: str,
    payload: Mapping[str, Any] | list[Any] | tuple[Any, ...],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
    mode: str = "consolidated",
) -> RealtimeQuote | IntradayBar | None:
    name = provider.strip().lower()
    if name == "alpaca" and isinstance(payload, Mapping):
        return normalize_alpaca_message(payload, received_at=received_at, feed=feed)
    if name == "tiingo":
        return normalize_tiingo_message(payload, received_at=received_at, mode=mode, feed=feed)
    raise ValueError(f"unsupported realtime provider: {provider}")


def normalize_alpaca_rest_quotes(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
) -> list[RealtimeQuote]:
    rows: list[RealtimeQuote] = []
    quotes = payload.get("quotes") if isinstance(payload.get("quotes"), Mapping) else payload
    if not isinstance(quotes, Mapping):
        return rows
    for symbol, quote_payload in quotes.items():
        if not isinstance(quote_payload, Mapping):
            continue
        value = dict(quote_payload)
        value.setdefault("S", symbol)
        quote = normalize_alpaca_quote(value, received_at=received_at, feed=feed)
        if quote is not None:
            rows.append(quote)
    return rows


def normalize_alpaca_rest_trades(
    payload: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    feed: str | None = None,
) -> list[RealtimeQuote]:
    rows: list[RealtimeQuote] = []
    trades = payload.get("trades") if isinstance(payload.get("trades"), Mapping) else payload
    if not isinstance(trades, Mapping):
        return rows
    for symbol, trade_payload in trades.items():
        if not isinstance(trade_payload, Mapping):
            continue
        value = dict(trade_payload)
        value.setdefault("S", symbol)
        trade = normalize_alpaca_trade(value, received_at=received_at, feed=feed)
        if trade is not None:
            rows.append(trade)
    return rows


def normalize_tiingo_rest_rows(
    payload: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    mode: str = "consolidated",
    feed: str | None = None,
) -> list[RealtimeQuote | IntradayBar]:
    if isinstance(payload, Mapping):
        rows: Iterable[Any] = payload.get("data") if isinstance(payload.get("data"), list) else [payload]
    else:
        rows = payload
    output: list[RealtimeQuote | IntradayBar] = []
    for row in rows:
        if isinstance(row, Mapping):
            value = normalize_tiingo_message(row, received_at=received_at, mode=mode, feed=feed)
            if value is not None:
                output.append(value)
    return output


# Stable short aliases for callers that do not need to distinguish stream vs
# REST at the call site.
normalize_alpaca = normalize_alpaca_message
normalize_tiingo = normalize_tiingo_message
normalize_alpaca_payload = normalize_alpaca_message
normalize_tiingo_payload = normalize_tiingo_message
