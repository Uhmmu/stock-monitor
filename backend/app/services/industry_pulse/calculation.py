"""Pure deterministic indicators and composite rules for Industry Pulse."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import statistics
from typing import Any, Iterable


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rows(rows: Iterable[Any], as_of: date | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows or []:
        if hasattr(row, "date"):
            values = {"date": row.date, "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume}
        else:
            values = dict(row)
        day = values.get("date")
        if isinstance(day, datetime):
            day = day.date()
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day[:10])
            except ValueError:
                continue
        close = _num(values.get("close"))
        if not isinstance(day, date) or close is None or close <= 0:
            continue
        if as_of is not None and day > as_of:
            continue
        values["date"] = day
        values["close"] = close
        values["open"] = _num(values.get("open")) or close
        values["high"] = _num(values.get("high")) or close
        values["low"] = _num(values.get("low")) or close
        volume = _num(values.get("volume"))
        values["volume"] = int(volume) if volume is not None and volume >= 0 else None
        result.append(values)
    result.sort(key=lambda item: item["date"])
    return result


def _change(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods or closes[-1 - periods] <= 0:
        return None
    return (closes[-1] / closes[-1 - periods] - 1.0) * 100.0


def sma(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    value = sum(values[:window]) / window
    alpha = 2.0 / (window + 1)
    for item in values[window:]:
        value = alpha * item + (1 - alpha) * value
    return value


def rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-window - 1 :], values[-window:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    if average_loss == 0:
        return 100.0 if average_gain else 50.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def atr(rows: list[dict[str, Any]], window: int = 14) -> float | None:
    if len(rows) <= window:
        return None
    true_ranges: list[float] = []
    for previous, current in zip(rows[-window - 1 :], rows[-window:]):
        high = float(current["high"])
        low = float(current["low"])
        previous_close = float(previous["close"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(true_ranges) / window


def realized_volatility(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    returns = [math.log(current / previous) for previous, current in zip(values[-window - 1 :], values[-window:]) if previous > 0 and current > 0]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(252) * 100.0


def relative_volume(rows: list[dict[str, Any]], window: int = 20) -> dict[str, float | None]:
    volumes = [float(row["volume"]) for row in rows if row.get("volume") is not None and float(row["volume"]) >= 0]
    if len(volumes) <= window:
        return {"relative_volume": None, "volume_z": None, "volume_percentile": None}
    current = volumes[-1]
    baseline = volumes[-window - 1 : -1]
    average = sum(baseline) / len(baseline)
    deviation = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0
    percentile = sum(value <= current for value in baseline) / len(baseline) * 100.0
    return {
        "relative_volume": current / average if average > 0 else None,
        "volume_z": (current - average) / deviation if deviation > 0 else (0.0 if current == average else None),
        "volume_percentile": percentile,
    }


def relative_strength(values: list[float], benchmark: list[float] | None, periods: tuple[int, ...] = (5, 20, 60, 120, 252)) -> dict[str, float | None | bool]:
    if not benchmark:
        return {**{f"rs_{period}d": None for period in periods}, "rs_ratio": None, "rs_ratio_ma20": None, "rs_ratio_slope": None, "rs_breakout_20d": False, "rs_breakout_60d": False, "rs_breakout_120d": False}
    length = min(len(values), len(benchmark))
    values = values[-length:]
    benchmark = benchmark[-length:]
    ratio = [own / base for own, base in zip(values, benchmark) if own > 0 and base > 0]
    result: dict[str, float | None] = {}
    for period in periods:
        result[f"rs_{period}d"] = _change(ratio, period) if _change(ratio, period) is not None else None
    result["rs_ratio"] = ratio[-1] if ratio else None
    result["rs_ratio_ma20"] = sma(ratio, 20)
    previous_ratio_ma = sma(ratio[:-5], 20) if len(ratio) >= 25 else None
    result["rs_ratio_slope"] = ((result["rs_ratio_ma20"] / previous_ratio_ma) - 1) * 100 if result["rs_ratio_ma20"] and previous_ratio_ma else None
    for window in (20, 60, 120):
        result[f"rs_breakout_{window}d"] = bool(len(ratio) > window and ratio[-1] > max(ratio[-window - 1 : -1]))
    return result


def _score(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def calculate_etf_metrics(rows: Iterable[Any], *, benchmark_rows: Iterable[Any] | None = None, benchmark_name: str = "SPY", as_of: date | None = None) -> dict[str, Any]:
    """Calculate only information available at ``as_of`` (look-ahead safe)."""
    history = _rows(rows, as_of)
    benchmark = _rows(benchmark_rows or (), as_of)
    closes = [float(row["close"]) for row in history]
    benchmark_by_date = {row["date"]: float(row["close"]) for row in benchmark}
    common = [(row["date"], float(row["close"]), benchmark_by_date[row["date"]]) for row in history if row["date"] in benchmark_by_date]
    benchmark_closes = [item[2] for item in common]
    if not history:
        return {"status": "unavailable", "data_quality": 0.0, "coverage": 0.0, "as_of": as_of}
    target_day = as_of or history[-1]["date"]
    stale_sessions = sum(1 for offset in range(1, max(0, (target_day - history[-1]["date"]).days) + 1) if (history[-1]["date"] + timedelta(days=offset)).weekday() < 5)
    freshness = 1.0 if stale_sessions <= 1 else .5 if stale_sessions <= 3 else 0.0
    returns = {str(period): _change(closes, period) for period in (1, 5, 20, 60, 120, 252)}
    moving = {f"ma{period}": sma(closes, period) for period in (20, 50, 200)}
    previous_ma20 = sma(closes[:-5], 20) if len(closes) >= 25 else None
    slope = ((moving["ma20"] / previous_ma20) - 1.0) * 100 if moving["ma20"] and previous_ma20 else None
    atr_value = atr(history, 14)
    volume = relative_volume(history)
    volume60 = relative_volume(history, window=60)
    volumes = [float(row["volume"]) for row in history if row.get("volume") is not None]
    rs = relative_strength([item[1] for item in common], benchmark_closes)
    breakout = {window: bool(len(closes) > window and closes[-1] > max(closes[-window - 1 : -1])) for window in (20, 60, 120)}
    trend_score = _score(returns["60"], -20, 20)
    if moving["ma20"] and moving["ma50"] and moving["ma200"]:
        trend_score = max(0.0, min(100.0, (trend_score or 50.0) * .4 + (100.0 if closes[-1] > moving["ma20"] > moving["ma50"] > moving["ma200"] else 35.0) * .6))
    rs20 = rs.get("rs_20d")
    momentum_score = _score(returns["20"], -15, 15)
    volume_score = _score(volume.get("volume_z"), -2, 3)
    vol20 = realized_volatility(closes, 20)
    vol60 = realized_volatility(closes, 60)
    vol_ratio = vol20 / vol60 if vol20 is not None and vol60 and vol60 > 0 else None
    volatility_state = "unknown"
    if vol_ratio is not None:
        volatility_state = "extreme" if vol_ratio >= 1.8 else "expanding" if vol_ratio >= 1.25 else "contracting" if vol_ratio <= .8 else "normal"
    avg_volume20 = sum(volumes[-20:]) / len(volumes[-20:]) if volumes[-20:] else None
    dollar_volume = closes[-1] * avg_volume20 if avg_volume20 is not None else None
    liquidity_quality = (_score(math.log10(dollar_volume), 6, 8) or 0) / 100 if dollar_volume and dollar_volume > 0 else 0.0
    metrics: dict[str, Any] = {
        "status": "unavailable" if freshness == 0 else "partial" if len(history) < 252 or freshness < 1 else "ready",
        "error_code": "stale_history" if freshness == 0 else None,
        "as_of": history[-1]["date"],
        "stale_sessions": stale_sessions,
        "bars": len(history),
        "coverage": min(1.0, len(history) / 252),
        "data_quality": min(1.0, len(history) / 252) * (1.0 if any(row.get("volume") is not None for row in history) else .75) * freshness,
        "close": closes[-1],
        "returns": returns,
        "return_1d": returns["1"], "return_5d": returns["5"], "return_20d": returns["20"],
        "return_60d": returns["60"], "return_120d": returns["120"], "return_252d": returns["252"],
        "ma": moving,
        "ma20_slope": slope,
        "rsi14": rsi(closes, 14),
        "atr14": atr_value,
        "atr14_pct": atr_value / closes[-1] * 100 if atr_value else None,
        "realized_vol20": vol20,
        "realized_vol60": vol60,
        "avg_volume5": sum(volumes[-5:]) / len(volumes[-5:]) if volumes[-5:] else None,
        "avg_volume20": avg_volume20,
        "dollar_volume": dollar_volume,
        "liquidity_quality": liquidity_quality,
        "distance_high20": (closes[-1] / max(closes[-20:]) - 1) * 100 if len(closes) >= 20 else None,
        "distance_high60": (closes[-1] / max(closes[-60:]) - 1) * 100 if len(closes) >= 60 else None,
        "distance_high252": (closes[-1] / max(closes[-252:]) - 1) * 100 if len(closes) >= 252 else None,
        "breakouts": {f"{window}d": value for window, value in breakout.items()},
        **volume,
        "volume_z60": volume60.get("volume_z"), "volume_percentile60": volume60.get("volume_percentile"),
        **rs,
        "rs_breakout": bool(rs.get("rs_breakout_20d") or rs.get("rs_breakout_60d") or rs.get("rs_breakout_120d")),
        "relative_strength_benchmark": benchmark_name,
        "volatility_state": volatility_state,
        "scores": {
            "trend": trend_score,
            "relative_strength": _score(rs20, -15, 15),
            "volume": volume_score,
            "momentum": momentum_score,
        },
    }
    return metrics


def metrics_vol_high(closes: list[float]) -> bool:
    vol20 = realized_volatility(closes, 20)
    vol60 = realized_volatility(closes, 60)
    return bool(vol20 is not None and vol60 is not None and vol20 > vol60 * 1.35)


def _weighted(values: list[tuple[float, float]]) -> float | None:
    valid = [(value, weight) for value, weight in values if value is not None and weight > 0]
    if not valid:
        return None
    total = sum(weight for _, weight in valid)
    return sum(value * weight for value, weight in valid) / total


def calculate_composite(
    metrics_by_ticker: dict[str, dict[str, Any]],
    mappings: Iterable[dict[str, Any]],
    *,
    benchmark_metrics: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
    exposure_threshold: float = 0.30,
) -> dict[str, Any]:
    """Aggregate ETF metrics with explicit effective-weight accounting."""
    weights = weights or {"trend": .25, "relative_strength": .25, "volume": .15, "momentum": .10, "breadth": .15, "consensus": .10}
    mappings = list(mappings)
    eligible_mappings = [mapping for mapping in mappings if mapping.get("mapping_type", "etf_proxy") == "etf_proxy" and mapping.get("role", "primary") in {"primary", "secondary"} and float(mapping.get("exposure_weight", mapping.get("exposure", 1.0)) or 0) >= exposure_threshold]
    usable: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for mapping in eligible_mappings:
        role = mapping.get("role", "primary")
        exposure = float(mapping.get("exposure_weight", mapping.get("exposure", 1.0)) or 0)
        if role not in {"primary", "secondary"} or exposure < exposure_threshold:
            continue
        ticker = str(mapping.get("ticker", "")).upper()
        metric = metrics_by_ticker.get(ticker)
        if not metric or metric.get("status") == "unavailable":
            continue
        quality = float(metric.get("data_quality", 0) or 0)
        liquidity = float(metric.get("liquidity_quality", mapping.get("liquidity", 1.0)) or 0)
        effective = float(mapping.get("role_weight", 1.0 if role == "primary" else .6)) * float(mapping.get("purity", 1.0) or 0) * exposure * float(mapping.get("confidence", 1.0) or 0) * liquidity * quality
        if effective > 0:
            usable.append((mapping, metric, effective))
    if not usable:
        return {"pulse": None, "status": "unavailable", "coverage_quality": 0.0, "effective_weight": 0.0, "members": []}
    component_values: dict[str, float | None] = {}
    for component in ("trend", "relative_strength", "volume", "momentum"):
        component_values[component] = _weighted([(float(metric.get("scores", {}).get(component)), weight) for _, metric, weight in usable if metric.get("scores", {}).get(component) is not None])
    # ETF breadth and consensus are separate from price direction.  They are
    # explicit and remain neutral when the sample is too small.
    positive = [metric for _, metric, _ in usable if (metric.get("returns", {}).get("20") or 0) > 0]
    breadth = len(positive) / len(usable) * 100.0 if usable else None
    dispersion = [metric.get("returns", {}).get("20") for _, metric, _ in usable if metric.get("returns", {}).get("20") is not None]
    consensus = _score(100 - statistics.pstdev(dispersion), 0, 100) if len(dispersion) > 1 else None
    component_values["breadth"] = breadth
    component_values["consensus"] = consensus
    pulse = _weighted([(value, float(weights.get(component, 0))) for component, value in component_values.items() if value is not None])
    returns = [_num(metric.get("returns", {}).get("20")) for _, metric, _ in usable]
    rs = [_num(metric.get("rs_20d")) for _, metric, _ in usable]
    heat_values: list[float] = []
    risk_values: list[float] = []
    for _, metric, _ in usable:
        heat_parts = [
            _score(metric.get("rsi14"), 50, 80),
            _score(metric.get("distance_high20"), -25, 0),
            _score(metric.get("volume_z"), -1, 3),
            _score(metric.get("returns", {}).get("20"), -10, 20),
        ]
        risk_parts = [
            _score(metric.get("realized_vol20"), 10, 45),
            _score(metric.get("atr14_pct"), 1, 8),
            _score(abs(metric.get("distance_high60") or 0), 0, 30),
            _score(metric.get("volume_z"), 1, 4),
        ]
        if any(part is not None for part in heat_parts):
            heat_values.append(sum(part for part in heat_parts if part is not None) / len([part for part in heat_parts if part is not None]))
        if any(part is not None for part in risk_parts):
            risk_values.append(sum(part for part in risk_parts if part is not None) / len([part for part in risk_parts if part is not None]))
    heat = sum(heat_values) / len(heat_values) if heat_values else None
    risk = sum(risk_values) / len(risk_values) if risk_values else None
    coverage = min(1.0, len(usable) / max(1, len(eligible_mappings))) * min(1.0, sum(weight for _, _, weight in usable) / max(1.0, len(usable)))
    high_purity_count = sum(float(mapping.get("purity", 0) or 0) >= .7 for mapping, _, _ in usable)
    confidence = min(coverage, .95 if high_purity_count >= 2 else .69 if len(usable) == 1 and usable[0][0].get("role", "primary") == "primary" else .45)
    mood = classify_mood(pulse, heat, risk, breadth, consensus)
    return {
        "pulse": pulse,
        "status": "ready" if coverage >= .6 else "partial",
        "coverage_quality": coverage,
        "confidence": confidence,
        "effective_weight": sum(weight for _, _, weight in usable),
        "components": component_values,
        "heat": heat,
        "risk": risk,
        "mood": mood,
        "members": [mapping.get("ticker") for mapping, _, _ in usable],
        "relative_strength": sum(value for value in rs if value is not None) / len([value for value in rs if value is not None]) if any(value is not None for value in rs) else None,
        "benchmark": benchmark_metrics or {},
    }


def classify_mood(pulse: float | None, heat: float | None, risk: float | None, breadth: float | None, consensus: float | None, delta: float | None = None) -> str:
    if pulse is None:
        return "unavailable"
    if risk is not None and risk >= 85 and (pulse < 35 or (breadth is not None and breadth < 25)):
        return "panic"
    if heat is not None and heat >= 85 and risk is not None and risk >= 60:
        return "overheated"
    if pulse >= 75 and heat is not None and heat >= 65 and (breadth is None or breadth >= 55):
        return "strong"
    if pulse >= 70 and heat is not None and heat >= 60 and (breadth is None or breadth >= 50):
        return "leadership"
    if pulse >= 65 and (breadth is None or breadth >= 45):
        return "constructive"
    if heat is not None and heat >= 70 and pulse >= 55:
        return "heating"
    if delta is not None and delta <= -8:
        return "weakening"
    if pulse <= 35 and risk is not None and risk >= 60:
        return "risk-off"
    if pulse <= 45:
        return "cooling"
    if consensus is not None and consensus < 35:
        return "disagreement"
    return "neutral"


def detect_regime(current: dict[str, Any], previous: dict[str, Any] | None = None) -> str:
    pulse = current.get("pulse")
    old = previous.get("pulse") if previous else None
    if pulse is None:
        return "unavailable"
    if current.get("mood") == "panic":
        return "panic"
    if current.get("mood") == "risk-off":
        return "risk_off"
    if (current.get("heat") or 0) >= 80 and pulse >= 70:
        return "overheated"
    if old is not None and pulse - old >= 8:
        return "heating"
    if old is not None and old - pulse >= 8:
        return "cooling"
    if pulse >= 65:
        return "leadership"
    return "neutral"


def calculate_focus(snapshots: Iterable[dict[str, Any]], previous: dict[int, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = [dict(row) for row in snapshots if row.get("pulse") is not None and float(row.get("coverage_quality") or 0) >= .45 and float(row.get("confidence") or 0) >= .4]
    signals: list[dict[str, Any]] = []
    candidates_by_type: dict[str, list[dict[str, Any]]] = {
        "leaders": [row for row in rows if (row.get("pulse") or 0) >= 65],
        "fastest_heating": [row for row in rows if (row.get("change_5d") or 0) >= 5 and (not previous or (row.get("change_5d") or 0) > (previous.get(row.get("node_id"), {}).get("change_5d") or 0))],
        "rs_breakout": [row for row in rows if row.get("metrics_json", {}).get("rs_breakout") or row.get("rs_breakout")],
        "volume_shock": [row for row in rows if abs(row.get("volume_z") or row.get("metrics_json", {}).get("volume_z") or 0) >= 2 and row.get("direction") in {"up", "down"}],
        "overheated": [row for row in rows if (row.get("heat") or 0) >= 80 and (row.get("risk") or 0) >= 60],
        "cooling": [row for row in rows if previous and (row.get("change_5d") or 0) <= -3 and (previous.get(row.get("node_id"), {}).get("pulse") or 0) >= 65],
        "risk_off": [row for row in rows if (row.get("pulse") or 0) <= 40 and (row.get("risk") or 0) >= 65],
        "reversal": [row for row in rows if (previous and (previous.get(row.get("node_id"), {}).get("pulse") or 0) < 40) and (row.get("relative_strength") or 0) > 50 and ((row.get("volume_z") or 0) > 0 or row.get("direction") == "up")],
        "rotation": [row for row in rows if previous and (previous.get(row.get("node_id"), {}).get("pulse") or 0) < 50 <= (row.get("pulse") or 0) and (row.get("relative_strength") or 0) > 50 and (row.get("change_5d") or 0) > 0],
    }
    for signal_type, candidates in candidates_by_type.items():
        key = {"leaders": "pulse", "fastest_heating": "change_5d", "rs_breakout": "relative_strength", "volume_shock": "volume_z", "overheated": "heat", "cooling": "change_5d", "risk_off": "risk", "reversal": "relative_strength", "rotation": "relative_strength"}[signal_type]
        reverse = signal_type not in {"cooling"}
        candidates.sort(key=lambda row: float(row.get(key) or 0), reverse=reverse)
        for rank, row in enumerate(candidates[:5], 1):
            signals.append({"signal_type": signal_type, "node_id": row.get("node_id"), "rank": rank, "score": row.get(key), "payload": row})
    return signals


__all__ = [
    "atr", "calculate_composite", "calculate_etf_metrics", "calculate_focus", "classify_mood",
    "detect_regime", "ema", "realized_volatility", "relative_strength", "relative_volume", "rsi", "sma",
]
