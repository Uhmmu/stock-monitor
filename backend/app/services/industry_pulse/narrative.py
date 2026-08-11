"""Optional cached Luna narrative, deliberately isolated from calculations."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IndustryPulseNarrative
from app.services.llm import generate_analysis


def build_narrative_evidence(node: dict[str, Any], snapshot: dict[str, Any]) -> str:
    return json.dumps({"node": node, "snapshot": snapshot}, ensure_ascii=False, sort_keys=True, default=str)


def generate_node_narrative(db: Session, *, node_id: int, trading_date: date, node: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    evidence = build_narrative_evidence(node, snapshot)
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    row = db.scalar(select(IndustryPulseNarrative).where(IndustryPulseNarrative.node_id == node_id, IndustryPulseNarrative.trading_date == trading_date))
    if row and row.status == "completed" and row.input_hash == digest and row.summary:
        return {"status": "completed", "model": row.model, "cached": True}
    if row is None:
        row = IndustryPulseNarrative(node_id=node_id, trading_date=trading_date)
        db.add(row)
    row.input_hash = digest
    settings = get_settings()
    if not settings.industry_pulse_ai_enabled or not settings.openai_api_key:
        row.status = "skipped"
        return {"status": row.status, "model": None}
    try:
        text, model = generate_analysis(f"Industry Pulse: {node.get('name')}", evidence, tier="medium", report_type="industry_pulse")
        row.summary, row.model, row.status, row.error = text, model, "completed", None
        return {"status": row.status, "model": model, "cached": False}
    except Exception as exc:
        row.status, row.error = "failed", str(exc)[:500]
        return {"status": row.status, "model": None, "error": str(exc)[:500]}


__all__ = ["build_narrative_evidence", "generate_node_narrative"]
