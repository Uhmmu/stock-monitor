"""Small deterministic strategy registry used by the backtest simulator."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from .contracts import BarEvent, InstrumentSpec


DUAL_MA_STRATEGY = "dual-ma-trend-v1"
RSI_MEAN_REVERSION_STRATEGY = "rsi-mean-reversion-v1"


def _feature(bar: BarEvent, *names: str) -> Decimal | None:
    values = {str(key).lower().replace("_", "").replace("-", ""): value for key, value in bar.features.items()}
    for name in names:
        value = values.get(name.lower().replace("_", "").replace("-", ""))
        if value is not None:
            return value
    return None


def _close_values(history: Sequence[BarEvent] | None, current: BarEvent) -> list[Decimal]:
    rows = list(history or ())
    if not rows or rows[-1] != current:
        rows.append(current)
    return [bar.close for bar in rows]


def _sma(values: Sequence[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    return sum(values[-period:], Decimal("0")) / Decimal(period)


def _rsi(values: Sequence[Decimal], period: int = 14) -> Decimal | None:
    if len(values) < period + 1:
        return None
    changes = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = [change for change in changes if change > 0]
    losses = [-change for change in changes if change < 0]
    average_gain = sum(gains, Decimal("0")) / Decimal(period)
    average_loss = sum(losses, Decimal("0")) / Decimal(period)
    if average_loss == 0:
        return Decimal("100") if average_gain else Decimal("50")
    return Decimal("100") - (Decimal("100") / (Decimal("1") + average_gain / average_loss))


def dual_ma_target(
    bar: BarEvent | InstrumentSpec,
    history: Sequence[BarEvent] | BarEvent | None = None,
    maybe_history: Sequence[BarEvent] | None = None,
) -> Decimal:
    """Long when SMA20 is above SMA50, short when below, otherwise flat."""

    # The service adapter may pass the richer ``(instrument, bar, history)``
    # callback shape.  Keeping this tiny compatibility branch here avoids a
    # second strategy implementation in the adapter.
    if isinstance(bar, InstrumentSpec):
        bar, history = history, maybe_history
    if not isinstance(bar, BarEvent):
        return Decimal("0")
    closes = _close_values(history, bar)
    fast = _feature(bar, "sma20")
    slow = _feature(bar, "sma50")
    if fast is None:
        fast = _sma(closes, 20)
    if slow is None:
        slow = _sma(closes, 50)
    if fast is None or slow is None:
        return Decimal("0")
    if fast > slow:
        return Decimal("1")
    if fast < slow:
        return Decimal("-1")
    return Decimal("0")


def rsi_mean_reversion_target(
    bar: BarEvent | InstrumentSpec,
    history: Sequence[BarEvent] | BarEvent | None = None,
    maybe_history: Sequence[BarEvent] | None = None,
) -> Decimal:
    """Long at RSI <= 30, short at RSI >= 70, otherwise flat."""

    if isinstance(bar, InstrumentSpec):
        bar, history = history, maybe_history
    if not isinstance(bar, BarEvent):
        return Decimal("0")
    value = _feature(bar, "rsi", "rsi14")
    if value is None:
        value = _rsi(_close_values(history, bar))
    if value is None:
        return Decimal("0")
    if value <= Decimal("30"):
        return Decimal("1")
    if value >= Decimal("70"):
        return Decimal("-1")
    return Decimal("0")


StrategyCallable = Callable[..., Any]


STRATEGY_REGISTRY: dict[str, StrategyCallable] = {
    DUAL_MA_STRATEGY: dual_ma_target,
    RSI_MEAN_REVERSION_STRATEGY: rsi_mean_reversion_target,
}

_CANONICAL_NAMES = {
    DUAL_MA_STRATEGY: DUAL_MA_STRATEGY,
    RSI_MEAN_REVERSION_STRATEGY: RSI_MEAN_REVERSION_STRATEGY,
    "dual_ma": DUAL_MA_STRATEGY,
    "dual-ma": DUAL_MA_STRATEGY,
    "rsi_reversal": RSI_MEAN_REVERSION_STRATEGY,
    "rsi-mean-reversion": RSI_MEAN_REVERSION_STRATEGY,
}


def register_strategy(name: str, target: StrategyCallable) -> None:
    if not str(name).strip() or not callable(target):
        raise ValueError("strategy name and callable are required")
    key = str(name).strip()
    STRATEGY_REGISTRY[key] = target
    _CANONICAL_NAMES[key] = key


def get_strategy(name: str) -> StrategyCallable:
    try:
        return STRATEGY_REGISTRY[canonical_strategy_name(name)]
    except KeyError as exc:
        raise ValueError(f"unknown backtest strategy {name!r}") from exc


def canonical_strategy_name(name: str) -> str:
    """Return the versioned identifier persisted in a result manifest."""

    try:
        return _CANONICAL_NAMES[str(name).strip()]
    except KeyError as exc:
        raise ValueError(f"unknown backtest strategy {name!r}") from exc


def available_strategies() -> tuple[str, ...]:
    return (DUAL_MA_STRATEGY, RSI_MEAN_REVERSION_STRATEGY)


# Friendly function aliases used by small adapter/tests.
dual_ma_strategy = dual_ma_target
rsi_strategy = rsi_mean_reversion_target


# Compatibility names for adapters that use ``strategy_registry`` terminology.
strategy_registry = STRATEGY_REGISTRY
