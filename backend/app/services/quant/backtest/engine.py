"""Pure deterministic bar-event backtest engine.

There are deliberately no persistence, provider, task-queue, or application
imports in this module.  A later adapter can convert stored candles into the
contracts in :mod:`contracts` and persist the returned DTOs unchanged.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from types import MappingProxyType
from typing import Any

from .contracts import (
    ZERO,
    BacktestConfig,
    BarEvent,
    InstrumentSpec,
    coerce_bar,
    coerce_instrument,
    decimal,
    quantity_round_down,
)
from .strategies import StrategyCallable, canonical_strategy_name, get_strategy


BPS = Decimal("10000")


class BacktestCancelled(RuntimeError):
    pass


def _d(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else decimal(value)


def _decimal_text(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    return format(value.normalize(), "f")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_value(item) for item in value), key=str)
    return value


def _hash_payload(value: Any) -> str:
    payload = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    nav: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    gross_notional: Decimal
    leverage: Decimal
    drawdown: Decimal
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    spread_cost: Decimal = ZERO
    slippage_cost: Decimal = ZERO
    positions: Mapping[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "nav": self.nav,
            "cash": self.cash,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "gross_notional": self.gross_notional,
            "leverage": self.leverage,
            "drawdown": self.drawdown,
            "fees": self.fees,
            "funding": self.funding,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "positions": self.positions,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True, slots=True)
class TradeRow:
    trade_id: int
    timestamp: datetime
    instrument_id: str | int
    symbol: str
    side: str
    action: str
    quantity: Decimal
    price: Decimal
    notional: Decimal
    realized_pnl: Decimal
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    position_quantity: Decimal
    closing_fill: bool = False
    liquidation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp.isoformat(),
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "side": self.side,
            "action": self.action,
            "quantity": self.quantity,
            "price": self.price,
            "notional": self.notional,
            "realized_pnl": self.realized_pnl,
            "fee": self.fee,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "position_quantity": self.position_quantity,
            "closing_fill": self.closing_fill,
            "liquidation": self.liquidation,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True, slots=True)
class RejectRow:
    timestamp: datetime
    instrument_id: str | int
    symbol: str
    reason: str
    requested_quantity: Decimal
    requested_notional: Decimal
    target_exposure: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "reason": self.reason,
            "requested_quantity": self.requested_quantity,
            "requested_notional": self.requested_notional,
            "target_exposure": self.target_exposure,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True, slots=True)
class LiquidationRow:
    timestamp: datetime
    instrument_id: str | int
    symbol: str
    quantity: Decimal
    price: Decimal
    equity: Decimal
    maintenance_requirement: Decimal
    reason: str = "maintenance_margin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "price": self.price,
            "equity": self.equity,
            "maintenance_requirement": self.maintenance_requirement,
            "reason": self.reason,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    strategy_name: str
    seed: int | str
    interval: str
    initial_capital: Decimal
    final_nav: Decimal
    equity: tuple[EquityPoint, ...]
    trades: tuple[TradeRow, ...]
    rejects: tuple[RejectRow, ...]
    liquidations: tuple[LiquidationRow, ...]
    metrics: Mapping[str, Any]
    segments: Mapping[str, Mapping[str, Any]]
    result_hash: str
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "equity", tuple(self.equity))
        object.__setattr__(self, "trades", tuple(self.trades))
        object.__setattr__(self, "rejects", tuple(self.rejects))
        object.__setattr__(self, "liquidations", tuple(self.liquidations))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        # Keep nested segment values as plain dictionaries: the persistence
        # adapter can pass them directly through its JSON normaliser.
        object.__setattr__(self, "segments", MappingProxyType({key: dict(value) for key, value in self.segments.items()}))
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))

    @property
    def hash(self) -> str:
        return self.result_hash

    @property
    def deterministic_hash(self) -> str:
        return self.result_hash

    @property
    def run_hash(self) -> str:
        return self.result_hash

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    @property
    def equity_rows(self) -> tuple[EquityPoint, ...]:
        return self.equity

    @property
    def trade_rows(self) -> tuple[TradeRow, ...]:
        return self.trades

    @property
    def segment_summaries(self) -> Mapping[str, Mapping[str, Any]]:
        return self.segments

    def to_dict(self) -> dict[str, Any]:
        return _json_value({
            "strategy_name": self.strategy_name,
            "seed": self.seed,
            "interval": self.interval,
            "initial_capital": self.initial_capital,
            "final_nav": self.final_nav,
            "equity": [point.to_dict() for point in self.equity],
            "trades": [row.to_dict() for row in self.trades],
            "rejects": [row.to_dict() for row in self.rejects],
            "liquidations": [row.to_dict() for row in self.liquidations],
            "metrics": self.metrics,
            "segments": self.segments,
            "result_hash": self.result_hash,
            "config": self.config,
        })

    as_dict = to_dict


@dataclass(slots=True)
class _Position:
    quantity: Decimal = ZERO
    entry_price: Decimal = ZERO


@dataclass(slots=True)
class _Ledger:
    cash: Decimal
    realized: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    spread_cost: Decimal = ZERO
    slippage_cost: Decimal = ZERO
    trade_seq: int = 0
    closing_fills: int = 0
    wins: int = 0
    losses: int = 0


def _id_key(value: Any) -> str:
    return str(value)


def _normalise_instruments(values: Any) -> list[InstrumentSpec]:
    if isinstance(values, Mapping):
        result = [coerce_instrument(item, instrument_id=key) for key, item in values.items()]
    else:
        result = [coerce_instrument(item) for item in values]
    if not result:
        raise ValueError("at least one instrument is required")
    keyed: dict[str, InstrumentSpec] = {}
    for item in result:
        key = _id_key(item.instrument_id)
        if key in keyed:
            raise ValueError(f"duplicate instrument {item.instrument_id!r}")
        keyed[key] = item
    return sorted(keyed.values(), key=lambda item: (_id_key(item.instrument_id), item.symbol))


def _normalise_bars(values: Any, instruments: Sequence[InstrumentSpec]) -> dict[str, list[BarEvent]]:
    grouped: dict[str, list[BarEvent]] = {_id_key(item.instrument_id): [] for item in instruments}
    by_key = {_id_key(item.instrument_id): item for item in instruments}
    by_symbol = {item.symbol: item for item in instruments}
    if isinstance(values, Mapping):
        source = values.items()
        for key, rows in source:
            lookup = _id_key(key)
            if lookup not in by_key and str(key) in by_symbol:
                lookup = _id_key(by_symbol[str(key)].instrument_id)
            if lookup not in by_key:
                raise ValueError(f"bars contain unknown instrument {key!r}")
            grouped[lookup] = [coerce_bar(row, instrument_id=by_key[lookup].instrument_id) for row in rows]
    else:
        rows = list(values)
        # A flat event list is unambiguous for one instrument.
        if len(instruments) == 1 and all(isinstance(row, (BarEvent, Mapping)) for row in rows):
            key = _id_key(instruments[0].instrument_id)
            grouped[key] = [coerce_bar(row, instrument_id=instruments[0].instrument_id) for row in rows]
        else:
            for item in rows:
                if isinstance(item, (tuple, list)) and len(item) == 2 and not isinstance(item[0], (datetime, date)):
                    key, data = item
                    lookup = _id_key(key)
                    if lookup not in by_key and str(key) in by_symbol:
                        lookup = _id_key(by_symbol[str(key)].instrument_id)
                    if lookup not in by_key:
                        raise ValueError(f"bars contain unknown instrument {key!r}")
                    grouped[lookup] = [coerce_bar(row, instrument_id=by_key[lookup].instrument_id) for row in data]
                    continue
                bar = coerce_bar(item)
                if bar.instrument_id is None:
                    raise ValueError("flat bars for multiple instruments need instrument_id")
                lookup = _id_key(bar.instrument_id)
                if lookup not in by_key and str(bar.instrument_id) in by_symbol:
                    lookup = _id_key(by_symbol[str(bar.instrument_id)].instrument_id)
                if lookup not in by_key:
                    raise ValueError(f"bars contain unknown instrument {bar.instrument_id!r}")
                grouped[lookup].append(bar)
    for key, rows in grouped.items():
        if not rows:
            raise ValueError(f"no bars for instrument {by_key[key].symbol}")
        rows.sort(key=lambda row: row.timestamp)
        timestamps = [row.timestamp for row in rows]
        if len(set(timestamps)) != len(timestamps):
            raise ValueError(f"duplicate bar timestamp for {by_key[key].symbol}")
    sequences = [tuple(row.timestamp for row in grouped[_id_key(item.instrument_id)]) for item in instruments]
    if any(sequence != sequences[0] for sequence in sequences[1:]):
        raise ValueError("selected instruments must have synchronized bar timestamps")
    return grouped


def _feature_target(target: Any, instrument: InstrumentSpec, bar: BarEvent, history: Sequence[BarEvent]) -> Decimal:
    if target is None:
        return ZERO
    if not callable(target):
        result = target
    else:
        try:
            signature = inspect.signature(target)
            positional = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_varargs = any(parameter.kind == parameter.VAR_POSITIONAL for parameter in signature.parameters.values())
            if has_varargs or len(positional) >= 3:
                result = target(instrument, bar, history)
            elif len(positional) == 2:
                result = target(bar, history)
            else:
                result = target(bar)
        except (TypeError, ValueError):
            # Builtins and opaque callables may not expose a signature.
            result = target(instrument, bar, history)
    if isinstance(result, Mapping):
        result = result.get(instrument.instrument_id, result.get(instrument.symbol, ZERO))
    value = decimal(result, name="strategy target") if result is not None else ZERO
    return max(Decimal("-1"), min(Decimal("1"), value))


def _round_price(price: Decimal, tick: Decimal, *, buy: bool) -> Decimal:
    units = (price / tick).to_integral_value(rounding=ROUND_UP if buy else ROUND_DOWN)
    return units * tick


def _fill_price(raw_price: Decimal, config: BacktestConfig, instrument: InstrumentSpec, *, buy: bool) -> tuple[Decimal, Decimal, Decimal]:
    spread = config.full_spread_bps / BPS / Decimal("2")
    slip = config.slippage_bps / BPS
    adverse = spread + slip
    adjusted = raw_price * (Decimal("1") + adverse if buy else Decimal("1") - adverse)
    price = _round_price(adjusted, instrument.tick_size, buy=buy)
    spread_cost = abs(raw_price * spread)
    slippage_cost = abs(raw_price * slip)
    return price, spread_cost, slippage_cost


def _mark_position(position: _Position, price: Decimal) -> Decimal:
    if position.quantity == ZERO:
        return ZERO
    return (price - position.entry_price) * position.quantity


def _mark_equity(ledger: _Ledger, positions: Mapping[str, _Position], prices: Mapping[str, Decimal]) -> Decimal:
    return ledger.cash + sum((_mark_position(positions[key], prices[key]) for key in positions), ZERO)


def _apply_funding(
    ledger: _Ledger,
    positions: Mapping[str, _Position],
    instruments: Mapping[str, InstrumentSpec],
    bars: Mapping[str, BarEvent],
) -> None:
    for key, position in positions.items():
        if position.quantity == ZERO:
            continue
        rate = bars[key].funding_rate
        if rate == ZERO:
            continue
        cost = abs(position.quantity) * bars[key].open * rate
        if position.quantity < ZERO:
            cost = -cost
        ledger.cash -= cost
        ledger.funding += cost


def _apply_fill(
    *,
    ledger: _Ledger,
    position: _Position,
    instrument: InstrumentSpec,
    timestamp: datetime,
    delta: Decimal,
    raw_price: Decimal,
    config: BacktestConfig,
    trade_rows: list[TradeRow],
    liquidation: bool = False,
) -> tuple[Decimal, Decimal, Decimal]:
    """Apply a signed quantity delta and return (realized, fee, notional)."""

    if delta == ZERO:
        return ZERO, ZERO, ZERO
    buy = delta > ZERO
    price, spread_cost_per_unit, slippage_cost_per_unit = _fill_price(raw_price, config, instrument, buy=buy)
    old_qty = position.quantity
    old_entry = position.entry_price
    close_qty = ZERO
    realized = ZERO
    if old_qty != ZERO and old_qty * delta < ZERO:
        close_qty = min(abs(old_qty), abs(delta))
        realized = (price - old_entry) * close_qty if old_qty > ZERO else (old_entry - price) * close_qty
    new_qty = old_qty + delta
    open_qty = abs(new_qty) if old_qty == ZERO or old_qty * new_qty < ZERO else ZERO
    if old_qty == ZERO:
        position.entry_price = price
    elif old_qty * delta > ZERO:
        position.entry_price = (abs(old_qty) * old_entry + abs(delta) * price) / (abs(old_qty) + abs(delta))
    elif new_qty == ZERO:
        position.entry_price = ZERO
    elif old_qty * new_qty < ZERO:
        position.entry_price = price
    position.quantity = new_qty

    quantity = abs(delta)
    notional = quantity * price
    fee = notional * config.taker_fee_bps / BPS
    spread_cost = quantity * spread_cost_per_unit
    slippage_cost = quantity * slippage_cost_per_unit
    ledger.cash += realized - fee
    ledger.realized += realized
    ledger.fees += fee
    ledger.spread_cost += spread_cost
    ledger.slippage_cost += slippage_cost
    ledger.trade_seq += 1
    closing = close_qty > ZERO
    if liquidation:
        action = "liquidation"
    elif closing and open_qty:
        action = "flip"
    elif closing:
        action = "close"
    else:
        action = "open"
    row = TradeRow(
        trade_id=ledger.trade_seq,
        timestamp=timestamp,
        instrument_id=instrument.instrument_id,
        symbol=instrument.symbol,
        side="buy" if buy else "sell",
        action=action,
        quantity=quantity,
        price=price,
        notional=notional,
        realized_pnl=realized,
        fee=fee,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        position_quantity=new_qty,
        closing_fill=closing,
        liquidation=liquidation,
    )
    trade_rows.append(row)
    if closing:
        ledger.closing_fills += 1
        if realized > ZERO:
            ledger.wins += 1
        elif realized < ZERO:
            ledger.losses += 1
    return realized, fee, notional


def _maybe_liquidate(
    *,
    ledger: _Ledger,
    positions: Mapping[str, _Position],
    instruments: Mapping[str, InstrumentSpec],
    bars: Mapping[str, BarEvent],
    config: BacktestConfig,
    trade_rows: list[TradeRow],
    liquidation_rows: list[LiquidationRow],
    halted: set[str],
    use_extremes: bool,
) -> bool:
    if not any(position.quantity != ZERO for position in positions.values()):
        return False
    prices = {
        key: (bars[key].low if positions[key].quantity > ZERO else bars[key].high) if use_extremes else bars[key].open
        for key in positions
    }
    worst_equity = _mark_equity(ledger, positions, prices)
    maintenance = sum((abs(positions[key].quantity) * prices[key] * config.maintenance_margin_ratio for key in positions), ZERO)
    if worst_equity > maintenance:
        return False
    for key, position in positions.items():
        if position.quantity == ZERO:
            continue
        instrument = instruments[key]
        old_quantity = position.quantity
        raw_price = prices[key]
        _apply_fill(
            ledger=ledger,
            position=position,
            instrument=instrument,
            timestamp=bars[key].timestamp,
            delta=-old_quantity,
            raw_price=raw_price,
            config=config,
            trade_rows=trade_rows,
            liquidation=True,
        )
        liquidation_rows.append(
            LiquidationRow(
                timestamp=bars[key].timestamp,
                instrument_id=instrument.instrument_id,
                symbol=instrument.symbol,
                quantity=abs(old_quantity),
                price=trade_rows[-1].price,
                equity=worst_equity,
                maintenance_requirement=maintenance,
            )
        )
        halted.add(key)
    return True


def _sharpe(points: Sequence[EquityPoint], interval: str) -> Decimal:
    if len(points) < 2:
        return ZERO
    returns = [points[index].nav / points[index - 1].nav - Decimal("1") for index in range(1, len(points)) if points[index - 1].nav > ZERO]
    if len(returns) < 2:
        return ZERO
    mean = sum(returns, ZERO) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(len(returns))
    if variance <= ZERO:
        return ZERO
    annual_periods = {"1h": Decimal(365 * 24), "4h": Decimal(365 * 6), "1d": Decimal(365)}.get(interval, Decimal(365))
    return mean / variance.sqrt() * annual_periods.sqrt()


def _segment_summary(points: Sequence[EquityPoint], initial: Decimal) -> dict[str, Mapping[str, Any]]:
    count = len(points)
    first_end = max(1, int(count * 0.6)) if count else 0
    second_end = max(first_end, int(count * 0.8)) if count else 0
    ranges = {"train": (0, first_end), "validation": (first_end, second_end), "test": (second_end, count)}
    weights = {"train": Decimal("0.6"), "validation": Decimal("0.2"), "test": Decimal("0.2")}
    result: dict[str, Mapping[str, Any]] = {}
    for name, (start, end) in ranges.items():
        if start >= end:
            result[name] = MappingProxyType({"weight": weights[name], "bars": 0, "return": ZERO, "max_drawdown": ZERO})
            continue
        base = initial if start == 0 else points[start - 1].nav
        rows = points[start:end]
        peak = base
        drawdown = ZERO
        for row in rows:
            peak = max(peak, row.nav)
            drawdown = min(drawdown, row.nav / peak - Decimal("1") if peak else ZERO)
        result[name] = MappingProxyType(
            {
                "weight": weights[name],
                "bars": end - start,
                "return": rows[-1].nav / base - Decimal("1") if base else ZERO,
                "max_drawdown": drawdown,
                "start_nav": base,
                "end_nav": rows[-1].nav,
            }
        )
    return result


def _config_payload(config: BacktestConfig) -> dict[str, Any]:
    return {
        "initial_capital": config.initial_capital,
        "interval": config.interval,
        "leverage": config.leverage,
        "strategy_name": config.strategy_name,
        "target_exposure": config.target_exposure,
        "taker_fee_bps": config.taker_fee_bps,
        "full_spread_bps": config.full_spread_bps,
        "slippage_bps": config.slippage_bps,
        "maintenance_margin_ratio": config.maintenance_margin_ratio,
        "seed": config.seed,
        "price_rounding": config.price_rounding,
    }


def run_backtest(
    instruments: Sequence[InstrumentSpec] | Mapping[Any, InstrumentSpec | Mapping[str, Any]],
    bars: Mapping[Any, Sequence[BarEvent | Mapping[str, Any]]] | Sequence[BarEvent | Mapping[str, Any]],
    config: BacktestConfig | Mapping[str, Any] | None = None,
    strategy: str | StrategyCallable | None = None,
    *,
    seed: int | str | None = None,
    progress: Callable[[int, datetime], bool] | None = None,
) -> BacktestResult:
    """Run a causal, target-position simulation over synchronized bars.

    Strategy targets are observed at each bar close and become orders at the
    next bar open.  Funding is charged to positions that existed before that
    open; a same-time newly opened position never receives retroactive funding.
    """

    instrument_rows = _normalise_instruments(instruments)
    cfg = config if isinstance(config, BacktestConfig) else BacktestConfig.from_mapping(config or {})
    if seed is not None:
        # A seed is metadata only: the core has no random branch.
        cfg = BacktestConfig.from_mapping({**{key: getattr(cfg, key) for key in cfg.__dataclass_fields__}, "seed": seed})
    selected_name = strategy if isinstance(strategy, str) else cfg.strategy_name
    target = get_strategy(selected_name) if isinstance(selected_name, str) else strategy
    strategy_name = canonical_strategy_name(selected_name) if isinstance(selected_name, str) else cfg.strategy_name
    grouped = _normalise_bars(bars, instrument_rows)
    instrument_map = {_id_key(item.instrument_id): item for item in instrument_rows}
    positions = {key: _Position() for key in instrument_map}
    ledger = _Ledger(cash=cfg.initial_capital)
    trades: list[TradeRow] = []
    rejects: list[RejectRow] = []
    liquidations: list[LiquidationRow] = []
    halted: set[str] = set()
    equity_rows: list[EquityPoint] = []
    pending: dict[str, Decimal] = {key: ZERO for key in instrument_map}
    timestamps = [row.timestamp for row in grouped[_id_key(instrument_rows[0].instrument_id)]]
    peak = cfg.initial_capital

    for index, timestamp in enumerate(timestamps):
        if progress is not None and not progress(index, timestamp):
            raise BacktestCancelled("backtest cancelled")
        current_bars = {key: grouped[key][index] for key in instrument_map}
        # Funding precedes any order generated by the preceding close.
        if index:
            _apply_funding(ledger, positions, instrument_map, current_bars)
            _maybe_liquidate(
                ledger=ledger,
                positions=positions,
                instruments=instrument_map,
                bars=current_bars,
                config=cfg,
                trade_rows=trades,
                liquidation_rows=liquidations,
                halted=halted,
                use_extremes=False,
            )

            open_prices = {key: current_bars[key].open for key in instrument_map}
            fill_equity = _mark_equity(ledger, positions, open_prices)
            for key, instrument in instrument_map.items():
                if key in halted:
                    continue
                exposure = pending[key]
                position = positions[key]
                if exposure == ZERO:
                    target_quantity = ZERO
                elif fill_equity <= ZERO:
                    rejects.append(
                        RejectRow(
                            timestamp=timestamp,
                            instrument_id=instrument.instrument_id,
                            symbol=instrument.symbol,
                            reason="non_positive_equity",
                            requested_quantity=ZERO,
                            requested_notional=ZERO,
                            target_exposure=exposure,
                        )
                    )
                    continue
                else:
                    notional = fill_equity * cfg.leverage * abs(exposure) / Decimal(len(instrument_map))
                    raw_quantity = notional / current_bars[key].open
                    target_quantity = quantity_round_down(raw_quantity, instrument.step_size)
                    target_quantity = target_quantity if exposure > ZERO else -target_quantity
                    if target_quantity == ZERO and position.quantity == ZERO:
                        rejects.append(
                            RejectRow(
                                timestamp=timestamp,
                                instrument_id=instrument.instrument_id,
                                symbol=instrument.symbol,
                                reason="step_size",
                                requested_quantity=raw_quantity if exposure > ZERO else -raw_quantity,
                                requested_notional=notional,
                                target_exposure=exposure,
                            )
                        )
                        continue
                    if target_quantity != ZERO and abs(target_quantity) * current_bars[key].open < instrument.min_notional and position.quantity == ZERO:
                        rejects.append(
                            RejectRow(
                                timestamp=timestamp,
                                instrument_id=instrument.instrument_id,
                                symbol=instrument.symbol,
                                reason="min_notional",
                                requested_quantity=target_quantity,
                                requested_notional=abs(target_quantity) * current_bars[key].open,
                                target_exposure=exposure,
                            )
                        )
                        continue
                delta = target_quantity - position.quantity
                if delta == ZERO:
                    continue
                if quantity_round_down(delta, instrument.step_size) == ZERO:
                    rejects.append(
                        RejectRow(
                            timestamp=timestamp,
                            instrument_id=instrument.instrument_id,
                            symbol=instrument.symbol,
                            reason="step_size",
                            requested_quantity=delta,
                            requested_notional=abs(delta) * current_bars[key].open,
                            target_exposure=exposure,
                        )
                    )
                    continue
                _apply_fill(
                    ledger=ledger,
                    position=position,
                    instrument=instrument,
                    timestamp=timestamp,
                    delta=delta,
                    raw_price=current_bars[key].open,
                    config=cfg,
                    trade_rows=trades,
                )

            # A fill can itself consume the maintenance buffer on a gap bar.
            _maybe_liquidate(
                ledger=ledger,
                positions=positions,
                instruments=instrument_map,
                bars=current_bars,
                config=cfg,
                trade_rows=trades,
                liquidation_rows=liquidations,
                halted=halted,
                use_extremes=True,
            )

        close_prices = {key: current_bars[key].close for key in instrument_map}
        nav = _mark_equity(ledger, positions, close_prices)
        peak = max(peak, nav)
        gross = sum((abs(positions[key].quantity) * close_prices[key] for key in instrument_map), ZERO)
        unrealized = nav - ledger.cash
        equity_rows.append(
            EquityPoint(
                timestamp=timestamp,
                nav=nav,
                cash=ledger.cash,
                unrealized_pnl=unrealized,
                realized_pnl=ledger.realized,
                gross_notional=gross,
                leverage=gross / nav if nav > ZERO else ZERO,
                drawdown=nav / peak - Decimal("1") if peak else ZERO,
                fees=ledger.fees,
                funding=ledger.funding,
                spread_cost=ledger.spread_cost,
                slippage_cost=ledger.slippage_cost,
                positions={instrument_map[key].symbol: positions[key].quantity for key in instrument_map if positions[key].quantity != ZERO},
            )
        )

        # Only this close is visible to the strategy; the pending target is
        # consumed at the following bar's open.
        if index < len(timestamps) - 1:
            for key, instrument in instrument_map.items():
                history = grouped[key][: index + 1]
                pending[key] = _feature_target(target, instrument, current_bars[key], history) * cfg.target_exposure

    final_nav = equity_rows[-1].nav if equity_rows else cfg.initial_capital
    total_return = final_nav / cfg.initial_capital - Decimal("1")
    max_drawdown = min((point.drawdown for point in equity_rows), default=ZERO)
    turnover_notional = sum((row.notional for row in trades), ZERO)
    turnover = turnover_notional / cfg.initial_capital
    annualized_sharpe = _sharpe(equity_rows, cfg.interval)
    metrics: dict[str, Any] = {
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "annualized_sharpe": annualized_sharpe,
        "annualized_sharpe_by_interval": {cfg.interval: annualized_sharpe},
        "sharpe": annualized_sharpe,
        "sharpe_by_interval": {cfg.interval: annualized_sharpe},
        "turnover": turnover,
        "turnover_ratio": turnover,
        "turnover_notional": turnover_notional,
        "fees": ledger.fees,
        "total_fees": ledger.fees,
        "funding": ledger.funding,
        "total_funding": ledger.funding,
        "spread_cost": ledger.spread_cost,
        "slippage": ledger.slippage_cost,
        "slippage_cost": ledger.slippage_cost,
        "realized_pnl": ledger.realized,
        "fills": len(trades),
        "closing_fills": ledger.closing_fills,
        "wins": ledger.wins,
        "losses": ledger.losses,
        "win_count": ledger.wins,
        "loss_count": ledger.losses,
        "rejects": len(rejects),
        "reject_count": len(rejects),
        "rejected_orders": len(rejects),
        "liquidations": len(liquidations),
    }
    segments = _segment_summary(equity_rows, cfg.initial_capital)
    config_payload = _config_payload(cfg)
    config_payload["strategy_name"] = strategy_name
    result_payload = {
        "strategy_name": strategy_name,
        "seed": cfg.seed,
        "interval": cfg.interval,
        "initial_capital": cfg.initial_capital,
        "final_nav": final_nav,
        "equity": [point.to_dict() for point in equity_rows],
        "trades": [row.to_dict() for row in trades],
        "rejects": [row.to_dict() for row in rejects],
        "liquidations": [row.to_dict() for row in liquidations],
        "metrics": metrics,
        "segments": segments,
        "config": config_payload,
    }
    result_hash = _hash_payload(result_payload)
    return BacktestResult(
        strategy_name=str(strategy_name),
        seed=cfg.seed,
        interval=cfg.interval,
        initial_capital=cfg.initial_capital,
        final_nav=final_nav,
        equity=tuple(equity_rows),
        trades=tuple(trades),
        rejects=tuple(rejects),
        liquidations=tuple(liquidations),
        metrics=metrics,
        segments=segments,
        result_hash=result_hash,
        config=config_payload,
    )


# Names used by the service adapter and by early experiments.
simulate_backtest = run_backtest
backtest = run_backtest
run = run_backtest
