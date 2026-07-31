from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import ExternalSearchRun

from .deep_search.service import DeepSearchService
from .exceptions import ExternalSearchError
from .metrics import external_search_metrics
from .schemas import DeepRunCreateAPIRequest, DeepRunEventOut, DeepRunOut

router = APIRouter(prefix="/api/external-search/v1", tags=["external-search"], dependencies=[Depends(get_current_user)])
CurrentUser = Annotated[Any, Depends(get_current_user)]
Database = Annotated[Session, Depends(get_db)]


def _error(request: Request, exc: ExternalSearchError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(status_code=exc.status_code, content={
        "request_id": request_id,
        "error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
    })


@router.post("/deep-runs", response_model=DeepRunOut)
async def create_deep_run(body: DeepRunCreateAPIRequest, request: Request, user: CurrentUser, db: Database):
    service = DeepSearchService(db)
    try:
        row = await service.create_run(
            user_id=user.id, role=user.role, conversation_id=body.conversation_id,
            user_message_id=body.user_message_id, assistant_message_id=body.assistant_message_id,
            query=body.query, mode=body.web_access_mode, generation_index=body.generation_index,
            confirmation=body.confirmation,
        )
        await service.ensure_background(row)
        return service.out(row)
    except ExternalSearchError as exc:
        return _error(request, exc)


@router.get("/deep-runs/{run_id}", response_model=DeepRunOut)
async def get_deep_run(run_id: str, request: Request, user: CurrentUser, db: Database):
    service = DeepSearchService(db)
    try:
        return service.out(await service.sync_run(run_id, user.id))
    except ExternalSearchError as exc:
        return _error(request, exc)


@router.get("/deep-runs/{run_id}/events", response_model=list[DeepRunEventOut])
def list_deep_run_events(run_id: str, request: Request, user: CurrentUser, db: Database):
    service = DeepSearchService(db)
    try:
        return service.events(run_id, user.id)
    except ExternalSearchError as exc:
        return _error(request, exc)


@router.post("/deep-runs/{run_id}/cancel", response_model=DeepRunOut)
async def cancel_deep_run(run_id: str, request: Request, user: CurrentUser, db: Database):
    service = DeepSearchService(db)
    try:
        return service.out(await service.cancel_run(run_id, user.id))
    except ExternalSearchError as exc:
        return _error(request, exc)


@router.get("/conversations/{conversation_id}/active-deep-run", response_model=DeepRunOut | None)
async def active_deep_run(conversation_id: int, request: Request, user: CurrentUser, db: Database):
    row = db.scalar(select(ExternalSearchRun).where(
        ExternalSearchRun.conversation_id == conversation_id,
        ExternalSearchRun.user_id == user.id,
        ExternalSearchRun.status.in_(("pending", "queued", "running")),
    ).order_by(ExternalSearchRun.created_at.desc()).limit(1))
    if row is None:
        return None
    service = DeepSearchService(db)
    try:
        return service.out(await service.sync_run(row.public_id, user.id))
    except ExternalSearchError as exc:
        return _error(request, exc)


@router.get("/metrics")
def metrics(request: Request, user: CurrentUser):
    if user.role != "admin":
        return _error(request, ExternalSearchError("WEB_SEARCH_NOT_ALLOWED", "Metrics are available to administrators only.", status_code=403))
    return external_search_metrics.snapshot()
