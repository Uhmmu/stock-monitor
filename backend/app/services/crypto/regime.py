"""Deterministic USD-M derivatives regime v1 (WP 4.4).

The classifier is descriptive evidence beside Mood, never a sentiment score
or trading gate. It reads persisted point-in-time facts only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

VERSION = "crypto-usdm-regime-v1"
HOUR = timedelta(hours=1)
ZERO = Decimal("0")
THRESHOLDS = {
    "minimum": {"oi": 120, "funding": 14, "basis": 120, "taker": 18, "coverage": "0.70"},
    "oi": {"change": "0.05", "z": "1.50"},
    "funding": {"rate": "0.0005", "z": "1.50"},
    "basis": {"rate": "0.0010", "z": "1.50"},
    "taker": {"imbalance": "0.10"},
}
THRESHOLD_HASH = hashlib.sha256(
    json.dumps(THRESHOLDS, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def _value(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _zscore(current: Decimal | None, history: list[Decimal]) -> tuple[Decimal | None, str | None]:
    if current is None or not history:
        return None, "MISSING_HISTORY"
    mean = sum(history, ZERO) / Decimal(len(history))
    variance = sum(((item - mean) ** 2 for item in history), ZERO) / Decimal(len(history))
    if variance == 0:
        return None, "NO_VARIANCE"
    return (current - mean) / variance.sqrt(), None


def _row_hash(row: Any, fields: Iterable[str]) -> dict:
    return {
        "time": str(_value(row, "observed_at") or _value(row, "funding_time")),
        "source_hash": _value(row, "source_hash"),
        "revision": _value(row, "revision"),
        **{field: str(_value(row, field)) for field in fields},
    }


def _ratio(change_from: Decimal | None, current: Decimal | None) -> Decimal | None:
    if change_from is None or current is None or change_from <= 0 or current <= 0:
        return None
    return current / change_from - 1


def evaluate_regime(
    metrics: Iterable[Any],
    funding_rates: Iterable[Any],
    *,
    evaluated_at: datetime | None = None,
) -> dict:
    evaluated_at = _utc(evaluated_at) or datetime.now(UTC)
    metric_rows = sorted(
        (row for row in metrics if _utc(_value(row, "observed_at")) is not None),
        key=lambda row: _utc(_value(row, "observed_at")),
    )
    funding_rows = sorted(
        (row for row in funding_rates if _utc(_value(row, "funding_time")) is not None),
        key=lambda row: _utc(_value(row, "funding_time")),
    )
    metric_rows = [row for row in metric_rows if _utc(_value(row, "observed_at")) <= evaluated_at]
    if not metric_rows:
        return _insufficient(evaluated_at, ["NO_DERIVATIVES_METRICS"])

    current = metric_rows[-1]
    as_of = _utc(_value(current, "observed_at"))
    rows = { _utc(_value(row, "observed_at")): row for row in metric_rows if _utc(_value(row, "observed_at")) <= as_of }

    current_oi = _decimal(_value(current, "open_interest_base"))
    baseline = rows.get(as_of - timedelta(hours=24))
    oi24 = _ratio(_decimal(_value(baseline, "open_interest_base")) if baseline else None, current_oi)
    oi_changes: list[Decimal] = []
    for offset in range(1, 169):
        timestamp = as_of - offset * HOUR
        row = rows.get(timestamp)
        prior = rows.get(timestamp - timedelta(hours=24))
        change = _ratio(
            _decimal(_value(prior, "open_interest_base")) if prior else None,
            _decimal(_value(row, "open_interest_base")) if row else None,
        )
        if change is not None:
            oi_changes.append(change)
    z_oi, oi_z_error = _zscore(oi24, oi_changes)

    basis_rate = _decimal(_value(current, "basis_rate"))
    basis_history = [
        value
        for offset in range(1, 169)
        if (value := _decimal(_value(rows.get(as_of - offset * HOUR), "basis_rate"))) is not None
    ]
    z_basis, basis_z_error = _zscore(basis_rate, basis_history)

    usable_funding = [row for row in funding_rows if _utc(_value(row, "funding_time")) <= as_of]
    latest_funding = usable_funding[-1] if usable_funding else None
    funding_rate = _decimal(_value(latest_funding, "funding_rate")) if latest_funding else None
    funding_time = _utc(_value(latest_funding, "funding_time")) if latest_funding else None
    prior_funding = [
        _decimal(_value(row, "funding_rate"))
        for row in usable_funding[:-1]
        if funding_time - timedelta(days=7) <= _utc(_value(row, "funding_time")) < funding_time
    ] if funding_time else []
    prior_funding = [value for value in prior_funding if value is not None]
    funding_fresh = funding_time is not None and as_of - funding_time <= timedelta(hours=9)
    z_funding, funding_z_error = _zscore(funding_rate, prior_funding)

    taker_rows = [rows.get(as_of - offset * HOUR) for offset in range(24)]
    taker_pairs = [
        (buy, sell)
        for row in taker_rows if row is not None
        if (buy := _decimal(_value(row, "taker_buy_volume"))) is not None
        if (sell := _decimal(_value(row, "taker_sell_volume"))) is not None
    ]
    taker_total = sum((buy + sell for buy, sell in taker_pairs), ZERO)
    taker24 = (
        sum((buy - sell for buy, sell in taker_pairs), ZERO) / taker_total
        if taker_total > 0 else None
    )

    counts = {
        "oi": len(oi_changes), "funding": len(prior_funding),
        "basis": len(basis_history), "taker": len(taker_pairs),
    }
    ready = {
        "oi": oi24 is not None and z_oi is not None and counts["oi"] >= 120,
        "funding": funding_fresh and z_funding is not None and counts["funding"] >= 14,
        "basis": basis_rate is not None and z_basis is not None and counts["basis"] >= 120,
        "taker": taker24 is not None and counts["taker"] >= 18,
    }
    coverage_parts = {
        "oi": min(Decimal(counts["oi"]) / 168, 1) if oi24 is not None else ZERO,
        "funding": min(Decimal(counts["funding"]) / 21, 1) if funding_fresh else ZERO,
        "basis": min(Decimal(counts["basis"]) / 168, 1) if basis_rate is not None else ZERO,
        "taker": min(Decimal(counts["taker"]) / 24, 1) if taker_total > 0 else ZERO,
    }
    coverage = sum(coverage_parts.values(), ZERO) / 4
    sufficient = ready["oi"] and sum(ready[key] for key in ("funding", "basis", "taker")) >= 2 and coverage >= Decimal("0.70")

    evidence: list[str] = []
    omissions: list[str] = []
    warnings: list[str] = []
    for family, error in (("OI", oi_z_error), ("FUNDING", funding_z_error), ("BASIS", basis_z_error)):
        if error:
            omissions.append(f"{family}_{error}")
    if not funding_fresh:
        omissions.append("FUNDING_STALE_OR_MISSING")
    if counts["taker"] < 18 or taker_total <= 0:
        omissions.append("TAKER_HISTORY_INSUFFICIENT")

    oi_up = ready["oi"] and oi24 >= Decimal("0.05") and z_oi >= Decimal("1.50")
    oi_down = ready["oi"] and oi24 <= Decimal("-0.05") and z_oi <= Decimal("-1.50")
    funding_long = ready["funding"] and funding_rate >= Decimal("0.0005") and z_funding >= Decimal("1.50")
    funding_short = ready["funding"] and funding_rate <= Decimal("-0.0005") and z_funding <= Decimal("-1.50")
    basis_long = ready["basis"] and basis_rate >= Decimal("0.0010") and z_basis >= Decimal("1.50")
    basis_short = ready["basis"] and basis_rate <= Decimal("-0.0010") and z_basis <= Decimal("-1.50")
    taker_long = ready["taker"] and taker24 >= Decimal("0.10")
    taker_short = ready["taker"] and taker24 <= Decimal("-0.10")
    votes_long = sum((funding_long, basis_long, taker_long))
    votes_short = sum((funding_short, basis_short, taker_short))

    if oi_up: evidence.append("OI_24H_RISE_EXTREME")
    if oi_down: evidence.append("OI_24H_FALL_EXTREME")
    if funding_long: evidence.append("FUNDING_POSITIVE_EXTREME")
    if funding_short: evidence.append("FUNDING_NEGATIVE_EXTREME")
    if basis_long: evidence.append("BASIS_PREMIUM_EXTREME")
    if basis_short: evidence.append("BASIS_DISCOUNT_EXTREME")
    if taker_long: evidence.append("TAKER_BUY_IMBALANCE")
    if taker_short: evidence.append("TAKER_SELL_IMBALANCE")
    if votes_long and votes_short:
        evidence.append("DIRECTIONAL_CONFLICT")

    if not sufficient:
        state = "INSUFFICIENT_DATA"
    elif oi_down:
        state = "DELEVERAGING"
    elif oi_up and votes_long >= 2 and votes_long > votes_short:
        state = "LONG_CROWDING"
    elif oi_up and votes_short >= 2 and votes_short > votes_long:
        state = "SHORT_CROWDING"
    elif oi_up:
        state = "LEVERAGE_BUILDUP"
    else:
        state = "BALANCED"

    if state == "INSUFFICIENT_DATA":
        confidence = ZERO
    else:
        conflict = 1 - Decimal(min(votes_long, votes_short)) / 3
        oi_strength = min(Decimal(1), max(abs(oi24) / Decimal("0.10"), abs(z_oi) / 3))
        if state in ("LONG_CROWDING", "SHORT_CROWDING"):
            factor = Decimal(max(votes_long, votes_short)) / 3
        elif state in ("LEVERAGE_BUILDUP", "DELEVERAGING"):
            factor = oi_strength
        else:
            factor = 1 - Decimal(max(votes_long, votes_short)) / 6
        confidence = min(Decimal(1), max(ZERO, coverage * conflict * factor))

    valid_until = as_of + timedelta(hours=2)
    stale = evaluated_at > valid_until
    if stale:
        warnings.append("STALE_DATA")
    input_rows = [
        _row_hash(row, ("open_interest_base", "basis_rate", "taker_buy_volume", "taker_sell_volume"))
        for row in metric_rows if _utc(_value(row, "observed_at")) >= as_of - timedelta(hours=192)
    ] + [
        _row_hash(row, ("funding_rate",)) for row in usable_funding
        if _utc(_value(row, "funding_time")) >= as_of - timedelta(days=7)
    ]
    input_hash = hashlib.sha256(
        json.dumps(sorted(input_rows, key=lambda item: item["time"]), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "state": state, "version": VERSION, "threshold_hash": THRESHOLD_HASH, "input_hash": input_hash,
        "as_of": as_of.isoformat(), "valid_until": valid_until.isoformat(), "stale": stale,
        "confidence": str(confidence.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "confidence_meaning": "coverage_and_rule_agreement_only",
        "features": {
            "oi_change_24h": _text(oi24), "oi_z": _text(z_oi),
            "funding_rate": _text(funding_rate), "funding_z": _text(z_funding),
            "basis_rate": _text(basis_rate), "basis_z": _text(z_basis),
            "taker_imbalance_24h": _text(taker24),
        },
        "sample_counts": counts,
        "coverage": _text(coverage),
        "coverage_by_family": {key: _text(value) for key, value in coverage_parts.items()},
        "evidence": evidence, "omissions": sorted(set(omissions)), "warnings": warnings,
        "note": "描述同时出现的衍生品证据；不代表因果、情绪或收益预测。",
    }


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _insufficient(evaluated_at: datetime, omissions: list[str]) -> dict:
    input_hash = hashlib.sha256(b"[]").hexdigest()
    return {
        "state": "INSUFFICIENT_DATA", "version": VERSION, "threshold_hash": THRESHOLD_HASH,
        "input_hash": input_hash, "as_of": evaluated_at.isoformat(),
        "valid_until": (evaluated_at + timedelta(hours=2)).isoformat(), "stale": False,
        "confidence": "0.00", "confidence_meaning": "coverage_and_rule_agreement_only",
        "features": {}, "sample_counts": {"oi": 0, "funding": 0, "basis": 0, "taker": 0},
        "coverage": "0", "coverage_by_family": {"oi": "0", "funding": "0", "basis": "0", "taker": "0"},
        "evidence": [], "omissions": omissions, "warnings": [],
        "note": "描述同时出现的衍生品证据；不代表因果、情绪或收益预测。",
    }
