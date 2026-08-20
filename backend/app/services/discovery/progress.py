"""Observability for the Pi Agent research funnel.

The sidecar reports lightweight funnel events (never raw chain-of-thought)
through the internal agent gateway; they are persisted per run and folded into
``StockDiscoveryRun.funnel_stats`` so the polling frontend can render research
progress without exposing model reasoning.
"""

from __future__ import annotations

import logging
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
