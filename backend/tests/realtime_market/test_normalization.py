from datetime import UTC, datetime

from app.services.realtime_market import (
    IntradayBar,
    RealtimeQuote,
    normalize_alpaca_bar,
    normalize_alpaca_message,
    normalize_alpaca_quote,
    normalize_tiingo_message,
    normalize_tiingo_quote,
)


def test_alpaca_trade_and_quote_keep_provider_timestamp_separate_from_receive_time():
    received = datetime(2026, 8, 7, 14, 31, 3, tzinfo=UTC)
    trade = normalize_alpaca_message({
        "T": "t", "S": "MSFT", "p": 418.2, "s": 10,
        "t": "2026-08-07T14:31:00.123456Z", "i": 77,
    }, received_at=received, feed="iex")
    assert isinstance(trade, RealtimeQuote)
    assert trade.provider == "alpaca"
    assert trade.timestamp == datetime(2026, 8, 7, 14, 31, 0, 123456, tzinfo=UTC)
    assert trade.received_at == received
    assert trade.last_trade_size == 10
    assert trade.source_id == "77"

    quote = normalize_alpaca_quote({
        "S": "MSFT", "bp": 418.1, "ap": 418.3, "bs": 20, "as": 30,
        "t": 1786113060,
    }, received_at=received, feed="iex")
    assert quote is not None
    assert quote.price == 418.2
    assert quote.bid == 418.1 and quote.ask == 418.3
    assert quote.timestamp == datetime.fromtimestamp(1786113060, UTC)


def test_alpaca_quote_treats_non_positive_sides_as_unavailable():
    base = {"S": "MSFT", "t": 1786113060}

    bid_missing = normalize_alpaca_quote({**base, "bp": 0, "ap": 418.3})
    assert bid_missing is not None
    assert bid_missing.price == 418.3
    assert bid_missing.bid is None and bid_missing.ask == 418.3

    ask_missing = normalize_alpaca_quote({**base, "bp": 418.1, "ap": 0})
    assert ask_missing is not None
    assert ask_missing.price == 418.1
    assert ask_missing.bid == 418.1 and ask_missing.ask is None

    assert normalize_alpaca_quote({**base, "bp": 0, "ap": 0}) is None


def test_alpaca_bar_normalization_does_not_accept_control_messages():
    assert normalize_alpaca_message({"T": "subscription", "bars": ["MSFT"]}) is None
    bar = normalize_alpaca_bar({
        "T": "b", "S": "MSFT", "o": 418.0, "h": 419.0, "l": 417.5,
        "c": 418.5, "v": 1000, "vw": 418.25, "n": 40,
        "t": "2026-08-07T14:31:00Z",
    }, feed="iex")
    assert isinstance(bar, IntradayBar)
    assert bar.interval == "1m" and bar.volume == 1000
    assert bar.market_session in {"premarket", "regular", "afterhours", "closed", "unknown"}


def test_tiingo_consolidated_reference_keeps_optional_entitlement_fields_none():
    value = normalize_tiingo_quote({
        "ticker": "NVDA", "tngoLast": 182.36, "lqRefPrice": 182.35,
        "prevClose": 179.24, "dayOpen": 179.40, "dayHigh": 183.02,
        "dayLow": 178.91, "timestamp": "2026-08-07T14:31:00.000Z",
        "tags": ["AI"],
    }, mode="consolidated")
    assert value is not None
    assert value.provider == "tiingo" and value.source_role == "reference"
    assert value.price == 182.36
    assert value.bid is None and value.ask is None
    assert value.previous_close == 179.24


def test_tiingo_message_accepts_mapping_or_array_envelope():
    payload = {
        "type": "quote", "ticker": "AAPL", "last": 100.0,
        "timestamp": "2026-08-07T14:31:00Z",
    }
    assert isinstance(normalize_tiingo_message(payload, mode="iex"), RealtimeQuote)
    assert isinstance(normalize_tiingo_message([{"type": "quote", **payload}, {"status": "ok"}], mode="iex"), RealtimeQuote)
