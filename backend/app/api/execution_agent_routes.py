"""Signed TEST-only protocol for the standalone local execution agent."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExecutionAgent
from app.services.execution.auth import AgentAuthError, authenticate_request
from app.services.execution.health import health_payload
from app.services.execution.intents import claim_next_lease, lease_payload, project_eligible_intents
from app.services.execution.ledger import EventRejected, event_payload, record_event


router = APIRouter(prefix="/api/execution-agent/v1")
WIRE_VERSION = "execution-agent.v1"


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    event_nonce: str | None = Field(default=None, max_length=128)
    account_id: int | None = Field(default=None, gt=0)
    lease_id: str = Field(min_length=1, max_length=96)
    occurred_at: str | None = None


async def _agent(request: Request, db: Session = Depends(get_db)) -> ExecutionAgent:
    try:
        return authenticate_request(db, request, await request.body())
    except AgentAuthError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _require_scope(agent: ExecutionAgent, scope: str) -> None:
    if scope not in (agent.scopes or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "agent scope 不足")


@router.get("/status")
def agent_status(agent: ExecutionAgent = Depends(_agent), db: Session = Depends(get_db)):
    _require_scope(agent, "lease:read")
    return health_payload(db)


@router.get("/lease")
def next_lease(
    wire_version: str = Query(...),
    agent: ExecutionAgent = Depends(_agent),
    db: Session = Depends(get_db),
):
    _require_scope(agent, "lease:read")
    if wire_version != WIRE_VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT, "wire_version 不支持")
    project_eligible_intents(db)
    try:
        lease = claim_next_lease(db, agent)
        result = lease_payload(db, lease)
        db.commit()
    except (ValueError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"lease": result, "environment": "test", "live_ready": False}


@router.post("/events")
def post_event(
    payload: EventRequest,
    agent: ExecutionAgent = Depends(_agent),
    db: Session = Depends(get_db),
):
    _require_scope(agent, "event:write")
    try:
        event = record_event(
            db,
            agent_id=agent.id,
            event_id=payload.event_id,
            event_type=payload.event_type,
            payload=payload.payload,
            event_nonce=payload.event_nonce,
            account_id=payload.account_id,
            lease_id=payload.lease_id,
            occurred_at=payload.occurred_at,
        )
        db.commit()
    except EventRejected as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"event": event_payload(event), "status": "accepted", "idempotent": True}
