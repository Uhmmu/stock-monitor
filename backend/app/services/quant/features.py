"""Causal materialization of the bounded crypto quant feature set.

Only persisted ``MarketCandle``, ``CryptoDerivativesMetric`` and
``CryptoFundingRate`` rows are read.  No provider, network, or execution
module is imported here.  A feature row is append-only: a changed source hash
creates another vintage instead of replacing the prior payload.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BacktestRun,
    CryptoDerivativesMetric,
    CryptoFundingRate,
    CryptoInstrument,
    MarketCandle,
    QuantFeatureSet,
    QuantFeatureValue,
    QuantStrategyDefinition,
)
from app.services.crypto import derivatives as derivatives_repo
from app.services.technical_analysis_engine import atr, ema, macd, rsi, sma
from .registry import (
    FEATURE_NAMES,
    FEATURE_SET_KEY,
    FEATURE_SET_REGISTRY,
    STRATEGY_REGISTRY,
    canonical_hash,
    feature_set_definition,
)


INTERVAL_DELTAS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}
SOURCE_CAUSAL_VERSION = "source_causal_v1"
DEFAULT_PROVIDER = "binance_usdm"
QUANT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "ADAUSDT")


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float, Decimal)):
        number = float(value)
        parsed = datetime.fromtimestamp(number / (1000 if abs(number) >= 10_000_000_000 else 1), UTC)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    return result if result.is_finite() else None


def _float(value: Any) -> float | None:
    decimal = _decimal(value)
    return float(decimal) if decimal is not None else None


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return (_utc(value) or value).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _source_row(row: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {field: _json_value(_value(row, field)) for field in fields}


def candle_available_at(candle: Any) -> datetime | None:
    """Earliest UTC instant after an inclusive final candle close."""

    if _value(candle, "final", True) is False:
        return None
    close_ms = _value(candle, "close_time_ms")
    if close_ms is None:
        return None
    return datetime.fromtimestamp((int(close_ms) + 1) / 1000, UTC)


def metric_available_at(metric: Any, interval: str | None = None) -> datetime | None:
    """Source-causal availability for a periodic derivatives metric."""

    observed_at = _utc(_value(metric, "observed_at"))
    if observed_at is None:
        return None
    metric_interval = str(interval or _value(metric, "interval") or "1h")
    interval_delta = INTERVAL_DELTAS.get(metric_interval)
    if interval_delta is None:
        raise ValueError(f"unsupported metric interval {metric_interval!r}")
    candidates = [observed_at + interval_delta]
    for field in ("coverage_end", "provider_timestamp"):
        timestamp = _utc(_value(metric, field))
        if timestamp is not None:
            candidates.append(timestamp)
    return max(candidates)


def funding_available_at(funding: Any) -> datetime | None:
    """Source-causal availability for realized funding only."""

    funding_time = _utc(_value(funding, "funding_time"))
    if funding_time is None:
        return None
    candidates = [funding_time]
    for field in ("coverage_end", "provider_timestamp"):
        timestamp = _utc(_value(funding, field))
        if timestamp is not None:
            candidates.append(timestamp)
    return max(candidates)


def source_causal_available_at(row: Any, *, kind: str | None = None, interval: str | None = None) -> datetime | None:
    """Dispatch the one versioned source-causal policy for a raw row."""

    if kind in {"candle", "market_candle"} or _value(row, "close_time_ms") is not None:
        return candle_available_at(row)
    if kind in {"funding", "funding_rate"} or _value(row, "funding_time") is not None:
        return funding_available_at(row)
    return metric_available_at(row, interval=interval)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _select_current_candle(candles: Sequence[Any], candle: Any | int | None) -> tuple[list[Any], Any]:
    ordered = sorted(candles, key=lambda row: int(_value(row, "open_time_ms", 0)))
    if not ordered:
        raise ValueError("at least one candle is required")
    if candle is None:
        current = ordered[-1]
    elif isinstance(candle, int):
        current = next((row for row in ordered if int(_value(row, "open_time_ms")) == candle), None)
        if current is None:
            current = ordered[candle]
    else:
        current = candle
    if candle_available_at(current) is None:
        raise ValueError("forming candle is not eligible")
    current_open = int(_value(current, "open_time_ms"))
    past = [row for row in ordered if int(_value(row, "open_time_ms")) <= current_open]
    if not any(row is current or int(_value(row, "open_time_ms")) == current_open for row in past):
        past.append(current)
        past.sort(key=lambda row: int(_value(row, "open_time_ms", 0)))
    return past, current


def _returns(closes: list[float], period: int) -> float | None:
    if len(closes) <= period or closes[-1 - period] == 0:
        return None
    return closes[-1] / closes[-1 - period] - 1


def _realized_volatility(closes: list[float], period: int = 24) -> float | None:
    if len(closes) <= period:
        return None
    changes = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    changes = changes[-period:]
    return statistics.pstdev(changes) if len(changes) == period else None


def _zscore(value: float | None, values: list[float]) -> float | None:
    if value is None or not values:
        return None
    mean = statistics.fmean(values)
    deviation = statistics.pstdev(values)
    return None if deviation == 0 else (value - mean) / deviation


def _latest_before(rows: Sequence[Any], at: datetime, field: str) -> Any | None:
    eligible = []
    for row in rows:
        timestamp = _utc(_value(row, field))
        if timestamp is not None and timestamp <= at:
            eligible.append((timestamp, row))
    return max(eligible, key=lambda item: item[0])[1] if eligible else None


def _metric_snapshot(metric: Any) -> dict[str, Any]:
    return _source_row(
        metric,
        (
            "instrument_id", "interval", "observed_at", "provider", "mark_price", "index_price",
            "basis", "basis_rate", "premium", "open_interest_base", "open_interest_quote",
            "open_interest_usd", "taker_buy_sell_ratio", "taker_buy_volume", "taker_sell_volume",
            "futures_volume_base", "futures_volume_quote", "source_hash", "revision",
            "coverage_start", "coverage_end", "provider_timestamp", "fetched_at", "quality",
        ),
    )


def _funding_snapshot(funding: Any) -> dict[str, Any]:
    return _source_row(
        funding,
        (
            "instrument_id", "funding_time", "provider", "funding_rate", "mark_price",
            "source_hash", "revision", "coverage_start", "coverage_end", "provider_timestamp",
            "fetched_at", "quality",
        ),
    )


def _candle_snapshot(candle: Any) -> dict[str, Any]:
    return _source_row(
        candle,
        (
            "id", "instrument_id", "interval", "open_time_ms", "price_type", "provider",
            "source_hash", "fetched_at",
        ),
    )


def _payload_value(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    # Stable enough for JSON/API while retaining materially useful precision.
    return float(value)


def build_feature_payload(
    candles: Sequence[Any],
    *,
    candle: Any | int | None = None,
    metrics: Sequence[Any] | Any | None = None,
    metric: Sequence[Any] | Any | None = None,
    funding: Sequence[Any] | Any | None = None,
    funding_rows: Sequence[Any] | Any | None = None,
    feature_set: Any | None = None,
) -> dict[str, Any]:
    """Build one deterministic feature vintage from persisted rows only."""

    history, current = _select_current_candle(candles, candle)
    interval = str(_value(current, "interval") or "1h")
    if interval not in INTERVAL_DELTAS:
        raise ValueError(f"unsupported candle interval {interval!r}")
    as_of = candle_available_at(current)
    assert as_of is not None
    closes = [_float(_value(row, "close")) for row in history]
    if any(value is None for value in closes):
        raise ValueError("candle close is required")
    close_values = [float(value) for value in closes if value is not None]
    highs = [_float(_value(row, "high")) for row in history]
    lows = [_float(_value(row, "low")) for row in history]
    rows = [
        {"high": high, "low": low, "close": close}
        for high, low, close in zip(highs, lows, close_values)
        if high is not None and low is not None
    ]
    omissions: list[str] = []
    warnings: list[str] = []

    values: dict[str, float | None] = {
        "return_1": _returns(close_values, 1),
        "return_6": _returns(close_values, 6),
        "return_24": _returns(close_values, 24),
        "realized_volatility_24": _realized_volatility(close_values),
    }
    if values["return_1"] is None:
        omissions.append("return_1")
    if values["return_6"] is None:
        omissions.append("return_6")
    if values["return_24"] is None:
        omissions.append("return_24")
    if values["realized_volatility_24"] is None:
        omissions.append("realized_volatility_24")

    atr_values = atr(rows, 14) if len(rows) == len(history) else []
    atr_last = atr_values[-1] if atr_values else None
    values["atr14_close"] = atr_last / close_values[-1] if atr_last is not None and close_values[-1] else None
    rsi_values = rsi(close_values, 14)
    values["rsi14"] = rsi_values[-1]
    macd_line, macd_signal, macd_histogram = macd(close_values)
    values.update(
        macd_line_12_26=macd_line[-1] if macd_line else None,
        macd_signal_9=macd_signal[-1] if macd_signal else None,
        macd_histogram=macd_histogram[-1] if macd_histogram else None,
    )
    sma20_values = sma(close_values, 20)
    sma50_values = sma(close_values, 50)
    sma20_last = sma20_values[-1]
    sma50_last = sma50_values[-1]
    values["sma20"] = sma20_last
    values["sma50"] = sma50_last
    values["sma20_distance"] = close_values[-1] / sma20_last - 1 if sma20_last else None
    values["sma50_distance"] = close_values[-1] / sma50_last - 1 if sma50_last else None

    volumes = [_float(_value(row, "base_volume")) for row in history]
    volume_values = [float(value) for value in volumes if value is not None]
    if len(volume_values) >= 20:
        values["volume_zscore20"] = _zscore(volume_values[-1], volume_values[-20:])
    else:
        values["volume_zscore20"] = None
    buy_volume = _float(_value(current, "taker_buy_base_volume"))
    base_volume = _float(_value(current, "base_volume"))
    values["taker_imbalance"] = ((2 * buy_volume / base_volume) - 1) if buy_volume is not None and base_volume else None

    for name, value in values.items():
        if value is None and name not in omissions:
            omissions.append(name)

    # Do not let an event timestamp masquerade as publication availability:
    # source rows whose causal clock is still in the future are omitted from
    # this decision bar (and therefore cannot make a feature look usable).
    metric_rows = [
        row for row in _as_list(metrics if metrics is not None else metric)
        if (available := metric_available_at(row)) is not None and available <= as_of
    ]
    funding_rows_list = [
        row for row in _as_list(funding if funding is not None else funding_rows)
        if (available := funding_available_at(row)) is not None and available <= as_of
    ]
    current_open = int(_value(current, "open_time_ms"))
    latest_metric = _latest_before(metric_rows, as_of, "observed_at")
    # OI change uses the latest metric and the latest observation no later than
    # one day before it; no future row can enter this window.
    oi_baseline = None
    if latest_metric is not None:
        latest_metric_at = _utc(_value(latest_metric, "observed_at"))
        if latest_metric_at is not None:
            oi_baseline = _latest_before(metric_rows, latest_metric_at - timedelta(hours=24), "observed_at")
    latest_oi = _decimal(_value(latest_metric, "open_interest_base")) if latest_metric is not None else None
    prior_oi = _decimal(_value(oi_baseline, "open_interest_base")) if oi_baseline is not None else None
    values["oi_change_24"] = float(latest_oi / prior_oi - 1) if latest_oi is not None and prior_oi not in (None, Decimal("0")) else None
    values["basis_rate"] = _float(_value(latest_metric, "basis_rate")) if latest_metric is not None else None
    values["taker_buy_sell_ratio"] = _float(_value(latest_metric, "taker_buy_sell_ratio")) if latest_metric is not None else None
    latest_funding = _latest_before(funding_rows_list, as_of, "funding_time")
    values["funding_rate"] = _float(_value(latest_funding, "funding_rate")) if latest_funding is not None else None
    for name in ("funding_rate", "oi_change_24", "basis_rate", "taker_buy_sell_ratio"):
        if values[name] is None and name not in omissions:
            omissions.append(name)

    metric_inputs = [row for row in (latest_metric, oi_baseline) if row is not None]
    source_times = [candle_available_at(row) for row in history]
    source_times += [metric_available_at(row) for row in metric_inputs]
    if latest_funding is not None:
        source_times.append(funding_available_at(latest_funding))
    source_times = [value for value in source_times if value is not None]
    available_at = max(source_times) if source_times else as_of

    # Snapshots include every source hash/revision used to construct this
    # bar, so replacing an old provider row creates a new feature vintage.
    input_snapshot = {
        "policy": SOURCE_CAUSAL_VERSION,
        "feature_set": str(_value(feature_set, "feature_set_key") or _value(feature_set, "key") or FEATURE_SET_KEY),
        "instrument_id": _value(current, "instrument_id"),
        "interval": interval,
        "bar_open_time_ms": current_open,
        "candles": [_candle_snapshot(row) for row in history],
        "derivatives": [_metric_snapshot(row) for row in metric_inputs],
        "funding": [_funding_snapshot(latest_funding)] if latest_funding is not None else [],
    }
    input_hash = canonical_hash(input_snapshot)
    payload = {name: _payload_value(values.get(name)) for name in FEATURE_NAMES}
    payload["returns"] = {str(period): payload[f"return_{period}"] for period in (1, 6, 24)}
    payload["returns_1"] = payload["return_1"]
    payload["returns_6"] = payload["return_6"]
    payload["returns_24"] = payload["return_24"]
    payload["rsi"] = payload["rsi14"]
    payload["macd"] = {
        "line": payload["macd_line_12_26"],
        "signal": payload["macd_signal_9"],
        "histogram": payload["macd_histogram"],
    }
    payload["bar"] = {
        "open_time_ms": current_open,
        "close_time_ms": _value(current, "close_time_ms"),
        "open": _json_value(_value(current, "open")),
        "high": _json_value(_value(current, "high")),
        "low": _json_value(_value(current, "low")),
        "close": _json_value(_value(current, "close")),
        "base_volume": _json_value(_value(current, "base_volume")),
        "quote_volume": _json_value(_value(current, "quote_volume")),
    }
    if latest_metric is not None:
        payload["derivatives"] = {
            "observed_at": _json_value(_value(latest_metric, "observed_at")),
            "open_interest_base": _json_value(_value(latest_metric, "open_interest_base")),
            "basis_rate": _json_value(_value(latest_metric, "basis_rate")),
            "taker_buy_sell_ratio": _json_value(_value(latest_metric, "taker_buy_sell_ratio")),
        }
    else:
        payload["derivatives"] = {}
    payload["funding"] = {
        "funding_time": _json_value(_value(latest_funding, "funding_time")),
        "funding_rate": _json_value(_value(latest_funding, "funding_rate")),
    } if latest_funding is not None else {}
    if not metric_inputs:
        warnings.append("DERIVATIVES_UNAVAILABLE")
    if latest_funding is None:
        warnings.append("FUNDING_UNAVAILABLE")
    quality = "ok" if not omissions else "partial"
    coverage = sum(values.get(name) is not None for name in FEATURE_NAMES) / len(FEATURE_NAMES)
    feature_set_key = str(
        _value(feature_set, "feature_set_key") or _value(feature_set, "key") or FEATURE_SET_KEY
    )
    feature_set_version = str(_value(feature_set, "version") or "v1")
    return {
        "feature_set_key": feature_set_key,
        "feature_set_version": feature_set_version,
        "instrument_id": _value(current, "instrument_id"),
        "interval": interval,
        "bar_open_time_ms": current_open,
        "as_of": as_of,
        "available_at": available_at,
        "input_hash": input_hash,
        "input_snapshot": input_snapshot,
        "payload": payload,
        "coverage": coverage,
        "quality": quality,
        "omissions": sorted(set(omissions)),
        "warnings": sorted(set(warnings)),
        "source_causal_version": SOURCE_CAUSAL_VERSION,
    }


def feature_input_hash(snapshot: Mapping[str, Any] | Any, *args: Any, **kwargs: Any) -> str:
    """Hash a frozen input snapshot; extra args keep old call sites tolerant."""

    if isinstance(snapshot, Mapping) and not args and not kwargs:
        return canonical_hash(snapshot)
    return canonical_hash({"snapshot": _json_value(snapshot), "args": _json_value(args), "kwargs": _json_value(kwargs)})


def materialize_feature_value(
    candles: Sequence[Any],
    **kwargs: Any,
) -> dict[str, Any]:
    return build_feature_payload(candles, **kwargs)


def persist_feature_value(
    db: Session,
    materialization: Mapping[str, Any] | None = None,
    *,
    feature_set_id: int | None = None,
    feature_set: QuantFeatureSet | None = None,
    candles: Sequence[Any] | None = None,
    lookup_existing: bool = True,
    flush: bool = True,
    **kwargs: Any,
) -> tuple[QuantFeatureValue, str]:
    """Insert one immutable feature vintage, returning ``(row, status)``."""

    if materialization is None:
        if candles is None:
            raise ValueError("candles are required when materialization is omitted")
        materialization = build_feature_payload(candles, feature_set=feature_set, **kwargs)
    values = dict(materialization)
    if feature_set_id is None:
        feature_set_id = int(_value(feature_set, "id") or 0)
    if not feature_set_id:
        raise ValueError("feature_set_id is required")
    instrument_id = values.get("instrument_id") or kwargs.get("instrument_id")
    if instrument_id is None:
        raise ValueError("instrument_id is required")
    identity = {
        "feature_set_id": feature_set_id,
        "instrument_id": instrument_id,
        "interval": values["interval"],
        "bar_open_time_ms": values["bar_open_time_ms"],
        "input_hash": values["input_hash"],
    }
    if lookup_existing:
        existing = db.scalar(select(QuantFeatureValue).filter_by(**identity))
        if existing is not None:
            return existing, "unchanged"
    model_fields = {
        "instrument_id", "interval", "bar_open_time_ms", "as_of", "available_at", "input_hash",
        "input_snapshot", "payload", "coverage", "quality", "omissions", "warnings",
        "source_causal_version",
    }
    row = QuantFeatureValue(
        feature_set_id=feature_set_id,
        **{key: value for key, value in values.items() if key in model_fields},
    )
    db.add(row)
    if flush:
        db.flush()
    return row, "inserted"


def ensure_registry(db: Session) -> dict[str, Any]:
    """Idempotently persist the two strategies and one released feature set."""

    strategy_rows: dict[str, QuantStrategyDefinition] = {}
    for definition in STRATEGY_REGISTRY.values():
        values = definition.as_dict()
        row = db.scalar(
            select(QuantStrategyDefinition).filter_by(
                strategy_key=definition.key, version=definition.version
            )
        )
        if row is None:
            row = QuantStrategyDefinition(
                strategy_key=definition.key,
                name=definition.name,
                version=definition.version,
                description=definition.description,
                interval=definition.interval,
                universe=values["universe"],
                parameter_schema=values["parameter_schema"],
                default_parameters=values["default_parameters"],
                config=values["config"],
                config_hash=definition.config_hash,
                code_version=definition.code_version,
                status=definition.status,
            )
            db.add(row)
            db.flush()
        elif row.config_hash != definition.config_hash:
            raise ValueError(f"registered strategy {definition.key!r} has immutable hash mismatch")
        strategy_rows[definition.key] = row

    definition = feature_set_definition()
    values = definition.as_dict()
    feature_row = db.scalar(
        select(QuantFeatureSet).filter_by(feature_set_key=definition.key, version=definition.version)
    )
    if feature_row is None:
        feature_row = QuantFeatureSet(
            feature_set_key=definition.key,
            name=definition.name,
            version=definition.version,
            description="Causal crypto candle/derivatives features",
            supported_intervals=values["supported_intervals"],
            feature_schema=values["feature_schema"],
            parameters=values["parameters"],
            input_declarations=values["input_declarations"],
            input_hash=canonical_hash(values["input_declarations"]),
            availability_policy=definition.availability_policy,
            config_hash=definition.config_hash,
            code_version=definition.code_version,
            status=definition.status,
        )
        db.add(feature_row)
        db.flush()
    elif feature_row.config_hash != definition.config_hash:
        raise ValueError(f"registered feature set {definition.key!r} has immutable hash mismatch")
    return {
        "strategies": strategy_rows,
        "feature_set": feature_row,
        "strategy_ids": {key: row.id for key, row in strategy_rows.items()},
        "feature_set_id": feature_row.id,
    }


def _dedupe_by_open_time(rows: Sequence[Any]) -> list[Any]:
    by_time: dict[int, Any] = {}
    for row in rows:
        by_time[int(_value(row, "open_time_ms"))] = row
    return [by_time[key] for key in sorted(by_time)]


def materialize_features(
    db: Session,
    instruments: Sequence[CryptoInstrument] | None = None,
    intervals: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Materialize persisted USD-M features without any upstream fetch."""

    registry = ensure_registry(db)
    if instruments is None:
        instruments = list(
            db.scalars(
                select(CryptoInstrument)
                .where(
                    CryptoInstrument.kind == "perpetual",
                    CryptoInstrument.market == "usdm_futures",
                    CryptoInstrument.status == "trading",
                    CryptoInstrument.provider_symbol.in_(QUANT_SYMBOLS),
                )
                .order_by(CryptoInstrument.provider_symbol)
            )
        )
    selected_intervals = list(intervals or ("1h", "4h", "1d"))
    inserted = unchanged = skipped = 0
    items: list[dict[str, Any]] = []
    for instrument in instruments:
        for interval in selected_intervals:
            if interval not in INTERVAL_DELTAS:
                items.append({"instrument_id": instrument.id, "interval": interval, "status": "invalid"})
                continue
            latest_materialized = db.scalar(select(func.max(QuantFeatureValue.bar_open_time_ms)).where(
                QuantFeatureValue.feature_set_id == registry["feature_set_id"],
                QuantFeatureValue.instrument_id == instrument.id,
                QuantFeatureValue.interval == interval,
            ))
            warmup_ms = int(INTERVAL_DELTAS[interval].total_seconds() * 1000 * 63)
            candle_filters = [
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.interval == interval,
                MarketCandle.provider == DEFAULT_PROVIDER,
                MarketCandle.price_type == "trade",
            ]
            if latest_materialized is not None:
                candle_filters.append(MarketCandle.open_time_ms >= latest_materialized - warmup_ms)
            candles = list(db.scalars(
                select(MarketCandle)
                .where(*candle_filters)
                .order_by(MarketCandle.open_time_ms.desc())
                .limit(9_000)
            ))
            if not candles:
                candles = list(db.scalars(
                    select(MarketCandle)
                    .where(
                        MarketCandle.instrument_id == instrument.id,
                        MarketCandle.interval == interval,
                        MarketCandle.price_type == "trade",
                    )
                    .order_by(MarketCandle.open_time_ms.desc())
                    .limit(9_000)
                ))
            candles.reverse()
            candles = _dedupe_by_open_time(candles)
            metrics = derivatives_repo.read_derivatives_history(
                db, instrument_id=instrument.id, interval="1h", provider=DEFAULT_PROVIDER, limit=5000
            )
            funding = derivatives_repo.read_funding_history(
                db, instrument_id=instrument.id, provider=DEFAULT_PROVIDER, limit=5000
            )
            existing_keys = set(db.execute(
                select(QuantFeatureValue.bar_open_time_ms, QuantFeatureValue.input_hash).where(
                    QuantFeatureValue.feature_set_id == registry["feature_set_id"],
                    QuantFeatureValue.instrument_id == instrument.id,
                    QuantFeatureValue.interval == interval,
                )
            ))
            interval_inserted = interval_unchanged = interval_skipped = 0
            for index, current in enumerate(candles):
                try:
                    built = build_feature_payload(
                        candles[max(0, index - 63): index + 1], candle=current,
                        metrics=metrics, funding=funding,
                        feature_set=registry["feature_set"],
                    )
                    key = (built["bar_open_time_ms"], built["input_hash"])
                    if key in existing_keys:
                        status = "unchanged"
                    else:
                        persist_feature_value(
                            db, built, feature_set_id=registry["feature_set_id"],
                            lookup_existing=False, flush=False,
                        )
                        existing_keys.add(key)
                        status = "inserted"
                except ValueError:
                    interval_skipped += 1
                    continue
                if status == "inserted":
                    inserted += 1
                    interval_inserted += 1
                else:
                    unchanged += 1
                    interval_unchanged += 1
            skipped += interval_skipped
            db.flush()
            items.append({
                "instrument_id": instrument.id,
                "interval": interval,
                "status": "ready" if interval_inserted or interval_unchanged else "unavailable",
                "inserted": interval_inserted,
                "unchanged": interval_unchanged,
                "skipped": interval_skipped,
            })
    db.flush()
    return {
        "feature_set": FEATURE_SET_KEY,
        "feature_set_id": registry["feature_set_id"],
        "inserted": inserted,
        "unchanged": unchanged,
        "skipped": skipped,
        "items": items,
    }


