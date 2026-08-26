"""Optional, read-only bridge from crypto regime context to Mood consumers.

This module intentionally has no import from the equity Mood service or its
models.  It produces a separate context envelope that a future consumer may
read; it never creates, updates, or scores an equity ``MoodSnapshot``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

BRIDGE_VERSION = "crypto-regime-mood-context-v1"


def _copy(value: Any) -> Any:
    """Copy nested persisted evidence while keeping the payload JSON-safe."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_copy(item) for item in value]
    return value


def build_mood_bridge_payload(
    regime: Mapping[str, Any] | None,
    *,
    validation: Mapping[str, Any] | None = None,
    scope_key: str | None = None,
) -> dict[str, Any]:
    """Build a separate crypto context envelope without mutating Mood.

    The bridge remains observational until the validation payload reports a
    ready sample for every selected horizon.  Even then, ``equity_mood_impact``
    stays false: this function is a read-only context adapter, not a scoring
    or snapshot writer.
    """

    base = {
        "bridge_version": BRIDGE_VERSION,
        "context_type": "crypto_derivatives_regime",
        "scope_type": "crypto_regime",
        "scope_key": scope_key or "crypto",
        "read_only": True,
        "equity_mood_impact": False,
        "writes_mood_snapshots": False,
    }
    if not isinstance(regime, Mapping) or not regime.get("state"):
        return {
            **base,
            "status": "UNAVAILABLE",
            "reason": "REGIME_UNAVAILABLE",
            "state": None,
            "validation_status": "INSUFFICIENT_DATA",
            "warnings": ["CRYPTO_REGIME_BRIDGE_UNAVAILABLE"],
        }

    validation_status = (
        str(validation.get("status"))
        if isinstance(validation, Mapping) and validation.get("status")
        else "INSUFFICIENT_DATA"
    )
    status = "READY" if validation_status == "READY" else "OBSERVATIONAL"
    warning_values = {
        "CRYPTO_CONTEXT_ONLY",
        "EQUITY_MOOD_UNCHANGED",
        *(str(item) for item in (regime.get("warnings") or [])),
    }
    if isinstance(validation, Mapping):
        warning_values.update(str(item) for item in (validation.get("warnings") or []))
    return {
        **base,
        "status": status,
        "validation_status": validation_status,
        "validation_version": (
            validation.get("validation_version")
            if isinstance(validation, Mapping)
            else None
        ),
        "regime_version": regime.get("version"),
        "regime_input_hash": regime.get("input_hash"),
        "state": regime.get("state"),
        "as_of": regime.get("as_of"),
        "valid_until": regime.get("valid_until"),
        "confidence": regime.get("confidence"),
        "coverage": regime.get("coverage"),
        "evidence": _copy(regime.get("evidence") or []),
        "features": _copy(regime.get("features") or {}),
        "omissions": _copy(regime.get("omissions") or []),
        "warnings": sorted(warning_values),
        "validation": _copy(validation) if isinstance(validation, Mapping) else None,
    }


# Keep the call-site wording flexible without adding a second implementation.
build_crypto_mood_context = build_mood_bridge_payload
