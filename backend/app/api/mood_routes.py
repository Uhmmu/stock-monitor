from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_admin_user, get_current_user
from app.database import get_db
from app.models import User
from app.services.mood import latest_mood_payload, mood_history_payload, mood_report_payload


router = APIRouter(prefix="/api/mood", dependencies=[Depends(get_current_user)])
Range = Literal["7", "20", "60", "90", "180"]
Scope = Literal["market", "sector", "ai_chain", "watchlist"]


class MoodRecoveryRequest(BaseModel):
    trading_date: date
    scopes: list[str] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=3, max_length=500)


@router.get("/overview")
def mood_overview(
    range: Range = Query("20"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return latest_mood_payload(db, range_days=range)


@router.get("/report")
def mood_report(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return mood_report_payload(db)


@router.get("/history-health")
def mood_history_health(
    trading_date: date | None = None,
    days: int = Query(60, ge=5, le=3650),
    db: Session = Depends(get_db),
):
    from app.services.mood_history import history_health_payload

    return history_health_payload(db, trading_date=trading_date, days=days)


@router.get("/history-health/{trading_date}")
def mood_history_health_detail(trading_date: date, db: Session = Depends(get_db)):
    from app.services.mood_history import history_health_payload

    return history_health_payload(db, trading_date=trading_date, days=60)


@router.get("/history-gaps")
def mood_history_gaps(days: int = Query(60, ge=5, le=3650), db: Session = Depends(get_db)):
    from app.services.mood_history import history_gaps_payload

    return history_gaps_payload(db, days=days)


@router.post("/history-recovery")
def mood_history_recovery(
    payload: MoodRecoveryRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.mood_history import recover_missing_mood

    try:
        result = recover_missing_mood(db, payload.trading_date, payload.scopes, payload.reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    if result.get("status") == "REJECTED":
        raise HTTPException(409, result.get("reason") or "EOD snapshot already exists")
    return result


@router.get("/{scope_type}/{scope_key}")
def mood_detail(
    scope_type: Scope,
    scope_key: str,
    range: Range = Query("60"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = mood_history_payload(db, scope_type, scope_key, days=range)
    if not payload.get("item"):
        raise HTTPException(404, "未找到情绪快照")
    return payload


__all__ = ["router"]