def feature_work_due(db: Session) -> bool:
    """Cheap Beat check: materialize only when a supported closed bar is newer."""

    definition = feature_set_definition()
    feature_set_id = db.scalar(select(QuantFeatureSet.id).where(
        QuantFeatureSet.feature_set_key == definition.key,
        QuantFeatureSet.version == definition.version,
    ))
    if feature_set_id is None:
        return True
    instruments = list(db.scalars(select(CryptoInstrument).where(
        CryptoInstrument.kind == "perpetual",
        CryptoInstrument.market == "usdm_futures",
        CryptoInstrument.status == "trading",
        CryptoInstrument.provider_symbol.in_(QUANT_SYMBOLS),
    )))
    for instrument in instruments:
        for interval in INTERVAL_DELTAS:
            candle_max = db.scalar(select(func.max(MarketCandle.open_time_ms)).where(
                MarketCandle.instrument_id == instrument.id,
                MarketCandle.interval == interval,
                MarketCandle.provider == DEFAULT_PROVIDER,
                MarketCandle.price_type == "trade",
            ))
            feature_max = db.scalar(select(func.max(QuantFeatureValue.bar_open_time_ms)).where(
                QuantFeatureValue.feature_set_id == feature_set_id,
                QuantFeatureValue.instrument_id == instrument.id,
                QuantFeatureValue.interval == interval,
            ))
            if candle_max is not None and (feature_max is None or candle_max > feature_max):
                return True
    return False


