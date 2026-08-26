"""Persistence helpers for crypto funding and derivatives metrics (WP 4.3).

Provider adapters hand this module small normalized dictionaries.  The module
does not make network calls or infer unavailable values: a partial endpoint
update only fills fields that are present, and separate ratio definitions stay
separate in metadata rather than being merged under one label.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CryptoDerivativesMetric, CryptoFundingRate, CryptoInstrument, MarketCandle

UTC = timezone.utc
DEFAULT_PROVIDER = "binance_usdm"
DEFAULT_INTERVAL = "1h"
MAX_READ_LIMIT = 5000
DEFAULT_READ_LIMIT = 1000


class DerivativesValidationError(ValueError):
    """Malformed provider data rejected before it can reach the database."""


class MetricDefinitionConflict(DerivativesValidationError):
    """One time point attempted to combine incompatible metric definitions."""


FUNDING_COLUMNS = (
    "funding_rate", "predicted_rate", "mark_price", "provider_timestamp",
    "coverage_start", "coverage_end", "quality", "metadata_json",
)

METRIC_VALUE_COLUMNS = (
    "mark_price", "index_price", "basis", "basis_rate", "premium",
    "mark_timestamp", "index_timestamp", "open_interest_base", "open_interest_quote",
    "open_interest_usd", "long_short_ratio",
    "top_trader_account_ratio", "top_trader_position_ratio", "taker_buy_sell_ratio",
    "taker_buy_volume", "taker_sell_volume", "futures_volume_base",
    "futures_volume_quote", "futures_volume_usd",
)

METRIC_META_COLUMNS = (
    "provider_timestamp", "coverage_start", "coverage_end", "quality", "metadata_json",
)

# Stable definitions are response metadata, not columns: one wide row carries
# several incompatible units and ratio denominators at once.
METRIC_DEFINITIONS = {
    "mark_price": {"metric_name": "mark_price", "definition": "provider mark price", "scope": "instrument", "unit": "quote_per_base"},
    "index_price": {"metric_name": "index_price", "definition": "provider index price", "scope": "instrument", "unit": "quote_per_base"},
    "basis": {"metric_name": "basis", "definition": "mark_price - index_price at identical provider timestamp", "scope": "instrument", "unit": "quote_per_base"},
    "basis_rate": {"metric_name": "basis_rate", "definition": "basis divided by index_price at identical provider timestamp", "scope": "instrument", "unit": "ratio"},
    "open_interest_base": {"metric_name": "open_interest_base", "definition": "provider open interest contracts/base units", "scope": "instrument", "unit": "base"},
    "open_interest_usd": {"metric_name": "open_interest_usd", "definition": "provider open interest notional", "scope": "instrument", "unit": "quote"},
    "long_short_ratio": {"metric_name": "long_short_ratio", "definition": "provider-defined long/short ratio; denominator retained by source metadata", "scope": "provider_scope", "unit": "ratio"},
    "top_trader_account_ratio": {"metric_name": "top_trader_account_ratio", "definition": "top trader long/short account ratio", "scope": "top_trader", "unit": "ratio"},
    "top_trader_position_ratio": {"metric_name": "top_trader_position_ratio", "definition": "top trader long/short position ratio", "scope": "top_trader", "unit": "ratio"},
    "taker_buy_sell_ratio": {"metric_name": "taker_buy_sell_ratio", "definition": "provider taker buy volume divided by sell volume", "scope": "instrument", "unit": "ratio"},
    "futures_volume_base": {"metric_name": "futures_volume_base", "definition": "provider futures base volume for interval", "scope": "instrument", "unit": "base"},
    "futures_volume_quote": {"metric_name": "futures_volume_quote", "definition": "provider futures quote volume for interval", "scope": "instrument", "unit": "quote"},
}


@dataclass
class PersistSummary:
    requested: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: list[dict] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _utc(value: Any, *, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float, Decimal)):
        number = float(value)
        # Binance timestamps are milliseconds; accepting seconds keeps the
        # helper useful for fixtures from other public providers.
        parsed = datetime.fromtimestamp(number / (1000 if abs(number) >= 10_000_000_000 else 1), UTC)
    else:
        text = str(value).strip()
        try:
            number = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise DerivativesValidationError(f"invalid {field_name} timestamp") from exc
        else:
            parsed = datetime.fromtimestamp(number / (1000 if abs(number) >= 10_000_000_000 else 1), UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DerivativesValidationError(f"invalid {field_name} decimal") from exc


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value, field_name="timestamp").isoformat()
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def _source_hash(values: Mapping[str, Any]) -> str:
    ignored = {"source_hash", "fetched_at", "created_at", "updated_at"}
    payload = {key: value for key, value in values.items() if key not in ignored}
    encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _value(row: Mapping[str, Any], *keys: str, field_name: str) -> Decimal | None:
    return _decimal(_first(row, *keys), field_name=field_name)


def normalize_funding_rate(
    row: Mapping[str, Any],
    *,
    instrument_id: int | None = None,
    provider: str = DEFAULT_PROVIDER,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Normalize one provider funding event to persistence columns."""

    instrument = row.get("instrument_id", instrument_id)
    if instrument is None:
        raise DerivativesValidationError("funding event requires instrument_id")
    funding_time = _utc(
        _first(row, "funding_time", "fundingTime", "event_time", "eventTime", "timestamp", "time"),
        field_name="funding_time",
    )
    rate = _value(row, "funding_rate", "fundingRate", "rate", field_name="funding_rate")
    if funding_time is None:
        raise DerivativesValidationError("funding event requires funding_time")
    if rate is None:
        raise DerivativesValidationError("funding event requires funding_rate")
    normalized: dict[str, Any] = {
        "instrument_id": int(instrument),
        "provider": str(row.get("provider", provider)),
        "funding_time": funding_time,
        "funding_rate": rate,
        "predicted_rate": _value(row, "predicted_rate", "predictedRate", "nextFundingRate", field_name="predicted_rate"),
        "mark_price": _value(row, "mark_price", "markPrice", field_name="mark_price"),
        "provider_timestamp": _utc(
            _first(row, "provider_timestamp", "providerTimestamp", "provider_time"),
            field_name="provider_timestamp",
        ) or funding_time,
        "coverage_start": _utc(_first(row, "coverage_start", "coverageStart"), field_name="coverage_start"),
        "coverage_end": _utc(_first(row, "coverage_end", "coverageEnd"), field_name="coverage_end"),
        "fetched_at": _utc(fetched_at or row.get("fetched_at"), field_name="fetched_at") or _utcnow(),
        "quality": str(row.get("quality") or "ok"),
        "metadata_json": dict(row.get("metadata_json") or row.get("metadata") or {}),
    }
    normalized["source_hash"] = str(row.get("source_hash") or _source_hash(normalized))[:64]
    return normalized


