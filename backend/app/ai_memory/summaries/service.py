from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.config import (
    endpoint_for_model,
    get_provider_registry,
    provider_name_for_model,
)
from app.ai.providers.schemas import ProviderMessage, ProviderRequest
from app.config import get_settings
from app.models import (
    AIConversation,
    AIConversationSummarySnapshot,
    AIMessage,
)

from ..audit import audit_event
from ..metrics import ai_memory_metrics
from ..prompts.summary import SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimeSensitiveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=2000)
    as_of: str = Field(max_length=64)
    expires_at: str = Field("", max_length=64)


class StructuredSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_goal: str = Field("", max_length=4000)
    current_topics: list[str] = Field(default_factory=list, max_length=50)
    symbols: list[str] = Field(default_factory=list, max_length=50)
    confirmed_user_statements: list[str] = Field(
        default_factory=list, max_length=50
    )
    confirmed_facts: list[str] = Field(default_factory=list, max_length=100)
    current_conclusions: list[str] = Field(default_factory=list, max_length=50)
    open_questions: list[str] = Field(default_factory=list, max_length=50)
    planned_actions: list[str] = Field(default_factory=list, max_length=50)
    important_constraints: list[str] = Field(default_factory=list, max_length=50)
    decision_candidates: list[str] = Field(default_factory=list, max_length=30)
    memory_candidates: list[str] = Field(default_factory=list, max_length=30)
    time_sensitive_items: list[TimeSensitiveItem] = Field(
        default_factory=list, max_length=50
    )


class SummaryProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary_text: str = Field(min_length=1)
    structured_summary: StructuredSummary


