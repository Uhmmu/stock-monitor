"""Deterministic, provider-neutral options analytics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import math
from statistics import median
from typing import Any, Iterable, Mapping

STALE_DAYS = 7


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


def _atm_iv(rows: list[Mapping[str, Any]], spot: float | None) -> float | None:
    if spot is None or spot <= 0:
        return None
    candidates = [row for row in rows if row.get("iv") is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (abs(float(row["strike"]) / spot - 1), -float(row.get("volume") or 0), float(row["strike"])))
    return float(candidates[0]["iv"])


def _moneyness_iv(rows: list[Mapping[str, Any]], spot: float | None, *, side: str) -> float | None:
    if spot is None or spot <= 0:
        return None
    candidates = []
    for row in rows:
        iv = row.get("iv")
        ratio = float(row["strike"]) / spot
        if iv is None:
            continue
        if side == "put" and 0.70 <= ratio < 0.98:
            target = abs(ratio - 0.90)
        elif side == "call" and 1.02 < ratio <= 1.30:
            target = abs(ratio - 1.10)
        else:
            continue
        candidates.append((target, -float(row.get("volume") or 0), float(iv)))
    return min(candidates)[2] if candidates else None


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


def _activity(total_volume: int | None, total_oi: int | None, active: int, history: Any) -> tuple[float, str, dict[str, float]]:
    volume_component = min(1.0, (total_volume or 0) / 10_000) if total_volume is not None else 0.0
    oi_component = min(1.0, (total_oi or 0) / 50_000) if total_oi is not None else 0.0
    turnover_component = min(1.0, (total_volume / total_oi)) if total_volume is not None and total_oi else 0.0
    breadth_component = min(1.0, active / 20)
    score = round(100 * (0.4 * volume_component + 0.3 * oi_component + 0.2 * turnover_component + 0.1 * breadth_component), 4)
    prior = _history_values(history, "total_volume")
    if total_volume is None or not prior:
        return score, "insufficient_history", {
            "volume": round(volume_component, 4), "open_interest": round(oi_component, 4),
            "turnover": round(turnover_component, 4), "breadth": round(breadth_component, 4),
        }
    baseline = median(prior)
    ratio = (total_volume / baseline) if total_volume is not None and baseline > 0 else 1.0
    status = "extreme" if ratio >= 4 else "high" if ratio >= 2.5 else "elevated" if ratio >= 1.5 else "low" if ratio <= .6 else "normal"
    return score, status, {
        "volume": round(volume_component, 4), "open_interest": round(oi_component, 4),
        "turnover": round(turnover_component, 4), "breadth": round(breadth_component, 4), "history_ratio": round(ratio, 4),
    }


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


def compute_options_analytics(payload: Mapping[str, Any], history: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Return a persistable OptionsSnapshot-shaped row plus explainable metrics."""
    source = dict(payload or {})
    history_rows = list(history or ())
    fetched_at = source.get("fetched_at") or datetime.now(UTC).isoformat()
    expirations = _expiration_rows(source)
    result: dict[str, Any] = {
        "symbol": str(source.get("symbol") or "").upper(),
        "asset_type": source.get("asset_type") or "unknown",
        "sector_node_id": source.get("sector_node_id") or source.get("sector_id"),
        "provider": source.get("provider") or "yfinance",
        "status": str(source.get("status") or "OK").upper(),
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
        result["metrics_json"] = {"history_available": bool(history_rows)}
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
    call_atm = _atm_iv(nearest_calls, spot)
    put_atm = _atm_iv(nearest_puts, spot)
    result["call_atm_iv"] = call_atm
    result["put_atm_iv"] = put_atm
    atm_values = [item for item in (call_atm, put_atm) if item is not None]
    result["atm_iv"] = median(atm_values) if atm_values else None
    result["near_term_iv"] = result["atm_iv"]
    if len(expirations) > 1:
        next_calls = _valid_rows(filter_contracts(expirations[1]["calls"], spot))
        next_puts = _valid_rows(filter_contracts(expirations[1]["puts"], spot))
        next_values = [item for item in (_atm_iv(next_calls, spot), _atm_iv(next_puts, spot)) if item is not None]
        result["next_term_iv"] = median(next_values) if next_values else None
    prior_iv = _history_values(history_rows, "atm_iv")
    if result["atm_iv"] is not None and prior_iv:
        result["iv_change"] = result["atm_iv"] - prior_iv[-1]
    put_otm = _moneyness_iv(nearest_puts, spot, side="put")
    call_otm = _moneyness_iv(nearest_calls, spot, side="call")
    if put_otm is not None and result["atm_iv"] is not None:
        result["downside_skew"] = put_otm - result["atm_iv"]
    if call_otm is not None and result["atm_iv"] is not None:
        result["upside_skew"] = call_otm - result["atm_iv"]
    total_volume = (result["call_volume"] or 0) + (result["put_volume"] or 0) if result["call_volume"] is not None or result["put_volume"] is not None else None
    total_oi = (result["call_open_interest"] or 0) + (result["put_open_interest"] or 0) if result["call_open_interest"] is not None or result["put_open_interest"] is not None else None
    score, activity_status, activity_components = _activity(total_volume, total_oi, len(all_nearest), history_rows)
    result["activity_score"] = score
    result["activity_status"] = activity_status
    result["total_volume"] = total_volume
    result["total_open_interest"] = total_oi
    iv_rows = [row for row in all_nearest if row.get("iv") is not None]
    observed_rows = [row for row in all_nearest if any(row.get(key) is not None for key in ("volume", "open_interest", "iv"))]
    volume_coverage = sum(row.get("volume") is not None for row in all_nearest) / len(all_nearest) if all_nearest else 0.0
    oi_coverage = sum(row.get("open_interest") is not None for row in all_nearest) / len(all_nearest) if all_nearest else 0.0
    iv_coverage = len(iv_rows) / len(all_nearest) if all_nearest else 0.0
    # Coverage measures metric availability rather than merely row count:
    # an IV-only chain must not look complete when volume/OI are absent.
    result["coverage"] = round((volume_coverage + oi_coverage + iv_coverage) / 3, 4)
    result["quality_score"] = round(min(1.0, 0.55 * result["coverage"] + 0.25 * (len(observed_rows) / len(all_nearest) if all_nearest else 0) + 0.20 * min(1.0, len(all_nearest) / 20)), 4)
    if not iv_rows:
        result["warnings"].append("no_valid_iv")
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
    call_bias = ((result["call_volume"] or 0) - (result["put_volume"] or 0)) / total_volume if total_volume else 0
    oi_bias = ((result["call_open_interest"] or 0) - (result["put_open_interest"] or 0)) / total_oi if total_oi else 0
    skew = result["downside_skew"]
    if call_bias > .2 and oi_bias > 0:
        bias = "bullish_leaning"
    elif call_bias < -.2 and skew is not None and skew > .03:
        bias = "hedging"
    elif call_bias < -.2 or (skew is not None and skew > .08):
        bias = "bearish_leaning"
    elif abs(call_bias) < .1:
        bias = "neutral"
    else:
        bias = "mixed"
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["skew_method"] = "moneyness_proxy"
    result["metrics_json"] = {
        "total_volume": total_volume,
        "total_open_interest": total_oi,
        "call_atm_iv": call_atm,
        "put_atm_iv": put_atm,
        "skew_method": "moneyness_proxy",
        "activity_components": activity_components,
        "options_bias": bias,
        "bias_components": {"volume": call_bias, "open_interest": oi_bias, "downside_skew": skew},
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
    result["options_bias"] = bias
    return _safe(result)


analyze_options = compute_options_analytics
calculate_options_analytics = compute_options_analytics

__all__ = ["analyze_options", "calculate_options_analytics", "compute_options_analytics", "filter_contracts"]