def feature_status(db: Session) -> dict[str, Any]:
    """Small read-only status payload for API/debug callers."""

    definition = feature_set_definition()
    row = db.scalar(select(QuantFeatureSet).filter_by(feature_set_key=definition.key, version=definition.version))
    if row is None:
        return {"status": "unavailable", "feature_set": definition.as_dict(), "count": 0, "instruments": []}
    count = db.scalar(
        select(func.count(QuantFeatureValue.id)).where(QuantFeatureValue.feature_set_id == row.id)
    ) or 0
    candidate = QuantFeatureValue.__table__.alias("candidate")
    latest_id = (
        select(candidate.c.id)
        .where(
            candidate.c.feature_set_id == row.id,
            candidate.c.instrument_id == QuantFeatureValue.instrument_id,
            candidate.c.interval == QuantFeatureValue.interval,
        )
        .order_by(candidate.c.as_of.desc(), candidate.c.id.desc())
        .limit(1)
        .correlate(QuantFeatureValue)
        .scalar_subquery()
    )
    values = list(db.scalars(
        select(QuantFeatureValue).where(
            QuantFeatureValue.feature_set_id == row.id,
            QuantFeatureValue.id == latest_id,
        )
    ))
    return {
        "status": "ready" if count else "unavailable",
        "feature_set": definition.as_dict(),
        "feature_set_id": row.id,
        "count": count,
        "instruments": [
            {
                "instrument_id": value.instrument_id,
                "interval": value.interval,
                "as_of": value.as_of.isoformat() if value.as_of else None,
                "available_at": value.available_at.isoformat() if value.available_at else None,
                "input_hash": value.input_hash,
                "quality": value.quality,
            }
            for value in values
        ],
    }


# Compatibility aliases used by small callers/tests.
available_at_for_candle = candle_available_at
available_at_for_metric = metric_available_at
available_at_for_funding = funding_available_at
build_features = build_feature_payload
materialize_feature = materialize_feature_value


__all__ = [
    "DEFAULT_PROVIDER",
    "FEATURE_SET_KEY",
    "SOURCE_CAUSAL_VERSION",
    "available_at_for_candle",
    "available_at_for_funding",
    "available_at_for_metric",
    "build_feature_payload",
    "build_features",
    "candle_available_at",
    "ensure_registry",
    "feature_input_hash",
    "feature_status",
    "funding_available_at",
    "materialize_feature",
    "materialize_feature_value",
    "materialize_features",
    "metric_available_at",
    "persist_feature_value",
    "source_causal_available_at",
]