class SummaryError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ConversationSummaryService:
    def __init__(self, db: Session):
        self.db = db

    def _conversation(
        self, conversation_id: int, user_id: int
    ) -> AIConversation:
        item = self.db.scalar(
            select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
        )
        if item is None:
            raise LookupError("Conversation not found")
        return item

    def current(
        self, conversation_id: int, user_id: int
    ) -> AIConversationSummarySnapshot | None:
        conversation = self._conversation(conversation_id, user_id)
        if conversation.current_summary_snapshot_id:
            return self.db.scalar(
                select(AIConversationSummarySnapshot).where(
                    AIConversationSummarySnapshot.id
                    == conversation.current_summary_snapshot_id,
                    AIConversationSummarySnapshot.user_id == user_id,
                    AIConversationSummarySnapshot.status == "completed",
                )
            )
        return self.db.scalar(
            select(AIConversationSummarySnapshot)
            .where(
                AIConversationSummarySnapshot.conversation_id
                == conversation_id,
                AIConversationSummarySnapshot.user_id == user_id,
                AIConversationSummarySnapshot.status == "completed",
            )
            .order_by(AIConversationSummarySnapshot.version.desc())
            .limit(1)
        )

    def history(
        self, conversation_id: int, user_id: int
    ) -> list[AIConversationSummarySnapshot]:
        self._conversation(conversation_id, user_id)
        return list(
            self.db.scalars(
                select(AIConversationSummarySnapshot)
                .where(
                    AIConversationSummarySnapshot.conversation_id
                    == conversation_id,
                    AIConversationSummarySnapshot.user_id == user_id,
                )
                .order_by(AIConversationSummarySnapshot.version.desc())
            )
        )

    def should_trigger(self, conversation_id: int, user_id: int) -> bool:
        settings = get_settings()
        if not settings.ai_summary_enabled or not settings.ai_summary_automatic_enabled:
            return False
        conversation = self._conversation(conversation_id, user_id)
        current = self.current(conversation_id, user_id)
        through = current.through_message_id if current else 0
        filters = [
            AIMessage.conversation_id == conversation_id,
            AIMessage.user_id == user_id,
            AIMessage.id > (through or 0),
            AIMessage.deleted_at.is_(None),
            AIMessage.status.in_(("completed", "partial", "cancelled")),
            AIMessage.content != "",
        ]
        count, chars = self.db.execute(
            select(func.count(AIMessage.id), func.coalesce(func.sum(func.length(AIMessage.content)), 0)).where(
                *filters
            )
        ).one()
        context_ratio = int(chars or 0) / max(settings.ai_max_context_chars, 1)
        return bool(
            (current is None and conversation.completed_message_count >= settings.ai_summary_trigger_message_count)
            or int(count or 0)
            >= settings.ai_summary_unsummarized_message_count
            or int(chars or 0) >= settings.ai_summary_trigger_chars
            or context_ratio >= settings.ai_summary_context_ratio
        )

    def request_refresh(
        self, conversation_id: int, user_id: int, *, force: bool = False
    ) -> AIConversationSummarySnapshot:
        settings = get_settings()
        if not settings.ai_summary_enabled:
            raise SummaryError("AI_SUMMARY_DISABLED", "Conversation summary is disabled")
        conversation = self._conversation(conversation_id, user_id)
        pending = self.db.scalar(
            select(AIConversationSummarySnapshot)
            .where(
                AIConversationSummarySnapshot.conversation_id == conversation_id,
                AIConversationSummarySnapshot.user_id == user_id,
                AIConversationSummarySnapshot.status == "pending",
            )
            .order_by(AIConversationSummarySnapshot.version.desc())
            .limit(1)
        )
        if pending:
            created_at = pending.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if created_at > utcnow() - timedelta(minutes=5):
                return pending
            pending.status = "failed"
            pending.error_code = "AI_SUMMARY_TASK_FAILED"
            pending.error_message_safe = "Summary task did not start in time."
        if not force and not self.should_trigger(conversation_id, user_id):
            current = self.current(conversation_id, user_id)
            if current:
                return current
            raise SummaryError(
                "AI_SUMMARY_NOT_REQUIRED", "Conversation does not require a summary"
            )
        previous = self.current(conversation_id, user_id)
        through = previous.through_message_id if previous else 0
        messages = list(
            self.db.scalars(
                select(AIMessage)
                .where(
                    AIMessage.conversation_id == conversation_id,
                    AIMessage.user_id == user_id,
                    AIMessage.id > (through or 0),
                    AIMessage.deleted_at.is_(None),
                    AIMessage.status.in_(("completed", "partial", "cancelled")),
                    AIMessage.content != "",
                )
                .order_by(AIMessage.id)
                .limit(500)
            )
        )
        if not messages:
            if previous:
                return previous
            raise SummaryError(
                "AI_SUMMARY_NOT_REQUIRED", "Conversation has no completed messages"
            )
        version = int(
            self.db.scalar(
                select(
                    func.coalesce(
                        func.max(AIConversationSummarySnapshot.version), 0
                    )
                ).where(
                    AIConversationSummarySnapshot.conversation_id
                    == conversation_id
                )
            )
            or 0
        ) + 1
        model = settings.ai_summary_model.strip() or settings.ai_model
        provider = (
            settings.ai_summary_provider.strip()
            or provider_name_for_model(model, settings)
        )
        snapshot = AIConversationSummarySnapshot(
            user_id=user_id,
            conversation_id=conversation_id,
            version=version,
            status="pending",
            from_message_id=messages[0].id,
            through_message_id=messages[-1].id,
            source_message_count=len(messages),
            source_character_count=sum(len(row.content) for row in messages),
            structured_summary={},
            provider=provider,
            model=model,
            prompt_version=settings.ai_summary_prompt_version,
            estimated_tokens=max(
                1, sum(len(row.content) for row in messages) // 4
            ),
        )
        conversation.summary_status = "pending"
        self.db.add(snapshot)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(AIConversationSummarySnapshot)
                .where(
                    AIConversationSummarySnapshot.conversation_id
                    == conversation_id,
                    AIConversationSummarySnapshot.status == "pending",
                )
                .order_by(AIConversationSummarySnapshot.version.desc())
            )
            if existing:
                return existing
            raise
        self.db.refresh(snapshot)
        ai_memory_metrics.increment("summary", "triggered")
        ai_memory_metrics.observe(
            "summary", "input_messages", snapshot.source_message_count
        )
        audit_event(
            "summary.triggered",
            user_id=user_id,
            conversation_id=conversation_id,
            snapshot_id=snapshot.id,
            version=snapshot.version,
            status=snapshot.status,
            source_message_count=snapshot.source_message_count,
            source_character_count=snapshot.source_character_count,
            provider=snapshot.provider,
            model=snapshot.model,
        )
        return snapshot

    def enqueue(
        self, conversation_id: int, user_id: int, *, force: bool = False
    ) -> AIConversationSummarySnapshot:
        snapshot = self.request_refresh(conversation_id, user_id, force=force)
        if snapshot.status != "pending":
            return snapshot
        try:
            from app.tasks.celery_app import summarize_ai_conversation

            summarize_ai_conversation.delay(snapshot.id)
        except Exception:  # noqa: BLE001 - queue failures must not fail chat.
            # Queue failures never abort the chat request. A manual refresh can
            # retry after the stale-pending timeout.
            logger.warning(
                "Unable to enqueue conversation summary snapshot %s",
                snapshot.id,
            )
        return snapshot

    async def process(
        self, snapshot_id: int
    ) -> AIConversationSummarySnapshot | None:
        started = perf_counter()
        snapshot = self.db.scalar(
            select(AIConversationSummarySnapshot).where(
                AIConversationSummarySnapshot.id == snapshot_id
            )
        )
        if snapshot is None or snapshot.status != "pending":
            return snapshot
        conversation = self.db.scalar(
            select(AIConversation).where(
                AIConversation.id == snapshot.conversation_id,
                AIConversation.user_id == snapshot.user_id,
                AIConversation.deleted_at.is_(None),
            )
        )
        if conversation is None:
            snapshot.status = "failed"
            snapshot.error_code = "AI_SUMMARY_TASK_FAILED"
            snapshot.error_message_safe = "Conversation no longer exists."
            self.db.commit()
            duration_ms = int((perf_counter() - started) * 1000)
            ai_memory_metrics.increment("summary", "failed")
            audit_event(
                "summary.failed",
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                snapshot_id=snapshot.id,
                version=snapshot.version,
                status=snapshot.status,
                source_message_count=snapshot.source_message_count,
                source_character_count=snapshot.source_character_count,
                provider=snapshot.provider,
                model=snapshot.model,
                duration_ms=duration_ms,
                error_code=snapshot.error_code,
            )
            return snapshot
        previous = self.db.scalar(
            select(AIConversationSummarySnapshot)
            .where(
                AIConversationSummarySnapshot.conversation_id
                == snapshot.conversation_id,
                AIConversationSummarySnapshot.user_id == snapshot.user_id,
                AIConversationSummarySnapshot.status == "completed",
                AIConversationSummarySnapshot.version < snapshot.version,
            )
            .order_by(AIConversationSummarySnapshot.version.desc())
            .limit(1)
        )
        messages = list(
            self.db.scalars(
                select(AIMessage)
                .where(
                    AIMessage.conversation_id == snapshot.conversation_id,
                    AIMessage.user_id == snapshot.user_id,
                    AIMessage.id >= snapshot.from_message_id,
                    AIMessage.id <= snapshot.through_message_id,
                    AIMessage.deleted_at.is_(None),
                    AIMessage.status.in_(("completed", "partial", "cancelled")),
                    AIMessage.content != "",
                )
                .order_by(AIMessage.id)
            )
        )
        payload = {
            "previous_summary": (
                {
                    "summary_text": previous.summary_text,
                    "structured_summary": previous.structured_summary,
                    "through_message_id": previous.through_message_id,
                }
                if previous
                else None
            ),
            "new_messages": [
                {
                    "id": row.id,
                    "role": row.role,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                    "content": row.content,
                }
                for row in messages
            ],
        }
        settings = get_settings()
        model = snapshot.model or settings.ai_model
        try:
            if not all(endpoint_for_model(model, settings)):
                raise SummaryError(
                    "AI_SUMMARY_PROVIDER_FAILED",
                    "Summary model credentials are not configured.",
                )
            provider = get_provider_registry().get(
                snapshot.provider or provider_name_for_model(model, settings)
            )
            request = ProviderRequest(
                model=model,
                messages=[
                    ProviderMessage(
                        role="system", content=SUMMARY_SYSTEM_PROMPT
                    ),
                    ProviderMessage(
                        role="user",
                        content=json.dumps(
                            payload, ensure_ascii=False, default=str
                        ),
                    ),
                ],
                tools=[],
                tool_choice="none",
                temperature=0,
                max_output_tokens=settings.ai_summary_max_output_tokens,
                metadata={
                    "purpose": "conversation_summary",
                    "snapshot_id": str(snapshot.id),
                },
            )
            attempts = max(1, settings.ai_summary_max_retries + 1)
            response = None
            parsed = None
            for attempt in range(attempts):
                try:
                    response = await asyncio.wait_for(
                        provider.create_response(request),
                        timeout=settings.ai_summary_timeout_seconds,
                    )
                    raw = (response.content or "").strip()
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
                    parsed = SummaryProviderOutput.model_validate_json(raw)
                    break
                except (
                    asyncio.TimeoutError,
                    ValidationError,
                    json.JSONDecodeError,
                ):
                    if attempt == attempts - 1:
                        raise
                    ai_memory_metrics.increment("summary", "retry")
                except Exception:
                    if attempt == attempts - 1:
                        raise
                    ai_memory_metrics.increment("summary", "retry")
            if response is None or parsed is None:
                raise SummaryError(
                    "AI_SUMMARY_PROVIDER_FAILED",
                    "Summary provider did not return a result.",
                )
            if len(parsed.summary_text) > 20000:
                raise SummaryError(
                    "AI_SUMMARY_TOO_LARGE", "Summary output exceeded its limit."
                )
            now = utcnow()
            snapshot.status = "completed"
            snapshot.summary_text = parsed.summary_text
            snapshot.structured_summary = parsed.structured_summary.model_dump(
                mode="json"
            )
            snapshot.input_tokens = (
                response.usage.input_tokens if response.usage else 0
            ) or 0
            snapshot.output_tokens = (
                response.usage.output_tokens if response.usage else 0
            ) or 0
            snapshot.completed_at = now
            snapshot.error_code = None
            snapshot.error_message_safe = None
            if previous:
                previous.status = "superseded"
                previous.superseded_at = now
            conversation.current_summary_snapshot_id = snapshot.id
            conversation.summary = snapshot.summary_text
            conversation.summary_status = "ready"
            conversation.summary_updated_at = now
            self._prune(snapshot.conversation_id)
            self.db.commit()
            duration_ms = int((perf_counter() - started) * 1000)
            ai_memory_metrics.increment("summary", "completed")
            ai_memory_metrics.observe(
                "summary",
                "compression_ratio",
                len(snapshot.summary_text or "")
                / max(snapshot.source_character_count, 1),
            )
            ai_memory_metrics.observe(
                "summary",
                "tokens",
                snapshot.input_tokens + snapshot.output_tokens,
            )
            ai_memory_metrics.observe(
                "summary",
                "context_chars_saved",
                max(
                    snapshot.source_character_count
                    - len(snapshot.summary_text or ""),
                    0,
                ),
            )
            audit_event(
                "summary.completed",
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                snapshot_id=snapshot.id,
                version=snapshot.version,
                status=snapshot.status,
                source_message_count=snapshot.source_message_count,
                source_character_count=snapshot.source_character_count,
                provider=snapshot.provider,
                model=snapshot.model,
                duration_ms=duration_ms,
            )
        except (ValidationError, json.JSONDecodeError):
            self._fail(
                snapshot,
                conversation,
                "AI_SUMMARY_INVALID_OUTPUT",
                "Summary provider returned invalid structured output.",
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except asyncio.TimeoutError:
            self._fail(
                snapshot,
                conversation,
                "AI_SUMMARY_PROVIDER_FAILED",
                "Summary provider timed out.",
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except SummaryError as exc:
            self._fail(
                snapshot,
                conversation,
                exc.code,
                str(exc),
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except Exception:  # noqa: BLE001 - persist a safe failure state.
            logger.warning(
                "Conversation summary processing failed for snapshot %s",
                snapshot_id,
            )
            self.db.rollback()
            snapshot = self.db.get(AIConversationSummarySnapshot, snapshot_id)
            conversation = (
                self.db.get(AIConversation, snapshot.conversation_id)
                if snapshot
                else None
            )
            if snapshot and conversation:
                self._fail(
                    snapshot,
                    conversation,
                    "AI_SUMMARY_PROVIDER_FAILED",
                    "Summary provider failed.",
                    duration_ms=int((perf_counter() - started) * 1000),
                )
        return self.db.get(AIConversationSummarySnapshot, snapshot_id)

    def _fail(
        self,
        snapshot: AIConversationSummarySnapshot,
        conversation: AIConversation,
        code: str,
        message: str,
        *,
        duration_ms: int,
    ) -> None:
        snapshot.status = "failed"
        snapshot.error_code = code
        snapshot.error_message_safe = message[:500]
        current = self.current(conversation.id, conversation.user_id)
        conversation.summary_status = "ready" if current else "failed"
        self.db.commit()
        ai_memory_metrics.increment("summary", "failed")
        audit_event(
            "summary.failed",
            user_id=snapshot.user_id,
            conversation_id=snapshot.conversation_id,
            snapshot_id=snapshot.id,
            version=snapshot.version,
            status=snapshot.status,
            source_message_count=snapshot.source_message_count,
            source_character_count=snapshot.source_character_count,
            provider=snapshot.provider,
            model=snapshot.model,
            duration_ms=duration_ms,
            error_code=code,
        )

    def _prune(self, conversation_id: int) -> None:
        keep = min(
            max(get_settings().ai_summary_max_snapshots_per_conversation, 1),
            50,
        )
        rows = list(
            self.db.scalars(
                select(AIConversationSummarySnapshot)
                .where(
                    AIConversationSummarySnapshot.conversation_id
                    == conversation_id
                )
                .order_by(AIConversationSummarySnapshot.version.desc())
                .offset(keep)
            )
        )
        for row in rows:
            self.db.delete(row)
