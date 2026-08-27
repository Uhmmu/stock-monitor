from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.quant.backtest import (
    BacktestConfig,
    BarEvent,
    InstrumentSpec,
    RSI_MEAN_REVERSION_STRATEGY,
    run_backtest,
)
from app.services.quant.backtest.strategies import STRATEGY_REGISTRY


UTC = timezone.utc


def bars(closes: list[str], *, opens: list[str] | None = None, funding: list[str] | None = None, features=None):
    opens = opens or closes
    funding = funding or ["0"] * len(closes)
    result = []
    for index, (opened, closed, rate) in enumerate(zip(opens, closes, funding)):
        value = Decimal(closed)
        open_value = Decimal(opened)
        result.append(
            BarEvent(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=open_value,
                high=max(open_value, value),
                low=min(open_value, value),
                close=value,
                volume=Decimal("1"),
                funding_rate=Decimal(rate),
                features=(features[index] if features else {}),
            )
        )
    return result


def instrument(**kwargs):
    return InstrumentSpec(
        instrument_id=kwargs.pop("instrument_id", "btc"),
        symbol=kwargs.pop("symbol", "BTCUSDT"),
        tick_size=kwargs.pop("tick_size", "0.01"),
        step_size=kwargs.pop("step_size", "0.001"),
        min_notional=kwargs.pop("min_notional", "0"),
        **kwargs,
    )


def test_dual_ma_uses_close_then_fills_next_open_and_marks_nav():
    rows = bars(
        ["100", "110", "120"],
        opens=["100", "105", "115"],
        features=[{}, {"sma20": "2", "sma50": "1"}, {"sma20": "2", "sma50": "1"}],
    )
    result = run_backtest([instrument(step_size="1")], {"btc": rows}, BacktestConfig(initial_capital="1000"))

    assert result.strategy_name == "dual-ma-trend-v1"
    assert len(result.trades) == 1
    fill = result.trades[0]
    assert fill.timestamp == rows[2].timestamp
    assert fill.price == Decimal("115.04")  # 1bp half spread + 2bp slippage, rounded up for a buy
    assert result.equity[1].positions == {}
    assert result.equity[-1].positions["BTCUSDT"] == Decimal("8")
    assert result.equity[-1].nav > Decimal("1000")


def test_short_pnl_and_funding_signs_are_applied_before_same_time_fill():
    rows = bars(
        ["100", "90", "80"],
        opens=["100", "100", "90"],
        funding=["0", "0.01", "-0.01"],
        features=[{}, {"rsi": "80"}, {"rsi": "20"}],
    )
    result = run_backtest(
        [instrument(step_size="1")],
        {"btc": rows},
        BacktestConfig(initial_capital="1000", strategy_name=RSI_MEAN_REVERSION_STRATEGY, taker_fee_bps="0", full_spread_bps="0", slippage_bps="0"),
    )

    # RSI 80 at bar 1 schedules a short for bar 2. The 1% bar-1 funding is
    # charged before that fill and therefore cannot charge the new short.
    assert len(result.trades) == 1
    assert result.trades[0].side == "sell"
    assert result.metrics["funding"] == Decimal("0")
    assert result.equity[-1].positions["BTCUSDT"] < 0


def test_long_funding_is_a_cost_and_negative_rate_is_credit():
    rows = bars(
        ["100", "100", "100", "100"],
        opens=["100", "100", "100", "100"],
        funding=["0", "0", "0.01", "-0.01"],
        features=[{"sma20": "2", "sma50": "1"}, {"sma20": "2", "sma50": "1"}, {"sma20": "2", "sma50": "1"}, {}],
    )
    result = run_backtest(
        [instrument(step_size="1")],
        {"btc": rows},
        BacktestConfig(initial_capital="1000", taker_fee_bps="0", full_spread_bps="0", slippage_bps="0"),
    )
    # Position opens at bar 1. It pays 1% at bar 2's open and receives 1% at
    # bar 3's open.  The first charge is on the larger pre-funding position;
    # the second credit is consequently slightly smaller after rebalancing.
    assert result.metrics["funding"] == Decimal("1.00")


def test_rounding_and_min_notional_reject_are_recorded():
    rows = bars(
        ["100", "100"],
        features=[{"sma20": "2", "sma50": "1"}, {}],
    )
    result = run_backtest(
        [instrument(step_size="0.6", min_notional="100")],
        {"btc": rows},
        BacktestConfig(initial_capital="100", taker_fee_bps="0", full_spread_bps="0", slippage_bps="0"),
    )
    assert not result.trades
    assert result.metrics["rejects"] == 1
    assert result.rejects[0].reason == "min_notional"


def test_step_rounding_to_zero_is_a_reject():
    rows = bars(["100", "100"], features=[{"sma20": "2", "sma50": "1"}, {}])
    result = run_backtest(
        [instrument(step_size="10")],
        {"btc": rows},
        BacktestConfig(initial_capital="100", taker_fee_bps="0", full_spread_bps="0", slippage_bps="0"),
    )
    assert not result.trades
    assert result.rejects[0].reason == "step_size"


def test_maintenance_liquidation_is_conservative_and_reported():
    rows = bars(
        ["100", "10", "10"],
        opens=["100", "100", "10"],
        features=[{"sma20": "2", "sma50": "1"}, {"sma20": "2", "sma50": "1"}, {"sma20": "2", "sma50": "1"}],
    )
    result = run_backtest(
        [instrument(step_size="1")],
        {"btc": rows},
        BacktestConfig(
            initial_capital="1000",
            taker_fee_bps="0",
            full_spread_bps="0",
            slippage_bps="0",
            leverage="3",
            maintenance_margin_ratio="0.5",
        ),
    )
    assert result.metrics["liquidations"] == 1
    assert result.liquidations[0].reason == "maintenance_margin"
    assert result.trades[-1].liquidation is True
    assert result.equity[-1].positions == {}


def test_result_hash_and_segments_are_reproducible():
    rows = bars(["100", "101", "102", "101", "103"], features=[{}] + [{"sma20": "2", "sma50": "1"}] * 4)
    config = BacktestConfig(initial_capital="1000", seed=42, taker_fee_bps="0", full_spread_bps="0", slippage_bps="0")
    first = run_backtest([instrument(step_size="1")], {"btc": rows}, config)
    second = run_backtest([instrument(step_size="1")], {"btc": rows}, config)
    assert first.result_hash == second.result_hash
    assert set(first.segments) == {"train", "validation", "test"}
    assert first.to_dict()["result_hash"] == first.result_hash
    json.dumps(first.to_dict())


def test_config_rejects_leverage_outside_requested_range():
    with pytest.raises(ValueError, match="leverage"):
        BacktestConfig(leverage="3.1")


def test_alias_strategy_still_persists_versioned_identifier():
    rows = bars(["100", "100"], features=[{"sma20": "2", "sma50": "1"}, {}])
    result = run_backtest([instrument(step_size="1")], {"btc": rows}, BacktestConfig(strategy="dual_ma", taker_fee_bps="0", full_spread_bps="0", slippage_bps="0"))
    assert result.strategy_name == "dual-ma-trend-v1"
    assert set(STRATEGY_REGISTRY) == {"dual-ma-trend-v1", "rsi-mean-reversion-v1"}
