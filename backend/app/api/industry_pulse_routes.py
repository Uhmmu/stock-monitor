from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import IndustryPulseNode, User
from app.services.industry_pulse.seed_registry import seed_audit_report
from app.services.industry_pulse.service import ai_chain_payload, focus_payload, node_detail_payload, overview_payload, replacement_reviews_payload, system_status_payload, taxonomy_payload

router = APIRouter(prefix="/api/industry-pulse", dependencies=[Depends(get_current_user)])


def _range_days(value: Literal["30", "90", "365"]) -> int:
    return int(value)


@router.get("/overview")
def industry_pulse_overview(range: Literal["30", "90", "365"] = Query("30"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return overview_payload(db, _range_days(range))


@router.get("/focus")
def industry_pulse_focus(range: Literal["30", "90", "365"] = Query("30"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return focus_payload(db, _range_days(range))


@router.get("/ai-chain")
def industry_pulse_ai_chain(range: Literal["30", "90", "365"] = Query("30"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ai_chain_payload(db, _range_days(range))


@router.get("/taxonomy")
def industry_pulse_taxonomy(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return taxonomy_payload(db)


@router.get("/status")
def industry_pulse_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return system_status_payload(db)


@router.get("/replacement-reviews")
def industry_pulse_replacement_reviews(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return replacement_reviews_payload(db)


@router.get("/seed-audit")
def industry_pulse_seed_audit(user: User = Depends(get_current_user)):
    return seed_audit_report()


@router.get("/nodes/{node_id}")
def industry_pulse_node(node_id: str, range: Literal["30", "90", "365"] = Query("30"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        numeric_id = int(node_id)
        node = db.get(IndustryPulseNode, numeric_id)
    except ValueError:
        node = db.scalar(select(IndustryPulseNode).where(IndustryPulseNode.node_key == node_id))
        numeric_id = node.id if node else -1
    payload = node_detail_payload(db, numeric_id, _range_days(range))
    if payload is None:
        raise HTTPException(404, "未找到行业节点")
    return payload


__all__ = ["router"]
