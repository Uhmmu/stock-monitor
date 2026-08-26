"""Offline validation of the persisted crypto derivatives regime.

The regime classifier is deliberately separate from this module.  A
validation run replays that classifier at historical cutoffs and joins each
state to candles that close strictly after the cutoff.  Inputs are expected to
be rows already persisted by the crypto repositories; this module never owns a
provider client, a database session, or a write path.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CryptoRegimeSnapshot, CryptoRegimeValidationRun
from app.services.crypto.regime import VERSION as REGIME_VERSION
from app.services.crypto.regime import evaluate_regime

VALIDATION_VERSION = "crypto-usdm-regime-validation-v1"
SUPPORTED_HORIZONS = ("1h", "4h", "1d")
HORIZON_DELTAS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}
MIN_SAMPLE_COUNT = 8


def _field(row: Any, *names: str) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if name in row:
                return row[name]
        return None
    for name in names:
        value = getattr(row, name, None)
        if value is not None:
            return value
    return None


def _utc(value: Any) -> datetime | None:
    """Parse persisted datetime or millisecond timestamp values as UTC."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float, Decimal)):
        number = float(value)
        parsed = datetime.fromtimestamp(
            number / (1000 if abs(number) >= 10_000_000_000 else 1), UTC
        )
    else:
        text = str(value).strip()
        try:
            number = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            parsed = datetime.fromtimestamp(
                number / (1000 if abs(number) >= 10_000_000_000 else 1), UTC
            )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value).isoformat() if _utc(value) else None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_canonical(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _row_identity(row: Any) -> str:
    """Stable tie-breaker for malformed/duplicate fixture rows."""

    return _digest(
        {
            "id": _field(row, "id"),
            "source_hash": _field(row, "source_hash"),
            "revision": _field(row, "revision"),
            "observed_at": _field(row, "observed_at", "observedAt"),
            "funding_time": _field(row, "funding_time", "fundingTime"),
            "open_time_ms": _field(row, "open_time_ms", "openTime"),
            "close_time_ms": _field(row, "close_time_ms", "closeTime"),
            "close": _field(row, "close", "close_price", "closePrice"),
        }
    )


def _sorted_rows(rows: Iterable[Any], timestamp_names: tuple[str, ...]) -> list[Any]:
    materialized = list(rows or [])
    return sorted(
        materialized,
        key=lambda row: (
            _utc(_field(row, *timestamp_names)) or datetime.min.replace(tzinfo=UTC),
            _row_identity(row),
        ),
    )


def _candle_times(row: Any, interval: str) -> tuple[datetime | None, datetime | None]:
    """Return open/close times without using an unpersisted current price.

    ``MarketCandle`` always has millisecond open/close columns.  The small
    fallbacks make frozen dictionaries useful in tests while retaining the
    same strict ordering rules.
    """

    open_time = _utc(_field(row, "open_time", "open_time_ms", "openTime"))
    close_time = _utc(_field(row, "close_time", "close_time_ms", "closeTime"))
    if close_time is None:
        close_time = _utc(_field(row, "timestamp", "time", "observed_at"))
    if open_time is None and close_time is not None:
        open_time = close_time - HORIZON_DELTAS[interval]
    return open_time, close_time


def _prepared_candles(candles: Iterable[Any], horizon: str) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in candles or []:
        row_interval = _field(row, "interval")
        if row_interval not in (None, "", horizon):
            continue
        if _field(row, "final") is False:
            continue
        open_time, close_time = _candle_times(row, horizon)
        close = _decimal(_field(row, "close", "close_price", "closePrice"))
        if open_time is None or close_time is None or close is None or close <= 0:
            continue
        prepared.append(
            {
                "open_time": open_time,
                "close_time": close_time,
                "close": close,
                "source_hash": _field(row, "source_hash"),
                "provider": _field(row, "provider"),
                "id": _field(row, "id"),
                "interval": row_interval or horizon,
            }
        )
    return sorted(
        prepared,
        key=lambda row: (
            row["close_time"],
            row["open_time"],
            str(row["source_hash"] or ""),
            str(row["id"] or ""),
        ),
    )


def _forward_outcome(
    candles: list[dict[str, Any]], cutoff: datetime, horizon: str
) -> dict[str, Any]:
    """Join an as-of cutoff to a later *closed* candle only.

    The anchor must have closed at or before the cutoff.  The target candle
    must start at/after the cutoff and close no earlier than the requested
    horizon.  Thus a forming/partially overlapping candle can never leak into
    either side of a validation sample.
    """

    anchor_candidates = [row for row in candles if row["close_time"] <= cutoff]
    if not anchor_candidates:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": "NO_ANCHOR_CANDLE",
            "horizon": horizon,
        }
    anchor = anchor_candidates[-1]
    target_at = cutoff + HORIZON_DELTAS[horizon]
    target_candidates = [
        row
        for row in candles
        if row["open_time"] >= cutoff
        and row["close_time"] > cutoff
        # MarketCandle stores an inclusive millisecond close_time.  Allow
        # that final millisecond while retaining the strict later-candle rule.
        and row["close_time"] + timedelta(milliseconds=1) >= target_at
    ]
    if not target_candidates:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": "NO_FORWARD_CANDLE",
            "horizon": horizon,
            "anchor_time": anchor["close_time"].isoformat(),
            "target_at": target_at.isoformat(),
        }
    target = target_candidates[0]
    forward_return = target["close"] / anchor["close"] - Decimal("1")
    direction = "UP" if forward_return > 0 else "DOWN" if forward_return < 0 else "FLAT"
    return {
        "status": "READY",
        "horizon": horizon,
        "anchor_time": anchor["close_time"].isoformat(),
        "target_time": target["close_time"].isoformat(),
        "target_at": target_at.isoformat(),
        "anchor_close": str(anchor["close"]),
        "target_close": str(target["close"]),
        "forward_return": str(forward_return),
        "direction": direction,
        "anchor_source_hash": anchor["source_hash"],
        "target_source_hash": target["source_hash"],
        "provider": target["provider"],
    }


