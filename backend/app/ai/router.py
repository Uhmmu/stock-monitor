from __future__ import annotations

import logging
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute

from app.ai_memory.metrics import ai_memory_metrics
from app.ai_rich_content.metrics import rich_content_metrics
from app.ai_rich_content.registry import rich_block_registry
from app.ai_tools.executor import ToolExecutor
from app.ai_tools.registry import tool_registry
from app.auth import get_current_user
from app.config import get_settings
from app.external_search.enums import (
    EFFORT_BASE_COST_USD,
    DeepSearchEffort,
    WebAccessMode,
)
from app.research.router import gateway
from app.research.service import ResearchGateway

from .audit import audit_ai_request
from .config import (
    allowed_models,
    effective_api_base,
    effective_api_key,
    model_catalog,
    provider_name_for_model,
)
from .enums import AIErrorCode
from .exceptions import AIError
from .metrics import ai_metrics
from .orchestrator import AIOrchestrator
from .schemas import AIErrorResponse, AIRespondRequest, AIRespondResponse
from .streaming import encode_sse

logger = logging.getLogger(__name__)


class AIValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def validated(request: Request):
            request.state.ai_request_id = request.headers.get("X-Request-ID") or str(uuid4())
            try:
                return await original(request)
            except RequestValidationError:
                return _error(request.state.ai_request_id, AIError(AIErrorCode.request_invalid, "AI request validation failed.", status_code=422))

        return validated


router = APIRouter(prefix="/api/ai/v1", tags=["ai-orchestrator"], dependencies=[Depends(get_current_user)], route_class=AIValidationRoute)
current_user_dependency = Depends(get_current_user)
gateway_dependency = Depends(gateway)


def _orchestrator(gw: ResearchGateway) -> AIOrchestrator:
    return AIOrchestrator(registry=tool_registry, executor=ToolExecutor(tool_registry, gw))


def _error(request_id: str, exc: AIError) -> JSONResponse:
    body = AIErrorResponse(request_id=request_id, error={"code": exc.code.value, "message": exc.message, "retryable": exc.retryable})
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


def _validate_tools(body: AIRespondRequest) -> None:
    known = {definition.name for definition in tool_registry.list()}
    requested = set(body.allowed_tools or []) | set(body.denied_tools)
    if unknown := requested - known:
        raise AIError(AIErrorCode.request_invalid, f"Unknown tool names: {', '.join(sorted(unknown))}", status_code=422)


