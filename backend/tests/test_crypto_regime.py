from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.crypto.regime import evaluate_regime


def _scenario(
    *,
    oi_multiplier=Decimal("1.10"),
    basis_rate=Decimal("0.002"),
    funding_rate=Decimal("0.001"),
    taker_buy=Decimal("60"),
    taker_sell=Decimal("40"),
):
    end = datetime(2026, 8, 26, 12, tzinfo=UTC)
    metrics = []
    for index in range(193):
        observed = end - timedelta(hours=192 - index)
        metrics.append({
            "observed_at": observed,
            "open_interest_base": Decimal("1000") + index + Decimal(index % 7) / 10,
            "basis_rate": Decimal(index % 5) / Decimal("100000"),
            "taker_buy_volume": taker_buy,
            "taker_sell_volume": taker_sell,
            "source_hash": f"m{index}",
            "revision": 0,
        })
    metrics[-1]["open_interest_base"] = metrics[-25]["open_interest_base"] * oi_multiplier
    metrics[-1]["basis_rate"] = basis_rate
    funding = [
        {
            "funding_time": end - timedelta(hours=8 * (21 - index)),
            "funding_rate": Decimal(index % 4) / Decimal("100000"),
            "source_hash": f"f{index}",
            "revision": 0,
        }
        for index in range(22)
    ]
    funding[-1]["funding_rate"] = funding_rate
    return end, metrics, funding


def test_regime_classifies_frozen_long_crowding_and_is_order_stable():
    end, metrics, funding = _scenario()
    result = evaluate_regime(metrics, funding, evaluated_at=end)
    reordered = evaluate_regime(reversed(metrics), reversed(funding), evaluated_at=end)
    assert result["state"] == "LONG_CROWDING"
    assert {"OI_24H_RISE_EXTREME", "BASIS_PREMIUM_EXTREME", "TAKER_BUY_IMBALANCE"} <= set(result["evidence"])
    assert result["input_hash"] == reordered["input_hash"]
    assert result["version"] == "crypto-usdm-regime-v1"


def test_regime_deleveraging_precedes_directional_votes():
    end, metrics, funding = _scenario(oi_multiplier=Decimal("0.90"))
    result = evaluate_regime(metrics, funding, evaluated_at=end)
    assert result["state"] == "DELEVERAGING"
    assert "OI_24H_FALL_EXTREME" in result["evidence"]


def test_regime_covers_short_buildup_and_balanced_states():
    end, metrics, funding = _scenario(
        basis_rate=Decimal("-0.002"), funding_rate=Decimal("-0.001"),
        taker_buy=Decimal("40"), taker_sell=Decimal("60"),
    )
    assert evaluate_regime(metrics, funding, evaluated_at=end)["state"] == "SHORT_CROWDING"

    end, metrics, funding = _scenario(
        basis_rate=Decimal("0.00002"), funding_rate=Decimal("0.00002"),
        taker_buy=Decimal("50"), taker_sell=Decimal("50"),
    )
    assert evaluate_regime(metrics, funding, evaluated_at=end)["state"] == "LEVERAGE_BUILDUP"

    metrics[-1]["open_interest_base"] = metrics[-25]["open_interest_base"] * Decimal("1.02")
    assert evaluate_regime(metrics, funding, evaluated_at=end)["state"] == "BALANCED"


def test_regime_conflicting_vote_reduces_confidence():
    end, aligned_metrics, funding = _scenario()
    aligned = evaluate_regime(aligned_metrics, funding, evaluated_at=end)
    end, conflict_metrics, funding = _scenario(taker_buy=Decimal("40"), taker_sell=Decimal("60"))
    conflict = evaluate_regime(conflict_metrics, funding, evaluated_at=end)
    assert conflict["state"] == "LONG_CROWDING"
    assert Decimal(conflict["confidence"]) < Decimal(aligned["confidence"])


def test_regime_insufficient_and_stale_boundaries():
    end, metrics, funding = _scenario()
    insufficient = evaluate_regime(metrics[-100:], funding[-10:], evaluated_at=end)
    assert insufficient["state"] == "INSUFFICIENT_DATA"
    assert insufficient["confidence"] == "0.00"

    valid_until = end + timedelta(hours=2)
    assert evaluate_regime(metrics, funding, evaluated_at=valid_until)["stale"] is False
    stale = evaluate_regime(metrics, funding, evaluated_at=valid_until + timedelta(microseconds=1))
    assert stale["stale"] is True
    assert "STALE_DATA" in stale["warnings"]
