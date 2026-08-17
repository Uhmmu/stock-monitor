"""Offline validation of persisted deterministic Mood snapshots.

Forward outcomes are joined only after states and events have been fixed.  The
module never calls providers and never updates production Mood snapshots.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from bisect import bisect_left
from collections import defaultdict
from datetime import UTC, date, datetime
from statistics import fmean, median, pstdev
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice, MoodSnapshot, MoodValidationResult, MoodValidationRun
from app.services.mood import (
    CALCULATION_VERSION,
    DIVERGENCE_TYPES,
    MOOD_STATES,
    WATCHLIST_STATES,
    MoodSignal,
    aggregate_signals,
    calculate_divergences,
    classify_mood_state,
    classify_watchlist_state,
)


VALIDATION_VERSION = "mood_validation_v1"
ENGINE_VERSION = "deterministic_mood_v1"
HORIZONS = (1, 5, 10, 20, 60)
MIN_SAMPLE = 8
SCOPE_TYPES = ("market", "sector", "ai_chain", "watchlist")
BASELINE_PARAMETERS = {
    "base_weights": {"price": .22, "technical": .15, "breadth": .20, "relative_strength": .13, "options": .12, "news": .12, "volume": .06, "composite": .08},
    "minimum_coverage": .12,
    "divergence_mismatch": {"high": 58, "low": 42},
    "divergence_severity": {"medium": .16, "high": .30},
    "confirmation_sessions": 2,
    "fast_breakdown_score": 25,
    "confidence_formula": "weighted_signal_confidence * agreement",
}
STATE_ORDER = {state: index for index, state in enumerate(MOOD_STATES[:-1])}
SOURCE_PRIORITY = {"fmp": 4, "yahoo": 3, "yfinance": 3, "finnhub": 2}


def parameter_registry() -> dict[str, Any]:
    encoded = json.dumps(BASELINE_PARAMETERS, sort_keys=True, separators=(",", ":"))
    return {"name": "BASELINE", "frozen": True, "parameters": BASELINE_PARAMETERS, "hash": hashlib.sha256(encoded.encode()).hexdigest()}


def _safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position); high = math.ceil(position)
    return ordered[low] if low == high else ordered[low] * (high - position) + ordered[high] * (position - low)


def _bootstrap_median_ci(values: list[float], seed: str, samples: int = 300) -> dict[str, float] | None:
    if len(values) < MIN_SAMPLE:
        return None
    rng = random.Random(hashlib.sha256(seed.encode()).digest())
    medians = [median(rng.choices(values, k=len(values))) for _ in range(samples)]
    return {"low": round(_quantile(medians, .025) or 0, 8), "high": round(_quantile(medians, .975) or 0, 8), "level": .95}


def robust_stats(values: Iterable[float | None], seed: str = "mood") -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    n = len(clean)
    if not clean:
        return {"n": 0, "status": "INSUFFICIENT_SAMPLE"}
    ordered = sorted(clean)
    trim = int(n * .1) if n >= 10 else 0
    trimmed = ordered[trim:n - trim] if trim else ordered
    return {
        "n": n,
        "status": "READY" if n >= MIN_SAMPLE else "INSUFFICIENT_SAMPLE",
        "mean": round(fmean(clean), 8), "trimmed_mean": round(fmean(trimmed), 8),
        "median": round(median(clean), 8), "p25": round(_quantile(clean, .25) or 0, 8), "p75": round(_quantile(clean, .75) or 0, 8),
        "positive_rate": round(sum(value > 0 for value in clean) / n, 6),
        "negative_rate": round(sum(value < 0 for value in clean) / n, 6),
        "median_ci": _bootstrap_median_ci(clean, seed),
    }


def confidence_bucket(value: float | None, *, agreement: bool = False) -> str | None:
    if value is None or not math.isfinite(float(value)):
        return None
    number = max(0.0, min(1.0, float(value)))
    if number < .4:
        return "0.0-0.4"
    lower = math.floor(number * 10) / 10
    if number == 1:
        lower = .9
    lower = max(.4, lower) if not agreement else max(.4, lower)
    return f"{lower:.1f}-{lower + .1:.1f}"


def segment_episodes(rows: Iterable[MoodSnapshot]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row.trading_date, row.id or 0))
    episodes: list[dict[str, Any]] = []
    for row in ordered:
        if not episodes or episodes[-1]["state"] != row.state:
            episodes.append({"state": row.state, "entry": row, "exit": row, "rows": [row]})
        else:
            episodes[-1]["exit"] = row; episodes[-1]["rows"].append(row)
    for index, episode in enumerate(episodes):
        episode["duration"] = len(episode["rows"])
        episode["previous_state"] = episodes[index - 1]["state"] if index else None
        episode["next_state"] = episodes[index + 1]["state"] if index + 1 < len(episodes) else None
    return episodes


def replay_snapshot_states(rows: Iterable[MoodSnapshot], cutoff: date | None = None) -> list[tuple[MoodSnapshot, str]]:
    """Replay stored candidates forward; rows after cutoff are never inspected."""
    ordered = sorted((row for row in rows if cutoff is None or row.trading_date <= cutoff), key=lambda row: (row.trading_date, row.id or 0))
    if not ordered:
        return []
    current = ordered[0].state
    prior_candidate = ordered[0].candidate_state
    replayed = [(ordered[0], current)]
    for row in ordered[1:]:
        candidate = row.candidate_state or "INSUFFICIENT_DATA"
        if candidate == current or candidate == "INSUFFICIENT_DATA" or (candidate == "BREAKDOWN" and row.mood_score is not None and row.mood_score <= 25):
            current = candidate
        elif prior_candidate == candidate:
            current = candidate
        replayed.append((row, current))
        prior_candidate = candidate
    return replayed


def _price_series(rows: Iterable[HistoricalPrice]) -> dict[str, tuple[list[date], list[float]]]:
    chosen: dict[tuple[str, date], HistoricalPrice] = {}
    for row in rows:
        key = (row.symbol.upper(), row.date)
        old = chosen.get(key)
        rank = (SOURCE_PRIORITY.get(row.source.lower(), 0), row.source.lower(), row.id or 0)
        old_rank = (SOURCE_PRIORITY.get(old.source.lower(), 0), old.source.lower(), old.id or 0) if old is not None else (-1, "", -1)
        if old is None or rank > old_rank:
            chosen[key] = row
    grouped: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for (symbol, day), row in chosen.items():
        value = row.adjusted_close if row.adjusted_close is not None else row.close
        if value is not None and float(value) > 0:
            grouped[symbol].append((day, float(value)))
    return {symbol: ([item[0] for item in sorted(values)], [item[1] for item in sorted(values)]) for symbol, values in grouped.items()}


def _symbol(row: MoodSnapshot) -> str | None:
    manifest = row.input_manifest if isinstance(row.input_manifest, dict) else {}
    if row.scope_type == "market":
        return "SPY"
    if row.scope_type == "watchlist":
        return row.scope_key.upper()
    candidates = manifest.get("proxy_symbols") or manifest.get("symbols") or manifest.get("constituent_symbols") or []
    return str(candidates[0]).upper() if candidates else None


def _outcome(series: dict[str, tuple[list[date], list[float]]], symbol: str | None, day: date, horizon: int, benchmark: str = "SPY") -> dict[str, float] | None:
    if not symbol or symbol not in series:
        return None
    days, closes = series[symbol]
    index = bisect_left(days, day)
    if index >= len(days) or days[index] != day or index + horizon >= len(days):
        return None
    window = closes[index:index + horizon + 1]
    base = window[0]
    daily = [window[pos] / window[pos - 1] - 1 for pos in range(1, len(window))]
    peaks: list[float] = []
    running = window[0]
    for value in window:
        running = max(running, value); peaks.append(value / running - 1)
    result = {
        "return": window[-1] / base - 1,
        "realized_volatility": pstdev(daily) * math.sqrt(252) if len(daily) > 1 else 0.0,
        "mae": min(0.0, *(value / base - 1 for value in window[1:])),
        "mfe": max(0.0, *(value / base - 1 for value in window[1:])),
        "max_drawdown": min(peaks),
    }
    if benchmark in series:
        benchmark_result = _outcome(series, benchmark, day, horizon, benchmark="") if symbol != benchmark else None
        if benchmark_result is not None:
            result["excess_return"] = result["return"] - benchmark_result["return"]
    return result


def _coverage(rows: list[MoodSnapshot]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[MoodSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[(row.scope_type, row.scope_key)].append(row)
    scopes = []
    for (scope_type, scope_key), values in sorted(grouped.items()):
        categories: dict[str, int] = defaultdict(int)
        missing: dict[str, int] = defaultdict(int)
        for row in values:
            present = {str(item.get("category")) for item in (row.signals or []) if isinstance(item, dict) and item.get("normalized_score") is not None}
            for category in present:
                categories[category] += 1
            for source in row.missing_sources or []:
                missing[str(source)] += 1
        valid = sum(row.state != "INSUFFICIENT_DATA" for row in values)
        scopes.append({
            "scope_type": scope_type, "scope_key": scope_key, "first_valid_date": min(row.trading_date for row in values),
            "last_valid_date": max(row.trading_date for row in values), "valid_sessions": valid,
            "missing_sessions": len(values) - valid, "total_snapshots": len(values),
            "signal_coverage": {category: round(count / len(values), 4) for category, count in sorted(categories.items())},
            "top_missing_sources": sorted(missing.items(), key=lambda item: item[1], reverse=True)[:5],
        })
    return {"scope_count": len(scopes), "snapshot_count": len(rows), "scopes": _safe(scopes)}


def _result(run_id: int, study_type: str, *, scope_type: str | None = None, scope_key: str | None = None,
            state: str | None = None, transition_from: str | None = None, transition_to: str | None = None,
            divergence_type: str | None = None, bucket: str | None = None, horizon: int | None = None,
            sample_mode: str = "daily", sample_count: int = 0, metrics: dict | None = None,
            confidence_interval: dict | None = None, warnings: list | None = None, event_refs: list | None = None) -> MoodValidationResult:
    identity = _safe({"study": study_type, "scope_type": scope_type, "scope_key": scope_key, "state": state,
                      "from": transition_from, "to": transition_to, "divergence": divergence_type,
                      "bucket": bucket, "horizon": horizon, "mode": sample_mode})
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    quality = "READY" if sample_count >= MIN_SAMPLE else "INSUFFICIENT_SAMPLE"
    warning_values = list(warnings or [])
    if quality != "READY" and "INSUFFICIENT_SAMPLE" not in warning_values:
        warning_values.append("INSUFFICIENT_SAMPLE")
    return MoodValidationResult(
        run_id=run_id, result_key=key, study_type=study_type, scope_type=scope_type, scope_key=scope_key,
        state=state, transition_from=transition_from, transition_to=transition_to, divergence_type=divergence_type,
        bucket=bucket, horizon=horizon, sample_mode=sample_mode, sample_count=sample_count,
        metrics=_safe(metrics or {}), confidence_interval=_safe(confidence_interval or {}), quality=quality,
        warnings=warning_values, event_refs=_safe((event_refs or [])[:100]),
    )


def _persistence(rows: list[MoodSnapshot], index: int, state: str, offsets: tuple[int, ...] = (1, 3, 5, 10)) -> dict[str, bool | None]:
    return {f"{offset}d": rows[index + offset].state == state if index + offset < len(rows) else None for offset in offsets}


def _outcome_metrics(samples: list[dict[str, Any]], seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = {name: robust_stats((sample.get(name) for sample in samples), f"{seed}:{name}") for name in ("return", "excess_return", "realized_volatility", "mae", "mfe", "max_drawdown")}
    ci = metrics.get("return", {}).get("median_ci") or {}
    return metrics, {"median_forward_return": ci}


def _study(rows: list[MoodSnapshot], prices: dict[str, tuple[list[date], list[float]]], horizons: tuple[int, ...], run_id: int) -> tuple[list[MoodValidationResult], list[str]]:
    results: list[MoodValidationResult] = []
    warnings: list[str] = ["OBSERVATIONAL_ONLY", "MULTIPLE_COMPARISONS", "OVERLAPPING_DAILY_WINDOWS"]
    by_scope: dict[tuple[str, str], list[MoodSnapshot]] = defaultdict(list)
    for row in rows:
        by_scope[(row.scope_type, row.scope_key)].append(row)
    for values in by_scope.values():
        values.sort(key=lambda row: (row.trading_date, row.id or 0))

    for scope_type in SCOPE_TYPES:
        audits = [(row, expected) for key, values in by_scope.items() if key[0] == scope_type for row, expected in replay_snapshot_states(values)]
        if audits:
            mismatches = [{"snapshot_id": row.id, "scope_key": row.scope_key, "date": row.trading_date, "stored": row.state, "replayed": expected}
                          for row, expected in audits if row.state != expected]
            results.append(_result(run_id, "replay_audit", scope_type=scope_type, sample_mode="chronological", sample_count=len(audits),
                                   metrics={"state_match_rate": 1 - len(mismatches) / len(audits), "mismatch_count": len(mismatches)},
                                   warnings=["CALIBRATION_WARNING:REPLAY_MISMATCH"] if mismatches else [], event_refs=mismatches))

    # Coverage and state occupancy/duration.
    for scope_type in SCOPE_TYPES:
        scope_rows = [row for row in rows if row.scope_type == scope_type]
        if not scope_rows:
            continue
        episodes = [episode for key, values in by_scope.items() if key[0] == scope_type for episode in segment_episodes(values)]
        state_counts: dict[str, int] = defaultdict(int)
        for row in scope_rows:
            state_counts[row.state] += 1
        applicable_states = WATCHLIST_STATES if scope_type == "watchlist" else MOOD_STATES
        for state in applicable_states:
            count = state_counts.get(state, 0)
            matching = [episode for episode in episodes if episode["state"] == state]
            durations = [episode["duration"] for episode in matching]
            rapid1 = sum(episode["next_state"] == episode["previous_state"] and episode["duration"] <= 1 for episode in matching)
            rapid3 = sum(episode["next_state"] == episode["previous_state"] and episode["duration"] <= 3 for episode in matching)
            refs = [{"snapshot_id": episode["entry"].id, "scope_key": episode["entry"].scope_key, "entry_date": episode["entry"].trading_date,
                     "exit_date": episode["exit"].trading_date, "previous_state": episode["previous_state"], "next_state": episode["next_state"]} for episode in matching]
            metrics = {"count": count, "percentage": round(count / len(scope_rows), 6), "episode_count": len(matching),
                       "median_duration": median(durations) if durations else None, "mean_duration": fmean(durations) if durations else None,
                       "max_duration": max(durations, default=None), "one_day_reversal_rate": rapid1 / len(matching) if matching else None,
                       "three_day_reversal_rate": rapid3 / len(matching) if matching else None}
            state_warnings = ["CALIBRATION_WARNING:STATE_DOMINANCE"] if count / len(scope_rows) > .7 else []
            if len(matching) <= 2: state_warnings.append("CALIBRATION_WARNING:RARE_STATE")
            results.append(_result(run_id, "state_occupancy", scope_type=scope_type, state=state, sample_mode="daily", sample_count=count, metrics=metrics, warnings=state_warnings, event_refs=refs))

        transition_count = sum(max(0, len(segment_episodes(values)) - 1) for key, values in by_scope.items() if key[0] == scope_type)
        short_episodes = sum(episode["duration"] == 1 for episode in episodes)
        results.append(_result(run_id, "state_churn", scope_type=scope_type, sample_count=len(scope_rows), metrics={
            "transition_count": transition_count, "transition_rate": transition_count / max(1, len(scope_rows) - len([key for key in by_scope if key[0] == scope_type])),
            "one_day_episode_rate": short_episodes / len(episodes) if episodes else None,
        }, warnings=["CALIBRATION_WARNING:EXCESSIVE_CHURN"] if episodes and short_episodes / len(episodes) > .3 else []))

        # Daily and entry forward outcomes remain distinct.
        for mode in ("daily", "episode_entry"):
            observations = scope_rows if mode == "daily" else [episode["entry"] for episode in episodes]
            for state in sorted({row.state for row in observations}):
                state_rows = [row for row in observations if row.state == state]
                for horizon in horizons:
                    samples = [] ; refs = []
                    for row in state_rows:
                        outcome = _outcome(prices, _symbol(row), row.trading_date, horizon)
                        if outcome is not None:
                            samples.append(outcome); refs.append({"snapshot_id": row.id, "scope_key": row.scope_key, "date": row.trading_date})
                    metrics, ci = _outcome_metrics(samples, f"state:{scope_type}:{state}:{mode}:{horizon}")
                    results.append(_result(run_id, "state_outcome", scope_type=scope_type, state=state, horizon=horizon, sample_mode=mode,
                                           sample_count=len(samples), metrics=metrics, confidence_interval=ci,
                                           warnings=["OVERLAPPING_WINDOWS"] if mode == "daily" and horizon > 1 else [], event_refs=refs))

    # Confirmed final-state transitions, persistence, reversal and outcome.
    transitions: dict[tuple[str, str, str], list[tuple[list[MoodSnapshot], int]]] = defaultdict(list)
    for (scope_type, _), values in by_scope.items():
        for index in range(1, len(values)):
            if values[index].state != values[index - 1].state:
                transitions[(scope_type, values[index - 1].state, values[index].state)].append((values, index))
    for (scope_type, old, new), events in sorted(transitions.items()):
        persistence = [_persistence(values, index, new) for values, index in events]
        metrics = {"count": len(events)}
        for offset in (1, 3, 5, 10):
            valid = [item[f"{offset}d"] for item in persistence if item[f"{offset}d"] is not None]
            metrics[f"persistence_{offset}d"] = sum(valid) / len(valid) if valid else None
        reversed_events = [any(row.state == old for row in values[index + 1:index + 4]) for values, index in events]
        metrics["rapid_reversal_rate"] = sum(reversed_events) / len(reversed_events) if reversed_events else None
        refs = [{"snapshot_id": values[index].id, "scope_key": values[index].scope_key, "date": values[index].trading_date} for values, index in events]
        results.append(_result(run_id, "transition", scope_type=scope_type, transition_from=old, transition_to=new,
                               sample_mode="transition", sample_count=len(events), metrics=metrics, event_refs=refs))
        for horizon in horizons:
            samples = [outcome for values, index in events if (outcome := _outcome(prices, _symbol(values[index]), values[index].trading_date, horizon)) is not None]
            outcome_metrics, ci = _outcome_metrics(samples, f"transition:{scope_type}:{old}:{new}:{horizon}")
            results.append(_result(run_id, "transition_outcome", scope_type=scope_type, transition_from=old, transition_to=new,
                                   horizon=horizon, sample_mode="transition", sample_count=len(samples), metrics=outcome_metrics,
                                   confidence_interval=ci, event_refs=refs))

    # Divergence onset episodes; continuous active days count once.
    divergence_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    severity_rank = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    for (scope_type, _), values in by_scope.items():
        for divergence_type in DIVERGENCE_TYPES:
            active: dict[str, Any] | None = None
            for index, row in enumerate(values):
                item = next((item for item in (row.divergences or []) if item.get("type") == divergence_type), {})
                if item.get("active") and not item.get("resolved"):
                    if active is None:
                        active = {"row": row, "values": values, "index": index, "duration": 0, "severity": "LOW", "resolved": False}
                    active["duration"] += 1
                    if severity_rank.get(str(item.get("severity")), 0) > severity_rank.get(active["severity"], 0): active["severity"] = str(item.get("severity"))
                elif active is not None:
                    active["resolved"] = bool(item.get("resolved")); divergence_groups[(scope_type, divergence_type, active["severity"])].append(active); active = None
            if active is not None:
                divergence_groups[(scope_type, divergence_type, active["severity"])].append(active)
    for (scope_type, divergence_type, severity), episodes in sorted(divergence_groups.items()):
        durations = [episode["duration"] for episode in episodes]
        deterioration = []
        for episode in episodes:
            before = STATE_ORDER.get(episode["row"].state)
            later = [STATE_ORDER.get(row.state) for row in episode["values"][episode["index"] + 1:episode["index"] + 6] if STATE_ORDER.get(row.state) is not None]
            deterioration.append(bool(later and before is not None and max(later) > before))
        metrics = {"episode_count": len(episodes), "mean_duration": fmean(durations), "median_duration": median(durations), "max_duration": max(durations),
                   "resolution_rate": sum(episode["resolved"] for episode in episodes) / len(episodes),
                   "state_deterioration_rate_5d": sum(deterioration) / len(deterioration) if deterioration else None}
        refs = [{"snapshot_id": episode["row"].id, "scope_key": episode["row"].scope_key, "date": episode["row"].trading_date,
                 "duration": episode["duration"], "state": episode["row"].state} for episode in episodes]
        results.append(_result(run_id, "divergence", scope_type=scope_type, divergence_type=divergence_type, bucket=severity,
                               sample_mode="onset", sample_count=len(episodes), metrics=metrics, event_refs=refs))
        for duration_bucket, selected in (("1", [e for e in episodes if e["duration"] == 1]), ("2-3", [e for e in episodes if 2 <= e["duration"] <= 3]),
                                          ("4-5", [e for e in episodes if 4 <= e["duration"] <= 5]), ("6+", [e for e in episodes if e["duration"] > 5])):
            if selected:
                results.append(_result(run_id, "divergence_duration", scope_type=scope_type, divergence_type=divergence_type, bucket=f"{severity}:{duration_bucket}",
                                       sample_mode="onset", sample_count=len(selected), metrics={"episode_count": len(selected), "resolution_rate": sum(e["resolved"] for e in selected) / len(selected)},
                                       event_refs=[{"snapshot_id": e["row"].id, "scope_key": e["row"].scope_key, "date": e["row"].trading_date} for e in selected]))

    # Divergence/state and active-count combinations are kept event based.
    combo_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    count_groups: dict[tuple[str, str], list[MoodSnapshot]] = defaultdict(list)
    for (scope_type, _), values in by_scope.items():
        for row in values:
            active = [item for item in row.divergences or [] if item.get("active") and not item.get("resolved")]
            count_bucket = "0" if not active else "1" if len(active) == 1 else "2" if len(active) == 2 else "3+"
            count_groups[(scope_type, count_bucket)].append(row)
            for item in active:
                if item.get("onset"):
                    combo_groups[(scope_type, row.state, str(item.get("type")))].append({"row": row, "item": item})
    for (scope_type, state, divergence_type), samples in sorted(combo_groups.items()):
        results.append(_result(run_id, "divergence_state", scope_type=scope_type, state=state, divergence_type=divergence_type,
                               sample_mode="onset", sample_count=len(samples), metrics={"episode_count": len(samples)},
                               event_refs=[{"snapshot_id": item["row"].id, "scope_key": item["row"].scope_key, "date": item["row"].trading_date} for item in samples]))
    for (scope_type, bucket), samples in sorted(count_groups.items()):
        results.append(_result(run_id, "divergence_count", scope_type=scope_type, bucket=bucket, sample_count=len(samples),
                               metrics={"mean_confidence": fmean(row.confidence for row in samples if row.confidence is not None) if any(row.confidence is not None for row in samples) else None}))

    # Reliability calibration: confidence, agreement, data quality and coverage.
    for dimension in ("confidence", "agreement", "quality", "coverage"):
        grouped: dict[tuple[str, str], list[tuple[list[MoodSnapshot], int]]] = defaultdict(list)
        for (scope_type, _), values in by_scope.items():
            for index, row in enumerate(values):
                raw = row.agreement_score if dimension == "agreement" else getattr(row, dimension)
                bucket = confidence_bucket(raw, agreement=dimension == "agreement") if dimension in {"confidence", "agreement"} else ("HIGH" if raw is not None and raw >= .75 else "MEDIUM" if raw is not None and raw >= .5 else "LOW" if raw is not None else None)
                if bucket: grouped[(scope_type, bucket)].append((values, index))
        for (scope_type, bucket), samples in sorted(grouped.items()):
            metrics: dict[str, Any] = {}
            for offset in (1, 3, 5):
                flags = [values[index + offset].state == values[index].state for values, index in samples if index + offset < len(values)]
                metrics[f"persistence_{offset}d"] = sum(flags) / len(flags) if flags else None
            reversals = [values[index + 1].state != values[index].state for values, index in samples if index + 1 < len(values)]
            metrics["rapid_reversal_rate"] = sum(reversals) / len(reversals) if reversals else None
            metrics["mean_agreement"] = fmean(row.agreement_score for values, index in samples if (row := values[index]).agreement_score is not None) if any(values[index].agreement_score is not None for values, index in samples) else None
            metrics["mean_coverage"] = fmean(row.coverage for values, index in samples if (row := values[index]).coverage is not None) if any(values[index].coverage is not None for values, index in samples) else None
            metrics["mean_active_divergences"] = fmean(sum(bool(item.get("active")) for item in values[index].divergences or []) for values, index in samples)
            metrics["candidate_rejection_rate"] = sum(values[index].candidate_state != values[index].state for values, index in samples) / len(samples)
            results.append(_result(run_id, f"{dimension}_calibration", scope_type=scope_type, bucket=bucket, sample_mode="daily",
                                   sample_count=len(samples), metrics=metrics,
                                   event_refs=[{"snapshot_id": values[index].id, "scope_key": values[index].scope_key, "date": values[index].trading_date} for values, index in samples]))

    for dimension in ("confidence", "agreement"):
        for scope_type in SCOPE_TYPES:
            buckets = sorted((row for row in results if row.study_type == f"{dimension}_calibration" and row.scope_type == scope_type and row.sample_count >= MIN_SAMPLE), key=lambda row: row.bucket or "")
            if len(buckets) < 2: continue
            low, high = buckets[0], buckets[-1]
            low_value = (low.metrics or {}).get("persistence_3d"); high_value = (high.metrics or {}).get("persistence_3d")
            separation = high_value - low_value if low_value is not None and high_value is not None else None
            results.append(_result(run_id, "calibration_value", scope_type=scope_type, bucket=dimension.upper(),
                                   sample_count=min(low.sample_count, high.sample_count), metrics={"low_bucket": low.bucket, "high_bucket": high.bucket,
                                   "persistence_3d_difference": separation}, warnings=["LOW_CALIBRATION_VALUE"] if separation is not None and abs(separation) < .05 else []))

    # Evidence contribution and evidence-mode reliability.
    contribution: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    proxy_groups: dict[tuple[str, str], list[tuple[list[MoodSnapshot], int]]] = defaultdict(list)
    for (scope_type, _), values in by_scope.items():
        for index, row in enumerate(values):
            for group in (row.evidence or {}).values() if isinstance(row.evidence, dict) else []:
                if isinstance(group, list):
                    for item in group:
                        if isinstance(item, dict) and item.get("category") and item.get("weight") is not None:
                            contribution[(scope_type, row.state, str(item["category"]))].append(float(item["weight"]))
            evidence_type = str((row.input_manifest or {}).get("evidence_type") or "UNKNOWN")
            proxy_groups[(scope_type, evidence_type)].append((values, index))
    for (scope_type, state, category), weights in sorted(contribution.items()):
        results.append(_result(run_id, "evidence_contribution", scope_type=scope_type, state=state, bucket=category,
                               sample_count=len(weights), metrics={"mean_effective_weight": fmean(weights), "appearance_count": len(weights)}))
    for (scope_type, evidence_type), samples in sorted(proxy_groups.items()):
        flags = [values[index + 3].state == values[index].state for values, index in samples if index + 3 < len(values)]
        results.append(_result(run_id, "evidence_mode", scope_type=scope_type, bucket=evidence_type, sample_count=len(samples),
                               metrics={"persistence_3d": sum(flags) / len(flags) if flags else None}))

    for scope_type in SCOPE_TYPES:
        category_totals: dict[str, float] = defaultdict(float)
        for (kind, _state, category), weights in contribution.items():
            if kind == scope_type: category_totals[category] += sum(weights)
        total = sum(category_totals.values())
        if total:
            dominant, weight = max(category_totals.items(), key=lambda item: item[1])
            share = weight / total
            results.append(_result(run_id, "weight_dominance", scope_type=scope_type, bucket=dominant,
                                   sample_count=sum(1 for row in rows if row.scope_type == scope_type),
                                   metrics={"dominant_category": dominant, "effective_weight_share": share, "category_shares": {key: value / total for key, value in category_totals.items()}},
                                   warnings=["CALIBRATION_WARNING:SIGNAL_DOMINANCE"] if share > .75 else []))

    # Category ablations use saved as-of signals and compare candidate states only.
    for category in ("news", "options", "breadth", "relative_strength"):
        for scope_type in SCOPE_TYPES:
            candidates = [row for row in rows if row.scope_type == scope_type and row.signals]
            comparisons = []
            divergence_delta = []
            for row in candidates:
                try:
                    signals = [MoodSignal.model_validate(item) for item in row.signals if isinstance(item, dict) and item.get("category") != category]
                    summary = aggregate_signals(signals)
                    candidate = classify_watchlist_state(summary) if scope_type == "watchlist" else classify_mood_state(summary)
                    comparisons.append(candidate == row.candidate_state)
                    divergence_delta.append(sum(item.get("active", False) for item in calculate_divergences(signals, as_of=row.trading_date)) - sum(item.get("active", False) for item in row.divergences or []))
                except Exception:
                    continue
            if comparisons:
                results.append(_result(run_id, "ablation", scope_type=scope_type, bucket=f"NO_{category.upper()}", sample_count=len(comparisons),
                                       metrics={"candidate_state_agreement": sum(comparisons) / len(comparisons), "mean_divergence_count_delta": fmean(divergence_delta)},
                                       warnings=["STATIC_CANDIDATE_COMPARISON"] ))

    # Predefined adjacent-state separation; never scan for the prettiest pair.
    pairs = (("ACCUMULATION", "EXPANSION"), ("EXPANSION", "LEADERSHIP"), ("LEADERSHIP", "CROWDED"),
             ("CROWDED", "DISTRIBUTION"), ("DETERIORATION", "BREAKDOWN"))
    outcome_rows = [row for row in results if row.study_type == "state_outcome" and row.sample_mode == "episode_entry"]
    for scope_type in SCOPE_TYPES:
        for left, right in pairs:
            for horizon in horizons:
                a = next((row for row in outcome_rows if row.scope_type == scope_type and row.state == left and row.horizon == horizon), None)
                b = next((row for row in outcome_rows if row.scope_type == scope_type and row.state == right and row.horizon == horizon), None)
                if not a or not b: continue
                a_stats = (a.metrics or {}).get("return", {}); b_stats = (b.metrics or {}).get("return", {})
                difference = b_stats.get("median") - a_stats.get("median") if a_stats.get("median") is not None and b_stats.get("median") is not None else None
                results.append(_result(run_id, "state_separation", scope_type=scope_type, transition_from=left, transition_to=right,
                                       horizon=horizon, sample_mode="episode_entry", sample_count=min(a.sample_count, b.sample_count),
                                       metrics={"left_n": a.sample_count, "right_n": b.sample_count, "median_return_difference": difference,
                                                "left_distribution": a_stats, "right_distribution": b_stats}))

    # Period robustness by calendar year, without hindsight regime labels.
    year_groups: dict[tuple[str, int], list[MoodSnapshot]] = defaultdict(list)
    for row in rows: year_groups[(row.scope_type, row.trading_date.year)].append(row)
    for (scope_type, year), values in sorted(year_groups.items()):
        counts: dict[str, int] = defaultdict(int)
        for row in values: counts[row.state] += 1
        results.append(_result(run_id, "period_robustness", scope_type=scope_type, bucket=str(year), sample_count=len(values),
                               metrics={"state_occupancy": {state: count / len(values) for state, count in counts.items()}}))

    results.append(_result(run_id, "parameter_audit", sample_count=len(rows), metrics=parameter_registry(), warnings=["FROZEN_BASELINE", "NO_AUTOMATIC_CALIBRATION"]))

    return results, warnings


def create_run(db: Session, user_id: int, *, date_from: date | None = None, date_to: date | None = None,
               scope_filter: Iterable[str] | None = None, horizons: Iterable[int] | None = None) -> MoodValidationRun:
    from app.services.mood_history import history_health_payload

    minimum, maximum = db.execute(select(func.min(MoodSnapshot.trading_date), func.max(MoodSnapshot.trading_date)).where(
        MoodSnapshot.calculation_version == CALCULATION_VERSION,
        MoodSnapshot.snapshot_type == "EOD",
    )).one()
    if minimum is None or maximum is None:
        raise ValueError("No persisted Mood history is available")
    start, end = date_from or minimum, date_to or maximum
    if start > end or start < minimum or end > maximum:
        raise ValueError(f"Validation range must be within {minimum} and {maximum}")
    scopes = sorted(set(scope_filter or SCOPE_TYPES))
    if not scopes or not set(scopes) <= set(SCOPE_TYPES):
        raise ValueError("Invalid scope filter")
    selected_horizons = tuple(sorted(set(int(value) for value in (horizons or HORIZONS))))
    if not selected_horizons or not set(selected_horizons) <= set(HORIZONS):
        raise ValueError("Forward horizons must be one of 1, 5, 10, 20, 60")
    data_cutoff = db.scalar(select(func.max(HistoricalPrice.date))) or end
    history_health = history_health_payload(db)
    history_warnings = ["HISTORY_QUALITY_WARNING"] if history_health.get("health_status") not in {"HEALTHY"} else []
    run = MoodValidationRun(
        created_by_user_id=user_id, status="pending", progress=0, engine_version=ENGINE_VERSION,
        calculation_version=CALCULATION_VERSION, validation_version=VALIDATION_VERSION,
        parameter_set=parameter_registry(), date_from=start, date_to=end, scope_filter=scopes,
        benchmark_config={"primary": "SPY", "policy": "fixed; unavailable outcomes remain missing"},
        forward_horizons=list(selected_horizons), data_cutoff=data_cutoff, coverage={}, warnings=history_warnings,
    )
    db.add(run); db.flush(); return run


def execute_run(db: Session, run_id: int) -> MoodValidationRun:
    run = db.get(MoodValidationRun, run_id)
    if run is None:
        raise ValueError("Validation run not found")
    if run.status == "completed":
        return run
    run.status = "running"; run.started_at = datetime.now(UTC); run.progress = 5; run.error_message = None
    db.execute(delete(MoodValidationResult).where(MoodValidationResult.run_id == run.id)); db.flush()
    try:
        rows = list(db.scalars(select(MoodSnapshot).where(
            MoodSnapshot.calculation_version == run.calculation_version,
            MoodSnapshot.snapshot_type == "EOD",
            MoodSnapshot.trading_date >= run.date_from, MoodSnapshot.trading_date <= run.date_to,
            MoodSnapshot.scope_type.in_(run.scope_filter),
        ).order_by(MoodSnapshot.scope_type, MoodSnapshot.scope_key, MoodSnapshot.trading_date)).all())
        if not rows:
            raise ValueError("No Mood snapshots match this run")
        run.coverage = _coverage(rows); run.progress = 20; db.flush()
        symbols = {"SPY"}
        symbols.update(symbol for row in rows if (symbol := _symbol(row)))
        price_rows = list(db.scalars(select(HistoricalPrice).where(HistoricalPrice.symbol.in_(symbols), HistoricalPrice.date <= run.data_cutoff).order_by(HistoricalPrice.symbol, HistoricalPrice.date)).all())
        results, warnings = _study(rows, _price_series(price_rows), tuple(run.forward_horizons), run.id)
        db.add_all(results)
        run.warnings = list(run.warnings or []) + warnings + [
            "STRICT_REPLAY_USES_PERSISTED_SNAPSHOTS_ONLY",
            "MISSING_HISTORY_IS_NOT_SYNTHESIZED",
            "NEWS_AND_TECHNICAL_POINT_IN_TIME_PROVENANCE_LIMITED",
        ]
        run.status = "completed"; run.progress = 100; run.completed_at = datetime.now(UTC)
        db.flush(); return run
    except Exception as exc:
        run.status = "failed"; run.completed_at = datetime.now(UTC); run.error_message = str(exc)[:2000]
        run.warnings = list(run.warnings or []) + ["VALIDATION_FAILED"]
        db.flush(); raise


def run_payload(run: MoodValidationRun) -> dict[str, Any]:
    return _safe({
        "run_id": run.id, "status": run.status, "progress": run.progress, "created_at": run.created_at,
        "started_at": run.started_at, "completed_at": run.completed_at, "engine_version": run.engine_version,
        "calculation_version": run.calculation_version, "validation_version": run.validation_version,
        "parameter_set": run.parameter_set, "date_from": run.date_from, "date_to": run.date_to,
        "data_cutoff": run.data_cutoff, "scope_filter": run.scope_filter, "benchmark_config": run.benchmark_config,
        "forward_horizons": run.forward_horizons, "coverage": run.coverage, "warnings": run.warnings,
        "error_message": run.error_message,
    })


def result_payload(row: MoodValidationResult) -> dict[str, Any]:
    return _safe({
        "id": row.id, "study_type": row.study_type, "scope_type": row.scope_type, "scope_key": row.scope_key,
        "state": row.state, "transition_from": row.transition_from, "transition_to": row.transition_to,
        "divergence_type": row.divergence_type, "bucket": row.bucket, "horizon": row.horizon,
        "sample_mode": row.sample_mode, "sample_count": row.sample_count, "metrics": row.metrics,
        "confidence_interval": row.confidence_interval, "quality": row.quality, "warnings": row.warnings,
        "event_refs": row.event_refs,
    })


def latest_overview(db: Session, run_id: int | None = None) -> dict[str, Any]:
    run = db.get(MoodValidationRun, run_id) if run_id else db.scalar(select(MoodValidationRun).order_by(MoodValidationRun.created_at.desc(), MoodValidationRun.id.desc()).limit(1))
    if run is None:
        minimum, maximum, count = db.execute(select(func.min(MoodSnapshot.trading_date), func.max(MoodSnapshot.trading_date), func.count(MoodSnapshot.id)).where(
            MoodSnapshot.calculation_version == CALCULATION_VERSION,
            MoodSnapshot.snapshot_type == "EOD",
        )).one()
        return {"status": "unavailable", "engine_version": ENGINE_VERSION, "calculation_version": CALCULATION_VERSION,
                "validation_version": VALIDATION_VERSION, "available_range": _safe({"from": minimum, "to": maximum, "snapshots": count}),
                "parameter_set": parameter_registry(), "warnings": ["RUN_REQUIRED"]}
    studies: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if run.status == "completed":
        for row in db.scalars(select(MoodValidationResult).where(MoodValidationResult.run_id == run.id).order_by(MoodValidationResult.study_type, MoodValidationResult.id)).all():
            studies[row.study_type].append(result_payload(row))
    return {"status": run.status, "run": run_payload(run), "studies": dict(studies), "limitations": [
        "Confidence validates state reliability, not future return probability.",
        "Results are observational and include multiple comparisons.",
        "Missing point-in-time provenance is reported rather than reconstructed with current data.",
    ]}


def snapshot_detail(db: Session, snapshot_id: int) -> dict[str, Any] | None:
    row = db.get(MoodSnapshot, snapshot_id)
    if row is None:
        return None
    return _safe({"snapshot_id": row.id, "scope_type": row.scope_type, "scope_key": row.scope_key, "trading_date": row.trading_date,
                  "state": row.state, "candidate_state": row.candidate_state, "previous_state": row.previous_state,
                  "confidence": row.confidence, "agreement": row.agreement_score, "quality": row.quality, "coverage": row.coverage,
                  "signals": row.signals, "evidence": row.evidence, "divergences": row.divergences, "transition": row.transition,
                  "input_manifest": row.input_manifest, "calculation_version": row.calculation_version})


def validation_study_payload(db: Session, study: str = "overview", scope_type: str | None = None, limit: int = 100) -> dict[str, Any]:
    run = db.scalar(select(MoodValidationRun).where(MoodValidationRun.status == "completed").order_by(MoodValidationRun.completed_at.desc(), MoodValidationRun.id.desc()).limit(1))
    if run is None:
        return {"status": "unavailable", "study": study, "results": [], "warnings": ["NO_COMPLETED_VALIDATION_RUN"]}
    mapping = {
        "overview": ("state_occupancy",), "states": ("state_occupancy", "state_outcome"),
        "transitions": ("transition", "transition_outcome"), "divergences": ("divergence", "divergence_duration"),
        "confidence": ("confidence_calibration",), "agreement": ("agreement_calibration",),
        "evidence": ("evidence_contribution", "evidence_mode"), "ablation": ("ablation",),
    }
    query = select(MoodValidationResult).where(MoodValidationResult.run_id == run.id, MoodValidationResult.study_type.in_(mapping.get(study, (study,))))
    if scope_type: query = query.where(MoodValidationResult.scope_type == scope_type)
    rows = db.scalars(query.order_by(MoodValidationResult.sample_count.desc(), MoodValidationResult.id).limit(max(1, min(limit, 200)))).all()
    return {"status": "ready", "study": study, "run": run_payload(run), "results": [result_payload(row) for row in rows],
            "warnings": ["OBSERVATIONAL_ONLY", "SAMPLE_COUNTS_AND_LIMITATIONS_MUST_BE_REPORTED"]}


__all__ = ["VALIDATION_VERSION", "ENGINE_VERSION", "HORIZONS", "MIN_SAMPLE", "parameter_registry", "robust_stats",
           "confidence_bucket", "segment_episodes", "replay_snapshot_states", "create_run", "execute_run", "run_payload", "result_payload",
           "latest_overview", "snapshot_detail", "validation_study_payload"]
