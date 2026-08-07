from datetime import UTC, datetime, timedelta

from app.services.realtime_market import IntradayBar, MinuteAggregator, RealtimeQuote, aggregate_quotes


BASE = datetime(2026, 8, 7, 14, 31, tzinfo=UTC)


def quote(second: int, price: float, *, size: int = 1, source_id: str | None = None) -> RealtimeQuote:
    moment = BASE + timedelta(seconds=second)
    return RealtimeQuote(
        symbol="MSFT", price=price, last_trade_price=price, last_trade_size=size,
        timestamp=moment, received_at=moment + timedelta(milliseconds=5),
        provider="alpaca", feed="iex", source_id=source_id,
    )


def test_minute_aggregation_ohlcv_and_duplicate_idempotency():
    aggregator = MinuteAggregator()
    assert aggregator.add_quote(quote(2, 100, size=10, source_id="a")) == []
    assert aggregator.add_quote(quote(20, 105, size=20, source_id="b")) == []
    assert aggregator.add_quote(quote(20, 105, size=20, source_id="b")) == []
    output = aggregator.add_quote(quote(61, 103, size=5, source_id="c"))
    assert len(output) == 1
    bar = output[0]
    assert bar.timestamp == BASE
    assert bar.open == 100 and bar.high == 105 and bar.low == 100 and bar.close == 105
    assert bar.volume == 30 and bar.trade_count == 2
    assert aggregator.duplicates == 1


def test_out_of_order_inside_active_minute_keeps_earliest_open_and_latest_close():
    aggregator = MinuteAggregator()
    aggregator.add_quote(quote(40, 104, source_id="late"))
    aggregator.add_quote(quote(5, 101, source_id="early"))
    snapshot = aggregator.snapshot("MSFT")
    assert snapshot is not None
    assert snapshot.open == 101 and snapshot.close == 104
    assert snapshot.high == 104 and snapshot.low == 101


def test_late_event_for_emitted_minute_is_ignored_and_no_missing_minutes_are_fabricated():
    aggregator = MinuteAggregator()
    aggregator.add_quote(quote(1, 100, source_id="one"))
    first = aggregator.add_quote(quote(61, 101, source_id="two"))
    assert len(first) == 1
    # Minute 32 is skipped; crossing into minute 33 emits only the current
    # completed minute, not synthetic zero-volume rows.
    second = aggregator.add_quote(quote(121, 102, source_id="three"))
    assert len(second) == 1
    assert aggregator.add_quote(quote(10, 99, source_id="late")) == []
    assert aggregator.out_of_order == 1


def test_provider_bar_can_be_aggregated_and_flush_marks_partial():
    aggregator = MinuteAggregator()
    row = IntradayBar(
        symbol="AAPL", timestamp=BASE, interval="1m", open=10, high=12,
        low=9, close=11, volume=100, vwap=10.5, provider="tiingo", feed="iex",
    )
    aggregator.add_bar(row)
    output = aggregator.flush()
    assert len(output) == 1 and output[0].is_partial is True


def test_aggregate_quotes_sorts_input_before_grouping():
    values = aggregate_quotes([quote(61, 102, source_id="b"), quote(1, 100, source_id="a")])
    assert len(values) == 2
    assert [bar.close for bar in values] == [100, 102]
