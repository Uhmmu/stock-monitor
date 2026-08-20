"""Observability for the Pi Agent research funnel.

The sidecar reports lightweight funnel events (never raw chain-of-thought)
through the internal agent gateway; they are persisted per run and folded into
``StockDiscoveryRun.funnel_stats`` so the polling frontend can render research
progress without exposing model reasoning.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StockDiscoveryAgentEvent, StockDiscoveryRun

logger = logging.getLogger(__name__)

# Ordered funnel milestones the frontend renders as a progress strip.
FUNNEL_STAGES: dict[str, str] = {
    "research_started": "planning",
    "portfolio_loaded": "planning",
    "theme_discovered": "discovering",
    "candidate_discovered": "discovering",
    "candidate_screened": "internal_verification",
    "candidate_rejected": "internal_verification",
    "candidate_promoted": "external_research",
    "external_search": "external_research",
    "evidence_found": "external_research",
    "bear_case_checked": "counter_evidence",
    "portfolio_fit_checked": "portfolio_fit",
    "finalized": "synthesizing",
}

_STAGE_LABELS: dict[str, str] = {
    "planning": "pi_planning",
    "discovering": "pi_discovering",
    "internal_verification": "pi_internal_verification",
    "external_research": "pi_external_research",
    "counter_evidence": "pi_counter_evidence",
    "portfolio_fit": "pi_portfolio_fit",
    "synthesizing": "pi_synthesizing",
}

_STAGE_ORDER: dict[str, int] = {name: index for index, name in enumerate(_STAGE_LABELS.values())}


def _advance_stage(run: StockDiscoveryRun, funnel_stage: str) -> None:
    mapped = _STAGE_LABELS.get(funnel_stage)
    if mapped is None:
        return
    current = _STAGE_ORDER.get(run.stage, -1)
    if _STAGE_ORDER[mapped] > current:
        run.stage = mapped


def _merge_stats(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current or {})
    for key, value in incoming.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            merged[key] = value
        else:
            base = merged.get(key)
            merged[key] = value + base if isinstance(base, (int, float)) and not isinstance(base, bool) else value
    return merged


def record_agent_event(
    db: Session,
    run: StockDiscoveryRun,
    event_type: str,
    detail: str = "",
    funnel_stats: dict[str, Any] | None = None,
    *,
    stage: str | None = None,
) -> StockDiscoveryAgentEvent:
    event = StockDiscoveryAgentEvent(
        run_id=run.id,
        event_type=event_type,
        detail=(detail or "")[:2000],
    )
    db.add(event)
    if funnel_stats:
        run.funnel_stats = _merge_stats(run.funnel_stats or {}, funnel_stats)
    if stage:
        run.stage = stage[:64]
    else:
        _advance_stage(run, FUNNEL_STAGES.get(event_type, ""))
    db.commit()
    return event


def agent_events_payload(db: Session, run_id: int, limit: int = 200) -> list[dict]:
    rows = db.scalars(select(StockDiscoveryAgentEvent)
        .where(StockDiscoveryAgentEvent.run_id == run_id)
        .order_by(StockDiscoveryAgentEvent.id.desc()).limit(limit)).all()
    return [{"event_type": row.event_type, "detail": row.detail, "created_at": row.created_at.isoformat() if row.created_at else None} for row in reversed(rows)]


# ---------------------------------------------------------------------------
# Hybrid progress / ETA model
#
# progress = max(stage entry weight, funnel-stat refinement, time-based
# progress against a *frozen* historical duration estimate). Stage and funnel
# counters only move forward (see record_agent_event), and the duration
# estimate is restricted to runs requested before this one, so every
# component is monotonic and the reported percentage never visibly regresses.
# ETA may still rise or fall freely. While running the percentage is capped
# below 100 so long final-synthesis phases render as "finalizing" instead of
# a fake 99%.
# ---------------------------------------------------------------------------

STAGE_BASE_PROGRESS: dict[str, int] = {
    # Pi research funnel (sidecar-driven stages)
    "pi_planning": 5,
    "pi_discovering": 18,
    "pi_internal_verification": 38,
    "pi_external_research": 58,
    "pi_counter_evidence": 74,
    "pi_portfolio_fit": 84,
    "pi_synthesizing": 90,
    # pipeline engines
    "preparing_portfolio": 3,
    "preparing_local_data": 6,
    "budget_check": 8,
    "searching_market": 12,
    "analyzing_with_local_ai": 30,
    "running_finance_agent": 20,
    "running_exa_finance_agent": 20,
    # shared post-processing after the engine returns
    "normalizing_candidates": 92,
    "local_verification": 95,
    "applying_filters": 97,
    "retrying": 3,
    "completed": 100,
}

_DEFAULT_EXPECTED_SECONDS: float = 240.0
DEFAULT_EXPECTED_DURATION_SECONDS: dict[str, float] = {
    "pi_agent": 420.0,
    "agent_finance": 150.0,
    "exa_finance": 300.0,
    "search_local": 180.0,
}

RUNNING_PROGRESS_CAP = 95
PENDING_PROGRESS = 1
_MIN_SAMPLE_SECONDS = 5.0
_MAX_SAMPLE_SECONDS = 7200.0


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _recent_durations(db: Session, *, user_id: int | None, discovery_mode: str,
                      before: datetime | None, limit: int = 8) -> list[float]:
    filters = [
        StockDiscoveryRun.discovery_mode == discovery_mode,
        StockDiscoveryRun.status.in_(("completed", "completed_with_warnings")),
        StockDiscoveryRun.started_at.is_not(None),
        StockDiscoveryRun.completed_at.is_not(None),
    ]
    if user_id is not None:
        filters.append(StockDiscoveryRun.user_id == user_id)
    if before is not None:
        filters.append(StockDiscoveryRun.requested_at <= before)
    rows = db.execute(
        select(StockDiscoveryRun.started_at, StockDiscoveryRun.completed_at)
        .where(*filters).order_by(StockDiscoveryRun.id.desc()).limit(limit)
    ).all()
    durations: list[float] = []
    for started, completed in rows:
        if started is None or completed is None:
            continue
        seconds = (_as_utc(completed) - _as_utc(started)).total_seconds()
        if _MIN_SAMPLE_SECONDS <= seconds <= _MAX_SAMPLE_SECONDS:
            durations.append(seconds)
    return durations


def estimate_duration_seconds(
    db: Session, *, user_id: int, discovery_mode: str, before: datetime | None = None,
) -> float:
    """Median duration of recent successful runs: user history first, then
    global history for the same engine, then the per-engine default."""
    user_durations = _recent_durations(db, user_id=user_id, discovery_mode=discovery_mode, before=before)
    if len(user_durations) >= 2:
        return _median(user_durations)
    global_durations = _recent_durations(db, user_id=None, discovery_mode=discovery_mode, before=before)
    if len(global_durations) >= 2:
        return _median(global_durations)
    return DEFAULT_EXPECTED_DURATION_SECONDS.get(discovery_mode, _DEFAULT_EXPECTED_SECONDS)


def _funnel_refinement(stage: str | None, stats: dict[str, Any]) -> float | None:
    """Within-stage progress for the internal screening stage: screened
    candidates over the discovered pool (prompt targets >= 25)."""
    if stage != "pi_internal_verification":
        return None
    discovered = stats.get("candidates_discovered")
    screened = stats.get("candidates_screened")
    if not isinstance(screened, (int, float)) or screened <= 0:
        return None
    pool = float(discovered) if isinstance(discovered, (int, float)) and discovered > 0 else 25.0
    fraction = min(1.0, screened / max(pool, 25.0))
    base = STAGE_BASE_PROGRESS["pi_internal_verification"]
    next_base = STAGE_BASE_PROGRESS["pi_external_research"]
    return base + (next_base - base) * fraction


def run_progress_payload(db: Session, run: StockDiscoveryRun | None, *, now: datetime | None = None) -> dict:
    """Progress / ETA snapshot for a run row (see the model notes above)."""
    if run is None:
        return {}
    mode = run.discovery_mode or "search_local"
    expected = estimate_duration_seconds(db, user_id=run.user_id, discovery_mode=mode, before=run.requested_at)
    expected_payload = {"expected_duration_seconds": int(round(expected))}
    if run.status == "completed":
        return {"progress": 100, "eta_seconds": 0, **expected_payload}
    if run.status in ("failed", "blocked_by_budget"):
        # Terminal without a meaningful percentage; the UI renders the failure
        # state from status instead.
        return {"progress": None, "eta_seconds": None, **expected_payload}
    if run.status != "running":
        return {"progress": PENDING_PROGRESS, "eta_seconds": int(round(expected)), **expected_payload}
    now = _as_utc(now) or datetime.now(UTC)
    started = _as_utc(run.started_at) or _as_utc(run.requested_at)
    elapsed = max(0.0, (now - started).total_seconds()) if started else 0.0
    components: list[float] = [PENDING_PROGRESS]
    base = STAGE_BASE_PROGRESS.get(run.stage or "")
    if base is not None:
        components.append(float(min(base, RUNNING_PROGRESS_CAP)))
    funnel = _funnel_refinement(run.stage, run.funnel_stats or {})
    if funnel is not None:
        components.append(min(funnel, RUNNING_PROGRESS_CAP))
    if expected > 0:
        components.append(min(RUNNING_PROGRESS_CAP, 100.0 * elapsed / expected))
    progress = min(RUNNING_PROGRESS_CAP, max(components))
    eta = max(0.0, expected - elapsed)
    return {"progress": int(round(progress)), "eta_seconds": int(round(eta)), **expected_payload}