@router.post("/respond", response_model=AIRespondResponse | None)
async def respond(body: AIRespondRequest, request: Request, user: Any = current_user_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = getattr(request.state, "ai_request_id", None) or request.headers.get("X-Request-ID") or str(uuid4())
    started = perf_counter()
    try:
        _validate_tools(body); settings = get_settings()
        if body.stream:
            if not settings.ai_streaming_enabled:
                raise AIError(AIErrorCode.disabled, "AI streaming is disabled.", status_code=503)

            async def events():
                async for event in _orchestrator(gw).stream(request=body, user=user, request_id=request_id):
                    if await request.is_disconnected():
                        break
                    yield encode_sse(event)

            return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Request-ID": request_id})
        if not settings.ai_non_streaming_enabled:
            raise AIError(AIErrorCode.disabled, "Non-streaming AI responses are disabled.", status_code=503)
        return await _orchestrator(gw).respond(request=body, user=user, request_id=request_id)
    except AIError as exc:
        logger.warning("ai_request_error request_id=%s user_id=%s code=%s", request_id, user.id, exc.code.value)
        duration = int((perf_counter() - started) * 1000)
        model = body.model or get_settings().ai_model
        audit_ai_request(request_id=request_id, user_id=user.id, provider=provider_name_for_model(model), model=model, request=body, duration_ms=duration, error_code=exc.code.value)
        ai_metrics.record(status="error", model=body.model or get_settings().ai_model, duration_ms=duration, error_code=exc.code.value)
        return _error(request_id, exc)
    except Exception:
        logger.exception("ai_request_unhandled request_id=%s user_id=%s", request_id, user.id)
        duration = int((perf_counter() - started) * 1000)
        model = body.model or get_settings().ai_model
        audit_ai_request(request_id=request_id, user_id=user.id, provider=provider_name_for_model(model), model=model, request=body, duration_ms=duration, error_code=AIErrorCode.internal.value)
        ai_metrics.record(status="error", model=body.model or get_settings().ai_model, duration_ms=duration, error_code=AIErrorCode.internal.value)
        return _error(request_id, AIError(AIErrorCode.internal, "AI response failed.", status_code=500))


@router.get("/config")
def public_config():
    settings = get_settings()
    deep_modes = {}
    for effort in DeepSearchEffort:
        deep_modes[effort.value] = {
            "label": f"Deep · {effort.value.replace('xhigh', 'X-High').title() if effort.value != 'xhigh' else 'X-High'}",
            "estimated_base_cost_usd": EFFORT_BASE_COST_USD[effort],
            "confirmation_required": (
                effort == DeepSearchEffort.high and settings.exa_deep_high_confirmation_required
            ) or (
                effort == DeepSearchEffort.xhigh and settings.exa_deep_xhigh_confirmation_required
            ),
            "enabled": settings.exa_enabled and settings.exa_deep_search_enabled and bool(getattr(settings, f"exa_deep_{effort.value}_enabled")),
        }
    try:
        default_mode = WebAccessMode(settings.exa_default_web_access_mode).value
    except ValueError:
        default_mode = WebAccessMode.off.value
    available_modes = [WebAccessMode.off.value]
    external_ready = settings.exa_enabled and bool(settings.exa_api_key)
    if external_ready and settings.exa_search_enabled:
        available_modes.append(WebAccessMode.search.value)
    if external_ready and settings.exa_deep_search_enabled:
        available_modes.extend(f"deep_{effort.value}" for effort in DeepSearchEffort if deep_modes[effort.value]["enabled"])
    if default_mode not in available_modes:
        default_mode = WebAccessMode.off.value
    return {
        "enabled": settings.ai_enabled, "streaming": settings.ai_streaming_enabled,
        "default_model": settings.ai_model, "allowed_models": allowed_models(settings),
        "models": model_catalog(settings), "max_message_chars": 12000,
        "conversations_enabled": settings.ai_conversations_enabled,
        "conversation_runtime_mode": settings.ai_conversation_runtime_mode,
        "memory": {
            "enabled": settings.ai_memory_enabled,
            "use_in_context": settings.ai_memory_use_in_context,
            "candidate_extraction_enabled": settings.ai_memory_candidate_extraction_enabled,
            "explicit_save_requires_confirmation": settings.ai_memory_explicit_save_requires_confirmation,
            "max_active_memories": settings.ai_memory_max_active_items,
        },
        "conversation_summary": {
            "enabled": settings.ai_summary_enabled,
            "automatic": settings.ai_summary_automatic_enabled,
        },
        "investment_decisions": {
            "enabled": settings.ai_investment_decisions_enabled,
            "automatic_draft_suggestions": settings.ai_investment_decision_draft_suggestions,
        },
        "rich_content": {
            "enabled": settings.ai_rich_content_enabled,
            "schema_version": min(
                max(settings.ai_rich_content_schema_version, 1), 100
            ),
            "max_blocks_per_message": min(
                max(settings.ai_rich_content_max_blocks_per_message, 1),
                max(settings.ai_rich_content_hard_max_blocks, 1),
                10,
            ),
            "blocks": [
                {
                    "block_type": definition.block_type,
                    "version": definition.version,
                }
                for definition in rich_block_registry.list_supported()
            ],
        },
        "web_search": {
            "enabled": settings.exa_enabled,
            "configured": bool(settings.exa_api_key),
            "default_mode": default_mode,
            "available_modes": available_modes,
            "deep_modes": deep_modes,
        },
    }


@router.get("/health")
def health():
    settings = get_settings()
    return {"enabled": settings.ai_enabled, "provider": settings.ai_provider, "configured": bool(effective_api_base(settings) and effective_api_key(settings) and settings.ai_model in allowed_models(settings)), "tool_registry_ready": bool(tool_registry.list()), "tool_count": len(tool_registry.list()), "conversations_enabled": settings.ai_conversations_enabled, "conversation_runtime_mode": settings.ai_conversation_runtime_mode, "distributed_cancellation": False, "external_search_enabled": settings.exa_enabled, "external_search_configured": bool(settings.exa_api_key)}


@router.get("/metrics")
def metrics():
    if not get_settings().ai_debug_api_enabled:
        raise HTTPException(404, "AI debug API is disabled")
    result = ai_metrics.snapshot()
    result["summary_memory_decisions"] = ai_memory_metrics.snapshot()
    result["rich_content"] = rich_content_metrics.snapshot()
    return result
