"""Read-only, deterministic crypto quant contracts.

The package deliberately contains no provider or execution clients.  Registry
definitions and persisted feature materialization are pure research inputs;
the backtest/API layers may depend on them without gaining order authority.
"""

from .features import (
    build_feature_payload,
    candle_available_at,
    feature_input_hash,
    feature_status,
    funding_available_at,
    ensure_registry,
    materialize_features,
    materialize_feature_value,
    metric_available_at,
    persist_feature_value,
    source_causal_available_at,
)
from .registry import (
    FEATURE_SET_REGISTRY,
    STRATEGY_REGISTRY,
    canonical_hash,
    canonical_json,
    feature_set_definition,
    get_strategy_definition,
    validate_strategy_parameters,
)

__all__ = [
    "FEATURE_SET_REGISTRY",
    "STRATEGY_REGISTRY",
    "build_feature_payload",
    "candle_available_at",
    "canonical_hash",
    "canonical_json",
    "feature_input_hash",
    "feature_set_definition",
    "feature_status",
    "funding_available_at",
    "get_strategy_definition",
    "ensure_registry",
    "materialize_features",
    "materialize_feature_value",
    "metric_available_at",
    "persist_feature_value",
    "source_causal_available_at",
    "validate_strategy_parameters",
]
