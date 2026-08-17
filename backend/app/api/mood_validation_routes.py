from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_admin_user, get_current_user
from app.database import get_db
from app.models import MoodValidationResult, MoodValidationRun, User
from app.services.mood_validation import create_run, latest_overview, result_payload, run_payload, snapshot_detail


router = APIRouter(prefix="/api/mood-lab", dependencies=[Depends(get_current_user)])
Scope = Literal["market", "sector", "ai_chain", "watchlist"]


class CreateValidationRun(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    scopes: list[Scope] = Field(default_factory=lambda: ["market", "sector", "ai_chain", "watchlist"])
    horizons: list[Literal[1, 5, 10, 20, 60]] = Field(default_factory=lambda: [1, 5, 10, 20, 60])


@router.get("/overview")
def overview(run_id: int | None = None, db: Session = Depends(get_db)):
    return latest_overview(db, run_id)


@router.get("/runs")
def runs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    values = db.scalars(select(MoodValidationRun).order_by(MoodValidationRun.created_at.desc(), MoodValidationRun.id.desc()).limit(limit)).all()
    return {"runs": [run_payload(row) for row in values]}


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(payload: CreateValidationRun, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    active = db.scalar(select(MoodValidationRun).where(MoodValidationRun.status.in_(("pending", "running"))).order_by(MoodValidationRun.created_at.desc()).limit(1))
    if active is not None:
        return {**run_payload(active), "queued": False}
    try:
        run = create_run(db, admin.id, date_from=payload.date_from, date_to=payload.date_to, scope_filter=payload.scopes, horizons=payload.horizons)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    from app.tasks.celery_app import run_mood_validation
    task = run_mood_validation.delay(run.id)
    return {**run_payload(run), "queued": True, "task_id": task.id}


@router.get("/runs/{run_id}")
def run_status(run_id: int, db: Session = Depends(get_db)):
    row = db.get(MoodValidationRun, run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到验证任务")
    return run_payload(row)


@router.get("/runs/{run_id}/results")
def results(
    run_id: int,
    study_type: str | None = None,
    scope_type: Scope | None = None,
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    if db.get(MoodValidationRun, run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到验证任务")
    query = select(MoodValidationResult).where(MoodValidationResult.run_id == run_id)
    if study_type: query = query.where(MoodValidationResult.study_type == study_type)
    if scope_type: query = query.where(MoodValidationResult.scope_type == scope_type)
    values = db.scalars(query.order_by(MoodValidationResult.study_type, MoodValidationResult.id).limit(limit)).all()
    return {"run_id": run_id, "results": [result_payload(row) for row in values]}


@router.get("/snapshots/{snapshot_id}")
def detail(snapshot_id: int, db: Session = Depends(get_db)):
    payload = snapshot_detail(db, snapshot_id)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到情绪快照")
    return payload


__all__ = ["router"]
