"""Immutable, provider-free contracts for the quant backtest core.

The adapter that loads persisted market data belongs outside this package.  A
bar therefore carries only values needed by the simulator and an optional
point-in-time feature mapping.  Values are normalised to :class:`Decimal` so
the ledger does not inherit binary floating-point surprises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from types import MappingProxyType
from typing import Any, Mapping


ZERO = Decimal("0")


def decimal(value: Any, *, name: str = "value") -> Decimal:
    """Convert a scalar to a finite Decimal without accepting booleans."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _utc_timestamp(value: Any) -> datetime:
    """Normalise common adapter timestamps to timezone-aware UTC datetimes."""

    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = float(value)
        # Millisecond epochs are the shape used by exchange candle adapters.
        if abs(number) >= 100_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("timestamp must not be empty")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return _utc_timestamp(Decimal(text))
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"unsupported timestamp {value!r}") from exc
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    raise ValueError(f"unsupported timestamp {value!r}")


def _freeze_features(values: Mapping[str, Any] | None) -> Mapping[str, Decimal]:
    if not values:
        return MappingProxyType({})
    result: dict[str, Decimal] = {}
    for key, value in values.items():
        if value is None:
            continue
        result[str(key)] = decimal(value, name=f"feature {key}")
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Tradable instrument metadata required by the execution approximation."""

    instrument_id: str | int | None = None
    symbol: str = ""
    tick_size: Decimal = Decimal("0.01")
    step_size: Decimal = Decimal("0.001")
    min_notional: Decimal = ZERO
    # Constructor aliases retained at the boundary for simple adapter payloads.
    tick: Decimal | None = None
    step: Decimal | None = None
    id: str | int | None = None

    def __post_init__(self) -> None:
        identifier = self.id if self.id is not None else self.instrument_id
        if identifier is None or str(identifier) == "":
            raise ValueError("instrument_id is required")
        if not str(self.symbol).strip():
            raise ValueError("symbol is required")
        tick = decimal(self.tick if self.tick is not None else self.tick_size, name="tick_size")
        step = decimal(self.step if self.step is not None else self.step_size, name="step_size")
        minimum = decimal(self.min_notional, name="min_notional")
        if tick <= ZERO or step <= ZERO:
            raise ValueError("tick_size and step_size must be positive")
        if minimum < ZERO:
            raise ValueError("min_notional must be non-negative")
        object.__setattr__(self, "tick_size", tick)
        object.__setattr__(self, "step_size", step)
        object.__setattr__(self, "tick", tick)
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "instrument_id", identifier)
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "min_notional", minimum)
        object.__setattr__(self, "symbol", str(self.symbol).strip())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, instrument_id: str | int | None = None) -> "InstrumentSpec":
        identifier = value.get("instrument_id", value.get("id", instrument_id))
        return cls(
            instrument_id=identifier,
            symbol=value.get("symbol", value.get("ticker", identifier)),
            tick_size=value.get("tick_size", value.get("tick", "0.01")),
            step_size=value.get("step_size", value.get("step", "0.001")),
            min_notional=value.get("min_notional", value.get("minimum_notional", "0")),
        )


@dataclass(frozen=True, slots=True)
class BarEvent:
    """One synchronized, closed OHLCV bar and its point-in-time features."""

    timestamp: datetime | date | int | float | str | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: Decimal = ZERO
    features: Mapping[str, Decimal] = field(default_factory=dict)
    funding_rate: Decimal = ZERO
    instrument_id: str | int | None = None
    time: datetime | date | int | float | str | None = None
    funding: Decimal | None = None

    def __post_init__(self) -> None:
        when = _utc_timestamp(self.timestamp if self.timestamp is not None else self.time)
        opened = decimal(self.open, name="open")
        high = decimal(self.high, name="high")
        low = decimal(self.low, name="low")
        closed = decimal(self.close, name="close")
        volume = ZERO if self.volume is None else decimal(self.volume, name="volume")
        funding_value = self.funding if self.funding is not None else self.funding_rate
        funding = ZERO if funding_value is None else decimal(funding_value, name="funding_rate")
        if min(opened, high, low, closed) <= ZERO:
            raise ValueError("OHLC values must be positive")
        if high < max(opened, closed) or low > min(opened, closed) or high < low:
            raise ValueError("bar OHLC values are inconsistent")
        if volume < ZERO:
            raise ValueError("volume must be non-negative")
        object.__setattr__(self, "timestamp", when)
        object.__setattr__(self, "open", opened)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", closed)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(self, "features", _freeze_features(self.features))
        object.__setattr__(self, "funding_rate", funding)
        object.__setattr__(self, "time", when)
        object.__setattr__(self, "funding", funding)

    @property
    def time_ms(self) -> int:
        return int(self.timestamp.timestamp() * 1000)  # type: ignore[union-attr]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, instrument_id: str | int | None = None) -> "BarEvent":
        if "open_time_ms" in value:
            timestamp = _utc_timestamp(decimal(value["open_time_ms"], name="open_time_ms") / Decimal("1000"))
        elif "time_ms" in value:
            timestamp = _utc_timestamp(decimal(value["time_ms"], name="time_ms") / Decimal("1000"))
        else:
            timestamp = value.get("timestamp", value.get("time", value.get("open_time", value.get("as_of"))))
        if timestamp is None:
            raise ValueError("bar timestamp is required")
        features = value.get("features")
        if features is None:
            # Flat feature columns are convenient for CSV/JSON adapters.
            feature_names = {"sma20", "sma50", "rsi", "sma_20", "sma_50", "rsi14"}
            features = {key: value[key] for key in feature_names if key in value}
        return cls(
            timestamp=timestamp,
            open=value.get("open"),
            high=value.get("high"),
            low=value.get("low"),
            close=value.get("close"),
            volume=value.get("volume", value.get("base_volume", "0")),
            features=features,
            funding_rate=value.get("funding_rate", value.get("funding")) or "0",
            instrument_id=value.get("instrument_id", value.get("id", instrument_id)),
        )


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Deterministic execution and accounting assumptions."""

    initial_capital: Decimal = Decimal("10000")
    interval: str = "1d"
    leverage: Decimal = Decimal("1")
    strategy_name: str = "dual-ma-trend-v1"
    # ``strategy`` is accepted for adapter ergonomics; strategy_name wins only
    # when the alias is omitted.
    strategy: str | None = None
    taker_fee_bps: Decimal = Decimal("5")
    full_spread_bps: Decimal = Decimal("2")
    slippage_bps: Decimal = Decimal("2")
    maintenance_margin_ratio: Decimal = Decimal("0.005")
    seed: int | str = 0
    price_rounding: str = ROUND_DOWN
    target_exposure: Decimal = Decimal("1")
    # Short constructor aliases.  Canonical fields above remain the serialized
    # contract and aliases are normalised to the same Decimal values.
    capital: Decimal | None = None
    fee_bps: Decimal | None = None
    spread_bps: Decimal | None = None
    maintenance_margin: Decimal | None = None

    def __post_init__(self) -> None:
        capital = decimal(self.capital if self.capital is not None else self.initial_capital, name="initial_capital")
        leverage = decimal(self.leverage, name="leverage")
        fee = decimal(self.fee_bps if self.fee_bps is not None else self.taker_fee_bps, name="taker_fee_bps")
        spread = decimal(self.spread_bps if self.spread_bps is not None else self.full_spread_bps, name="full_spread_bps")
        slip = decimal(self.slippage_bps, name="slippage_bps")
        maintenance = decimal(
            self.maintenance_margin if self.maintenance_margin is not None else self.maintenance_margin_ratio,
            name="maintenance_margin_ratio",
        )
        target_exposure = decimal(self.target_exposure, name="target_exposure")
        if capital <= ZERO:
            raise ValueError("initial_capital must be positive")
        if leverage < Decimal("1") or leverage > Decimal("3"):
            raise ValueError("leverage must be between 1x and 3x")
        if min(fee, spread, slip, maintenance) < ZERO:
            raise ValueError("costs and maintenance margin must be non-negative")
        if target_exposure < Decimal("0.25") or target_exposure > Decimal("1"):
            raise ValueError("target_exposure must be between 0.25 and 1")
        strategy_name = self.strategy if self.strategy is not None else self.strategy_name
        if not str(strategy_name).strip():
            raise ValueError("strategy_name is required")
        object.__setattr__(self, "initial_capital", capital)
        object.__setattr__(self, "capital", capital)
        object.__setattr__(self, "leverage", leverage)
        object.__setattr__(self, "taker_fee_bps", fee)
        object.__setattr__(self, "fee_bps", fee)
        object.__setattr__(self, "full_spread_bps", spread)
        object.__setattr__(self, "spread_bps", spread)
        object.__setattr__(self, "slippage_bps", slip)
        object.__setattr__(self, "maintenance_margin_ratio", maintenance)
        object.__setattr__(self, "maintenance_margin", maintenance)
        object.__setattr__(self, "target_exposure", target_exposure)
        object.__setattr__(self, "strategy_name", str(strategy_name).strip())
        object.__setattr__(self, "strategy", str(strategy_name).strip())
        interval = str(self.interval).strip() or "1d"
        if interval not in {"1h", "4h", "1d"}:
            raise ValueError("interval must be one of 1h, 4h, 1d")
        object.__setattr__(self, "interval", interval)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BacktestConfig":
        data = dict(value)
        parameters = data.get("strategy_parameters")
        if isinstance(parameters, Mapping) and "target_exposure" not in data and "target_exposure" in parameters:
            data["target_exposure"] = parameters["target_exposure"]
        aliases = {
            "capital": "initial_capital",
            "starting_capital": "initial_capital",
            "fee_bps": "taker_fee_bps",
            "taker_fee": "taker_fee_bps",
            "spread_bps": "full_spread_bps",
            "full_spread": "full_spread_bps",
            "maintenance_margin": "maintenance_margin_ratio",
            "strategy": "strategy",
        }
        for source, target in aliases.items():
            if source in data and target not in data:
                data[target] = data[source]
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


