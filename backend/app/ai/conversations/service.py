from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.config import allowed_models, provider_name_for_model
from app.ai.enums import AIErrorCode
from app.ai.exceptions import AIError
from app.ai.orchestrator import AIOrchestrator
from app.ai.providers.schemas import ProviderMessage
from app.ai.schemas import AIRespondRequest, AIStreamEvent
from app.ai_memory.context import RelevantMemoryRetriever
from app.ai_memory.service import (
    process_user_message,
    record_context_usage,
)
from app.ai_memory.summaries.service import ConversationSummaryService
from app.ai_rich_content.schemas import RichContentDocument
from app.config import get_settings
from app.external_search.deep_search.service import DeepSearchService
from app.external_search.enums import WebAccessMode
from app.external_search.exceptions import ExternalSearchError
from app.models import AIConversation, AIMessage, ExternalSearchRun

from .audit import audit_conversation_action
from .history import ConversationHistoryLoader
from .repository import ConversationRepository, utcnow
from .runtime import ConversationRuntimeRegistry, runtime_registry
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
from .serializers import conversation_out, message_out


@dataclass
class PreparedGeneration:
    conversation: AIConversation
    user_message: AIMessage
    assistant_message: AIMessage
    request: AIRespondRequest
    history: Any
    used_memory_ids: list[int]
    used_decision_ids: list[int]


