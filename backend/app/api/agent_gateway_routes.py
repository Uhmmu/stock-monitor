"""Internal agent gateway for the Pi Agent discovery sidecar.

This router is service-to-service only: it authenticates with a shared
``AGENT_GATEWAY_TOKEN`` header instead of a user JWT, and it must never be
reachable from the public internet (nginx and Caddy only forward ``/api/``
paths that user auth already protects; the sidecar reaches the api container
directly on the compose network).

The sidecar impersonates a single user per discovery run; every request must
carry ``run_id`` + ``user_id`` and the run is verified to belong to that user
before any tool executes, so private portfolio tools stay user-scoped exactly
like the AI-chat path.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_tools.executor import ToolExecutor
from app.ai_tools.registry import tool_registry
from app.ai_tools.schemas import ToolExecutionContext
from app.ai_tools.scopes import DEFAULT_AGENT_TOOL_SCOPE, UnknownToolScope, resolve_tool_scope
from app.config import get_settings
from app.database import get_db
from app.models import StockDiscoveryRun, User
from app.research.service import ResearchGateway


router = APIRouter(prefix="/api/agent/v1")


# Backwards-compatible alias: the opportunity research scope is the default
# capability set for this gateway. New agent surfaces add scopes in
# ``app.ai_tools.scopes`` instead of extending a bespoke allowlist here.
ALLOWED_TOOL_NAMES = resolve_tool_scope(DEFAULT_AGENT_TOOL_SCOPE)


def _require_token(x_agent_token: str | None) -> None:
    expected = get_settings().agent_gateway_token.strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent gateway is not configured")
    if x_agent_token is None or x_agent_token.strip() != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent gateway token")


def _owned_run(db: Session, user_id: int, run_id: int) -> StockDiscoveryRun:
    run = db.scalar(select(StockDiscoveryRun).where(
        StockDiscoveryRun.id == run_id, StockDiscoveryRun.user_id == user_id))
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Discovery run not found for this user")
    return run


class GatewayCall(BaseModel):
    run_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_scope: str = Field(default=DEFAULT_AGENT_TOOL_SCOPE, max_length=64)


class ProgressEvent(BaseModel):
    run_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    event_type: Literal[
        "research_started", "portfolio_loaded", "theme_discovered",
        "candidate_discovered", "candidate_screened", "candidate_rejected",
        "candidate_promoted", "external_search", "evidence_found",
        "bear_case_checked", "portfolio_fit_checked", "finalized",
        "stage_update",
    ]
    stage: str | None = Field(default=None, max_length=64)
    detail: str = Field(default="", max_length=2000)
    funnel_stats: dict[str, Any] = Field(default_factory=dict)


def _gateway(db: Session, user: User, request: Request) -> ResearchGateway:
    return ResearchGateway(db, user, request_id=request.headers.get("X-Request-ID") or f"agent-gateway-{user.id}", request=request)


@router.get("/tools")
def list_tools(
    scope: str = DEFAULT_AGENT_TOOL_SCOPE,
    x_agent_token: str | None = Header(default=None),
):
    _require_token(x_agent_token)
    try:
        allowed = resolve_tool_scope(scope)
    except UnknownToolScope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown tool scope: {scope}") from None
    tools = tool_registry.export_openai_tools(allowed_tools=allowed)
    return {"tools": tools, "count": len(tools), "scope": scope or DEFAULT_AGENT_TOOL_SCOPE}


@router.post("/execute")
async def execute_tool(
    call: GatewayCall,
    request: Request,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_token(x_agent_token)
    settings = get_settings()
    user = db.get(User, call.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _owned_run(db, call.user_id, call.run_id)
    try:
        allowed = resolve_tool_scope(call.tool_scope)
    except UnknownToolScope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown tool scope: {call.tool_scope}") from None
    if call.tool not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tool is not allowed for agent research")
    context = ToolExecutionContext(
        request_id=f"pi-agent:{call.run_id}:{request.headers.get('X-Request-ID') or 'r'}",
        user_id=call.user_id,
        session_id=f"discovery-run-{call.run_id}",
        web_access_mode=(
            "deep_medium" if call.tool == "run_deep_web_research" else "search"
        ),
        deep_search_confirmed=False,
        caller="internal",
        allowed_tools=allowed,
        # Per-call ceilings stay at the executor defaults; run-level budget
        # enforcement happens at the sidecar (counters) plus executor limits.
        max_tool_calls=min(settings.ai_tools_max_calls_per_batch, 12),
        max_parallel_calls=max(1, settings.ai_tools_max_parallel_calls),
        max_total_output_chars=settings.ai_max_tool_result_chars,
    )
    gateway = _gateway(db, user, request)
    result = await ToolExecutor(tool_registry, gateway).execute(
        tool_name=call.tool, raw_arguments=call.arguments, context=context)
    return result.model_dump(mode="json")


@router.post("/progress")
def report_progress(
    event: ProgressEvent,
    x_agent_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _require_token(x_agent_token)
    run = _owned_run(db, event.user_id, event.run_id)
    from app.services.discovery.progress import record_agent_event
    record_agent_event(db, run, event.event_type, event.detail, event.funnel_stats, stage=event.stage)
    return {"ok": True}