def _evaluation_times(
    metrics: list[Any], requested: Iterable[datetime] | None
) -> list[datetime]:
    if requested is not None:
        values = {_utc(value) for value in requested}
    else:
        values = {
            _utc(_field(row, "observed_at", "observedAt")) for row in metrics
        }
    values.discard(None)
    return sorted(values)


def _summary(evaluations: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
    outcomes = [
        item["outcomes"][horizon]
        for item in evaluations
        if item["outcomes"].get(horizon, {}).get("status") == "READY"
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evaluations:
        outcome = item["outcomes"].get(horizon, {})
        if outcome.get("status") == "READY":
            grouped[item["state"]].append(outcome)

    def stats(values: list[dict[str, Any]]) -> dict[str, Any]:
        returns = [_decimal(item.get("forward_return")) for item in values]
        returns = [value for value in returns if value is not None]
        if not returns:
            return {"sample_count": 0, "mean_forward_return": None, "positive_rate": None}
        positive = sum(value > 0 for value in returns)
        return {
            "sample_count": len(returns),
            "mean_forward_return": str(sum(returns, Decimal("0")) / len(returns)),
            "positive_rate": str(Decimal(positive) / len(returns)),
        }

    state_stats = {state: stats(values) for state, values in sorted(grouped.items())}
    sample_count = len(outcomes)
    return {
        "horizon": horizon,
        "status": "READY" if sample_count >= MIN_SAMPLE_COUNT else "INSUFFICIENT_DATA",
        "sample_count": sample_count,
        "minimum_sample_count": MIN_SAMPLE_COUNT,
        "missing_outcome_count": len(evaluations) - sample_count,
        "coverage": str(Decimal(sample_count) / len(evaluations)) if evaluations else "0",
        "statistics": stats(outcomes),
        "by_state": state_stats,
        "warnings": ["OBSERVATIONAL_ONLY"]
        + (["INSUFFICIENT_SAMPLE"] if sample_count < MIN_SAMPLE_COUNT else [])
        + (["OVERLAPPING_WINDOWS"] if sample_count > 1 else []),
    }


def validate_regime_history(
    metrics: Iterable[Any],
    funding_rates: Iterable[Any],
    candles: Iterable[Any],
    *,
    evaluation_times: Iterable[datetime] | None = None,
    horizons: Iterable[str] = SUPPORTED_HORIZONS,
) -> dict[str, Any]:
    """Replay regime states and join point-in-time forward candle outcomes.

    ``metrics``, ``funding_rates`` and ``candles`` are intentionally plain
    iterables so callers can pass rows read from PostgreSQL.  No function in
    this module opens a session or calls a provider.  Evaluation cutoffs are
    explicit when supplied; otherwise each persisted metric timestamp is used.
    """

    requested_horizons = set(horizons)
    unsupported = requested_horizons.difference(SUPPORTED_HORIZONS)
    if unsupported:
        raise ValueError(
            "horizons must be one of 1h, 4h or 1d"
        )
    selected_horizons = tuple(
        horizon for horizon in SUPPORTED_HORIZONS if horizon in requested_horizons
    )
    if not selected_horizons:
        raise ValueError("horizons must include one of 1h, 4h or 1d")

    metric_rows = _sorted_rows(metrics, ("observed_at", "observedAt"))
    funding_rows = _sorted_rows(funding_rates, ("funding_time", "fundingTime"))
    candle_rows = list(candles or [])
    cutoffs = _evaluation_times(metric_rows, evaluation_times)
    candles_by_horizon = {
        horizon: _prepared_candles(candle_rows, horizon)
        for horizon in selected_horizons
    }

    evaluations: list[dict[str, Any]] = []
    for cutoff in cutoffs:
        regime = evaluate_regime(metric_rows, funding_rows, evaluated_at=cutoff)
        outcomes = {
            horizon: _forward_outcome(candles_by_horizon[horizon], cutoff, horizon)
            for horizon in selected_horizons
        }
        evaluations.append(
            {
                "evaluation_at": cutoff.isoformat(),
                "regime_as_of": regime.get("as_of"),
                "state": regime.get("state"),
                "regime_version": regime.get("version", REGIME_VERSION),
                "regime_input_hash": regime.get("input_hash"),
                "regime": regime,
                "outcomes": outcomes,
                "warnings": ["OBSERVATIONAL_ONLY"],
            }
        )

    summaries = {horizon: _summary(evaluations, horizon) for horizon in selected_horizons}
    valid_horizons = [item["status"] == "READY" for item in summaries.values()]
    status = "READY" if valid_horizons and all(valid_horizons) else "INSUFFICIENT_DATA"
    used_inputs = [
        {
            "evaluation_at": item["evaluation_at"],
            "regime_input_hash": item["regime_input_hash"],
            "outcomes": {
                horizon: {
                    key: value
                    for key, value in outcome.items()
                    if key not in {"anchor_close", "target_close"}
                }
                for horizon, outcome in item["outcomes"].items()
            },
        }
        for item in evaluations
    ]
    return {
        "status": status,
        "validation_version": VALIDATION_VERSION,
        "regime_version": REGIME_VERSION,
        "horizons": list(selected_horizons),
        "evaluation_count": len(evaluations),
        "evaluations": evaluations,
        "summaries": summaries,
        "input_hash": _digest(used_inputs),
        "warnings": [
            "STRICT_POINT_IN_TIME_CUTOFF",
            "FORWARD_OUTCOMES_USE_LATER_CLOSED_CANDLES_ONLY",
            "OBSERVATIONAL_ONLY",
        ]
        + (["INSUFFICIENT_DATA"] if status != "READY" else []),
    }


def _number(value: Any) -> float | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    return float(parsed)


def persist_regime_snapshot(
    db: Session,
    *,
    instrument_id: int,
    regime: Mapping[str, Any],
    evaluated_at: datetime | None = None,
    source: str = "persisted_derivatives",
) -> CryptoRegimeSnapshot:
    """Persist one immutable regime payload, returning an idempotent replay.

    A changed input hash creates a new versioned row.  Reusing the same
    identity with different payload bytes is rejected rather than rewriting
    historical evidence.
    """

    if not isinstance(regime, Mapping):
        raise ValueError("regime payload must be a mapping")
    as_of = _utc(regime.get("as_of"))
    if as_of is None:
        raise ValueError("regime payload requires as_of")
    version = str(regime.get("version") or REGIME_VERSION)
    input_hash = str(regime.get("input_hash") or "")
    if not input_hash:
        raise ValueError("regime payload requires input_hash")
    evaluated = _utc(evaluated_at) or as_of
    valid_until = _utc(regime.get("valid_until"))
    payload = _canonical(dict(regime))
    snapshot_key = _digest(
        {
            "instrument_id": instrument_id,
            "as_of": as_of,
            "regime_version": version,
            "input_hash": input_hash,
        }
    )
    existing = db.scalar(
        select(CryptoRegimeSnapshot).where(
            CryptoRegimeSnapshot.snapshot_key == snapshot_key
        )
    )
    if existing is not None:
        if _canonical(existing.payload or {}) != payload:
            raise ValueError("immutable regime snapshot identity has a different payload")
        return existing
    snapshot = CryptoRegimeSnapshot(
        instrument_id=instrument_id,
        regime_version=version,
        as_of=as_of,
        evaluated_at=evaluated,
        valid_until=valid_until,
        state=str(regime.get("state") or "INSUFFICIENT_DATA"),
        threshold_hash=regime.get("threshold_hash"),
        input_hash=input_hash,
        confidence=_number(regime.get("confidence")),
        coverage=_number(regime.get("coverage")),
        source=source,
        payload=payload,
        snapshot_key=snapshot_key,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def persist_validation_run(
    db: Session,
    *,
    instrument_id: int,
    validation: Mapping[str, Any],
    status: str | None = None,
) -> CryptoRegimeValidationRun:
    """Persist one complete validation result/evidence payload idempotently."""

    if not isinstance(validation, Mapping):
        raise ValueError("validation payload must be a mapping")
    validation_version = str(validation.get("validation_version") or VALIDATION_VERSION)
    regime_version = str(validation.get("regime_version") or REGIME_VERSION)
    input_hash = str(validation.get("input_hash") or "")
    if not input_hash:
        raise ValueError("validation payload requires input_hash")
    requested_status = str(status or validation.get("status") or "completed")
    # Validation quality (READY/INSUFFICIENT_DATA) is distinct from the
    # persistence lifecycle; an insufficient but completed study is still a
    # completed run with explicit gaps in its payload.
    run_status = (
        requested_status
        if requested_status in {"pending", "running", "completed", "failed"}
        else "completed"
        if requested_status in {"READY", "INSUFFICIENT_DATA", "PARTIAL_INSUFFICIENT_DATA", "OBSERVATIONAL"}
        else requested_status
    )
    if run_status not in {"pending", "running", "completed", "failed"}:
        raise ValueError("unsupported validation run status")
    result_payload = _canonical(dict(validation))
    evidence = _canonical(
        {
            "evaluations": validation.get("evaluations") or [],
            "summaries": validation.get("summaries") or {},
        }
    )
    run_key = _digest(
        {
            "instrument_id": instrument_id,
            "validation_version": validation_version,
            "input_hash": input_hash,
        }
    )
    existing = db.scalar(
        select(CryptoRegimeValidationRun).where(
            CryptoRegimeValidationRun.run_key == run_key
        )
    )
    if existing is not None:
        if _canonical(existing.result_payload or {}) != result_payload:
            raise ValueError("immutable validation run identity has a different payload")
        return existing
    evaluations = validation.get("evaluations") or []
    cutoff_values = [
        _utc(item.get("evaluation_at"))
        for item in evaluations
        if isinstance(item, Mapping)
    ]
    cutoff_values = [item for item in cutoff_values if item is not None]
    run = CryptoRegimeValidationRun(
        instrument_id=instrument_id,
        validation_version=validation_version,
        regime_version=regime_version,
        status=run_status,
        horizons=list(validation.get("horizons") or []),
        evaluation_count=int(validation.get("evaluation_count") or len(evaluations)),
        data_cutoff=_utc(validation.get("data_cutoff")) or (max(cutoff_values) if cutoff_values else None),
        input_hash=input_hash,
        result_payload=result_payload,
        evidence=evidence,
        warnings=list(validation.get("warnings") or []),
        run_key=run_key,
    )
    db.add(run)
    db.flush()
    return run


# The explicit alias reads naturally at call sites that run an offline study.
validate_historical_regime = validate_regime_history
persist_regime_validation_run = persist_validation_run
