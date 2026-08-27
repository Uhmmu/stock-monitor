"""Explicit, immutable registry for the supported quant definitions.

There is intentionally no plugin loader: a strategy can only be selected if
it is present in this module, and its only user parameter is bounded
``target_exposure``.  Hashes are SHA-256 over canonical JSON and therefore do
not depend on dictionary insertion order or Python's repr formatting.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _canonical(value: Any) -> Any:
    """Return JSON-compatible data with stable ordering and scalar forms."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # Sets are not used by the built-ins, but sorting their canonical
        # values makes the helper safe for callers building a config hash.
        values = [_canonical(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float is not hashable")
        return value
    return value


def canonical_json(value: Any) -> str:
    """Serialize a definition/config canonically for hashing and manifests."""

    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    version: str
    name: str
    description: str
    interval: str
    universe: tuple[str, ...]
    parameter_schema: Mapping[str, Any]
    default_parameters: Mapping[str, Any]
    implementation: str
    config_hash: str
    code_version: str = "registry-v1"
    status: str = "released"

    @property
    def strategy_key(self) -> str:
        return self.key

    @property
    def config(self) -> Mapping[str, Any]:
        return {
            "strategy_key": self.key,
            "version": self.version,
            "intervals": ("1h", "4h", "1d"),
            "universe": self.universe,
            "parameter_schema": self.parameter_schema,
            "default_parameters": self.default_parameters,
            "implementation": self.implementation,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.key,
            "key": self.key,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "interval": self.interval,
            "universe": list(self.universe),
            "parameter_schema": _canonical(self.parameter_schema),
            "default_parameters": _canonical(self.default_parameters),
            "config": _canonical(self.config),
            "implementation": self.implementation,
            "config_hash": self.config_hash,
            "code_version": self.code_version,
            "status": self.status,
        }


def _strategy(
    *,
    key: str,
    name: str,
    description: str,
    implementation: str,
) -> StrategyDefinition:
    schema = {
        "target_exposure": {
            "type": "number",
            "minimum": 0.25,
            "maximum": 1.0,
            "default": 1.0,
        }
    }
    defaults = {"target_exposure": 1.0}
    config = {
        "strategy_key": key,
        "version": "v1",
        "intervals": ["1h", "4h", "1d"],
        "universe": ["BTCUSDT", "ETHUSDT", "ADAUSDT"],
        "parameter_schema": schema,
        "default_parameters": defaults,
        "implementation": implementation,
    }
    return StrategyDefinition(
        key=key,
        version="v1",
        name=name,
        description=description,
        interval="1h",
        universe=("BTCUSDT", "ETHUSDT", "ADAUSDT"),
        parameter_schema=_freeze(schema),
        default_parameters=_freeze(defaults),
        implementation=implementation,
        config_hash=canonical_hash(config),
    )


STRATEGY_REGISTRY: Mapping[str, StrategyDefinition] = MappingProxyType(
    {
        "dual-ma-trend-v1": _strategy(
            key="dual-ma-trend-v1",
            name="Dual moving-average trend",
            description="SMA20/SMA50 trend target with no position when indicators are unavailable.",
            implementation="sma20_gt_sma50_target_exposure",
        ),
        "rsi-mean-reversion-v1": _strategy(
            key="rsi-mean-reversion-v1",
            name="RSI mean reversion",
            description="RSI14 oversold/overbought target with no position between thresholds.",
            implementation="rsi14_threshold_target_exposure",
        ),
    }
)


FEATURE_NAMES: tuple[str, ...] = (
    "return_1",
    "return_6",
    "return_24",
    "realized_volatility_24",
    "atr14_close",
    "rsi14",
    "macd_line_12_26",
    "macd_signal_9",
    "macd_histogram",
    "sma20",
    "sma50",
    "sma20_distance",
    "sma50_distance",
    "volume_zscore20",
    "taker_imbalance",
    "funding_rate",
    "oi_change_24",
    "basis_rate",
    "taker_buy_sell_ratio",
)

FEATURE_SET_KEY = "crypto-quant-features-v1"


@dataclass(frozen=True)
class FeatureSetDefinition:
    key: str
    version: str
    name: str
    supported_intervals: tuple[str, ...]
    features: tuple[str, ...]
    parameters: Mapping[str, Any]
    input_declarations: Mapping[str, Any]
    availability_policy: str
    config_hash: str
    code_version: str = "features-v1"
    status: str = "released"

    @property
    def feature_set_key(self) -> str:
        return self.key

    @property
    def feature_schema(self) -> Mapping[str, Any]:
        return {name: {"type": "number", "nullable": True} for name in self.features}

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_set_key": self.key,
            "key": self.key,
            "version": self.version,
            "name": self.name,
            "supported_intervals": list(self.supported_intervals),
            "features": list(self.features),
            "feature_schema": _canonical(self.feature_schema),
            "parameters": _canonical(self.parameters),
            "input_declarations": _canonical(self.input_declarations),
            "availability_policy": self.availability_policy,
            "config_hash": self.config_hash,
            "code_version": self.code_version,
            "status": self.status,
        }


_FEATURE_PARAMETERS = {
    "returns_periods": [1, 6, 24],
    "realized_volatility_period": 24,
    "atr_period": 14,
    "rsi_period": 14,
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "moving_average_periods": [20, 50],
    "volume_zscore_period": 20,
}
_FEATURE_INPUTS = {
    "trade_candle": {
        "authority": "market_candles",
        "price_type": "trade",
        "required": True,
        "final_only": True,
    },
    "derivatives_metric": {
        "authority": "crypto_derivatives_metrics",
        "interval": "1h",
        "required": False,
        "fields": ["open_interest_base", "basis_rate", "taker_buy_sell_ratio"],
    },
    "realized_funding": {
        "authority": "crypto_funding_rates",
        "required": False,
        "field": "funding_rate",
        "exclude": ["predicted_rate"],
    },
}
_FEATURE_CONFIG = {
    "key": FEATURE_SET_KEY,
    "version": "v1",
    "supported_intervals": ["1h", "4h", "1d"],
    "features": FEATURE_NAMES,
    "parameters": _FEATURE_PARAMETERS,
    "input_declarations": _FEATURE_INPUTS,
    "availability_policy": "source_causal_v1",
}

FEATURE_SET_REGISTRY: Mapping[str, FeatureSetDefinition] = MappingProxyType(
    {
        FEATURE_SET_KEY: FeatureSetDefinition(
            key=FEATURE_SET_KEY,
            version="v1",
            name="Crypto quant features",
            supported_intervals=("1h", "4h", "1d"),
            features=FEATURE_NAMES,
            parameters=_freeze(_FEATURE_PARAMETERS),
            input_declarations=_freeze(_FEATURE_INPUTS),
            availability_policy="source_causal_v1",
            config_hash=canonical_hash(_FEATURE_CONFIG),
        )
    }
)


def get_strategy_definition(key: str) -> StrategyDefinition:
    try:
        return STRATEGY_REGISTRY[key]
    except KeyError as exc:
        raise ValueError(f"unknown quant strategy {key!r}") from exc


def validate_strategy_parameters(
    strategy: str | StrategyDefinition,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Validate and normalize the sole user-configurable strategy parameter."""

    definition = get_strategy_definition(strategy) if isinstance(strategy, str) else strategy
    incoming = dict(parameters or {})
    unknown = sorted(set(incoming) - {"target_exposure"})
    if unknown:
        raise ValueError(f"unknown parameters for {definition.key}: {', '.join(unknown)}")
    raw = incoming.get("target_exposure", definition.default_parameters["target_exposure"])
    if isinstance(raw, bool):
        raise ValueError("target_exposure must be a number")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("target_exposure must be a number") from exc
    if not value.is_finite() or value < Decimal("0.25") or value > Decimal("1"):
        raise ValueError("target_exposure must be between 0.25 and 1.0")
    return {"target_exposure": float(value)}


def strategy_config_hash(
    strategy: str | StrategyDefinition,
    parameters: Mapping[str, Any] | None = None,
) -> str:
    definition = get_strategy_definition(strategy) if isinstance(strategy, str) else strategy
    return canonical_hash({"definition_hash": definition.config_hash, "parameters": validate_strategy_parameters(definition, parameters)})


def feature_set_definition(key: str = FEATURE_SET_KEY) -> FeatureSetDefinition:
    try:
        return FEATURE_SET_REGISTRY[key]
    except KeyError as exc:
        raise ValueError(f"unknown quant feature set {key!r}") from exc


# Friendly aliases for callers that use the term ``hash_config`` in manifests.
hash_config = canonical_hash
get_strategy = get_strategy_definition
validate_parameters = validate_strategy_parameters


__all__ = [
    "FEATURE_NAMES",
    "FEATURE_SET_KEY",
    "FEATURE_SET_REGISTRY",
    "FeatureSetDefinition",
    "STRATEGY_REGISTRY",
    "StrategyDefinition",
    "canonical_hash",
    "canonical_json",
    "feature_set_definition",
    "get_strategy_definition",
    "get_strategy",
    "hash_config",
    "strategy_config_hash",
    "validate_parameters",
    "validate_strategy_parameters",
]
