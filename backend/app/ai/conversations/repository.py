from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import PurePath

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import AIConversation, AIMessage, AIMessageCitation, AIToolCallRecord
from app.research.security import safe_external_url


def utcnow() -> datetime:
    return datetime.now(UTC)


def _datetime(value):
    if not value or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_conversation(self, *, user_id: int, **values) -> AIConversation:
        conversation = AIConversation(user_id=user_id, **values)
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def get_conversation_for_user(self, conversation_id: int, user_id: int, *, include_deleted: bool = False) -> AIConversation | None:
        query = select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user_id)
        if not include_deleted:
            query = query.where(AIConversation.deleted_at.is_(None))
        return self.db.scalar(query)

    def list_conversations_for_user(self, user_id: int, *, status: str, page: int, limit: int) -> tuple[list[tuple[AIConversation, str | None]], int]:
        filters = [AIConversation.user_id == user_id]
        if status == "deleted":
            filters.append(AIConversation.deleted_at.is_not(None))
        else:
            filters.extend([AIConversation.deleted_at.is_(None), AIConversation.status == status])
        total = self.db.scalar(select(func.count(AIConversation.id)).where(*filters)) or 0
        preview = (
            select(AIMessage.content)
            .where(AIMessage.conversation_id == AIConversation.id, AIMessage.deleted_at.is_(None), AIMessage.content != "")
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .limit(1)
            .correlate(AIConversation)
            .scalar_subquery()
        )
        rows = self.db.execute(
            select(AIConversation, preview.label("last_message_preview"))
            .where(*filters)
            .order_by(AIConversation.last_message_at.desc().nullslast(), AIConversation.created_at.desc(), AIConversation.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()
        return [(row[0], row[1]) for row in rows], total

    def update_conversation(self, conversation: AIConversation, values: dict) -> AIConversation:
        for key, value in values.items():
            setattr(conversation, key, value)
        conversation.updated_at = utcnow()
        self.db.flush()
        return conversation

    def archive_conversation(self, conversation: AIConversation) -> AIConversation:
        now = utcnow()
        conversation.status = "archived"
        conversation.archived_at = now
        conversation.updated_at = now
        self.db.flush()
        return conversation

    def unarchive_conversation(self, conversation: AIConversation) -> AIConversation:
        conversation.status = "active"
        conversation.archived_at = None
        conversation.updated_at = utcnow()
        self.db.flush()
        return conversation

    def soft_delete_conversation(self, conversation: AIConversation) -> AIConversation:
        now = utcnow()
        conversation.status = "deleted"
        conversation.deleted_at = now
        conversation.updated_at = now
        self.db.flush()
        return conversation

    def restore_conversation(self, conversation: AIConversation) -> AIConversation:
        conversation.status = "active"
        conversation.deleted_at = None
        conversation.archived_at = None
        conversation.updated_at = utcnow()
        self.db.flush()
        return conversation

    def permanently_delete_conversation(self, conversation: AIConversation) -> None:
        self.db.delete(conversation)
        self.db.flush()

    def create_message(self, *, conversation_id: int, user_id: int, role: str, status: str, content: str, **values) -> AIMessage:
        message = AIMessage(conversation_id=conversation_id, user_id=user_id, role=role, status=status, content=content, **values)
        self.db.add(message)
        self.db.flush()
        return message

    def get_message_for_user(self, message_id: int, conversation_id: int, user_id: int) -> AIMessage | None:
        return self.db.scalar(select(AIMessage).where(
            AIMessage.id == message_id,
            AIMessage.conversation_id == conversation_id,
            AIMessage.user_id == user_id,
            AIMessage.deleted_at.is_(None),
        ))

    def list_messages(self, conversation_id: int, user_id: int, *, page: int, limit: int) -> tuple[list[AIMessage], int]:
        filters = [AIMessage.conversation_id == conversation_id, AIMessage.user_id == user_id, AIMessage.deleted_at.is_(None)]
        total = self.db.scalar(select(func.count(AIMessage.id)).where(*filters)) or 0
        offset = max(0, total - page * limit)
        remaining = max(0, min(limit, total - (page - 1) * limit))
        if remaining == 0:
            return [], total
        items = list(self.db.scalars(
            select(AIMessage).where(*filters).order_by(AIMessage.created_at.asc(), AIMessage.id.asc()).offset(offset).limit(remaining)
        ))
        return items, total

    def list_history_messages(
        self,
        conversation_id: int,
        user_id: int,
        *,
        before_message_id: int,
        after_message_id: int = 0,
        limit: int,
    ) -> list[AIMessage]:
        eligible = ("completed", "partial", "cancelled")
        newer_generation = aliased(AIMessage)
        rows = list(self.db.scalars(
            select(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.user_id == user_id,
                AIMessage.id < before_message_id,
                AIMessage.id > after_message_id,
                AIMessage.deleted_at.is_(None),
                AIMessage.status.in_(eligible),
                AIMessage.content != "",
                or_(
                    AIMessage.role == "user",
                    ~exists().where(
                        newer_generation.conversation_id == AIMessage.conversation_id,
                        newer_generation.user_id == AIMessage.user_id,
                        newer_generation.parent_message_id == AIMessage.parent_message_id,
                        newer_generation.role == "assistant",
                        newer_generation.id < before_message_id,
                        newer_generation.deleted_at.is_(None),
                        newer_generation.status.in_(eligible),
                        newer_generation.content != "",
                        newer_generation.generation_index > AIMessage.generation_index,
                    ),
                ),
            )
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .limit(limit)
        ))
        return list(reversed(rows))

    def next_generation_index(self, parent_message_id: int) -> int:
        value = self.db.scalar(select(func.max(AIMessage.generation_index)).where(AIMessage.parent_message_id == parent_message_id))
        return int(value or 0) + 1

    def get_last_user_message(self, conversation_id: int, user_id: int) -> AIMessage | None:
        return self.db.scalar(
            select(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.user_id == user_id,
                AIMessage.role == "user",
                AIMessage.deleted_at.is_(None),
            )
            .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
            .limit(1)
        )

    def set_message_streaming(self, message: AIMessage, *, provider: str, model: str) -> None:
        message.status = "streaming"
        message.provider = provider
        message.model = model
        message.started_at = utcnow()
        message.updated_at = utcnow()
        self.db.flush()

    def replace_message_citations(self, message: AIMessage, citations: Iterable[dict]) -> None:
        self.db.execute(delete(AIMessageCitation).where(AIMessageCitation.message_id == message.id))
        for item in citations:
            locator = item.get("locator")
            if not isinstance(locator, str) or locator.startswith("/") or ".." in PurePath(locator).parts:
                locator = None
            url = safe_external_url(item.get("url"))
            self.db.add(AIMessageCitation(
                message_id=message.id,
                conversation_id=message.conversation_id,
                user_id=message.user_id,
                citation_key=str(item.get("key") or "")[:16],
                source_id=str(item.get("source_id") or "")[:256],
                source_type=str(item.get("source_type") or "unknown")[:64],
                title=str(item.get("title") or item.get("source_id") or "来源")[:300],
                symbol=(str(item["symbol"])[:32] if item.get("symbol") else None),
                provider=(str(item["provider"])[:64] if item.get("provider") else None),
                authority=(str(item["authority"])[:128] if item.get("authority") else None),
                published_at=_datetime(item.get("published_at")),
                retrieved_at=_datetime(item.get("retrieved_at")),
                locator=locator[:500] if locator else None,
                url=url[:2000] if url else None,
            ))
        self.db.flush()

    def replace_tool_call_records(self, message: AIMessage, records: Iterable[dict]) -> None:
        self.db.execute(delete(AIToolCallRecord).where(AIToolCallRecord.assistant_message_id == message.id))
        for item in records:
            self.db.add(AIToolCallRecord(
                conversation_id=message.conversation_id,
                assistant_message_id=message.id,
                user_id=message.user_id,
                tool_call_id=str(item.get("tool_call_id") or "")[:256],
                tool_name=str(item.get("tool") or item.get("tool_name") or "unknown")[:64],
                tool_version=(str(item["tool_version"])[:32] if item.get("tool_version") else None),
                status=str(item.get("status") or "unknown")[:32],
                result_mode=item.get("result_mode"),
                normalized_arguments=dict(item.get("normalized_arguments") or {}),
                arguments_hash=(str(item["arguments_hash"])[:64] if item.get("arguments_hash") else None),
                summary=(str(item["summary"])[:500] if item.get("summary") else None),
                warning_codes=[str(value)[:64] for value in item.get("warning_codes", [])[:20]],
                source_ids=[str(value)[:256] for value in item.get("source_ids", [])[:100]],
                duration_ms=max(0, int(item.get("duration_ms") or 0)),
                cache_hit=bool(item.get("cache_hit")),
                truncated=bool(item.get("truncated")),
                original_item_count=item.get("original_item_count"),
                returned_item_count=item.get("returned_item_count"),
                error_code=(str(item["error_code"])[:64] if item.get("error_code") else None),
                retryable=bool(item.get("retryable")),
                reused=bool(item.get("reused")),
                external_provider=(str(item["external_provider"])[:32] if item.get("external_provider") else None),
                external_request_id=(str(item["external_request_id"])[:256] if item.get("external_request_id") else None),
                external_run_id=(str(item["external_run_id"])[:64] if item.get("external_run_id") else None),
                cost_usd=item.get("cost_usd"),
                cost_estimated=bool(item.get("cost_estimated")),
                completed_at=utcnow(),
            ))
        self.db.flush()

    def list_citations_for_messages(self, message_ids: list[int], user_id: int) -> dict[int, list[AIMessageCitation]]:
        result = {message_id: [] for message_id in message_ids}
        if not message_ids:
            return result
        for item in self.db.scalars(select(AIMessageCitation).where(AIMessageCitation.message_id.in_(message_ids), AIMessageCitation.user_id == user_id).order_by(AIMessageCitation.message_id, AIMessageCitation.citation_key)):
            result[item.message_id].append(item)
        return result

    def list_tool_calls_for_messages(self, message_ids: list[int], user_id: int) -> dict[int, list[AIToolCallRecord]]:
        result = {message_id: [] for message_id in message_ids}
        if not message_ids:
            return result
        for item in self.db.scalars(select(AIToolCallRecord).where(AIToolCallRecord.assistant_message_id.in_(message_ids), AIToolCallRecord.user_id == user_id).order_by(AIToolCallRecord.assistant_message_id, AIToolCallRecord.created_at, AIToolCallRecord.id)):
            result[item.assistant_message_id].append(item)
        return result

    def update_conversation_after_messages(self, conversation: AIConversation, *, added: int, completed: int, at: datetime) -> None:
        conversation.message_count = max(0, conversation.message_count + added)
        conversation.completed_message_count = max(0, conversation.completed_message_count + completed)
        conversation.last_message_at = at
        conversation.updated_at = at
        self.db.flush()


def normalized_preview(value: str | None, limit: int = 180) -> str | None:
    if not value:
        return None
    clean = re.sub(r"\s+", " ", value).strip()
    return clean[:limit] + ("…" if len(clean) > limit else "")
