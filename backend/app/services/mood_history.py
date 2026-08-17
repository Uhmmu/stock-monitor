"""Immutable Daily EOD Mood history built only from persisted inputs."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import fmean, pstdev
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MoodDailyRun, MoodSnapshot
from app.services.market_calendar import expected_latest_market_session, market_sessions
from app.services.mood import (
    CALCULATION_VERSION,
    _latest_prior,
    _persist,
    _safe,
    _scope_payload,
    _scope_specs,
)


logger = logging.getLogger(__name__)

REQUIRED_CATEGORIES = {
    "market": ("price", "breadth"),
    "sector": ("price", "technical", "breadth"),
    "ai_chain": ("composite",),
    "watchlist": ("price", "technical"),
}
FINAL_STATUSES = {"COMPLETED", "PARTIAL", "FAILED"}


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _scope_id(scope_type: str, scope_key: str) -> str:
    return f"{scope_type}:{scope_key}"


def _observed_day(signal: dict[str, Any]) -> date | None:
    candidates = [signal.get("source_as_of")]
    for container in (signal.get("evidence"), signal.get("raw_evidence")):
        if isinstance(container, dict):
            candidates.extend(container.get(key) for key in ("as_of", "trading_date", "data_through", "published_at"))
        elif isinstance(container, list):
            candidates.extend(item.get("trading_date") for item in container if isinstance(item, dict))
    candidates.extend(str(ref)[-10:] for ref in signal.get("evidence_refs") or [])
    days = [parsed for value in candidates if (parsed := _day(value))]
    return max(days) if days else None


def _source_status(signal: dict[str, Any], trading_date: date) -> str:
    status = str(signal.get("status") or "UNAVAILABLE").upper()
    observed = _observed_day(signal)
    if signal.get("normalized_score") is None or status not in {"READY", "PARTIAL", "STALE"}:
        return "MISSING"
    if observed != trading_date or status == "STALE":
        return "STALE"
    return "ACCEPTABLE" if status == "PARTIAL" else "FRESH"


def _readiness(values: dict[str, Any]) -> dict[str, Any]:
    trading_date = _day(values["trading_date"])
    signals = [item for item in values.get("signals") or [] if isinstance(item, dict)]
    required = REQUIRED_CATEGORIES.get(str(values["scope_type"]), ())
    freshness: dict[str, str] = {}
    source_timestamps: dict[str, str | None] = {}
    source_states: dict[str, list[str]] = defaultdict(list)
    for signal in signals:
        category = str(signal.get("category") or "unknown")
        state = _source_status(signal, trading_date)
        prior = freshness.get(category)
        if prior is None or {"MISSING": 0, "STALE": 1, "ACCEPTABLE": 2, "FRESH": 3}[state] > {"MISSING": 0, "STALE": 1, "ACCEPTABLE": 2, "FRESH": 3}[prior]:
            freshness[category] = state
        source = str(signal.get("source") or category)
        source_states[source].append(state)
        observed = _observed_day(signal)
        current = _day(source_timestamps.get(source))
        if observed and (current is None or observed > current):
            source_timestamps[source] = observed.isoformat()
        else:
            source_timestamps.setdefault(source, None)
    source_health = {}
    for source, states in source_states.items():
        present = [state for state in states if state != "MISSING"]
        source_health[source] = (
            "MISSING" if not present else
            "STALE" if all(state == "STALE" for state in present) else
            "ACCEPTABLE" if "MISSING" in states or "STALE" in states or "ACCEPTABLE" in states else
            "FRESH"
        )
    missing = [category for category in required if freshness.get(category) not in {"FRESH", "ACCEPTABLE"}]
    return {
        "ready": not missing,
        "required_inputs": list(required),
        "available_inputs": sorted(category for category, status in freshness.items() if status in {"FRESH", "ACCEPTABLE"}),
        "freshness": freshness,
        "source_health": source_health,
        "source_timestamps": source_timestamps,
        "missing_reason": [f"{category}:{freshness.get(category, 'MISSING')}" for category in missing],
        "calculation_attempted": True,
        "snapshot_generated": False,
        "failure": None,
    }


def _expected(db: Session, scopes: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        {"scope_type": scope_type, "scope_key": scope_key, "node_id": node_id, "scope_id": _scope_id(scope_type, scope_key)}
        for scope_type, scope_key, node_id in _scope_specs(db, scopes)
    ]


def _eod_rows(db: Session, trading_date: date | None = None) -> list[MoodSnapshot]:
    query = select(MoodSnapshot).where(
        MoodSnapshot.calculation_version == CALCULATION_VERSION,
        MoodSnapshot.snapshot_type == "EOD",
    )
    if trading_date is not None:
        query = query.where(MoodSnapshot.trading_date == trading_date)
    return list(db.scalars(query.order_by(MoodSnapshot.trading_date, MoodSnapshot.scope_type, MoodSnapshot.scope_key)).all())


def _daily_summary(rows: Iterable[MoodSnapshot], expected: int, insufficient: int, failed: int) -> dict[str, Any]:
    values = list(rows)
    qualities = {"high": 0, "medium": 0, "low": 0, "insufficient": insufficient}
    source_counts: dict[str, Counter[str]] = defaultdict(Counter)
    states = Counter(row.state for row in values)
    confidences = [float(row.confidence) for row in values if row.confidence is not None]
    agreements = [float(row.agreement_score) for row in values if row.agreement_score is not None]
    divergence_count = 0
    stale_sources: set[str] = set()
    missing_sources: set[str] = set()
    for row in values:
        quality = float(row.quality or 0)
        qualities["high" if quality >= .75 else "medium" if quality >= .45 else "low"] += 1
        stale_sources.update(str(item) for item in row.stale_sources or [])
        missing_sources.update(str(item) for item in row.missing_sources or [])
        divergence_count += sum(bool(item.get("active")) for item in row.divergences or [] if isinstance(item, dict))
        readiness = (row.input_manifest or {}).get("readiness") or {}
        for source, status in (readiness.get("source_health") or {}).items():
            source_counts[str(source)][str(status)] += 1
    source_health = {}
    rank = {"FRESH": 0, "ACCEPTABLE": 1, "STALE": 2, "MISSING": 3}
    for source, counts in source_counts.items():
        worst = max(counts, key=rank.get)
        source_health[source] = {"status": worst, "count": sum(counts.values())}
    coverage = len(values) / expected if expected else 0.0
    denominator = expected or 1
    warnings: list[str] = []
    if len(values) >= 5 and states:
        state, count = states.most_common(1)[0]
        if count / len(values) >= .8:
            warnings.append(f"DISTRIBUTION_WARNING:{state}:{count}/{len(values)}")
    if len(confidences) >= 5 and (sum(value < .3 for value in confidences) / len(confidences) >= .5 or pstdev(confidences) < .01):
        warnings.append("CONFIDENCE_DISTRIBUTION_WARNING")
    health_status = (
        "FAILED" if expected and not values else
        "PARTIAL" if failed or insufficient or coverage < 1 else
        "DEGRADED" if qualities["low"] or stale_sources or missing_sources else
        "HEALTHY"
    )
    return {
        "health_status": health_status,
        "expected": expected,
        "generated": len(values),
        "snapshot_count": len(values),
        "coverage": round(coverage, 4),
        "quality_distribution": qualities,
        "quality_percentages": {key: round(count / denominator, 4) for key, count in qualities.items()},
        "source_health": source_health,
        "stale_sources": sorted(stale_sources),
        "stale_source_count": len(stale_sources),
        "missing_sources": sorted(missing_sources),
        "missing_source_count": len(missing_sources),
        "state_distribution": dict(states),
        "divergence_count": divergence_count,
        "average_confidence": round(fmean(confidences), 4) if confidences else None,
        "average_agreement": round(fmean(agreements), 4) if agreements else None,
        "insufficient": insufficient,
        "failed": failed,
        "warnings": warnings,
    }


def _run_payload(run: MoodDailyRun) -> dict[str, Any]:
    health = run.health or {}
    expected_ids = [item.get("scope_id") if isinstance(item, dict) else str(item) for item in run.expected_scopes or []]
    completed = list(run.completed_scopes or [])
    insufficient = [item.get("scope_id") if isinstance(item, dict) else str(item) for item in run.insufficient_scopes or []]
    failed = [item.get("scope_id") if isinstance(item, dict) else str(item) for item in run.failed_scopes or []]
    return _safe({
        "run_id": run.id,
        "trading_date": run.trading_date,
        "calculation_version": run.calculation_version,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "attempt_count": run.attempt_count,
        "expected": len(expected_ids),
        "generated": len(completed),
        "coverage": health.get("coverage", len(completed) / len(expected_ids) if expected_ids else 0),
        "missing_scopes": sorted(set(expected_ids) - set(completed) - set(insufficient) - set(failed)),
        "completed_scopes": completed,
        "insufficient_scopes": insufficient,
        "failed_scopes": failed,
        "readiness": run.readiness or {},
        "health": health,
        "warnings": run.warnings or [],
        "error_message": run.error_message,
    })


def run_daily_mood(
    db: Session,
    trading_date: date,
    now: datetime | None = None,
    finalize: bool = False,
    scopes: set[str] | None = None,
    recovery_reason: str | None = None,
) -> dict[str, Any]:
    """Materialize missing EOD scopes; finalized snapshots are never updated."""
    if not market_sessions(trading_date, trading_date):
        raise ValueError(f"{trading_date} is not an XNYS trading session")
    current = now or datetime.now(UTC)
    run = db.scalar(select(MoodDailyRun).where(
        MoodDailyRun.trading_date == trading_date,
        MoodDailyRun.calculation_version == CALCULATION_VERSION,
    ).limit(1))
    if run is not None and run.status == "COMPLETED" and scopes is None:
        return _run_payload(run)
    if run is not None and run.status in {"PARTIAL", "FAILED"} and scopes is None and not finalize:
        return _run_payload(run)
    if run is None:
        run = MoodDailyRun(
            trading_date=trading_date,
            calculation_version=CALCULATION_VERSION,
            status="PENDING",
            expected_scopes=_expected(db),
        )
        db.add(run)
        db.flush()
    expected = list(run.expected_scopes or [])
    requested = set(scopes or [])
    if requested:
        expected_ids = {item["scope_id"] for item in expected}
        unknown = requested - expected_ids
        if unknown:
            raise ValueError(f"Scopes were not expected for this run: {', '.join(sorted(unknown))}")
    existing = {_scope_id(row.scope_type, row.scope_key): row for row in _eod_rows(db, trading_date)}
    completed = set(run.completed_scopes or []) | set(existing)
    readiness = dict(run.readiness or {})
    insufficient = {item["scope_id"]: item for item in run.insufficient_scopes or [] if item.get("scope_id")}
    failed = {item["scope_id"]: item for item in run.failed_scopes or [] if item.get("scope_id")}
    targets = [item for item in expected if item["scope_id"] not in completed and (not requested or item["scope_id"] in requested)]
    run.status = "RUNNING"
    run.attempt_count = int(run.attempt_count or 0) + 1
    run.finished_at = None
    run.error_message = None
    db.flush()
    for spec in targets:
        scope_id = spec["scope_id"]
        try:
            with db.begin_nested():
                previous, _ = _latest_prior(
                    db, spec["scope_type"], spec["scope_key"], trading_date, CALCULATION_VERSION, "EOD",
                )
                values = _scope_payload(
                    db, spec["scope_type"], spec["scope_key"], spec.get("node_id"), trading_date, CALCULATION_VERSION, previous,
                )
                result = _readiness(values)
                readiness[scope_id] = result
                if not result["ready"]:
                    insufficient[scope_id] = {"scope_id": scope_id, "reasons": result["missing_reason"]}
                    failed.pop(scope_id, None)
                    continue
                if not finalize:
                    insufficient.pop(scope_id, None)
                    failed.pop(scope_id, None)
                    continue
                values["snapshot_type"] = "EOD"
                values["input_cutoff"] = current
                values["warnings"] = [
                    f"{source}:{status}" for source, status in result["source_health"].items() if status in {"STALE", "MISSING"}
                ]
                values["input_manifest"] = {
                    **(values.get("input_manifest") or {}),
                    "snapshot_type": "EOD",
                    "input_cutoff": current.isoformat(),
                    "readiness": result,
                }
                _persist(db, values, immutable=True)
                result["snapshot_generated"] = True
                readiness[scope_id] = result
                completed.add(scope_id)
                insufficient.pop(scope_id, None)
                failed.pop(scope_id, None)
        except Exception as exc:
            logger.exception("mood_eod_scope_failed trading_date=%s scope=%s", trading_date, scope_id)
            failed[scope_id] = {"scope_id": scope_id, "error": type(exc).__name__, "message": str(exc)[:500]}
            readiness.setdefault(scope_id, {"calculation_attempted": True, "snapshot_generated": False})["failure"] = type(exc).__name__
    run.completed_scopes = sorted(completed)
    run.insufficient_scopes = list(insufficient.values())
    run.failed_scopes = list(failed.values())
    run.readiness = readiness
    rows = _eod_rows(db, trading_date)
    run.health = _daily_summary(rows, len(expected), len(insufficient), len(failed))
    previous_run = db.scalar(select(MoodDailyRun).where(
        MoodDailyRun.calculation_version == CALCULATION_VERSION,
        MoodDailyRun.trading_date < trading_date,
        MoodDailyRun.status.in_(("COMPLETED", "PARTIAL")),
    ).order_by(MoodDailyRun.trading_date.desc()).limit(1))
    prior_divergences = int((previous_run.health or {}).get("divergence_count", 0)) if previous_run else 0
    if run.health["divergence_count"] >= max(20, prior_divergences * 3) and run.health["divergence_count"] > prior_divergences:
        run.health["warnings"].append("DIVERGENCE_DISTRIBUTION_WARNING")
    expected_ids = {item["scope_id"] for item in expected}
    if finalize and expected_ids and completed >= expected_ids:
        run.status = "COMPLETED"
    elif finalize:
        run.status = "PARTIAL" if completed else "FAILED"
    else:
        run.status = "PENDING"
    if run.status in FINAL_STATUSES:
        run.finished_at = current
        continuity = history_gaps_payload(db, days=60)
        run.health["continuity"] = {
            "status": continuity["status"],
            "gap_count": len(continuity["gaps"]),
            "duplicate_count": len(continuity["duplicates"]),
        }
        if continuity["status"] != "HEALTHY":
            run.health["warnings"].append("MOOD_HISTORY_CONTINUITY_WARNING")
    warnings = list(run.warnings or [])
    if recovery_reason:
        warnings.append(f"MANUAL_RECOVERY:{recovery_reason}")
    warnings.extend(item for item in run.health.get("warnings", []) if item not in warnings)
    run.warnings = list(dict.fromkeys(warnings))
    db.flush()
    logger.info(
        "mood_eod_run trading_date=%s expected=%s generated=%s insufficient=%s failed=%s status=%s",
        trading_date, len(expected), len(completed), len(insufficient), len(failed), run.status,
    )
    return _run_payload(run)


def _session_calendar(db: Session, end: date, days: int) -> list[dict[str, Any]]:
    sessions = market_sessions(end - timedelta(days=max(14, days * 2 + 10)), end)[-days:]
    first_run = db.scalar(select(func.min(MoodDailyRun.trading_date)).where(
        MoodDailyRun.calculation_version == CALCULATION_VERSION,
    ))
    if first_run:
        sessions = [session for session in sessions if session >= first_run]
    runs = {
        run.trading_date: run
        for run in db.scalars(select(MoodDailyRun).where(
            MoodDailyRun.calculation_version == CALCULATION_VERSION,
            MoodDailyRun.trading_date.in_(sessions),
        )).all()
    }
    output = []
    for session in sessions:
        run = runs.get(session)
        status = "MISSING" if run is None else "HEALTHY" if run.status == "COMPLETED" else run.status
        output.append({
            "trading_date": session.isoformat(),
            "status": status,
            "coverage": float((run.health or {}).get("coverage", 0)) if run else 0.0,
        })
    return output


def _maturity(rows: list[MoodSnapshot], end: date) -> dict[str, int]:
    if not rows:
        return {f"matured_{horizon}d_samples": 0 for horizon in (1, 5, 20, 60)}
    sessions = market_sessions(min(row.trading_date for row in rows), end)
    positions = {session: index for index, session in enumerate(sessions)}
    return {
        f"matured_{horizon}d_samples": sum(
            row.trading_date in positions and positions[row.trading_date] + horizon < len(sessions) for row in rows
        )
        for horizon in (1, 5, 20, 60)
    }


def history_health_payload(db: Session, trading_date: date | None = None, days: int = 60) -> dict[str, Any]:
    runs = list(db.scalars(select(MoodDailyRun).where(
        MoodDailyRun.calculation_version == CALCULATION_VERSION,
    ).order_by(MoodDailyRun.trading_date)).all())
    all_rows = _eod_rows(db)
    dates = sorted({row.trading_date for row in all_rows})
    latest_run = next((run for run in reversed(runs) if run.trading_date == trading_date), None) if trading_date else (runs[-1] if runs else None)
    selected_day = trading_date or (latest_run.trading_date if latest_run else dates[-1] if dates else expected_latest_market_session())
    selected_rows = [row for row in all_rows if row.trading_date == selected_day]
    selected_health = _daily_summary(
        selected_rows,
        len(latest_run.expected_scopes or []) if latest_run else len(selected_rows),
        len(latest_run.insufficient_scopes or []) if latest_run else 0,
        len(latest_run.failed_scopes or []) if latest_run else 0,
    )
    calendar = _session_calendar(db, selected_day, max(5, min(days, 3650))) if selected_day and runs else []
    gap_count = sum(item["status"] == "MISSING" for item in calendar)
    health_status = (
        "UNAVAILABLE" if latest_run is None else
        latest_run.status if latest_run.status in {"PARTIAL", "FAILED"} else
        "DEGRADED" if latest_run.status != "COMPLETED" else
        "DEGRADED" if gap_count else
        str((latest_run.health or {}).get("health_status") or "HEALTHY")
    )
    run_payload = _run_payload(latest_run) if latest_run else {
        "trading_date": selected_day,
        "status": None,
        "expected": 0,
        "generated": len(selected_rows),
        "coverage": 0.0,
        "missing_scopes": [],
        "insufficient_scopes": [],
        "failed_scopes": [],
    }
    warnings = list(latest_run.warnings or []) if latest_run else []
    if gap_count:
        warnings.append(f"MISSING_MOOD_SNAPSHOT:{gap_count}")
    complete_days = sum(run.status == "COMPLETED" for run in runs)
    partial_days = sum(run.status == "PARTIAL" for run in runs)
    maturity = _maturity(all_rows, selected_day) if selected_day else {f"matured_{horizon}d_samples": 0 for horizon in (1, 5, 20, 60)}
    return _safe({
        "health_status": health_status,
        "latest_eod": dates[-1] if dates else None,
        "oldest_eod": dates[0] if dates else None,
        "history_days": len(dates),
        "complete_days": complete_days,
        "partial_days": partial_days,
        "today": {
            "trading_date": run_payload.get("trading_date"),
            "status": run_payload.get("status"),
            "expected": run_payload.get("expected", 0),
            "generated": run_payload.get("generated", 0),
            "coverage": run_payload.get("coverage", 0),
            "missing_scopes": run_payload.get("missing_scopes", []),
            "insufficient_scopes": run_payload.get("insufficient_scopes", []),
            "failed_scopes": run_payload.get("failed_scopes", []),
            "stale_sources": selected_health["stale_sources"],
        },
        "quality_distribution": selected_health["quality_distribution"],
        "source_health": selected_health["source_health"],
        "calendar": calendar,
        "maturity": maturity,
        "validation_readiness": {
            "history_days": len(dates),
            "complete_days": complete_days,
            "partial_days": partial_days,
            "eligible_scopes": len({(row.scope_type, row.scope_key) for row in all_rows}),
            "oldest_snapshot": dates[0] if dates else None,
            "latest_snapshot": dates[-1] if dates else None,
            **maturity,
        },
        "warnings": list(dict.fromkeys(warnings + selected_health["warnings"])),
    })


def history_gaps_payload(db: Session, days: int = 60) -> dict[str, Any]:
    end = expected_latest_market_session()
    has_runs = db.scalar(select(MoodDailyRun.id).where(MoodDailyRun.calculation_version == CALCULATION_VERSION).limit(1))
    calendar = _session_calendar(db, end, max(5, min(days, 3650))) if end and has_runs else []
    gaps = [item for item in calendar if item["status"] != "HEALTHY"]
    duplicates = db.execute(select(
        MoodSnapshot.scope_type,
        MoodSnapshot.scope_key,
        MoodSnapshot.trading_date,
        MoodSnapshot.calculation_version,
        func.count(MoodSnapshot.id),
    ).where(MoodSnapshot.snapshot_type == "EOD").group_by(
        MoodSnapshot.scope_type,
        MoodSnapshot.scope_key,
        MoodSnapshot.trading_date,
        MoodSnapshot.calculation_version,
    ).having(func.count(MoodSnapshot.id) > 1)).all()
    return _safe({
        "status": "HEALTHY" if not gaps and not duplicates else "DEGRADED",
        "gaps": gaps,
        "duplicates": [
            {"scope_type": row[0], "scope_key": row[1], "trading_date": row[2], "calculation_version": row[3], "count": row[4]}
            for row in duplicates
        ],
        "calendar": calendar,
    })


def recover_missing_mood(
    db: Session,
    trading_date: date,
    scopes: Iterable[str],
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    requested = {str(item).strip() for item in scopes if str(item).strip()}
    if not requested or not reason.strip():
        raise ValueError("Scopes and recovery reason are required")
    existing = {
        _scope_id(row.scope_type, row.scope_key)
        for row in _eod_rows(db, trading_date)
        if _scope_id(row.scope_type, row.scope_key) in requested
    }
    missing = requested - existing
    if existing:
        return {"status": "REJECTED", "reason": "Requested EOD snapshots already exist", "existing_scopes": sorted(existing)}
    result = run_daily_mood(
        db,
        trading_date,
        now=now,
        finalize=True,
        scopes=missing,
        recovery_reason=reason.strip(),
    )
    return {**result, "status": result["status"], "recovered_scopes": sorted(missing), "skipped_existing_scopes": sorted(existing)}


__all__ = ["history_gaps_payload", "history_health_payload", "recover_missing_mood", "run_daily_mood"]
