from __future__ import annotations

import pytest

from app.services.quant.registry import (
    FEATURE_SET_KEY,
    FEATURE_SET_REGISTRY,
    STRATEGY_REGISTRY,
    canonical_hash,
    canonical_json,
    feature_set_definition,
    strategy_config_hash,
    validate_strategy_parameters,
)


def test_registry_contains_only_the_two_supported_strategies_and_feature_set():
    assert set(STRATEGY_REGISTRY) == {"dual-ma-trend-v1", "rsi-mean-reversion-v1"}
    assert set(FEATURE_SET_REGISTRY) == {FEATURE_SET_KEY}
    assert FEATURE_SET_REGISTRY[FEATURE_SET_KEY].availability_policy == "source_causal_v1"


def test_hash_is_deterministic_and_ordered_mapping_keys_do_not_matter():
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert canonical_hash({"values": [1, 2]}) != canonical_hash({"values": [2, 1]})


def test_strategy_config_hash_and_parameters_are_stable():
    first = strategy_config_hash("dual-ma-trend-v1", {"target_exposure": 0.5})
    second = strategy_config_hash("dual-ma-trend-v1", {"target_exposure": 0.50})
    assert first == second
    assert validate_strategy_parameters("dual-ma-trend-v1") == {"target_exposure": 1.0}
    assert validate_strategy_parameters("dual-ma-trend-v1", {"target_exposure": 0.25}) == {"target_exposure": 0.25}


@pytest.mark.parametrize("value", [0.249, 1.001, True, "not-a-number"])
def test_target_exposure_is_bounded(value):
    with pytest.raises(ValueError):
        validate_strategy_parameters("rsi-mean-reversion-v1", {"target_exposure": value})


def test_unknown_strategy_parameter_is_rejected():
    with pytest.raises(ValueError, match="unknown parameters"):
        validate_strategy_parameters("dual-ma-trend-v1", {"window": 20})


def test_registry_definition_is_not_mutable():
    definition = STRATEGY_REGISTRY["dual-ma-trend-v1"]
    with pytest.raises(TypeError):
        definition.parameter_schema["target_exposure"] = {}  # type: ignore[index]
    assert definition.config_hash == canonical_hash(definition.config)


def test_feature_set_lookup_rejects_unknown_versions():
    assert feature_set_definition().key == FEATURE_SET_KEY
    with pytest.raises(ValueError):
        feature_set_definition("missing-v1")