def normalize_derivatives_metric(
    row: Mapping[str, Any],
    *,
    instrument_id: int | None = None,
    provider: str = DEFAULT_PROVIDER,
    interval: str = DEFAULT_INTERVAL,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Normalize one endpoint response to a typed wide metric row.

    The provider may use Binance camelCase names or already normalized snake
    case.  Every unavailable typed value remains ``None``.
    """

    instrument = row.get("instrument_id", instrument_id)
    if instrument is None:
        raise DerivativesValidationError("derivatives metric requires instrument_id")
    observed = _utc(
        _first(row, "observed_at", "observedAt", "timestamp", "time", "event_time", "eventTime"),
        field_name="observed_at",
    )
    if observed is None:
        raise DerivativesValidationError("derivatives metric requires observed_at")

    mark_price = _value(row, "mark_price", "markPrice", field_name="mark_price")
    index_price = _value(row, "index_price", "indexPrice", field_name="index_price")
    mark_timestamp = _utc(_first(row, "mark_timestamp", "markTimestamp", "mark_time", "markTime"), field_name="mark_timestamp")
    index_timestamp = _utc(_first(row, "index_timestamp", "indexTimestamp", "index_time", "indexTime"), field_name="index_timestamp")
    # A single provider response containing both prices has one observation
    # timestamp; that is an explicit alignment, not an inferred price.
    if mark_price is not None and mark_timestamp is None:
        mark_timestamp = observed
    if index_price is not None and index_timestamp is None:
        index_timestamp = observed

    metadata = dict(row.get("metadata_json") or row.get("metadata") or {})
    definitions = dict(metadata.get("metric_definitions") or {})
    # An adapter may provide a more precise denominator/scope for one ratio;
    # preserve it under its metric key without making it a singular row label.
    for name in ("metric_name", "definition", "scope", "unit"):
        if row.get(name) not in (None, ""):
            metric_key = str(row.get("metric_key") or "long_short_ratio")
            definitions[metric_key] = {
                **dict(definitions.get(metric_key) or {}),
                name: str(row[name]),
            }
    ratio_definition = _first(row, "long_short_ratio_definition", "longShortRatioDefinition")
    if ratio_definition:
        definitions["long_short_ratio"] = {
            **dict(definitions.get("long_short_ratio") or {}),
            "definition": str(ratio_definition),
        }
    normalized: dict[str, Any] = {
        "instrument_id": int(instrument),
        "provider": str(row.get("provider", provider)),
        "interval": str(row.get("interval", interval)),
        "observed_at": observed,
        "mark_price": mark_price,
        "index_price": index_price,
        "basis": _value(row, "basis", "basis_value", field_name="basis"),
        "basis_rate": _value(row, "basis_rate", "basisRate", "basis_pct", "basisPercent", field_name="basis_rate"),
        "premium": _value(row, "premium", "premium_rate", "premiumRate", field_name="premium"),
        "mark_timestamp": mark_timestamp,
        "index_timestamp": index_timestamp,
        "open_interest_base": _value(row, "open_interest_base", "openInterest", "sumOpenInterest", field_name="open_interest_base"),
        "open_interest_quote": _value(row, "open_interest_quote", "openInterestQuote", field_name="open_interest_quote"),
        "open_interest_usd": _value(row, "open_interest_usd", "openInterestValue", "sumOpenInterestValue", field_name="open_interest_usd"),
        "long_short_ratio": _value(row, "long_short_ratio", "longShortRatio", "globalLongShortRatio", field_name="long_short_ratio"),
        "top_trader_account_ratio": _value(row, "top_trader_account_ratio", "topLongShortAccountRatio", field_name="top_trader_account_ratio"),
        "top_trader_position_ratio": _value(row, "top_trader_position_ratio", "topLongShortPositionRatio", field_name="top_trader_position_ratio"),
        "taker_buy_sell_ratio": _value(row, "taker_buy_sell_ratio", "buySellRatio", "takerBuySellRatio", field_name="taker_buy_sell_ratio"),
        "taker_buy_volume": _value(row, "taker_buy_volume", "buyVol", "takerBuyVolume", field_name="taker_buy_volume"),
        "taker_sell_volume": _value(row, "taker_sell_volume", "sellVol", "takerSellVolume", field_name="taker_sell_volume"),
        "futures_volume_base": _value(row, "futures_volume_base", "volume", "baseVolume", field_name="futures_volume_base"),
        "futures_volume_quote": _value(row, "futures_volume_quote", "quoteVolume", field_name="futures_volume_quote"),
        "futures_volume_usd": _value(row, "futures_volume_usd", "volumeUsd", "quoteVolumeUsd", field_name="futures_volume_usd"),
        "provider_timestamp": _utc(_first(row, "provider_timestamp", "providerTimestamp", "provider_time"), field_name="provider_timestamp") or observed,
        "coverage_start": _utc(_first(row, "coverage_start", "coverageStart"), field_name="coverage_start"),
        "coverage_end": _utc(_first(row, "coverage_end", "coverageEnd"), field_name="coverage_end"),
        "fetched_at": _utc(fetched_at or row.get("fetched_at"), field_name="fetched_at") or _utcnow(),
        "quality": str(row.get("quality") or "ok"),
        "metadata_json": metadata,
    }
    if normalized["basis"] is None:
        basis, basis_rate = compute_basis_values(
            normalized["mark_price"], normalized["index_price"],
            normalized["mark_timestamp"], normalized["index_timestamp"],
        )
        if basis is not None:
            normalized["basis"] = basis
            normalized["basis_rate"] = basis_rate
            if normalized["premium"] is None:
                normalized["premium"] = basis_rate
    definitions = {
        name: definition
        for name, definition in definitions.items()
        if name in METRIC_VALUE_COLUMNS and normalized.get(name) is not None
    }
    for name, definition in METRIC_DEFINITIONS.items():
        if normalized.get(name) is not None:
            definitions.setdefault(name, definition)
    metadata["metric_definitions"] = definitions
    normalized["source_hash"] = str(row.get("source_hash") or _source_hash(normalized))[:64]
    return normalized


def compute_basis(
    mark_price: Decimal | Any,
    index_price: Decimal | Any,
    mark_timestamp: Any,
    index_timestamp: Any,
) -> Decimal | None:
    """Return absolute mark-index basis only for exactly aligned timestamps."""

    mark = _decimal(mark_price, field_name="mark_price")
    index = _decimal(index_price, field_name="index_price")
    mark_time = _utc(mark_timestamp, field_name="mark_timestamp")
    index_time = _utc(index_timestamp, field_name="index_timestamp")
    if mark is None or index is None or mark_time is None or index_time is None or mark_time != index_time:
        return None
    return mark - index


def compute_basis_values(
    mark_price: Decimal | Any,
    index_price: Decimal | Any,
    mark_timestamp: Any,
    index_timestamp: Any,
) -> tuple[Decimal | None, Decimal | None]:
    basis = compute_basis(mark_price, index_price, mark_timestamp, index_timestamp)
    index = _decimal(index_price, field_name="index_price")
    if basis is None or index in (None, Decimal("0")):
        return basis, None
    return basis, basis / index


def merge_metric_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge endpoint-normalized rows only when their identity is identical."""

    if not rows:
        raise DerivativesValidationError("cannot merge an empty metric batch")
    normalized = [normalize_derivatives_metric(row) for row in rows]
    first = normalized[0]
    key = tuple(first[name] for name in ("instrument_id", "provider", "interval", "observed_at"))
    merged = dict(first)
    for row in normalized[1:]:
        row_key = tuple(row[name] for name in ("instrument_id", "provider", "interval", "observed_at"))
        if row_key != key:
            raise DerivativesValidationError("metric rows may merge only at identical instrument/interval/time/provider")
        incoming_definitions = (row.get("metadata_json") or {}).get("metric_definitions", {})
        current_definitions = (merged.get("metadata_json") or {}).get("metric_definitions", {})
        for name, incoming_definition in incoming_definitions.items():
            current_definition = current_definitions.get(name)
            if current_definition and current_definition != incoming_definition:
                raise MetricDefinitionConflict(f"incompatible definition for {name} at one derivatives time point")
        current_definitions.update(incoming_definitions)
        merged_metadata = {**(merged.get("metadata_json") or {}), **(row.get("metadata_json") or {})}
        merged_metadata["metric_definitions"] = current_definitions
        merged["metadata_json"] = merged_metadata
        for name in METRIC_VALUE_COLUMNS:
            if row.get(name) is not None:
                merged[name] = row[name]
        for name in ("provider_timestamp", "coverage_start", "coverage_end", "fetched_at", "quality"):
            if row.get(name) not in (None, "", {}):
                merged[name] = row[name]
    if not any(row.get("basis") is not None for row in normalized):
        basis, basis_rate = compute_basis_values(
            merged.get("mark_price"), merged.get("index_price"),
            merged.get("mark_timestamp"), merged.get("index_timestamp"),
        )
        if basis is not None:
            merged["basis"], merged["basis_rate"] = basis, basis_rate
            merged.setdefault("premium", basis_rate)
    merged["source_hash"] = _source_hash(merged)
    return merged


def _metric_key(values: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(values[name] for name in ("instrument_id", "interval", "observed_at", "provider"))


def _funding_key(values: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(values[name] for name in ("instrument_id", "funding_time", "provider"))


def _metadata_conflict(existing: CryptoDerivativesMetric, values: Mapping[str, Any]) -> bool:
    incoming = (values.get("metadata_json") or {}).get("metric_definitions", {})
    current = {
        name: definition
        for name, definition in (existing.metadata_json or {}).get("metric_definitions", {}).items()
        if name in METRIC_VALUE_COLUMNS and getattr(existing, name) is not None
    }
    return any(name in current and current[name] != definition for name, definition in incoming.items())


def upsert_funding_rate(
    db: Session,
    row: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[CryptoFundingRate, str]:
    values = normalize_funding_rate({**(row or {}), **kwargs})
    existing = db.scalar(
        select(CryptoFundingRate).where(
            CryptoFundingRate.instrument_id == values["instrument_id"],
            CryptoFundingRate.funding_time == values["funding_time"],
            CryptoFundingRate.provider == values["provider"],
        )
    )
    if existing is None:
        obj = CryptoFundingRate(**values)
        db.add(obj)
        db.flush()
        return obj, "inserted"
    if existing.source_hash == values["source_hash"]:
        return existing, "unchanged"
    for name in FUNDING_COLUMNS:
        incoming = values.get(name)
        if incoming is not None:
            setattr(existing, name, incoming)
    existing.source_hash = values["source_hash"]
    existing.revision += 1
    existing.fetched_at = values["fetched_at"]
    db.flush()
    return existing, "updated"


def persist_funding_rates(
    db: Session,
    rows: list[Mapping[str, Any]],
    *,
    instrument_id: int | None = None,
    provider: str = DEFAULT_PROVIDER,
) -> PersistSummary:
    summary = PersistSummary(requested=len(rows))
    for row in rows:
        try:
            obj, status = upsert_funding_rate(
                db,
                normalize_funding_rate(row, instrument_id=instrument_id, provider=provider),
            )
        except DerivativesValidationError as exc:
            summary.rejected.append({"reason": str(exc)})
            continue
        del obj
        setattr(summary, status, getattr(summary, status) + 1)
    db.flush()
    return summary


def upsert_derivatives_metric(
    db: Session,
    row: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[CryptoDerivativesMetric, str]:
    values = normalize_derivatives_metric({**(row or {}), **kwargs})
    existing = db.scalar(
        select(CryptoDerivativesMetric).where(
            CryptoDerivativesMetric.instrument_id == values["instrument_id"],
            CryptoDerivativesMetric.interval == values["interval"],
            CryptoDerivativesMetric.observed_at == values["observed_at"],
            CryptoDerivativesMetric.provider == values["provider"],
        )
    )
    if existing is None:
        obj = CryptoDerivativesMetric(**values)
        db.add(obj)
        db.flush()
        return obj, "inserted"
    if _metadata_conflict(existing, values):
        raise MetricDefinitionConflict("incompatible metric definition at one instrument/interval/time/provider")
    current_metadata = dict(existing.metadata_json or {})
    current_definitions = {
        name: definition
        for name, definition in current_metadata.get("metric_definitions", {}).items()
        if name in METRIC_VALUE_COLUMNS and getattr(existing, name) is not None
    }
    incoming_metadata = dict(values.get("metadata_json") or {})
    current_definitions.update(incoming_metadata.get("metric_definitions", {}))
    current_metadata.update(incoming_metadata)
    current_metadata["metric_definitions"] = current_definitions
    values["metadata_json"] = current_metadata
    incoming_values = {name: getattr(existing, name) for name in METRIC_VALUE_COLUMNS}
    for name in METRIC_VALUE_COLUMNS:
        if values.get(name) is not None:
            incoming_values[name] = values[name]
    merged = {**values, **incoming_values}
    # Do not invent a new basis when endpoint timestamps are absent/misaligned;
    # the prior aligned value is retained as the last known-good observation.
    computed_basis: tuple[Decimal, Decimal | None] | None = None
    if values.get("basis") is None:
        basis, basis_rate = compute_basis_values(
            merged.get("mark_price"), merged.get("index_price"),
            merged.get("mark_timestamp"), merged.get("index_timestamp"),
        )
        if basis is not None:
            merged["basis"], merged["basis_rate"] = basis, basis_rate
            if values.get("premium") is None:
                merged["premium"] = basis_rate
            computed_basis = basis, basis_rate
    changed = existing.source_hash != values["source_hash"]
    for name in METRIC_VALUE_COLUMNS + METRIC_META_COLUMNS:
        incoming = values.get(name)
        if incoming is not None and name in METRIC_VALUE_COLUMNS:
            # A null endpoint field never erases a valid prior field.
            setattr(existing, name, merged.get(name, incoming))
        elif incoming not in (None, "", {}):
            setattr(existing, name, incoming)
    if computed_basis is not None:
        existing.basis, existing.basis_rate = computed_basis
        if values.get("premium") is None:
            existing.premium = computed_basis[1]
    if not changed:
        return existing, "unchanged"
    existing.source_hash = values["source_hash"]
    existing.revision += 1
    existing.fetched_at = values["fetched_at"]
    db.flush()
    return existing, "updated"


def persist_derivatives_metrics(
    db: Session,
    rows: list[Mapping[str, Any]],
    *,
    instrument_id: int | None = None,
    provider: str = DEFAULT_PROVIDER,
    interval: str = DEFAULT_INTERVAL,
) -> PersistSummary:
    summary = PersistSummary(requested=len(rows))
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        try:
            normalized = normalize_derivatives_metric(
                row, instrument_id=instrument_id, provider=provider, interval=interval
            )
            grouped.setdefault(_metric_key(normalized), []).append(normalized)
        except DerivativesValidationError as exc:
            summary.rejected.append({"reason": str(exc)})
    for batch in grouped.values():
        try:
            values = batch[0] if len(batch) == 1 else merge_metric_rows(batch)
            _, status = upsert_derivatives_metric(db, values)
        except DerivativesValidationError as exc:
            summary.rejected.append({"reason": str(exc)})
            continue
        setattr(summary, status, getattr(summary, status) + 1)
    db.flush()
    return summary


def read_funding_history(
    db: Session,
    *,
    instrument_id: int,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    provider: str | None = None,
    limit: int = DEFAULT_READ_LIMIT,
) -> list[CryptoFundingRate]:
    query = select(CryptoFundingRate).where(CryptoFundingRate.instrument_id == instrument_id)
    if provider is not None:
        query = query.where(CryptoFundingRate.provider == provider)
    if start_at is not None:
        query = query.where(CryptoFundingRate.funding_time >= _utc(start_at, field_name="start_at"))
    if end_at is not None:
        query = query.where(CryptoFundingRate.funding_time <= _utc(end_at, field_name="end_at"))
    return list(db.scalars(query.order_by(CryptoFundingRate.funding_time.asc()).limit(max(1, min(limit, MAX_READ_LIMIT)))))


def read_derivatives_history(
    db: Session,
    *,
    instrument_id: int,
    interval: str = DEFAULT_INTERVAL,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    provider: str | None = None,
    limit: int = DEFAULT_READ_LIMIT,
) -> list[CryptoDerivativesMetric]:
    query = select(CryptoDerivativesMetric).where(
        CryptoDerivativesMetric.instrument_id == instrument_id,
        CryptoDerivativesMetric.interval == interval,
    )
    if provider is not None:
        query = query.where(CryptoDerivativesMetric.provider == provider)
    if start_at is not None:
        query = query.where(CryptoDerivativesMetric.observed_at >= _utc(start_at, field_name="start_at"))
    if end_at is not None:
        query = query.where(CryptoDerivativesMetric.observed_at <= _utc(end_at, field_name="end_at"))
    return list(db.scalars(query.order_by(CryptoDerivativesMetric.observed_at.asc()).limit(max(1, min(limit, MAX_READ_LIMIT)))))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (_utc(value, field_name="timestamp") or value).isoformat()


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def funding_history_payload(rows: list[CryptoFundingRate]) -> dict[str, Any]:
    items = [
        {
            "instrument_id": row.instrument_id,
            "provider": row.provider,
            "funding_time": _iso(row.funding_time),
            "funding_time_ms": int((_utc(row.funding_time, field_name="funding_time") or row.funding_time).timestamp() * 1000),
            "funding_rate": _decimal_text(row.funding_rate),
            "predicted_rate": _decimal_text(row.predicted_rate),
            "mark_price": _decimal_text(row.mark_price),
            "provider_timestamp": _iso(row.provider_timestamp),
            "source_hash": row.source_hash,
            "revision": row.revision,
            "quality": row.quality,
        }
        for row in rows
    ]
    return {
        "items": items,
        "count": len(items),
        "coverage": {
            "start": items[0]["funding_time"] if items else None,
            "end": items[-1]["funding_time"] if items else None,
        },
    }


def derivatives_history_payload(rows: list[CryptoDerivativesMetric]) -> dict[str, Any]:
    items = []
    for row in rows:
        item = {
            "instrument_id": row.instrument_id,
            "provider": row.provider,
            "interval": row.interval,
            "observed_at": _iso(row.observed_at),
            "metric_definitions": (row.metadata_json or {}).get("metric_definitions", {}),
            "revision": row.revision,
            "source_hash": row.source_hash,
            "quality": row.quality,
        }
        for name in METRIC_VALUE_COLUMNS:
            item[name] = _iso(getattr(row, name)) if name in ("mark_timestamp", "index_timestamp") else _decimal_text(getattr(row, name))
        item.update({"provider_timestamp": _iso(row.provider_timestamp), "fetched_at": _iso(row.fetched_at)})
        items.append(item)
    return {
        "items": items,
        "count": len(items),
        "coverage": {
            "start": items[0]["observed_at"] if items else None,
            "end": items[-1]["observed_at"] if items else None,
        },
    }


def derivatives_status_payload(
    db: Session,
    *,
    instrument_id: int,
    interval: str = DEFAULT_INTERVAL,
    provider: str | None = None,
) -> dict[str, Any]:
    funding_query = select(CryptoFundingRate).where(CryptoFundingRate.instrument_id == instrument_id)
    metric_query = select(CryptoDerivativesMetric).where(
        CryptoDerivativesMetric.instrument_id == instrument_id,
        CryptoDerivativesMetric.interval == interval,
    )
    if provider is not None:
        funding_query = funding_query.where(CryptoFundingRate.provider == provider)
        metric_query = metric_query.where(CryptoDerivativesMetric.provider == provider)
    funding_rows = list(db.scalars(funding_query.order_by(CryptoFundingRate.funding_time.asc())))
    metric_rows = list(db.scalars(metric_query.order_by(CryptoDerivativesMetric.observed_at.asc())))
    latest_funding = funding_rows[-1] if funding_rows else None
    latest_metric = metric_rows[-1] if metric_rows else None
    coverage = {
        name: sum(getattr(row, name) is not None for row in metric_rows)
        for name in METRIC_VALUE_COLUMNS
        if name not in {"mark_timestamp", "index_timestamp", "basis", "basis_rate", "premium"}
    }
    return {
        "instrument_id": instrument_id,
        "provider": provider,
        "interval": interval,
        "status": "ready" if metric_rows or funding_rows else "unavailable",
        "funding_count": len(funding_rows),
        "metric_count": len(metric_rows),
        "latest_funding_at": _iso(latest_funding.funding_time if latest_funding else None),
        "latest_metric_at": _iso(latest_metric.observed_at if latest_metric else None),
        "coverage": coverage,
        "funding_coverage": funding_history_payload(funding_rows)["coverage"],
        "metric_coverage": derivatives_history_payload(metric_rows)["coverage"],
    }


def collect_public_derivatives(db: Session, *, client, instrument: CryptoInstrument, limit: int = 500) -> dict:
    """Collect one bounded USD-M instrument; partial endpoint failures keep valid facts."""
    if instrument.kind != "perpetual" or instrument.market != "usdm_futures":
        raise DerivativesValidationError("USD-M perpetual instrument required")
    symbol = instrument.provider_symbol
    errors: dict[str, str] = {}

    try:
        funding_rows = [
            {
                "instrument_id": instrument.id, "provider": DEFAULT_PROVIDER,
                "funding_time": row.funding_time_ms, "funding_rate": row.funding_rate,
                "mark_price": row.mark_price, "metadata": {"rate_type": row.rate_type},
            }
            for row in client.funding_rate_history(symbol, limit=1000)
        ]
        funding_summary = persist_funding_rates(db, funding_rows)
    except Exception as exc:
        errors["funding"] = str(exc)[:300]
        funding_summary = PersistSummary()

    partial: dict[int, list[dict[str, Any]]] = {}
    def add(timestamp_ms: int, **values: Any) -> None:
        partial.setdefault(timestamp_ms, []).append({
            "instrument_id": instrument.id, "provider": DEFAULT_PROVIDER,
            "interval": "1h", "observed_at": timestamp_ms, **values,
        })

    calls = (
        ("open_interest", client.open_interest_history, lambda row: {
            "open_interest_base": row.sum_open_interest,
            "open_interest_usd": row.sum_open_interest_value,
        }),
        ("long_short", client.global_long_short_ratio, lambda row: {
            "long_short_ratio": row.long_short_ratio,
            "long_short_ratio_definition": "all trader accounts: long accounts / short accounts",
        }),
        ("taker", client.taker_buy_sell_volume, lambda row: {
            "taker_buy_sell_ratio": row.buy_sell_ratio,
            "taker_buy_volume": row.buy_volume,
            "taker_sell_volume": row.sell_volume,
        }),
    )
    for name, fetch, values in calls:
        try:
            for row in fetch(symbol, period="1h", limit=limit):
                add(row.event_time_ms, **values(row))
        except Exception as exc:
            errors[name] = str(exc)[:300]

    candle_rows = list(db.scalars(
        select(MarketCandle).where(
            MarketCandle.instrument_id == instrument.id,
            MarketCandle.interval == "1h",
            MarketCandle.provider == DEFAULT_PROVIDER,
            MarketCandle.price_type.in_(("trade", "mark", "index")),
            MarketCandle.final.is_(True),
        ).order_by(MarketCandle.open_time_ms.desc()).limit(limit * 3)
    ))
    by_time: dict[int, dict[str, MarketCandle]] = {}
    for candle in candle_rows:
        by_time.setdefault(candle.open_time_ms, {})[candle.price_type] = candle
    for timestamp_ms, prices in by_time.items():
        values: dict[str, Any] = {}
        if mark := prices.get("mark"):
            values.update(mark_price=mark.close, mark_timestamp=timestamp_ms)
        if index := prices.get("index"):
            values.update(index_price=index.close, index_timestamp=timestamp_ms)
        if trade := prices.get("trade"):
            values.update(
                futures_volume_base=trade.base_volume,
                futures_volume_quote=trade.quote_volume,
            )
        if values:
            add(timestamp_ms, **values)

    merged: list[dict[str, Any]] = []
    for rows in partial.values():
        try:
            merged.append(merge_metric_rows(rows))
        except DerivativesValidationError as exc:
            errors[f"merge_{rows[0]['observed_at']}"] = str(exc)[:300]
    metric_summary = persist_derivatives_metrics(db, merged)
    db.commit()
    return {
        "instrument_id": instrument.id,
        "funding": funding_summary.__dict__,
        "metrics": metric_summary.__dict__,
        "errors": errors,
        "status": "success" if not errors else "partial",
    }
