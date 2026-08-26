from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.crypto.mood_bridge import build_mood_bridge_payload
from app.services.crypto.regime_validation import validate_regime_history


def _scenario():
    cutoff = datetime(2026, 8, 26, 12, tzinfo=UTC)
    metrics = []
    for index in range(193):
        observed = cutoff - timedelta(hours=192 - index)
        metrics.append(
            {
                "observed_at": observed,
                "open_interest_base": Decimal("1000") + index + Decimal(index % 7) / 10,
                "basis_rate": Decimal(index % 5) / Decimal("100000"),
                "taker_buy_volume": Decimal("60"),
                "taker_sell_volume": Decimal("40"),
                "source_hash": f"m{index}",
                "revision": 0,
            }
        )
    metrics[-1]["open_interest_base"] = metrics[-25]["open_interest_base"] * Decimal("1.10")
    metrics[-1]["basis_rate"] = Decimal("0.002")
    funding = [
        {
            "funding_time": cutoff - timedelta(hours=8 * (21 - index)),
            "funding_rate": Decimal(index % 4) / Decimal("100000"),
            "source_hash": f"f{index}",
            "revision": 0,
        }
        for index in range(22)
    ]
    funding[-1]["funding_rate"] = Decimal("0.001")
    candles = []
    for interval, delta in (("1h", timedelta(hours=1)), ("4h", timedelta(hours=4)), ("1d", timedelta(days=1))):
        candles.extend(
            [
                {"interval": interval, "close_time": cutoff, "close": "100", "source_hash": f"{interval}-anchor"},
                {"interval": interval, "close_time": cutoff + delta, "close": "105", "source_hash": f"{interval}-target"},
            ]
        )
    return cutoff, metrics, funding, candles


def test_validation_replays_causally_for_all_required_horizons():
    cutoff, metrics, funding, candles = _scenario()
    result = validate_regime_history(
        metrics,
        funding,
        candles,
        evaluation_times=[cutoff],
        horizons=("1d", "1h", "4h"),
    )

    assert result["validation_version"] == "crypto-usdm-regime-validation-v1"
    assert result["horizons"] == ["1h", "4h", "1d"]
    evaluation = result["evaluations"][0]
    assert evaluation["state"] == "LONG_CROWDING"
    assert evaluation["regime"]["as_of"] == cutoff.isoformat()
    for horizon in result["horizons"]:
        outcome = evaluation["outcomes"][horizon]
        assert outcome["status"] == "READY"
        assert outcome["target_time"] > evaluation["evaluation_at"]
        assert outcome["forward_return"] == "0.05"
        assert result["summaries"][horizon]["sample_count"] == 1
        assert result["summaries"][horizon]["status"] == "INSUFFICIENT_DATA"
    assert result["status"] == "INSUFFICIENT_DATA"
    assert "OBSERVATIONAL_ONLY" in result["warnings"]


def test_future_derivatives_rows_cannot_change_an_earlier_evaluation():
    cutoff, metrics, funding, candles = _scenario()
    base = validate_regime_history(metrics, funding, candles, evaluation_times=[cutoff])
    future_metrics = [
        *metrics,
        {
            "observed_at": cutoff + timedelta(hours=1),
            "open_interest_base": Decimal("1"),
            "basis_rate": Decimal("-0.25"),
            "taker_buy_volume": Decimal("1"),
            "taker_sell_volume": Decimal("99"),
            "source_hash": "future-row",
            "revision": 0,
        },
    ]
    replayed = validate_regime_history(future_metrics, funding, candles, evaluation_times=[cutoff])

    assert replayed["evaluations"][0]["state"] == base["evaluations"][0]["state"]
    assert replayed["evaluations"][0]["regime_input_hash"] == base["evaluations"][0]["regime_input_hash"]
    assert replayed["input_hash"] == base["input_hash"]


def test_missing_forward_data_is_explicit_and_bridge_is_non_mutating():
    cutoff, metrics, funding, _candles = _scenario()
    result = validate_regime_history(metrics, funding, [], evaluation_times=[cutoff])
    for outcome in result["evaluations"][0]["outcomes"].values():
        assert outcome["status"] == "INSUFFICIENT_DATA"
        assert outcome["reason"] == "NO_ANCHOR_CANDLE"

    unavailable = build_mood_bridge_payload(None)
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["read_only"] is True
    assert unavailable["equity_mood_impact"] is False
    assert unavailable["writes_mood_snapshots"] is False

    context = build_mood_bridge_payload(
        result["evaluations"][0]["regime"], validation=result, scope_key="BTCUSDT"
    )
    assert context["status"] == "OBSERVATIONAL"
    assert context["scope_type"] == "crypto_regime"
    assert context["scope_key"] == "BTCUSDT"
    assert context["state"] == result["evaluations"][0]["state"]
    assert context["equity_mood_impact"] is False
    assert context["writes_mood_snapshots"] is False


def test_validation_output_is_order_stable():
    cutoff, metrics, funding, candles = _scenario()
    left = validate_regime_history(metrics, funding, candles, evaluation_times=[cutoff])
    right = validate_regime_history(reversed(metrics), reversed(funding), reversed(candles), evaluation_times=[cutoff])
    assert left == right
