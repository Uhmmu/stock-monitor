"""Deterministic, provider-neutral options analytics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import math
from statistics import mean, median, pstdev
from typing import Any, Iterable, Mapping

STALE_DAYS = 7
HISTORY_CHANGE_WINDOWS = (1, 5, 20)
HISTORY_AVERAGE_WINDOWS = (7, 20, 30, 60)
HISTORY_STAT_WINDOWS = (20, 60)
HISTORY_MINIMUMS = {20: 10, 60: 30}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _count(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _safe(value.item())
        except Exception:
            return None
    return str(value)


def _get(row: Mapping[str, Any], *keys: str) -> Any:
    lowered = {str(key).casefold().replace("_", "").replace(" ", ""): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.casefold().replace("_", "").replace(" ", ""))
        if value is not None:
            return value
    return None


def _rows(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = value.get("data", value.get("rows", value))
        if isinstance(value, Mapping):
            value = [value]
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict("records")
        except (TypeError, ValueError):
            value = []
    return [dict(item) for item in (value or []) if isinstance(item, Mapping)]


def _expiration_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    expiration_value = payload.get("expirations", ()) or ()
    if isinstance(expiration_value, Mapping):
        expiration_value = [
            {"expiration": key, **(value if isinstance(value, Mapping) else {})}
            for key, value in expiration_value.items()
        ]
    for raw in expiration_value:
        if not isinstance(raw, Mapping):
            continue
        expiration = _date(raw.get("expiration") or raw.get("date"))
        if expiration is None:
            continue
        rows.append({
            "expiration": expiration,
            "days_to_expiration": _count(raw.get("days_to_expiration")),
            "calls": _rows(raw.get("calls")),
            "puts": _rows(raw.get("puts")),
        })
    if rows:
        return sorted(rows, key=lambda item: item["expiration"])
    calls = _rows(payload.get("calls"))
    puts = _rows(payload.get("puts"))
    expiration = _date(payload.get("nearest_expiration") or payload.get("expiration"))
    if calls or puts:
        return [{
            "expiration": expiration,
            "days_to_expiration": _count(payload.get("days_to_expiration")),
            "calls": calls,
            "puts": puts,
        }]
    return []


def _valid_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for raw in rows:
        strike = _positive(_get(raw, "strike"))
        if strike is None:
            continue
        row = {
            "contract_symbol": _get(raw, "contract_symbol", "contractsymbol"),
            "strike": strike,
            "last_price": _positive(_get(raw, "last_price", "lastprice")),
            "volume": _count(_get(raw, "volume")),
            "open_interest": _count(_get(raw, "open_interest", "openinterest")),
            "iv": _number(_get(raw, "implied_volatility", "impliedvolatility", "iv")),
            "bid": _positive(_get(raw, "bid")),
            "ask": _positive(_get(raw, "ask")),
            "last_trade_date": _date(_get(raw, "last_trade_date", "lasttradedate")),
        }
        if row["iv"] is not None and not 0 < row["iv"] <= 5:
            row["iv"] = None
        if row["bid"] is not None and row["ask"] is not None and row["ask"] < row["bid"]:
            row["bid"] = row["ask"] = None
        result.append(row)
    return result


def filter_contracts(
    rows: Iterable[Mapping[str, Any]],
    spot: float | None = None,
    *,
    max_contracts: int = 300,
) -> list[dict[str, Any]]:
    """Apply the shared finite-chain quality filter for detail consumers."""
    valid = _valid_rows(rows)
    filtered = []
    for row in valid:
        if spot and not .5 <= float(row["strike"]) / spot <= 1.5:
            continue
        bid, ask = row.get("bid"), row.get("ask")
        midpoint = (bid + ask) / 2 if bid is not None and ask is not None else None
        if midpoint and (ask - bid) / midpoint > 1:
            continue
        if row.get("iv") is None and not (row.get("volume") or row.get("open_interest")):
            continue
        filtered.append(row)
    valid = filtered
    valid.sort(key=lambda row: (
        abs(float(row["strike"]) - spot) if spot and spot > 0 else float(row["strike"]),
        -(float(row.get("volume") or 0) + float(row.get("open_interest") or 0) * .01),
        float(row["strike"]),
    ))
    return [_safe(row) for row in valid[: max(0, min(300, int(max_contracts)))]]


def _sum(rows: Iterable[Mapping[str, Any]], key: str) -> int | None:
    values = [int(row[key]) for row in rows if row.get(key) is not None]
    return sum(values) if values else None


def _iv_candidates(
    rows: list[Mapping[str, Any]],
    spot: float | None,
    *,
    side: str = "atm",
    reference_date: date | None = None,
) -> list[float]:
    if spot is None or spot <= 0:
        return []
    candidates: list[tuple[float, float, float]] = []
    for row in rows:
        iv = _number(row.get("iv"))
        strike = _positive(row.get("strike"))
        if iv is None or not 0 < iv <= 5 or strike is None:
            continue
        last_trade = _date(row.get("last_trade_date"))
        if reference_date and last_trade and last_trade < reference_date - timedelta(days=STALE_DAYS):
            continue
        ratio = strike / spot
        distance = abs(ratio - 1)
        if side == "put":
            if not 0.70 <= ratio < 0.98:
                continue
            distance = abs(ratio - 0.90)
        elif side == "call":
            if not 1.02 < ratio <= 1.30:
                continue
            distance = abs(ratio - 1.10)
        elif distance > 0.08:
            continue
        # Prefer tight/liquid observations but keep multiple valid samples so
        # one malformed or illiquid contract cannot define the estimate.
        bid, ask = _number(row.get("bid")), _number(row.get("ask"))
        if bid is not None and ask is not None:
            midpoint = (bid + ask) / 2
            if ask < bid or (midpoint > 0 and (ask - bid) / midpoint > .5):
                continue
        liquidity = float(row.get("volume") or 0) + float(row.get("open_interest") or 0) * 0.01
        if liquidity <= 0 and not (bid is not None and ask is not None and ask > 0):
            continue
        candidates.append((distance, -liquidity, float(iv)))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[2] for item in candidates[:7]]


def _iv_estimate(
    rows: list[Mapping[str, Any]],
    spot: float | None,
    *,
    side: str = "atm",
    reference_date: date | None = None,
) -> tuple[float | None, int, list[str]]:
    values = _iv_candidates(rows, spot, side=side, reference_date=reference_date)
    warnings = []
    if not values:
        warnings.append("no_valid_iv")
        return None, 0, warnings
    if len(values) < 3:
        warnings.append("small_iv_sample")
    return float(median(values)), len(values), warnings


def _atm_iv(rows: list[Mapping[str, Any]], spot: float | None, reference_date: date | None = None) -> float | None:
    return _iv_estimate(rows, spot, reference_date=reference_date)[0]


def _moneyness_iv(rows: list[Mapping[str, Any]], spot: float | None, *, side: str, reference_date: date | None = None) -> float | None:
    values = _iv_candidates(rows, spot, side=side, reference_date=reference_date)
    return float(median(values)) if values else None


def _term_structure_status(near: float | None, next_term: float | None) -> str:
    if near is None or next_term is None:
        return "INSUFFICIENT_DATA"
    tolerance = max(0.01, abs(near) * 0.02)
    if abs(next_term - near) <= tolerance:
        return "FLAT"
    return "NORMAL" if next_term > near else "INVERTED"


def classify_options_bias(call_bias: float | None, oi_bias: float | None) -> str:
    if call_bias is None and oi_bias is None:
        return "MIXED"
    signs = [value for value in (call_bias, oi_bias) if value is not None and abs(value) >= 0.10]
    if len(signs) == 2 and signs[0] * signs[1] < 0:
        return "MIXED"
    combined = mean(signs) if signs else 0.0
    if combined >= 0.35:
        return "CALL_HEAVY"
    if combined >= 0.10:
        return "SLIGHT_CALL_HEAVY"
    if combined <= -0.35:
        return "PUT_HEAVY"
    if combined <= -0.10:
        return "SLIGHT_PUT_HEAVY"
    return "BALANCED"


def _levels(rows: Iterable[Mapping[str, Any]], key: str, *, limit: int = 5) -> list[dict[str, Any]]:
    grouped: dict[float, int] = {}
    for row in rows:
        amount = row.get(key)
        if amount is not None:
            grouped[float(row["strike"])] = grouped.get(float(row["strike"]), 0) + int(amount)
    return [{"strike": strike, key: amount} for strike, amount in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _history_values(history: Any, key: str) -> list[float]:
    values = []
    for row in history or ():
        if isinstance(row, Mapping) and (number := _number(row.get(key))) is not None:
            values.append(number)
    return values


def _row_mapping(row: Any) -> dict[str, Any]:
    """Read a snapshot mapping or ORM row without coupling history to SQLAlchemy."""
    if isinstance(row, Mapping):
        result = dict(row)
    else:
        result = {
            key: getattr(row, key, None)
            for key in (
                "symbol", "trading_date", "fetched_at", "atm_iv", "iv_change", "downside_skew",
                "upside_skew", "activity_score", "activity_status", "call_volume", "put_volume",
                "call_open_interest", "put_open_interest", "put_call_volume_ratio", "put_call_oi_ratio",
                "quality_score", "coverage", "sample_size", "status", "warnings", "metrics_json",
            )
        }
    metrics = result.get("metrics_json") or {}
    if isinstance(metrics, Mapping):
        for key in ("total_volume", "total_open_interest", "total_oi", "volume_oi_ratio", "options_bias"):
            if result.get(key) is None and metrics.get(key) is not None:
                result[key] = metrics[key]
    if result.get("total_volume") is None:
        values = [result.get(key) for key in ("call_volume", "put_volume")]
        values = [value for value in values if _number(value) is not None]
        if values:
            result["total_volume"] = sum(float(value) for value in values)
    if result.get("total_open_interest") is None and result.get("total_oi") is None:
        values = [result.get(key) for key in ("call_open_interest", "put_open_interest")]
        values = [value for value in values if _number(value) is not None]
        if values:
            result["total_open_interest"] = sum(float(value) for value in values)
    if result.get("total_oi") is None:
        result["total_oi"] = result.get("total_open_interest")
    if result.get("volume_oi_ratio") is None:
        volume, oi = _number(result.get("total_volume")), _number(result.get("total_oi"))
        result["volume_oi_ratio"] = volume / oi if volume is not None and oi and oi > 0 else None
    if result.get("trading_date") is None:
        result["trading_date"] = result.get("date")
    return result


def _history_date(row: Mapping[str, Any]) -> date | None:
    return _date(row.get("trading_date") or row.get("date") or row.get("fetched_at"))


def _history_metric(row: Mapping[str, Any], key: str) -> float | None:
    aliases = {
        "total_oi": ("total_oi", "total_open_interest"),
        "activity": ("total_volume",),
        "iv": ("atm_iv",),
        "skew": ("downside_skew",),
        "put_call": ("put_call_volume_ratio",),
        "put_call_oi": ("put_call_oi_ratio",),
    }
    for candidate in aliases.get(key, (key,)):
        value = _number(row.get(candidate))
        if value is not None:
            return value
    return None


def _required_history(window: int) -> int:
    return HISTORY_MINIMUMS.get(window, 2)


def _empirical_stats(current: float | None, values: list[float], window: int) -> dict[str, Any]:
    sample_count = len(values)
    required = _required_history(window)
    result: dict[str, Any] = {
        "value": current,
        "percentile": None,
        "zscore": None,
        "sample_count": sample_count,
        "required_samples": required,
        "status": "INSUFFICIENT_HISTORY",
    }
    if current is None or sample_count < required:
        return result
    average = mean(values)
    deviation = pstdev(values) if sample_count > 1 else 0.0
    result["percentile"] = round(sum(value <= current for value in values) / sample_count * 100.0, 4)
    result["zscore"] = round((current - average) / deviation, 4) if deviation else (0.0 if current == average else None)
    result["status"] = "READY"
    return result


def _history_comparison(current: Mapping[str, Any], prior: list[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = (
        "activity", "iv", "total_volume", "call_volume", "put_volume",
        "total_oi", "put_call", "put_call_oi", "skew",
    )
    current_values = {key: _history_metric(current, key) for key in metrics}
    changes: dict[str, dict[str, float | None]] = {}
    averages: dict[str, dict[str, float | None]] = {}
    statistics: dict[str, dict[str, Any]] = {}
    trend: dict[str, str] = {}
    for key in metrics:
        values = [_history_metric(row, key) for row in prior]
        values = [value for value in values if value is not None]
        changes[key] = {}
        for window in HISTORY_CHANGE_WINDOWS:
            changes[key][str(window)] = current_values[key] - values[-window] if current_values[key] is not None and len(values) >= window else None
            changes[key][f"{window}_pct"] = (
                (current_values[key] - values[-window]) / abs(values[-window]) * 100.0
                if current_values[key] is not None and len(values) >= window and values[-window] not in (None, 0)
                else None
            )
        averages[key] = {}
        for window in HISTORY_AVERAGE_WINDOWS:
            baseline = values[-window:]
            averages[key][str(window)] = round(mean(baseline), 6) if len(baseline) >= _required_history(window) else None
        statistics[key] = {
            str(window): _empirical_stats(current_values[key], values[-window:], window)
            for window in HISTORY_STAT_WINDOWS
        }
        selected_window = 60 if statistics[key]["60"]["status"] == "READY" else 20
        selected_stat = statistics[key][str(selected_window)]
        zscore = selected_stat.get("zscore")
        absolute_z = abs(zscore) if zscore is not None else None
        if zscore is None:
            anomaly = "INSUFFICIENT_HISTORY"
            anomaly_direction = "NONE"
        else:
            anomaly = "EXTREME" if absolute_z >= 3 else "HIGH" if absolute_z >= 2 else "NORMAL"
            anomaly_direction = "UP" if zscore >= 2 else "DOWN" if zscore <= -2 else "NONE"
        statistics[key]["selected_window"] = selected_window
        statistics[key]["anomaly_status"] = anomaly
        statistics[key]["anomaly_direction"] = anomaly_direction
        one_day = changes[key].get("1")
        trend[key] = "UP" if one_day is not None and one_day > 0 else "DOWN" if one_day is not None and one_day < 0 else "FLAT" if one_day == 0 else "INSUFFICIENT_HISTORY"

    activity_stats = statistics["activity"]
    activity_window = 60 if activity_stats["60"]["status"] == "READY" else 20
    activity_stat = activity_stats[str(activity_window)]
    activity_status = activity_stat["status"]
    activity_percentile = activity_stat["percentile"]
    activity_zscore = activity_stat["zscore"]
    anomaly_status = "INSUFFICIENT_HISTORY"
    anomaly_direction = "NONE"
    if activity_zscore is not None:
        anomaly_direction = "UP" if activity_zscore >= 2 else "DOWN" if activity_zscore <= -2 else "NONE"
        absolute_z = abs(activity_zscore)
        anomaly_status = "EXTREME" if absolute_z >= 3 else "HIGH" if absolute_z >= 2 else "NORMAL"
    result = {
        "status": activity_status,
        "prior_count": len(prior),
        "changes": changes,
        "averages": averages,
        "statistics": statistics,
        "trend": trend,
        "metric_anomalies": {
            key: {
                "status": statistics[key]["anomaly_status"],
                "direction": statistics[key]["anomaly_direction"],
                "trend": trend[key],
                "zscore": statistics[key][str(statistics[key]["selected_window"])]["zscore"],
                "percentile": statistics[key][str(statistics[key]["selected_window"])]["percentile"],
                "sample_count": statistics[key][str(statistics[key]["selected_window"])]["sample_count"],
            }
            for key in metrics
        },
        "activity_window": activity_window,
        "activity_level": _activity_level({"status": activity_status, "activity_percentile": activity_percentile, "activity_zscore": activity_zscore}),
        "activity_percentile": activity_percentile,
        "activity_zscore": activity_zscore,
        "anomaly_status": anomaly_status,
        "anomaly_direction": anomaly_direction,
        "sample_count": activity_stat["sample_count"],
        "required_samples": activity_stat["required_samples"],
        # Stable aliases for API/chart consumers.
        "change_1": changes["activity"]["1"],
        "change_5": changes["activity"]["5"],
        "change_20": changes["activity"]["20"],
        "average_7": averages["activity"]["7"],
        "average_20": averages["activity"]["20"],
        "average_30": averages["activity"]["30"],
        "average_60": averages["activity"]["60"],
    }
    for key in metrics:
        for window in HISTORY_STAT_WINDOWS:
            result[f"{key}_percentile_{window}"] = statistics[key][str(window)]["percentile"]
            result[f"{key}_zscore_{window}"] = statistics[key][str(window)]["zscore"]
        for window in HISTORY_CHANGE_WINDOWS:
            result[f"{key}_change_{window}"] = changes[key][str(window)]
    return _safe(result)


def enrich_options_history(
    history: Iterable[Mapping[str, Any] | Any] | None,
    current: Mapping[str, Any] | Any | None = None,
) -> dict[str, Any]:
    """Enrich observed snapshots without assuming calendar-day continuity.

    ``current`` is deliberately excluded from its own baseline.  The helper is
    shared by persistence and readers so old rows gain the same comparisons as
    newly persisted rows without a migration.
    """
    rows = [_row_mapping(row) for row in (history or ())]
    current_row_hint = _row_mapping(current) if current is not None else None
    current_day = _history_date(current_row_hint) if current_row_hint else None
    if current_day is not None:
        rows = [row for row in rows if _history_date(row) != current_day]
    rows.sort(key=lambda row: (_history_date(row) or date.min, str(row.get("fetched_at") or "")))
    enriched: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        comparison = _history_comparison(row, rows[:index])
        enriched.append({**row, "historical_comparison": comparison, "historical_regime": comparison})
    current_row = current_row_hint if current_row_hint is not None else (enriched[-1] if enriched else None)
    if current_row is not None:
        # If current is already the last stored row, use only earlier points.
        prior = rows
        if rows and current is None:
            prior = rows[:-1]
        comparison = _history_comparison(current_row, prior)
        current_enriched = {**current_row, "historical_comparison": comparison, "historical_regime": comparison}
    else:
        current_enriched = None
        comparison = None
    return {
        "status": "READY" if comparison and comparison.get("status") == "READY" else "INSUFFICIENT_HISTORY",
        "count": len(rows),
        "points": enriched,
        "history": enriched,
        "current": current_enriched,
        "historical_comparison": comparison,
        "historical_regime": comparison,
        "warnings": [] if comparison and comparison.get("status") == "READY" else ["INSUFFICIENT_HISTORY"],
    }


def _activity_level(comparison: Mapping[str, Any] | None) -> str:
    if not comparison or comparison.get("status") != "READY":
        return "INSUFFICIENT_HISTORY"
    zscore = _number(comparison.get("activity_zscore"))
    percentile = _number(comparison.get("activity_percentile"))
    if zscore is not None and zscore >= 3:
        return "EXTREME"
    if zscore is not None and zscore >= 2:
        return "HIGH"
    if percentile is not None and percentile <= 20:
        return "VERY_LOW"
    if percentile is not None and percentile <= 35:
        return "LOW"
    if percentile is not None and percentile >= 80:
        return "ELEVATED"
    return "NORMAL"


# Friendly aliases keep the read model discoverable without a second helper.
build_history_enrichment = enrich_options_history
history_enrichment = enrich_options_history


def _expiration_summary(item: Mapping[str, Any], spot: float | None) -> dict[str, Any]:
    calls = _valid_rows(item.get("calls", ()))
    puts = _valid_rows(item.get("puts", ()))
    values = [value for value in (_atm_iv(calls, spot), _atm_iv(puts, spot)) if value is not None]
    return {
        "expiration": item["expiration"],
        "days_to_expiration": item.get("days_to_expiration"),
        "atm_iv": median(values) if values else None,
        "call_volume": _sum(calls, "volume"),
        "put_volume": _sum(puts, "volume"),
        "call_open_interest": _sum(calls, "open_interest"),
        "put_open_interest": _sum(puts, "open_interest"),
    }


def _positioning_metrics(calls: list[Mapping[str, Any]], puts: list[Mapping[str, Any]], total_oi: int | None) -> dict[str, Any]:
    call_levels = _levels(calls, "open_interest", limit=5)
    put_levels = _levels(puts, "open_interest", limit=5)
    grouped: dict[float, dict[str, int]] = {}
    for side, rows in (("call", calls), ("put", puts)):
        for row in rows:
            amount = _count(row.get("open_interest"))
            if amount is None:
                continue
            strike = float(row["strike"])
            grouped.setdefault(strike, {"call_open_interest": 0, "put_open_interest": 0})[f"{side}_open_interest"] += amount
    largest = [
        {"strike": strike, **values, "total_open_interest": values["call_open_interest"] + values["put_open_interest"]}
        for strike, values in grouped.items()
    ]
    largest.sort(key=lambda item: (-item["total_open_interest"], item["strike"]))
    concentration = largest[0]["total_open_interest"] / total_oi if largest and total_oi else None
    call_oi = _sum(calls, "open_interest")
    put_oi = _sum(puts, "open_interest")
    call_concentration = call_levels[0]["open_interest"] / call_oi if call_levels and call_oi else None
    put_concentration = put_levels[0]["open_interest"] / put_oi if put_levels and put_oi else None
    status = (
        "HIGH_CONCENTRATION" if concentration is not None and concentration >= .35
        else "CONCENTRATED" if concentration is not None and concentration >= .20
        else "DISTRIBUTED" if concentration is not None
        else "INSUFFICIENT_DATA"
    )
    quality = min(1.0, len(largest) / 10) if largest else 0.0
    return {
        "status": status,
        "raw_metrics": {
            "total_oi": total_oi,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "oi_concentration": round(concentration, 6) if concentration is not None else None,
            "call_oi_concentration": round(call_concentration, 6) if call_concentration is not None else None,
            "put_oi_concentration": round(put_concentration, 6) if put_concentration is not None else None,
            "largest_call_strikes": call_levels,
            "largest_put_strikes": put_levels,
            "largest_oi_strikes": largest[:5],
        },
        "quality": round(quality, 4),
        "confidence": "high" if quality >= .75 else "medium" if quality >= .4 else "low",
    }


def compute_options_analytics(payload: Mapping[str, Any], history: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Return a persistable OptionsSnapshot-shaped row plus explainable metrics."""
    source = dict(payload or {})
    history_rows = list(history or ())
    fetched_at = source.get("fetched_at") or datetime.now(UTC).isoformat()
    reference_date = _date(fetched_at)
    expirations = _expiration_rows(source)
    result: dict[str, Any] = {
        "symbol": str(source.get("symbol") or "").upper(),
        "asset_type": source.get("asset_type") or "unknown",
        "sector_node_id": source.get("sector_node_id") or source.get("sector_id"),
        "provider": source.get("provider") or "yfinance",
        "status": str(source.get("status") or "OK").upper(),
        "trading_date": _date(source.get("trading_date") or fetched_at),
        "underlying_price": _positive(source.get("underlying_price")),
        "nearest_expiration": expirations[0]["expiration"] if expirations else _date(source.get("nearest_expiration")),
        "next_expiration": expirations[1]["expiration"] if len(expirations) > 1 else _date(source.get("next_expiration")),
        "days_to_expiration": expirations[0].get("days_to_expiration") if expirations else _count(source.get("days_to_expiration")),
        "active_contracts": 0,
        "call_volume": None,
        "put_volume": None,
        "call_open_interest": None,
        "put_open_interest": None,
        "put_call_volume_ratio": None,
        "put_call_oi_ratio": None,
        "volume_oi_ratio": None,
        "total_volume": None,
        "total_open_interest": None,
        "total_oi": None,
        "atm_iv": None,
        "call_atm_iv": None,
        "put_atm_iv": None,
        "near_term_iv": None,
        "next_term_iv": None,
        "iv_change": None,
        "downside_skew": None,
        "upside_skew": None,
        "activity_score": None,
        "activity_status": "insufficient_history",
        "activity_percentile": None,
        "activity_zscore": None,
        "activity_anomaly": "INSUFFICIENT_HISTORY",
        "activity_anomaly_direction": "NONE",
        "activity_history_status": "INSUFFICIENT_HISTORY",
        "options_bias": "MIXED",
        "bias_status": "INSUFFICIENT_DATA",
        "bias_components": {},
        "term_structure_status": "INSUFFICIENT_DATA",
        "iv_quality": {"status": "INSUFFICIENT_DATA", "sample_size": 0, "warnings": []},
        "skew_quality": {"status": "INSUFFICIENT_DATA", "sample_size": 0, "warnings": []},
        "quality_score": 0.0,
        "coverage": 0.0,
        "sample_size": 0,
        "warnings": list(source.get("warnings") or ()),
        "fetched_at": fetched_at,
    }
    if result["status"] in {"NO_OPTIONS", "NO_VALID_EXPIRATION", "PROVIDER_ERROR"} or not expirations:
        if not expirations and result["status"] == "OK":
            result["status"] = "NO_VALID_EXPIRATION"
        result["warnings"] = list(dict.fromkeys(result["warnings"] + ["no_usable_expiration"]))
        comparison = enrich_options_history(history_rows, current=result)["historical_comparison"]
        result["historical_comparison"] = comparison
        result["historical_regime"] = comparison
        result["metrics_json"] = {
            "history_available": bool(history_rows),
            "historical_comparison": comparison,
            "historical_regime": comparison,
            "options_state": {
                "activity": {"status": "INSUFFICIENT_HISTORY", "raw_metrics": {}, "historical_comparison": comparison, "quality": 0.0, "confidence": "low"},
                "bias": {"status": "INSUFFICIENT_DATA", "raw_metrics": {}, "historical_comparison": comparison, "quality": 0.0, "confidence": "low"},
                "risk_pricing": {"status": "INSUFFICIENT_DATA", "raw_metrics": {}, "historical_comparison": comparison, "quality": result["iv_quality"], "confidence": "low"},
                "positioning": {"status": "INSUFFICIENT_DATA", "raw_metrics": {}, "historical_comparison": comparison, "quality": 0.0, "confidence": "low"},
                "historical_regime": {"status": comparison.get("status") if comparison else "INSUFFICIENT_HISTORY", "raw_metrics": {}, "historical_comparison": comparison, "quality": 0.0, "confidence": "low"},
            },
        }
        return _safe(result)
    nearest_calls = _valid_rows(filter_contracts(expirations[0]["calls"], result["underlying_price"]))
    nearest_puts = _valid_rows(filter_contracts(expirations[0]["puts"], result["underlying_price"]))
    all_nearest = nearest_calls + nearest_puts
    result["active_contracts"] = len(all_nearest)
    result["sample_size"] = len(all_nearest)
    result["call_volume"] = _sum(nearest_calls, "volume")
    result["put_volume"] = _sum(nearest_puts, "volume")
    result["call_open_interest"] = _sum(nearest_calls, "open_interest")
    result["put_open_interest"] = _sum(nearest_puts, "open_interest")
    if result["call_volume"] not in (None, 0) and result["put_volume"] is not None:
        result["put_call_volume_ratio"] = result["put_volume"] / result["call_volume"]
    if result["call_open_interest"] not in (None, 0) and result["put_open_interest"] is not None:
        result["put_call_oi_ratio"] = result["put_open_interest"] / result["call_open_interest"]
    spot = result["underlying_price"]
    call_atm, call_iv_samples, call_iv_warnings = _iv_estimate(nearest_calls, spot, reference_date=reference_date)
    put_atm, put_iv_samples, put_iv_warnings = _iv_estimate(nearest_puts, spot, reference_date=reference_date)
    result["call_atm_iv"] = call_atm
    result["put_atm_iv"] = put_atm
    atm_values = [item for item in (call_atm, put_atm) if item is not None]
    result["atm_iv"] = median(atm_values) if atm_values else None
    result["near_term_iv"] = result["atm_iv"]
    if len(expirations) > 1:
        next_calls = _valid_rows(filter_contracts(expirations[1]["calls"], spot))
        next_puts = _valid_rows(filter_contracts(expirations[1]["puts"], spot))
        next_values = [item for item in (_atm_iv(next_calls, spot, reference_date), _atm_iv(next_puts, spot, reference_date)) if item is not None]
        result["next_term_iv"] = median(next_values) if next_values else None
    result["term_structure_status"] = _term_structure_status(result["near_term_iv"], result["next_term_iv"])
    prior_iv = _history_values(history_rows, "atm_iv")
    if result["atm_iv"] is not None and prior_iv:
        result["iv_change"] = result["atm_iv"] - prior_iv[-1]
    put_otm = _moneyness_iv(nearest_puts, spot, side="put", reference_date=reference_date)
    call_otm = _moneyness_iv(nearest_calls, spot, side="call", reference_date=reference_date)
    if put_otm is not None and result["atm_iv"] is not None:
        result["downside_skew"] = put_otm - result["atm_iv"]
    if call_otm is not None and result["atm_iv"] is not None:
        result["upside_skew"] = call_otm - result["atm_iv"]
    total_volume = (result["call_volume"] or 0) + (result["put_volume"] or 0) if result["call_volume"] is not None or result["put_volume"] is not None else None
    total_oi = (result["call_open_interest"] or 0) + (result["put_open_interest"] or 0) if result["call_open_interest"] is not None or result["put_open_interest"] is not None else None
    activity_components = {
        "total_volume": total_volume,
        "total_oi": total_oi,
        "volume_oi_ratio": total_volume / total_oi if total_volume is not None and total_oi else None,
        "active_contracts": len(all_nearest),
    }
    result["total_volume"] = total_volume
    result["total_open_interest"] = total_oi
    result["total_oi"] = total_oi
    result["volume_oi_ratio"] = total_volume / total_oi if total_volume is not None and total_oi else None
    iv_rows = [row for row in all_nearest if row.get("iv") is not None]
    observed_rows = [row for row in all_nearest if any(row.get(key) is not None for key in ("volume", "open_interest", "iv"))]
    volume_coverage = sum(row.get("volume") is not None for row in all_nearest) / len(all_nearest) if all_nearest else 0.0
    oi_coverage = sum(row.get("open_interest") is not None for row in all_nearest) / len(all_nearest) if all_nearest else 0.0
    iv_coverage = len(iv_rows) / len(all_nearest) if all_nearest else 0.0
    # Coverage measures metric availability rather than merely row count:
    # an IV-only chain must not look complete when volume/OI are absent.
    result["coverage"] = round((volume_coverage + oi_coverage + iv_coverage) / 3, 4)
    result["quality_score"] = round(min(1.0, 0.55 * result["coverage"] + 0.25 * (len(observed_rows) / len(all_nearest) if all_nearest else 0) + 0.20 * min(1.0, len(all_nearest) / 20)), 4)
    iv_warnings = list(dict.fromkeys(call_iv_warnings + put_iv_warnings))
    result["iv_quality"] = {
        "status": "READY" if call_iv_samples + put_iv_samples else "INSUFFICIENT_DATA",
        "sample_size": call_iv_samples + put_iv_samples,
        "warnings": iv_warnings,
    }
    skew_samples = sum(1 for value in (put_otm, call_otm) if value is not None)
    result["skew_quality"] = {
        "status": "READY" if skew_samples else "INSUFFICIENT_DATA",
        "sample_size": skew_samples,
        "warnings": [] if skew_samples else ["no_valid_skew"],
    }
    if not iv_rows:
        result["warnings"].append("no_valid_iv")
    result["warnings"].extend(iv_warnings)
    if total_volume in (None, 0) and total_oi in (None, 0):
        result["warnings"].append("missing_volume_and_open_interest")
        result["status"] = "INSUFFICIENT_LIQUIDITY"
    elif result["status"] == "OK" and (total_volume or 0) == 0 and (total_oi or 0) < 100:
        result["status"] = "INSUFFICIENT_LIQUIDITY"
    fetched_date = _date(fetched_at)
    latest_trade = max((row["last_trade_date"] for row in all_nearest if row.get("last_trade_date")), default=None)
    reference_date = fetched_date or date.today()
    if source.get("status") == "STALE_DATA" or (latest_trade and latest_trade < reference_date - timedelta(days=STALE_DAYS)):
        result["status"] = "STALE_DATA"
        result["warnings"].append("stale_last_trade")
    call_bias = ((result["call_volume"] or 0) - (result["put_volume"] or 0)) / total_volume if total_volume else None
    oi_bias = ((result["call_open_interest"] or 0) - (result["put_open_interest"] or 0)) / total_oi if total_oi else None
    skew = result["downside_skew"]
    bias = classify_options_bias(call_bias, oi_bias)
    result["options_bias"] = bias
    result["bias_status"] = "READY" if call_bias is not None or oi_bias is not None else "INSUFFICIENT_DATA"
    result["bias_components"] = {"volume": call_bias, "open_interest": oi_bias, "downside_skew": skew}
    positioning = _positioning_metrics(nearest_calls, nearest_puts, total_oi)
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["skew_method"] = "moneyness_proxy"
    result["metrics_json"] = {
        "total_volume": total_volume,
        "total_open_interest": total_oi,
        "total_oi": total_oi,
        "volume_oi_ratio": result["volume_oi_ratio"],
        "call_atm_iv": call_atm,
        "put_atm_iv": put_atm,
        "skew_method": "moneyness_proxy",
        "activity_components": activity_components,
        "options_bias": bias,
        "bias_status": result["bias_status"],
        "bias_components": result["bias_components"],
        "term_structure_status": result["term_structure_status"],
        "iv_quality": result["iv_quality"],
        "skew_quality": result["skew_quality"],
        "positioning": {
            **positioning,
            "historical_comparison": result.get("historical_comparison"),
        },
        "top_call_oi_levels": _levels(nearest_calls, "open_interest"),
        "top_put_oi_levels": _levels(nearest_puts, "open_interest"),
        # Stable aliases used by downstream API/UI serializers.
        "major_call_oi_levels": _levels(nearest_calls, "open_interest"),
        "major_put_oi_levels": _levels(nearest_puts, "open_interest"),
        "top_call_volume_levels": _levels(nearest_calls, "volume"),
        "top_put_volume_levels": _levels(nearest_puts, "volume"),
        "strike_oi_distribution": {
            "calls": _levels(nearest_calls, "open_interest", limit=300),
            "puts": _levels(nearest_puts, "open_interest", limit=300),
        },
        "strike_volume_distribution": {
            "calls": _levels(nearest_calls, "volume", limit=300),
            "puts": _levels(nearest_puts, "volume", limit=300),
        },
        "oi_distribution": [
            {"x": strike, "strike": strike, "call_open_interest": call_oi, "put_open_interest": put_oi, "value": (call_oi or 0) + (put_oi or 0)}
            for strike in sorted({float(row["strike"]) for row in all_nearest})
            for call_oi in (next((item["open_interest"] for item in nearest_calls if item["strike"] == strike), None),)
            for put_oi in (next((item["open_interest"] for item in nearest_puts if item["strike"] == strike), None),)
            if call_oi is not None or put_oi is not None
        ],
        "volume_distribution": [
            {"x": strike, "strike": strike, "call_volume": call_volume, "put_volume": put_volume, "value": (call_volume or 0) + (put_volume or 0)}
            for strike in sorted({float(row["strike"]) for row in all_nearest})
            for call_volume in (next((item["volume"] for item in nearest_calls if item["strike"] == strike), None),)
            for put_volume in (next((item["volume"] for item in nearest_puts if item["strike"] == strike), None),)
            if call_volume is not None or put_volume is not None
        ],
        "expiration_structure": [_expiration_summary(item, spot) for item in expirations[:2]],
        "iv_term_structure": [
            {"expiration": item["expiration"], "atm_iv": _expiration_summary(item, spot)["atm_iv"]}
            for item in expirations[:2]
        ],
        "filtered_calls": filter_contracts(expirations[0]["calls"], spot),
        "filtered_puts": filter_contracts(expirations[0]["puts"], spot),
        "history_available": bool(history_rows),
    }
    comparison = enrich_options_history(history_rows, current=result)["historical_comparison"]
    if comparison:
        result["historical_comparison"] = comparison
        result["historical_regime"] = comparison
        result["activity_percentile"] = comparison.get("activity_percentile")
        result["activity_zscore"] = comparison.get("activity_zscore")
        result["activity_anomaly"] = comparison.get("anomaly_status")
        result["activity_anomaly_direction"] = comparison.get("anomaly_direction")
        result["activity_history_status"] = comparison.get("status")
        # Activity is only the symbol's own-history percentile; there is no
        # universal absolute-volume score across unlike ETFs and stocks.
        result["activity_status"] = _activity_level(comparison)
        if comparison.get("activity_percentile") is not None:
            result["activity_score"] = comparison["activity_percentile"]
        else:
            result["activity_score"] = None
        result["activity_trend"] = (comparison.get("trend") or {}).get("activity")
    result["options_state"] = {
        "activity": {
            "status": _activity_level(result.get("historical_comparison")),
            "raw_metrics": {
                "score": result.get("activity_percentile"),
                "percentile": result.get("activity_percentile"),
                "zscore": result.get("activity_zscore"),
                "components": activity_components,
            },
            "historical_comparison": result.get("historical_comparison"),
            "quality": result.get("quality_score"),
            "confidence": "high" if result.get("quality_score", 0) >= .75 else "medium" if result.get("quality_score", 0) >= .45 else "low",
        },
        "bias": {
            "status": result.get("options_bias") if result.get("bias_status") == "READY" else "INSUFFICIENT_DATA",
            "raw_metrics": result.get("bias_components"),
            "historical_comparison": result.get("historical_comparison"),
            "quality": result.get("quality_score"),
            "confidence": "high" if result.get("bias_status") == "READY" else "low",
        },
        "risk_pricing": {
            "status": (
                "INSUFFICIENT_DATA" if result.get("atm_iv") is None
                else "INSUFFICIENT_HISTORY" if (result.get("historical_comparison") or {}).get("iv_percentile_20") is None
                else "IV_HIGH" if (result.get("historical_comparison") or {}).get("iv_percentile_20") >= 80
                else "IV_LOW" if (result.get("historical_comparison") or {}).get("iv_percentile_20") <= 20
                else "IV_NORMAL"
            ),
            "raw_metrics": {"atm_iv": result.get("atm_iv"), "near_term_iv": result.get("near_term_iv"), "next_term_iv": result.get("next_term_iv"), "downside_skew": result.get("downside_skew"), "upside_skew": result.get("upside_skew"), "term_structure_status": result.get("term_structure_status")},
            "historical_comparison": result.get("historical_comparison"),
            "quality": result.get("iv_quality"),
            "confidence": "high" if result.get("iv_quality", {}).get("sample_size", 0) >= 3 else "medium" if result.get("atm_iv") is not None else "low",
        },
        "positioning": positioning,
        "historical_regime": {
            "status": result.get("activity_history_status"),
            "raw_metrics": {"anomaly": result.get("activity_anomaly"), "direction": result.get("activity_anomaly_direction")},
            "historical_comparison": result.get("historical_comparison"),
            "quality": result.get("quality_score"),
            "confidence": "high" if result.get("activity_percentile") is not None else "low",
        },
    }
    result["metrics_json"]["historical_comparison"] = result.get("historical_comparison")
    result["metrics_json"]["historical_regime"] = result.get("historical_regime")
    result["metrics_json"]["activity_percentile"] = result.get("activity_percentile")
    result["metrics_json"]["activity_zscore"] = result.get("activity_zscore")
    result["metrics_json"]["activity_anomaly"] = result.get("activity_anomaly")
    result["metrics_json"]["activity_anomaly_direction"] = result.get("activity_anomaly_direction")
    result["metrics_json"]["options_state"] = result["options_state"]
    return _safe(result)


analyze_options = compute_options_analytics
calculate_options_analytics = compute_options_analytics

__all__ = [
    "analyze_options", "calculate_options_analytics", "compute_options_analytics", "filter_contracts",
    "enrich_options_history", "build_history_enrichment", "history_enrichment", "classify_options_bias",
]