def _safe_title(message: str) -> str:
    text = re.sub(r"```.*?```", " ", message, flags=re.DOTALL)
    text = re.sub(r"[`#>*_~\[\]()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "新对话"
    return text[:48] + ("…" if len(text) > 48 else "")


def _persistent_tool_record(record: Any) -> dict:
    if hasattr(record, "model_dump"):
        value = record.model_dump(mode="json")
        value["normalized_arguments"] = dict(getattr(record, "normalized_arguments", {}) or {})
        value["arguments_hash"] = getattr(record, "arguments_hash", None)
        return value
    return dict(record)


class ConversationService:
    def __init__(
        self,
        db: Session,
        orchestrator: AIOrchestrator,
        *,
        runtime: ConversationRuntimeRegistry = runtime_registry,
    ) -> None:
        self.db = db
        self.repository = ConversationRepository(db)
        self.history_loader = ConversationHistoryLoader(self.repository)
        self.orchestrator = orchestrator
        self.runtime = runtime

    @staticmethod
    def _ensure_enabled() -> None:
        if not get_settings().ai_conversations_enabled:
            raise AIError(AIErrorCode.disabled, "AI conversations are disabled.", status_code=503)

    def _conversation(self, conversation_id: int, user_id: int, *, include_deleted: bool = False) -> AIConversation:
        self._ensure_enabled()
        item = self.repository.get_conversation_for_user(conversation_id, user_id, include_deleted=include_deleted)
        if item is None:
            raise AIError(AIErrorCode.conversation_not_found, "Conversation not found.", status_code=404)
        return item

    def create_conversation(self, user_id: int, body: ConversationCreateRequest, *, request_id: str) -> AIConversation:
        self._ensure_enabled()
        if body.model and body.model not in allowed_models():
            raise AIError(AIErrorCode.model_not_allowed, "Requested model is not allowed.", status_code=422)
        title = body.title or (_safe_title(body.message) if body.message else "新对话")
        try:
            default_web_mode = body.web_access_mode or WebAccessMode(get_settings().exa_default_web_access_mode)
        except ValueError:
            default_web_mode = WebAccessMode.off
        conversation = self.repository.create_conversation(
            user_id=user_id,
            title=title,
            title_source="user" if body.title else "generated",
            active_symbol=body.active_symbol,
            active_symbols=body.active_symbols,
            active_portfolio_id=body.active_portfolio_id,
            page_context=body.page_context,
            model=body.model,
            provider=provider_name_for_model(body.model or get_settings().ai_model),
            web_access_mode=default_web_mode.value,
        )
        self.db.commit()
        self.db.refresh(conversation)
        audit_conversation_action("conversation.create", request_id=request_id, user_id=user_id, conversation_id=conversation.id, has_initial_message=bool(body.message))
        return conversation

    def get_conversation(self, conversation_id: int, user_id: int) -> ConversationOut:
        return conversation_out(self._conversation(conversation_id, user_id))

    def list_conversations(self, user_id: int, *, status: str, page: int, limit: int) -> ConversationPage:
        self._ensure_enabled()
        settings = get_settings()
        limit = min(max(limit, 1), min(max(settings.ai_conversation_max_page_size, 1), 100))
        rows, total = self.repository.list_conversations_for_user(user_id, status=status, page=page, limit=limit)
        return ConversationPage(
            items=[conversation_out(item, preview) for item, preview in rows],
            page=page,
            limit=limit,
            total=total,
            has_more=page * limit < total,
        )

    def update_conversation(self, conversation_id: int, user_id: int, body: ConversationUpdateRequest, *, request_id: str) -> ConversationOut:
        conversation = self._conversation(conversation_id, user_id)
        fields = body.model_fields_set
        values: dict[str, Any] = {}
        for name in ("active_symbol", "active_symbols", "active_portfolio_id", "page_context", "model", "web_access_mode"):
            if name in fields:
                value = getattr(body, name)
                values[name] = value.value if isinstance(value, WebAccessMode) else value
        if "model" in fields and body.model and body.model not in allowed_models():
            raise AIError(AIErrorCode.model_not_allowed, "Requested model is not allowed.", status_code=422)
        if "model" in fields:
            values["provider"] = provider_name_for_model(body.model or get_settings().ai_model)
        if "title" in fields and body.title:
            values["title"] = body.title
            values["title_source"] = "user"
        if "active_symbol" in fields and body.active_symbol and "active_symbols" not in fields:
            values["active_symbols"] = [body.active_symbol] + [value for value in (conversation.active_symbols or []) if value != body.active_symbol]
        if body.archived is True:
            self.repository.archive_conversation(conversation)
        elif body.archived is False:
            self.repository.unarchive_conversation(conversation)
        if values:
            self.repository.update_conversation(conversation, values)
        self.db.commit()
        self.db.refresh(conversation)
        audit_conversation_action("conversation.update", request_id=request_id, user_id=user_id, conversation_id=conversation.id, fields=sorted(fields))
        return conversation_out(conversation)

    def archive_conversation(self, conversation_id: int, user_id: int, *, request_id: str) -> ConversationOut:
        conversation = self._conversation(conversation_id, user_id)
        self.repository.archive_conversation(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        audit_conversation_action("conversation.archive", request_id=request_id, user_id=user_id, conversation_id=conversation.id)
        return conversation_out(conversation)

    async def delete_conversation(self, conversation_id: int, user_id: int, *, request_id: str) -> None:
        conversation = self._conversation(conversation_id, user_id)
        await self.stop_generation(conversation_id, user_id, request_id=request_id)
        active_runs = list(self.db.scalars(select(ExternalSearchRun).where(
            ExternalSearchRun.conversation_id == conversation_id,
            ExternalSearchRun.user_id == user_id,
            ExternalSearchRun.status.in_(("pending", "queued", "running")),
        )))
        for run in active_runs:
            try:
                await DeepSearchService(self.db).cancel_run(run.public_id, user_id)
            except ExternalSearchError:
                # Deletion remains recoverable and provider cancellation can be
                # retried from the durable run record.
                self.db.rollback()
        self.repository.soft_delete_conversation(conversation)
        self.db.commit()
        audit_conversation_action("conversation.delete", request_id=request_id, user_id=user_id, conversation_id=conversation.id)

    def restore_conversation(self, conversation_id: int, user_id: int, *, request_id: str) -> ConversationOut:
        if not get_settings().ai_conversation_restore_enabled:
            raise AIError(AIErrorCode.disabled, "Conversation restore is disabled.", status_code=503)
        conversation = self._conversation(conversation_id, user_id, include_deleted=True)
        if conversation.deleted_at is None:
            return conversation_out(conversation)
        self.repository.restore_conversation(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        audit_conversation_action("conversation.restore", request_id=request_id, user_id=user_id, conversation_id=conversation.id)
        return conversation_out(conversation)

    def list_messages(
        self,
        conversation_id: int,
        user_id: int,
        *,
        page: int,
        limit: int,
        rich_content: bool = False,
    ) -> MessagePage:
        self._conversation(conversation_id, user_id)
        settings = get_settings()
        limit = min(max(limit, 1), min(max(settings.ai_message_max_page_size, 1), 200))
        messages, total = self.repository.list_messages(conversation_id, user_id, page=page, limit=limit)
        ids = [item.id for item in messages]
        citations = self.repository.list_citations_for_messages(ids, user_id)
        tools = self.repository.list_tool_calls_for_messages(ids, user_id)
        return MessagePage(
            items=[
                message_out(
                    item,
                    citations[item.id],
                    tools[item.id],
                    include_rich_content=rich_content,
                )
                for item in messages
            ],
            page=page,
            limit=limit,
            total=total,
            has_more=page * limit < total,
        )

    def get_message(
        self,
        conversation_id: int,
        message_id: int,
        user_id: int,
        *,
        rich_content: bool = False,
    ) -> MessageOut:
        self._conversation(conversation_id, user_id)
        item = self.repository.get_message_for_user(message_id, conversation_id, user_id)
        if item is None:
            raise AIError(AIErrorCode.message_not_found, "Message not found.", status_code=404)
        citations = self.repository.list_citations_for_messages([item.id], user_id)[item.id]
        tools = self.repository.list_tool_calls_for_messages([item.id], user_id)[item.id]
        return message_out(
            item,
            citations,
            tools,
            include_rich_content=rich_content,
        )

    def _context_values(self, conversation: AIConversation, body: ConversationMessageCreateRequest) -> tuple[str | None, list[str], int | None, str | None, str | None, WebAccessMode]:
        fields = body.model_fields_set
        active_symbol = body.active_symbol if "active_symbol" in fields else conversation.active_symbol
        active_symbols = list(body.active_symbols if "active_symbols" in fields else (conversation.active_symbols or []))
        if active_symbol:
            active_symbols = [active_symbol] + [value for value in active_symbols if value != active_symbol]
        active_portfolio_id = body.active_portfolio_id if "active_portfolio_id" in fields else conversation.active_portfolio_id
        page_context = body.page_context if "page_context" in fields else conversation.page_context
        model = body.model or conversation.model
        web_mode = body.web_access_mode if "web_access_mode" in fields and body.web_access_mode is not None else WebAccessMode(conversation.web_access_mode)
        return active_symbol, active_symbols, active_portfolio_id, page_context, model, web_mode

    def _prepare_new(self, conversation_id: int, user: Any, body: ConversationMessageCreateRequest) -> PreparedGeneration:
        conversation = self._conversation(conversation_id, user.id)
        active_symbol, active_symbols, portfolio_id, page_context, model, web_mode = self._context_values(conversation, body)
        if model and model not in allowed_models():
            raise AIError(AIErrorCode.model_not_allowed, "Requested model is not allowed.", status_code=422)
        if conversation.status == "archived":
            self.repository.unarchive_conversation(conversation)
        updates = {
            "active_symbol": active_symbol,
            "active_symbols": active_symbols,
            "active_portfolio_id": portfolio_id,
            "page_context": page_context,
            "model": model,
            "provider": provider_name_for_model(model or get_settings().ai_model),
        }
        if conversation.title_source == "generated" and conversation.message_count == 0:
            updates["title"] = _safe_title(body.message)
        self.repository.update_conversation(conversation, updates)
        now = utcnow()
        user_message = self.repository.create_message(
            conversation_id=conversation.id,
            user_id=user.id,
            role="user",
            status="completed",
            content=body.message,
            content_format="plain_text",
            completed_at=now,
            estimated_tokens=max(1, (len(body.message) + 3) // 4),
            web_access_mode=web_mode.value,
        )
        assistant = self.repository.create_message(
            conversation_id=conversation.id,
            user_id=user.id,
            role="assistant",
            status="pending",
            content="",
            parent_message_id=user_message.id,
            reply_to_message_id=user_message.id,
            generation_index=self.repository.next_generation_index(user_message.id),
            model=model or get_settings().ai_model,
            provider=provider_name_for_model(model or get_settings().ai_model),
            web_access_mode=web_mode.value,
        )
        self.repository.update_conversation_after_messages(conversation, added=2, completed=1, at=now)
        self.db.commit()
        self.db.refresh(user_message)
        self.db.refresh(assistant)
        try:
            process_user_message(
                self.db,
                user_id=user.id,
                conversation_id=conversation.id,
                message_id=user_message.id,
                text=body.message,
            )
        except Exception:
            # Candidate extraction and explicit-memory conveniences are
            # optional. They must never make the user's chat turn fail.
            self.db.rollback()
        history = self.history_loader.load(conversation_id=conversation.id, user_id=user.id, before_message_id=user_message.id)
        relevant = RelevantMemoryRetriever(self.db).retrieve(
            user_id=user.id,
            message=body.message,
            active_symbol=active_symbol,
            active_symbols=active_symbols,
            portfolio_id=portfolio_id,
            page_context=page_context,
            web_access_mode=web_mode.value,
        )
        if relevant.text:
            history.messages.append(
                ProviderMessage(role="user", content=relevant.text)
            )
            history.estimated_chars += len(relevant.text)
        history.warnings.extend(relevant.warnings)
        assistant.summary_snapshot_id = history.summary_snapshot_id
        try:
            record_context_usage(
                self.db,
                user_id=user.id,
                assistant_message_id=assistant.id,
                memory_ids=relevant.memory_ids,
                decision_ids=relevant.decision_ids,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
        request = AIRespondRequest(
            message=body.message,
            active_symbol=active_symbol,
            active_symbols=active_symbols,
            active_portfolio_id=portfolio_id,
            page_context=page_context,
            stream=body.stream,
            allowed_tools=body.allowed_tools,
            denied_tools=body.denied_tools,
            model=model,
            web_access_mode=web_mode,
            deep_search_confirmed=body.deep_search_confirmed,
            user_message_id=user_message.id,
            assistant_message_id=assistant.id,
            generation_index=assistant.generation_index,
        )
        return PreparedGeneration(
            conversation,
            user_message,
            assistant,
            request,
            history,
            relevant.memory_ids,
            relevant.decision_ids,
        )

    def _prepare_regenerate(self, conversation_id: int, message_id: int, user: Any, body: RegenerateRequest) -> PreparedGeneration:
        conversation = self._conversation(conversation_id, user.id)
        target = self.repository.get_message_for_user(message_id, conversation_id, user.id)
        if target is None:
            raise AIError(AIErrorCode.message_not_found, "Message not found.", status_code=404)
        if target.role == "assistant":
            old_assistant = target
            user_message = self.repository.get_message_for_user(target.parent_message_id or 0, conversation_id, user.id)
        else:
            old_assistant = None
            user_message = target
        last_user = self.repository.get_last_user_message(conversation_id, user.id)
        if user_message is None or user_message.role != "user" or last_user is None or last_user.id != user_message.id:
            raise AIError(AIErrorCode.message_not_regeneratable, "Only the latest user turn can be regenerated.", status_code=409)
        model = body.model or conversation.model
        web_mode = body.web_access_mode or WebAccessMode(user_message.web_access_mode)
        if model and model not in allowed_models():
            raise AIError(AIErrorCode.model_not_allowed, "Requested model is not allowed.", status_code=422)
        assistant = self.repository.create_message(
            conversation_id=conversation.id,
            user_id=user.id,
            role="assistant",
            status="pending",
            content="",
            parent_message_id=user_message.id,
            reply_to_message_id=user_message.id,
            regenerated_from_message_id=old_assistant.id if old_assistant else None,
            generation_index=self.repository.next_generation_index(user_message.id),
            model=model or get_settings().ai_model,
            provider=provider_name_for_model(model or get_settings().ai_model),
            web_access_mode=web_mode.value,
        )
        now = utcnow()
        self.repository.update_conversation_after_messages(conversation, added=1, completed=0, at=now)
        self.db.commit()
        self.db.refresh(assistant)
        history = self.history_loader.load(conversation_id=conversation.id, user_id=user.id, before_message_id=user_message.id)
        relevant = RelevantMemoryRetriever(self.db).retrieve(
            user_id=user.id,
            message=user_message.content,
            active_symbol=conversation.active_symbol,
            active_symbols=conversation.active_symbols or [],
            portfolio_id=conversation.active_portfolio_id,
            page_context=conversation.page_context,
            web_access_mode=web_mode.value,
        )
        if relevant.text:
            history.messages.append(
                ProviderMessage(role="user", content=relevant.text)
            )
            history.estimated_chars += len(relevant.text)
        history.warnings.extend(relevant.warnings)
        assistant.summary_snapshot_id = history.summary_snapshot_id
        try:
            record_context_usage(
                self.db,
                user_id=user.id,
                assistant_message_id=assistant.id,
                memory_ids=relevant.memory_ids,
                decision_ids=relevant.decision_ids,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
        request = AIRespondRequest(
            message=user_message.content,
            active_symbol=conversation.active_symbol,
            active_symbols=conversation.active_symbols or [],
            active_portfolio_id=conversation.active_portfolio_id,
            page_context=conversation.page_context,
            stream=body.stream,
            model=model,
            web_access_mode=web_mode,
            deep_search_confirmed=body.deep_search_confirmed,
            user_message_id=user_message.id,
            assistant_message_id=assistant.id,
            generation_index=assistant.generation_index,
        )
        return PreparedGeneration(
            conversation,
            user_message,
            assistant,
            request,
            history,
            relevant.memory_ids,
            relevant.decision_ids,
        )

    def _start(self, prepared: PreparedGeneration) -> None:
        self.repository.set_message_streaming(
            prepared.assistant_message,
            provider=provider_name_for_model(prepared.request.model or get_settings().ai_model),
            model=prepared.request.model or get_settings().ai_model,
        )
        self.db.commit()

    def _finalize(
        self,
        prepared: PreparedGeneration,
        *,
        status: str,
        content: str,
        citations: list[dict] | None = None,
        tool_calls: list[dict] | None = None,
        usage: dict | None = None,
        response_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        rich_content: RichContentDocument | dict | None = None,
    ) -> AIMessage:
        assistant = self.repository.get_message_for_user(
            prepared.assistant_message.id,
            prepared.conversation.id,
            prepared.conversation.user_id,
        )
        if assistant is None:
            return prepared.assistant_message
        if assistant.status not in {"pending", "streaming"}:
            return assistant
        now = utcnow()
        assistant.status = status
        assistant.content = content[:30000]
        if rich_content is not None and status in {"completed", "partial"}:
            document = RichContentDocument.model_validate(rich_content)
            assistant.content = document.fallback_markdown[:30000]
            document = document.model_copy(
                update={"fallback_markdown": assistant.content}
            )
            assistant.content_schema_version = document.schema_version
            assistant.content_parts = document.model_dump(mode="json")
            assistant.content_format = "rich_markdown"
        else:
            assistant.content_schema_version = None
            assistant.content_parts = None
            assistant.content_format = "markdown"
        assistant.provider_response_id = response_id
        assistant.estimated_tokens = max(0, (len(assistant.content) + 3) // 4)
        assistant.error_code = error_code
        assistant.error_message_safe = error_message[:500] if error_message else None
        assistant.updated_at = now
        if status == "cancelled":
            assistant.cancelled_at = now
        else:
            assistant.completed_at = now
        usage = usage or {}
        assistant.input_tokens = max(0, int(usage.get("input_tokens") or 0))
        assistant.output_tokens = max(0, int(usage.get("output_tokens") or 0))
        assistant.total_tokens = max(0, int(usage.get("total_tokens") or assistant.input_tokens + assistant.output_tokens))
        safe_citations = citations or []
        safe_tools = tool_calls or []
        assistant.citation_count = len(safe_citations)
        assistant.tool_call_count = len(safe_tools)
        self.repository.replace_message_citations(assistant, safe_citations)
        self.repository.replace_tool_call_records(assistant, safe_tools)
        conversation = self.repository.get_conversation_for_user(prepared.conversation.id, prepared.conversation.user_id, include_deleted=True)
        if conversation is not None:
            self.repository.update_conversation_after_messages(conversation, added=0, completed=1, at=now)
        self.db.commit()
        self.db.refresh(assistant)
        if status in {"completed", "partial"}:
            try:
                ConversationSummaryService(self.db).enqueue(
                    prepared.conversation.id,
                    prepared.conversation.user_id,
                    force=False,
                )
            except Exception:
                self.db.rollback()
        return assistant

    async def _reserve(self, conversation_id: int) -> asyncio.Task:
        task = asyncio.current_task()
        if task is None:
            raise AIError(AIErrorCode.internal, "AI generation task is unavailable.", status_code=500)
        await self.runtime.reserve(conversation_id, task)
        return task

    async def _stream_prepared(self, prepared: PreparedGeneration, user: Any, request_id: str, task: asyncio.Task) -> AsyncIterator[AIStreamEvent]:
        content = ""
        citations: list[dict] = []
        tool_calls: list[dict] = []
        terminal = False
        try:
            await self.runtime.bind_message(prepared.conversation.id, prepared.assistant_message.id, task)
            self._start(prepared)
            yield AIStreamEvent(type="conversation.started", data={
                "conversation_id": prepared.conversation.id,
                "user_message_id": prepared.user_message.id,
                "assistant_message_id": prepared.assistant_message.id,
            })
            yield AIStreamEvent(type="message.created", data={
                "user_message": message_out(prepared.user_message).model_dump(mode="json"),
                "assistant_message": message_out(prepared.assistant_message).model_dump(mode="json"),
            })
            async for event in self.orchestrator.stream(
                request=prepared.request,
                user=user,
                request_id=request_id,
                history=prepared.history.messages,
                conversation_id=str(prepared.conversation.id),
            ):
                if event.type == "context.ready":
                    event.data.update({
                        "history_message_count": len(prepared.history.messages),
                        "history_chars": prepared.history.estimated_chars,
                        "history_truncated": prepared.history.truncated,
                    })
                if event.type == "response.delta":
                    content += str(event.data.get("delta") or "")
                    yield event
                elif event.type == "response.reset":
                    content = ""
                    yield event
                elif event.type == "citation.map":
                    citations = list(event.data.get("citations") or [])
                    yield event
                elif event.type == "response.completed":
                    content = str(event.data.get("answer") or content)
                    internal_tools = event.persistence.get("tool_calls")
                    rich_content = event.persistence.get("rich_content")
                    tool_calls = [
                        _persistent_tool_record(item)
                        for item in (internal_tools if isinstance(internal_tools, list) else event.data.get("tool_calls") or [])
                    ]
                    status = "partial" if event.data.get("status") == "partial" else "completed"
                    assistant = self._finalize(
                        prepared,
                        status=status,
                        content=content,
                        citations=citations,
                        tool_calls=tool_calls,
                        usage=event.data.get("usage") or {},
                        response_id=event.data.get("response_id"),
                        rich_content=rich_content,
                    )
                    yield AIStreamEvent(type="message.persisted", data={"assistant_message_id": assistant.id, "status": assistant.status})
                    yield event
                    terminal = True
                    audit_conversation_action("message.generate", request_id=request_id, user_id=user.id, conversation_id=prepared.conversation.id, user_message_id=prepared.user_message.id, assistant_message_id=assistant.id, status=assistant.status, history_message_count=len(prepared.history.messages), history_chars=prepared.history.estimated_chars, tool_call_count=assistant.tool_call_count, citation_count=assistant.citation_count, answer_length=len(assistant.content))
                    break
                elif event.type == "error":
                    status = "partial" if content else "failed"
                    assistant = self._finalize(
                        prepared,
                        status=status,
                        content=content,
                        citations=citations,
                        tool_calls=tool_calls,
                        error_code=str(event.data.get("code") or AIErrorCode.internal.value),
                        error_message=str(event.data.get("message") or "AI response failed."),
                    )
                    yield AIStreamEvent(type="message.persisted", data={"assistant_message_id": assistant.id, "status": assistant.status})
                    yield event
                    terminal = True
                    break
                else:
                    yield event
            if not terminal:
                self._finalize(
                    prepared,
                    status="partial" if content else "failed",
                    content=content,
                    citations=citations,
                    tool_calls=tool_calls,
                    error_code=AIErrorCode.stream_interrupted.value,
                    error_message="AI response stream ended unexpectedly.",
                )
        except asyncio.CancelledError:
            self._finalize(
                prepared,
                status="cancelled",
                content=content,
                citations=citations,
                tool_calls=tool_calls,
                error_code=AIErrorCode.generation_cancelled.value,
                error_message="Generation was stopped.",
            )
            raise
        except AIError as exc:
            assistant = self._finalize(
                prepared,
                status="partial" if content else "failed",
                content=content,
                citations=citations,
                tool_calls=tool_calls,
                error_code=exc.code.value,
                error_message=exc.message,
            )
            yield AIStreamEvent(type="message.persisted", data={"assistant_message_id": assistant.id, "status": assistant.status})
            yield AIStreamEvent(type="error", data={"request_id": request_id, "code": exc.code.value, "message": exc.message, "retryable": exc.retryable})
        except Exception:  # noqa: BLE001 -- convert provider/runtime failures to a safe persisted state.
            self.db.rollback()
            assistant = self._finalize(
                prepared,
                status="partial" if content else "failed",
                content=content,
                citations=citations,
                tool_calls=tool_calls,
                error_code=AIErrorCode.internal.value,
                error_message="AI response failed.",
            )
            yield AIStreamEvent(type="message.persisted", data={"assistant_message_id": assistant.id, "status": assistant.status})
            yield AIStreamEvent(type="error", data={"request_id": request_id, "code": AIErrorCode.internal.value, "message": "AI response failed.", "retryable": False})
        finally:
            if not terminal:
                current = self.repository.get_message_for_user(prepared.assistant_message.id, prepared.conversation.id, user.id)
                if current and current.status in {"pending", "streaming"}:
                    self._finalize(
                        prepared,
                        status="cancelled",
                        content=content,
                        citations=citations,
                        tool_calls=tool_calls,
                        error_code=AIErrorCode.generation_cancelled.value,
                        error_message="Generation was interrupted.",
                    )
            await self.runtime.unregister(prepared.conversation.id, task)

    async def stream_message(self, conversation_id: int, user: Any, body: ConversationMessageCreateRequest, *, request_id: str) -> AsyncIterator[AIStreamEvent]:
        task = await self._reserve(conversation_id)
        try:
            prepared = self._prepare_new(conversation_id, user, body)
        except Exception:
            await self.runtime.unregister(conversation_id, task)
            raise
        async for event in self._stream_prepared(prepared, user, request_id, task):
            yield event

    async def stream_regenerate(self, conversation_id: int, message_id: int, user: Any, body: RegenerateRequest, *, request_id: str) -> AsyncIterator[AIStreamEvent]:
        task = await self._reserve(conversation_id)
        try:
            prepared = self._prepare_regenerate(conversation_id, message_id, user, body)
        except Exception:
            await self.runtime.unregister(conversation_id, task)
            raise
        async for event in self._stream_prepared(prepared, user, request_id, task):
            yield event

    async def _respond_prepared(self, prepared: PreparedGeneration, user: Any, request_id: str, task: asyncio.Task) -> MessagePairResponse:
        try:
            await self.runtime.bind_message(prepared.conversation.id, prepared.assistant_message.id, task)
            self._start(prepared)
            result = await self.orchestrator.respond(
                request=prepared.request,
                user=user,
                request_id=request_id,
                history=prepared.history.messages,
                conversation_id=str(prepared.conversation.id),
            )
            assistant = self._finalize(
                prepared,
                status="partial" if result.status == "partial" else "completed",
                content=result.answer,
                citations=[item.model_dump(mode="json") for item in result.citations],
                tool_calls=[_persistent_tool_record(item) for item in result.tool_calls],
                usage=result.usage.model_dump(mode="json"),
                response_id=result.response_id,
                rich_content=result.rich_content,
            )
            return self._pair_response(prepared.conversation.id, prepared.user_message.id, assistant.id, user.id)
        except asyncio.CancelledError:
            self._finalize(prepared, status="cancelled", content="", error_code=AIErrorCode.generation_cancelled.value, error_message="Generation was stopped.")
            raise
        except AIError as exc:
            self._finalize(prepared, status="failed", content="", error_code=exc.code.value, error_message=exc.message)
            raise
        except Exception as exc:
            self.db.rollback()
            self._finalize(prepared, status="failed", content="", error_code=AIErrorCode.internal.value, error_message="AI response failed.")
            raise AIError(AIErrorCode.internal, "AI response failed.", status_code=500) from exc
        finally:
            await self.runtime.unregister(prepared.conversation.id, task)

    def _pair_response(self, conversation_id: int, user_message_id: int, assistant_message_id: int, user_id: int) -> MessagePairResponse:
        conversation = self._conversation(conversation_id, user_id)
        user_message = self.repository.get_message_for_user(user_message_id, conversation_id, user_id)
        assistant = self.repository.get_message_for_user(assistant_message_id, conversation_id, user_id)
        if user_message is None or assistant is None:
            raise AIError(AIErrorCode.internal, "Persisted AI messages could not be loaded.", status_code=500)
        citations = self.repository.list_citations_for_messages([assistant.id], user_id)[assistant.id]
        tools = self.repository.list_tool_calls_for_messages([assistant.id], user_id)[assistant.id]
        return MessagePairResponse(
            conversation=conversation_out(conversation),
            user_message=message_out(user_message),
            assistant_message=message_out(assistant, citations, tools),
        )

    async def respond_message(self, conversation_id: int, user: Any, body: ConversationMessageCreateRequest, *, request_id: str) -> MessagePairResponse:
        task = await self._reserve(conversation_id)
        try:
            prepared = self._prepare_new(conversation_id, user, body)
        except Exception:
            await self.runtime.unregister(conversation_id, task)
            raise
        return await self._respond_prepared(prepared, user, request_id, task)

    async def respond_regenerate(self, conversation_id: int, message_id: int, user: Any, body: RegenerateRequest, *, request_id: str) -> MessagePairResponse:
        task = await self._reserve(conversation_id)
        try:
            prepared = self._prepare_regenerate(conversation_id, message_id, user, body)
        except Exception:
            await self.runtime.unregister(conversation_id, task)
            raise
        return await self._respond_prepared(prepared, user, request_id, task)

    async def stop_generation(self, conversation_id: int, user_id: int, *, request_id: str) -> StopResponse:
        self._conversation(conversation_id, user_id)
        entry = await self.runtime.cancel(conversation_id)
        if entry is None:
            return StopResponse(stopped=False, assistant_message_id=None)
        try:
            await asyncio.wait_for(asyncio.gather(entry.task, return_exceptions=True), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        audit_conversation_action("generation.stop", request_id=request_id, user_id=user_id, conversation_id=conversation_id, assistant_message_id=entry.assistant_message_id, stopped=True)
        return StopResponse(stopped=True, assistant_message_id=entry.assistant_message_id)

    async def active_generation(self, conversation_id: int, user_id: int) -> ActiveGenerationResponse:
        self._conversation(conversation_id, user_id)
        entry = await self.runtime.active(conversation_id)
        return ActiveGenerationResponse(
            active=entry is not None,
            assistant_message_id=entry.assistant_message_id if entry else None,
            runtime_mode=get_settings().ai_conversation_runtime_mode,
        )