# Short aliases make the adapter boundary pleasant without creating a second
# set of contracts.
Instrument = InstrumentSpec
BacktestInstrument = InstrumentSpec
InstrumentMetadata = InstrumentSpec
InstrumentMeta = InstrumentSpec
BacktestBar = BarEvent
BarFeatureEvent = BarEvent
Bar = BarEvent
BacktestRunConfig = BacktestConfig


def coerce_instrument(value: InstrumentSpec | Mapping[str, Any], *, instrument_id: str | int | None = None) -> InstrumentSpec:
    if isinstance(value, InstrumentSpec):
        return value
    if isinstance(value, Mapping):
        return InstrumentSpec.from_mapping(value, instrument_id=instrument_id)
    raise TypeError("instruments must contain InstrumentSpec or mappings")


def coerce_bar(value: BarEvent | Mapping[str, Any], *, instrument_id: str | int | None = None) -> BarEvent:
    if isinstance(value, BarEvent):
        if value.instrument_id is not None or instrument_id is None:
            return value
        return BarEvent(
            timestamp=value.timestamp,
            open=value.open,
            high=value.high,
            low=value.low,
            close=value.close,
            volume=value.volume,
            features=value.features,
            funding_rate=value.funding_rate,
            instrument_id=instrument_id,
        )
    if isinstance(value, Mapping):
        return BarEvent.from_mapping(value, instrument_id=instrument_id)
    raise TypeError("bars must contain BarEvent or mappings")


def quantity_round_down(value: Decimal, step: Decimal) -> Decimal:
    """Round absolute quantity down to the exchange step while preserving sign."""

    if step <= ZERO:
        raise ValueError("step must be positive")
    sign = -1 if value < ZERO else 1
    units = (abs(value) / step).to_integral_value(rounding=ROUND_DOWN)
    return Decimal(sign) * units * step
