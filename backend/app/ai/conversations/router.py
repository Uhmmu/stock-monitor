from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.ai.enums import AIErrorCode
from app.ai.exceptions import AIError
from app.ai.router import _orchestrator
from app.ai.schemas import AIErrorResponse, AIStreamEvent
from app.ai.streaming import encode_sse
from app.ai_tools.registry import tool_registry
from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.research.router import gateway
from app.research.service import ResearchGateway

from .schemas import (
    ActiveGenerationResponse,
    ConversationCreateRequest,
    ConversationMessageCreateRequest,
    ConversationOut,
    ConversationPage,
    ConversationUpdateRequest,
    MessageOut,
    MessagePage,
    MessagePairResponse,
    RegenerateRequest,
    StopResponse,
)
from .service import ConversationService


def _error(request_id: str, exc: AIError) -> JSONResponse:
    body = AIErrorResponse(
        request_id=request_id,
        error={"code": exc.code.value, "message": exc.message, "retryable": exc.retryable},
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


class ConversationValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def validated(request: Request):
            request.state.ai_request_id = request.headers.get("X-Request-ID") or str(uuid4())
            try:
                return await original(request)
            except RequestValidationError:
                return _error(
                    request.state.ai_request_id,
                    AIError(AIErrorCode.request_invalid, "AI conversation request validation failed.", status_code=422),
                )

        return validated


current_user_dependency = Depends(get_current_user)
db_dependency = Depends(get_db)
gateway_dependency = Depends(gateway)

router = APIRouter(
    prefix="/api/ai/v1",
    tags=["ai-conversations"],
    dependencies=[current_user_dependency],
    route_class=ConversationValidationRoute,
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "ai_request_id", None) or request.headers.get("X-Request-ID") or str(uuid4())


def _service(db: Session, gw: ResearchGateway) -> ConversationService:
    return ConversationService(db, _orchestrator(gw))


def _validate_tools(body: ConversationMessageCreateRequest) -> None:
    known = {definition.name for definition in tool_registry.list()}
    requested = set(body.allowed_tools or []) | set(body.denied_tools)
    if unknown := requested - known:
        raise AIError(AIErrorCode.request_invalid, f"Unknown tool names: {', '.join(sorted(unknown))}", status_code=422)


def _sse_headers(request_id: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Request-ID": request_id,
    }


async def _safe_events(source, request_id: str):
    try:
        async for event in source:
            yield encode_sse(event)
    except AIError as exc:
        yield encode_sse(AIStreamEvent(type="error", data={
            "request_id": request_id,
            "code": exc.code.value,
            "message": exc.message,
            "retryable": exc.retryable,
        }))
    except Exception:  # noqa: BLE001 -- SSE boundaries must emit a sanitized terminal error.
        yield encode_sse(AIStreamEvent(type="error", data={
            "request_id": request_id,
            "code": AIErrorCode.internal.value,
            "message": "AI response failed.",
            "retryable": False,
        }))


@router.post("/conversations", response_model=ConversationOut | MessagePairResponse)
async def create_conversation(
    body: ConversationCreateRequest,
    request: Request,
    user: Any = current_user_dependency,
    db: Session = db_dependency,
    gw: ResearchGateway = gateway_dependency,
):
    request_id = _request_id(request)
    try:
        service = _service(db, gw)
        conversation = service.create_conversation(user.id, body, request_id=request_id)
        if not body.message:
            return ConversationOut.model_validate(service.get_conversation(conversation.id, user.id))
        message_body = ConversationMessageCreateRequest(
            message=body.message,
            active_symbol=body.active_symbol,
            active_symbols=body.active_symbols,
            active_portfolio_id=body.active_portfolio_id,
            page_context=body.page_context,
            model=body.model,
            web_access_mode=body.web_access_mode,
            stream=False,
        )
        return await service.respond_message(conversation.id, user, message_body, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(
    request: Request,
    status: Literal["active", "archived", "deleted"] = "active",
    page: int = Query(1, ge=1),
    limit: int | None = Query(None, ge=1),
    user: Any = current_user_dependency,
    db: Session = db_dependency,
    gw: ResearchGateway = gateway_dependency,
):
    request_id = _request_id(request)
    try:
        page_size = limit or get_settings().ai_conversation_default_page_size
        return _service(db, gw).list_conversations(user.id, status=status, page=page, limit=page_size)
    except AIError as exc:
        return _error(request_id, exc)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    try:
        return _service(db, gw).get_conversation(conversation_id, user.id)
    except AIError as exc:
        return _error(_request_id(request), exc)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def update_conversation(conversation_id: int, body: ConversationUpdateRequest, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        return _service(db, gw).update_conversation(conversation_id, user.id, body, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        await _service(db, gw).delete_conversation(conversation_id, user.id, request_id=request_id)
        return Response(status_code=204)
    except AIError as exc:
        return _error(request_id, exc)


@router.post("/conversations/{conversation_id}/restore", response_model=ConversationOut)
def restore_conversation(conversation_id: int, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        return _service(db, gw).restore_conversation(conversation_id, user.id, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)


@router.post("/conversations/{conversation_id}/archive", response_model=ConversationOut)
def archive_conversation(conversation_id: int, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        return _service(db, gw).archive_conversation(conversation_id, user.id, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagePage,
    response_model_exclude_none=True,
)
def list_messages(
    conversation_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    limit: int | None = Query(None, ge=1),
    include_citations: bool = True,
    include_tool_calls: bool = True,
    rich_content: bool = False,
    user: Any = current_user_dependency,
    db: Session = db_dependency,
    gw: ResearchGateway = gateway_dependency,
):
    del include_citations, include_tool_calls
    try:
        page_size = limit or get_settings().ai_message_default_page_size
        return _service(db, gw).list_messages(
            conversation_id,
            user.id,
            page=page,
            limit=page_size,
            rich_content=rich_content,
        )
    except AIError as exc:
        return _error(_request_id(request), exc)


@router.post("/conversations/{conversation_id}/messages", response_model=MessagePairResponse | None)
async def create_message(conversation_id: int, body: ConversationMessageCreateRequest, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        _validate_tools(body)
        service = _service(db, gw)
        service.get_conversation(conversation_id, user.id)
        if body.stream:
            if not get_settings().ai_streaming_enabled:
                raise AIError(AIErrorCode.disabled, "AI streaming is disabled.", status_code=503)
            return StreamingResponse(
                _safe_events(service.stream_message(conversation_id, user, body, request_id=request_id), request_id),
                media_type="text/event-stream",
                headers=_sse_headers(request_id),
            )
        return await service.respond_message(conversation_id, user, body, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}",
    response_model=MessageOut,
    response_model_exclude_none=True,
)
def get_message(
    conversation_id: int,
    message_id: int,
    request: Request,
    rich_content: bool = False,
    user: Any = current_user_dependency,
    db: Session = db_dependency,
    gw: ResearchGateway = gateway_dependency,
):
    try:
        return _service(db, gw).get_message(
            conversation_id,
            message_id,
            user.id,
            rich_content=rich_content,
        )
    except AIError as exc:
        return _error(_request_id(request), exc)


@router.post("/conversations/{conversation_id}/stop", response_model=StopResponse)
async def stop_generation(conversation_id: int, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        return await _service(db, gw).stop_generation(conversation_id, user.id, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)


@router.get("/conversations/{conversation_id}/active-generation", response_model=ActiveGenerationResponse)
async def active_generation(conversation_id: int, request: Request, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    try:
        return await _service(db, gw).active_generation(conversation_id, user.id)
    except AIError as exc:
        return _error(_request_id(request), exc)


@router.post("/conversations/{conversation_id}/messages/{message_id}/regenerate", response_model=MessagePairResponse | None)
async def regenerate(conversation_id: int, message_id: int, request: Request, body: RegenerateRequest | None = None, user: Any = current_user_dependency, db: Session = db_dependency, gw: ResearchGateway = gateway_dependency):
    request_id = _request_id(request)
    try:
        body = body or RegenerateRequest()
        service = _service(db, gw)
        service.get_message(conversation_id, message_id, user.id)
        if body.stream:
            return StreamingResponse(
                _safe_events(service.stream_regenerate(conversation_id, message_id, user, body, request_id=request_id), request_id),
                media_type="text/event-stream",
                headers=_sse_headers(request_id),
            )
        return await service.respond_regenerate(conversation_id, message_id, user, body, request_id=request_id)
    except AIError as exc:
        return _error(request_id, exc)
