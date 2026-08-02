from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AIConversation,
    AIConversationSummarySnapshot,
    AIInvestmentDecision,
    AIInvestmentDecisionEvidence,
    AIInvestmentDecisionReview,
    AIMemoryEvent,
    AIMessage,
    AIMessageCitation,
    AIMessageDecisionUsage,
    AIMessageMemoryUsage,
    AIUserMemory,
    AIUserMemoryPreference,
    Portfolio,
    PortfolioPosition,
    InvestmentCalendarEvent,
    TradeTransaction,
)
from app.research.security import safe_external_url

from .audit import audit_event
from .enums import MemoryScope, MemoryStatus
from .metrics import ai_memory_metrics
from .schemas import (
    DecisionCreate,
    DecisionDraftPreview,
    DecisionOut,
    DecisionPage,
    DecisionPatch,
    DecisionResolveRequest,
    EvidenceCreate,
    EvidenceOut,
    ExecuteDecisionRequest,
    ForgetResult,
    MemoryCreate,
    MemoryDetailOut,
    MemoryOut,
    MemoryPage,
    MemoryPatch,
    MemorySettingsOut,
    MemorySettingsPatch,
    ReviewCreate,
    ReviewOut,
)
from .decision_extraction import extract_conversation_decision, merge_decisions
from app.services.price_snapshots import get_latest_persisted_price_snapshot
from app.services.portfolio.performance import build_summary as build_portfolio_summary

MEMORY_TYPES = {
    "investment_style",
    "risk_policy",
    "portfolio_constraint",
    "valuation_preference",
    "market_preference",
    "research_preference",
    "communication_preference",
    "long_term_goal",
    "project_context",
    "watchlist_interest",
    "recurring_workflow",
    "general_preference",
}
SENSITIVE_PATTERNS = (
    r"\b(?:api[_ -]?key|secret|password|passphrase|bank account|trading account)\b",
    r"\b(?:种族|民族|宗教|政治立场|性取向|健康诊断|犯罪记录|银行账号|交易账号|密码|密钥|精确地址)\b",
    r"\bsk-[A-Za-z0-9_-]{12,}\b",
)
TRANSIENT_MARKET_PATTERNS = (
    r"(?:当前|今天|今日|刚刚|现在).{0,10}(?:价格|股价|新闻|情绪|目标价)",
    r"\b(?:today|current|breaking|latest)\b.{0,20}\b(?:price|news|sentiment|target)\b",
)
INJECTION_PATTERNS = (
    r"ignore (?:all |the )?(?:previous|above) instructions",
    r"(?:system|developer) prompt",
    r"忽略(?:以上|之前|前面).{0,12}(?:指令|提示)",
    r"(?:网页|新闻|sec|tool|工具)(?:内容|输出|文本).{0,12}(?:要求|指示|说)",
)
CORE_DECISION_FIELDS = {
    "decision_type",
    "symbols",
    "decision_date",
    "time_horizon",
    "action",
    "position_intent",
    "target_weight",
    "target_quantity",
    "target_price_min",
    "target_price_max",
    "thesis",
    "catalysts",
    "risks",
    "invalidation_conditions",
    "assumptions",
    "open_questions",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _snapshot(memory: AIUserMemory) -> dict[str, Any]:
    return {
        "status": memory.status,
        "memory_type": memory.memory_type,
        "scope": memory.scope,
        "scope_key": memory.scope_key,
        "content_hash": memory.normalized_content_hash,
        "importance": memory.importance,
    }


def normalize_memory_content(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return re.sub(r"[，。！？、,.!?;；:：\"'“”‘’]", "", value)


def memory_signature(value: str) -> str:
    return hashlib.sha256(normalize_memory_content(value).encode()).hexdigest()


def contains_sensitive_content(value: str) -> bool:
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)


def is_transient_market_fact(value: str) -> bool:
    return any(
        re.search(pattern, value, re.IGNORECASE)
        for pattern in TRANSIENT_MARKET_PATTERNS
    )


def memory_out(item: AIUserMemory) -> MemoryOut:
    return MemoryOut.model_validate(item)


def _freshness(item: AIInvestmentDecisionEvidence, now: datetime) -> str:
    as_of = _aware(item.as_of or item.retrieved_at or item.published_at)
    if as_of is None:
        return "unknown"
    age = now - as_of
    if age <= timedelta(days=30):
        return "fresh"
    if age <= timedelta(days=90):
        return "aging"
    return "stale"


def decision_out(
    item: AIInvestmentDecision,
    *,
    evidence: list[AIInvestmentDecisionEvidence] | None = None,
    reviews: list[AIInvestmentDecisionReview] | None = None,
) -> DecisionOut:
    now = utcnow()
    output = DecisionOut.model_validate(item)
    output.review_due = bool(
        get_settings().ai_investment_decision_review_due_enabled
        and item.status == "active"
        and item.target_review_at
        and _aware(item.target_review_at) <= now
    )
    output.evidence = []
    for row in evidence or []:
        row.freshness_status = _freshness(row, now)
        output.evidence.append(
            EvidenceOut.model_validate({
                "id": row.id,
                "source_id": row.source_id,
                "source_type": row.source_type,
                "origin": row.origin,
                "title": row.title,
                "symbol": row.symbol,
                "provider": row.provider,
                "authority": row.authority,
                "published_at": row.published_at,
                "retrieved_at": row.retrieved_at,
                "as_of": row.as_of,
                "url": safe_external_url(row.url),
                "locator": row.locator,
                "evidence_summary": row.evidence_summary,
                "evidence_role": row.evidence_role,
                "freshness_status": row.freshness_status,
                "created_at": row.created_at,
            })
        )
    if (
        get_settings().ai_investment_decision_review_due_enabled
        and item.status == "active"
        and any(row.freshness_status == "stale" for row in output.evidence)
    ):
        output.review_due = True
    output.reviews = [
        ReviewOut.model_validate({
            "id": row.id,
            "review_type": row.review_type,
            "status": row.status,
            "reviewed_at": row.reviewed_at,
            "data_as_of": row.data_as_of,
            "thesis_status": row.thesis_status,
            "invalidation_status": row.invalidation_status,
            "execution_status": row.execution_status,
            "what_changed": row.what_changed,
            "supporting_changes": list(row.supporting_changes or []),
            "contradicting_changes": list(row.contradicting_changes or []),
            "lessons": list(row.lessons or []),
            "next_action": row.next_action,
            "linked_message_id": row.linked_message_id,
            "linked_conversation_id": row.linked_conversation_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        })
        for row in reviews or []
    ]
    return output


class MemoryNotFound(LookupError):
    pass


class MemoryConflict(ValueError):
    pass


class AIMemoryService:
    def __init__(self, db: Session):
        self.db = db

    def _enabled(self) -> None:
        if not get_settings().ai_memory_enabled:
            raise MemoryConflict("AI memory is disabled")

    def _memory(self, memory_id: int, user_id: int) -> AIUserMemory:
        item = self.db.scalar(
            select(AIUserMemory).where(
                AIUserMemory.id == memory_id,
                AIUserMemory.user_id == user_id,
                AIUserMemory.deleted_at.is_(None),
            )
        )
        if item is None:
            raise MemoryNotFound("Memory not found")
        return item

    def _event(
        self,
        item: AIUserMemory,
        event_type: str,
        *,
        before: dict | None = None,
        conversation_id: int | None = None,
        message_id: int | None = None,
    ) -> None:
        self.db.add(
            AIMemoryEvent(
                user_id=item.user_id,
                memory_id=item.id,
                event_type=event_type,
                before_value=before,
                after_value=_snapshot(item),
                conversation_id=conversation_id,
                message_id=message_id,
            )
        )

    def settings(self, user_id: int) -> MemorySettingsOut:
        settings = get_settings()
        row = self.db.get(AIUserMemoryPreference, user_id)
        return MemorySettingsOut(
            enabled=settings.ai_memory_enabled and (row.enabled if row else True),
            use_in_context=settings.ai_memory_use_in_context
            and (row.use_in_context if row else True),
            candidate_extraction_enabled=settings.ai_memory_candidate_extraction_enabled
            and (row.candidate_extraction_enabled if row else True),
            max_active_memories=settings.ai_memory_max_active_items,
        )

    def update_settings(
        self, user_id: int, body: MemorySettingsPatch
    ) -> MemorySettingsOut:
        row = self.db.get(AIUserMemoryPreference, user_id)
        if row is None:
            row = AIUserMemoryPreference(user_id=user_id)
            self.db.add(row)
        for field in body.model_fields_set:
            setattr(row, field, getattr(body, field))
        row.updated_at = utcnow()
        self.db.commit()
        return self.settings(user_id)

    def _verify_sources(
        self,
        user_id: int,
        conversation_id: int | None,
        message_id: int | None,
    ) -> None:
        if conversation_id is not None and self.db.scalar(
            select(AIConversation.id).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
        ) is None:
            raise MemoryNotFound("Conversation not found")
        if message_id is not None and self.db.scalar(
            select(AIMessage.id).where(
                AIMessage.id == message_id,
                AIMessage.user_id == user_id,
                AIMessage.deleted_at.is_(None),
            )
        ) is None:
            raise MemoryNotFound("Message not found")

    def _active_count(self, user_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count(AIUserMemory.id)).where(
                    AIUserMemory.user_id == user_id,
                    AIUserMemory.status == MemoryStatus.active.value,
                    AIUserMemory.deleted_at.is_(None),
                )
            )
            or 0
        )

    def _duplicate(
        self,
        user_id: int,
        body: MemoryCreate,
        signature: str,
    ) -> AIUserMemory | None:
        return self.db.scalar(
            select(AIUserMemory).where(
                AIUserMemory.user_id == user_id,
                AIUserMemory.memory_type == body.memory_type.value,
                AIUserMemory.scope == body.scope.value,
                AIUserMemory.scope_key == body.scope_key,
                AIUserMemory.normalized_content_hash == signature,
                AIUserMemory.status.in_(("active", "proposed", "stale")),
                AIUserMemory.deleted_at.is_(None),
            )
        )

    def _conflict(
        self, user_id: int, body: MemoryCreate
    ) -> AIUserMemory | None:
        rows = list(
            self.db.scalars(
                select(AIUserMemory)
                .where(
                    AIUserMemory.user_id == user_id,
                    AIUserMemory.memory_type == body.memory_type.value,
                    AIUserMemory.scope == body.scope.value,
                    AIUserMemory.scope_key == body.scope_key,
                    AIUserMemory.status == "active",
                    AIUserMemory.deleted_at.is_(None),
                )
                .order_by(AIUserMemory.updated_at.desc(), AIUserMemory.id.desc())
            )
        )
        if not rows:
            return None
        if body.structured_value and isinstance(body.structured_value, dict):
            key = body.structured_value.get("constraint_key")
            if key:
                return next(
                    (
                        row
                        for row in rows
                        if isinstance(row.structured_value, dict)
                        and row.structured_value.get("constraint_key") == key
                    ),
                    None,
                )
        # Numeric constraints with the same type/scope are treated as a
        # replacement candidate (e.g. a 20% cap changed to 15%).
        if re.search(r"\d", body.content):
            return next((row for row in rows if re.search(r"\d", row.content)), None)
        return None

    def create_memory(self, user_id: int, body: MemoryCreate) -> MemoryOut:
        self._enabled()
        self._verify_sources(
            user_id, body.source_conversation_id, body.source_message_id
        )
        if is_transient_market_fact(body.content):
            raise MemoryConflict("Short-lived market facts cannot be saved as memory")
        sensitive = contains_sensitive_content(body.content)
        if sensitive and not get_settings().ai_memory_sensitive_storage_enabled:
            raise MemoryConflict("Sensitive memory storage is disabled")
        signature = memory_signature(body.content)
        duplicate = self._duplicate(user_id, body, signature)
        now = utcnow()
        if duplicate:
            if not body.proposed:
                before = _snapshot(duplicate)
                duplicate.status = "active"
                duplicate.last_confirmed_at = now
                duplicate.confirmed_at = duplicate.confirmed_at or now
                duplicate.updated_at = now
                self._event(
                    duplicate,
                    "duplicate",
                    before=before,
                    conversation_id=body.source_conversation_id,
                    message_id=body.source_message_id,
                )
                self.db.commit()
            return memory_out(duplicate)
        # Even when sensitive storage is explicitly enabled, the first write is
        # always a proposal so a second, explicit confirmation is required.
        status = "proposed" if body.proposed or sensitive else "active"
        if status == "active" and self._active_count(user_id) >= get_settings().ai_memory_max_active_items:
            raise MemoryConflict("Active memory limit reached")
        conflict = self._conflict(user_id, body)
        if conflict:
            ai_memory_metrics.increment("memory", "conflict")
        stale_after = body.stale_after
        if stale_after is None and status == "active":
            stale_days = {
                "risk_policy": 365,
                "portfolio_constraint": 365,
                "watchlist_interest": 180,
                "project_context": 365,
                "recurring_workflow": 90,
            }.get(body.memory_type.value)
            stale_after = now + timedelta(days=stale_days) if stale_days else None
        item = AIUserMemory(
            user_id=user_id,
            memory_type=body.memory_type.value,
            scope=body.scope.value,
            scope_key=body.scope_key,
            status=status,
            title=body.title,
            content=body.content,
            structured_value=body.structured_value,
            origin=body.origin,
            confidence=body.confidence,
            importance=body.importance,
            normalized_content_hash=signature,
            source_conversation_id=body.source_conversation_id,
            source_message_id=body.source_message_id,
            effective_from=now if status == "active" else None,
            expires_at=body.expires_at,
            stale_after=stale_after,
            last_confirmed_at=now if status == "active" else None,
            confirmed_at=now if status == "active" else None,
            supersedes_memory_id=conflict.id if conflict else None,
            conflict_group=(
                conflict.conflict_group or uuid4().hex if conflict else None
            ),
        )
        if conflict and not conflict.conflict_group:
            conflict.conflict_group = item.conflict_group
        self.db.add(item)
        self.db.flush()
        self._event(
            item,
            "proposed" if status == "proposed" else "confirmed",
            conversation_id=body.source_conversation_id,
            message_id=body.source_message_id,
        )
        if conflict and status == "active":
            self._supersede(conflict, item)
        self.db.commit()
        self.db.refresh(item)
        ai_memory_metrics.increment("memory", status)
        audit_event(
            "memory.create",
            user_id=user_id,
            memory_id=item.id,
            status=item.status,
            memory_type=item.memory_type,
            scope=item.scope,
            origin=item.origin,
            conversation_id=item.source_conversation_id,
            message_id=item.source_message_id,
        )
        return memory_out(item)

    def _supersede(
        self, old: AIUserMemory, replacement: AIUserMemory
    ) -> None:
        before = _snapshot(old)
        old.status = "archived"
        old.archived_at = utcnow()
        old.updated_at = old.archived_at
        self._event(old, "superseded", before=before)
        replacement.supersedes_memory_id = old.id

    def list_memories(
        self,
        user_id: int,
        *,
        status: str | None = None,
        memory_type: str | None = None,
        scope: str | None = None,
        scope_key: str | None = None,
        source_conversation_id: int | None = None,
        created_after: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MemoryPage:
        self.refresh_lifecycle(user_id)
        filters = [
            AIUserMemory.user_id == user_id,
            AIUserMemory.deleted_at.is_(None),
        ]
        if status:
            filters.append(AIUserMemory.status == status)
        if memory_type:
            filters.append(AIUserMemory.memory_type == memory_type)
        if scope:
            filters.append(AIUserMemory.scope == scope)
        if scope_key:
            filters.append(AIUserMemory.scope_key == scope_key)
        if source_conversation_id:
            filters.append(
                AIUserMemory.source_conversation_id == source_conversation_id
            )
        if created_after:
            filters.append(AIUserMemory.created_at >= created_after)
        if cursor:
            try:
                filters.append(AIUserMemory.id < int(cursor))
            except ValueError:
                raise MemoryConflict("Invalid cursor") from None
        total = int(
            self.db.scalar(select(func.count(AIUserMemory.id)).where(*filters)) or 0
        )
        rows = list(
            self.db.scalars(
                select(AIUserMemory)
                .where(*filters)
                .order_by(AIUserMemory.id.desc())
                .limit(min(max(limit, 1), 100) + 1)
            )
        )
        next_cursor = str(rows[limit - 1].id) if len(rows) > limit else None
        rows = rows[:limit]
        return MemoryPage(
            items=[memory_out(row) for row in rows],
            total=total,
            limit=limit,
            cursor=next_cursor,
        )

    def detail(self, memory_id: int, user_id: int) -> MemoryDetailOut:
        item = self._memory(memory_id, user_id)
        events = list(
            self.db.scalars(
                select(AIMemoryEvent)
                .where(
                    AIMemoryEvent.memory_id == item.id,
                    AIMemoryEvent.user_id == user_id,
                )
                .order_by(AIMemoryEvent.created_at.desc(), AIMemoryEvent.id.desc())
            )
        )
        return MemoryDetailOut(
            **memory_out(item).model_dump(),
            events=[
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "before_value": row.before_value,
                    "after_value": row.after_value,
                    "conversation_id": row.conversation_id,
                    "message_id": row.message_id,
                    "created_at": row.created_at,
                }
                for row in events
            ],
        )

    def patch_memory(
        self, memory_id: int, user_id: int, body: MemoryPatch
    ) -> MemoryOut:
        item = self._memory(memory_id, user_id)
        before = _snapshot(item)
        values = body.model_dump(exclude_unset=True)
        if "memory_type" in values:
            values["memory_type"] = values["memory_type"].value
        if "scope" in values:
            values["scope"] = values["scope"].value
        if values.get("content"):
            if is_transient_market_fact(values["content"]):
                raise MemoryConflict(
                    "Short-lived market facts cannot be saved as memory"
                )
            if contains_sensitive_content(values["content"]) and not get_settings().ai_memory_sensitive_storage_enabled:
                raise MemoryConflict("Sensitive memory storage is disabled")
            values["normalized_content_hash"] = memory_signature(values["content"])
        target_scope = values.get("scope", item.scope)
        target_key = values.get("scope_key", item.scope_key)
        if target_scope != "global" and not target_key:
            raise MemoryConflict("scope_key is required for non-global memories")
        if target_scope == "global":
            values["scope_key"] = None
        for key, value in values.items():
            setattr(item, key, value)
        item.updated_at = utcnow()
        self._event(item, "edited", before=before)
        self.db.commit()
        self.db.refresh(item)
        ai_memory_metrics.increment("memory", "edited")
        audit_event(
            "memory.edited",
            user_id=user_id,
            memory_id=item.id,
            status=item.status,
            memory_type=item.memory_type,
            scope=item.scope,
        )
        return memory_out(item)

    def _transition(
        self, item: AIUserMemory, status: str, event_type: str
    ) -> MemoryOut:
        before = _snapshot(item)
        now = utcnow()
        item.status = status
        item.updated_at = now
        if status == "active":
            item.confirmed_at = item.confirmed_at or now
            item.last_confirmed_at = now
            item.effective_from = item.effective_from or now
            item.archived_at = None
            if item.supersedes_memory_id:
                old = self.db.scalar(
                    select(AIUserMemory).where(
                        AIUserMemory.id == item.supersedes_memory_id,
                        AIUserMemory.user_id == item.user_id,
                        AIUserMemory.status == "active",
                    )
                )
                if old:
                    self._supersede(old, item)
        elif status == "rejected":
            item.rejected_at = now
        elif status == "archived":
            item.archived_at = now
        elif status == "deleted":
            item.deleted_at = now
        self._event(item, event_type, before=before)
        self.db.commit()
        self.db.refresh(item)
        ai_memory_metrics.increment("memory", event_type)
        if status == "active" and event_type != "active":
            ai_memory_metrics.increment("memory", "active")
        audit_event(
            f"memory.{event_type}",
            user_id=item.user_id,
            memory_id=item.id,
            status=item.status,
            memory_type=item.memory_type,
            scope=item.scope,
        )
        return memory_out(item)

    def confirm(self, memory_id: int, user_id: int) -> MemoryOut:
        item = self._memory(memory_id, user_id)
        if contains_sensitive_content(item.content) and not get_settings().ai_memory_sensitive_storage_enabled:
            raise MemoryConflict("Sensitive memory storage is disabled")
        if item.status not in {"proposed", "stale", "expired", "archived"}:
            if item.status == "active":
                return self._transition(item, "active", "confirmed")
            raise MemoryConflict("Memory cannot be confirmed from its current state")
        if (
            self._active_count(user_id)
            >= get_settings().ai_memory_max_active_items
            and item.supersedes_memory_id is None
        ):
            raise MemoryConflict("Active memory limit reached")
        return self._transition(item, "active", "confirmed")

    def reject(self, memory_id: int, user_id: int) -> MemoryOut:
        item = self._memory(memory_id, user_id)
        if item.status != "proposed":
            raise MemoryConflict("Only proposed memory can be rejected")
        return self._transition(item, "rejected", "rejected")

    def archive(self, memory_id: int, user_id: int) -> MemoryOut:
        return self._transition(
            self._memory(memory_id, user_id), "archived", "archived"
        )

    def restore(self, memory_id: int, user_id: int) -> MemoryOut:
        item = self._memory(memory_id, user_id)
        if item.status != "archived":
            raise MemoryConflict("Only archived memory can be restored")
        return self._transition(item, "active", "restored")

    def delete(self, memory_id: int, user_id: int) -> None:
        self._transition(
            self._memory(memory_id, user_id), "deleted", "deleted"
        )

    def refresh_lifecycle(self, user_id: int) -> int:
        now = utcnow()
        rows = list(
            self.db.scalars(
                select(AIUserMemory).where(
                    AIUserMemory.user_id == user_id,
                    AIUserMemory.status == "active",
                    AIUserMemory.deleted_at.is_(None),
                    or_(
                        AIUserMemory.expires_at <= now,
                        AIUserMemory.stale_after <= now,
                    ),
                )
            )
        )
        for row in rows:
            before = _snapshot(row)
            if row.expires_at and _aware(row.expires_at) <= now:
                row.status = "expired"
                event = "expired"
            else:
                row.status = "stale"
                event = "staled"
            row.updated_at = now
            self._event(row, event, before=before)
            ai_memory_metrics.increment("memory", event)
            audit_event(
                f"memory.{event}",
                user_id=user_id,
                memory_id=row.id,
                status=row.status,
                memory_type=row.memory_type,
                scope=row.scope,
            )
        if rows:
            self.db.commit()
        return len(rows)

    def forget(
        self, user_id: int, query: str, *, delete: bool = False
    ) -> ForgetResult:
        normalized = normalize_memory_content(query)
        terms = [term for term in re.split(r"\s+", normalized) if len(term) >= 2]
        rows = list(
            self.db.scalars(
                select(AIUserMemory)
                .where(
                    AIUserMemory.user_id == user_id,
                    AIUserMemory.status.in_(("active", "stale", "expired")),
                    AIUserMemory.deleted_at.is_(None),
                )
                .order_by(AIUserMemory.updated_at.desc())
            )
        )
        matches = [
            row
            for row in rows
            if normalized in normalize_memory_content(row.content)
            or any(term in normalize_memory_content(row.content) for term in terms)
        ]
        if len(matches) == 1:
            if delete:
                self.delete(matches[0].id, user_id)
            else:
                self.archive(matches[0].id, user_id)
            matches[0] = self._memory(matches[0].id, user_id) if not delete else matches[0]
            return ForgetResult(
                matched=[memory_out(matches[0])],
                changed=True,
                requires_selection=False,
            )
        return ForgetResult(
            matched=[memory_out(row) for row in matches[:20]],
            changed=False,
            requires_selection=len(matches) > 1,
        )


class DecisionNotFound(LookupError):
    pass


class DecisionConflict(ValueError):
    pass


class InvestmentDecisionService:
    def __init__(self, db: Session):
        self.db = db
        self._portfolio_summary_cache: dict[int, dict] = {}

    def _enabled(self) -> None:
        if not get_settings().ai_investment_decisions_enabled:
            raise DecisionConflict("Investment decisions are disabled")

    def _decision(self, decision_id: int, user_id: int) -> AIInvestmentDecision:
        item = self.db.scalar(
            select(AIInvestmentDecision).where(
                AIInvestmentDecision.id == decision_id,
                AIInvestmentDecision.user_id == user_id,
                AIInvestmentDecision.deleted_at.is_(None),
            )
        )
        if item is None:
            raise DecisionNotFound("Investment decision not found")
        return item

    def _portfolio(self, portfolio_id: int | None, user_id: int) -> None:
        if portfolio_id is None:
            return
        if self.db.scalar(
            select(Portfolio.id).where(
                Portfolio.id == portfolio_id, Portfolio.user_id == user_id
            )
        ) is None:
            raise DecisionNotFound("Portfolio not found")

    def _message(self, message_id: int | None, user_id: int) -> AIMessage | None:
        if message_id is None:
            return None
        row = self.db.scalar(
            select(AIMessage).where(
                AIMessage.id == message_id,
                AIMessage.user_id == user_id,
                AIMessage.deleted_at.is_(None),
            )
        )
        if row is None:
            raise DecisionNotFound("Message not found")
        return row

    def _load_related(
        self, ids: list[int], user_id: int
    ) -> tuple[
        dict[int, list[AIInvestmentDecisionEvidence]],
        dict[int, list[AIInvestmentDecisionReview]],
    ]:
        evidence = {value: [] for value in ids}
        reviews = {value: [] for value in ids}
        if not ids:
            return evidence, reviews
        for row in self.db.scalars(
            select(AIInvestmentDecisionEvidence)
            .where(
                AIInvestmentDecisionEvidence.decision_id.in_(ids),
                AIInvestmentDecisionEvidence.user_id == user_id,
            )
            .order_by(
                AIInvestmentDecisionEvidence.decision_id,
                AIInvestmentDecisionEvidence.created_at,
            )
        ):
            evidence[row.decision_id].append(row)
        for row in self.db.scalars(
            select(AIInvestmentDecisionReview)
            .where(
                AIInvestmentDecisionReview.decision_id.in_(ids),
                AIInvestmentDecisionReview.user_id == user_id,
            )
            .order_by(
                AIInvestmentDecisionReview.decision_id,
                AIInvestmentDecisionReview.created_at,
            )
        ):
            reviews[row.decision_id].append(row)
        return evidence, reviews

    def _next_number(self, user_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.coalesce(func.max(AIInvestmentDecision.decision_number), 0)).where(
                    AIInvestmentDecision.user_id == user_id
                )
            )
            or 0
        ) + 1

    def create(
        self,
        user_id: int,
        body: DecisionCreate,
        *,
        resolution_type: str = "standalone",
        supersedes_decision_id: int | None = None,
        merged_from_ids: list[int] | None = None,
    ) -> DecisionOut:
        self._enabled()
        self._portfolio(body.portfolio_id, user_id)
        self._message(body.source_user_message_id, user_id)
        self._message(body.source_assistant_message_id, user_id)
        if body.source_conversation_id and self.db.scalar(
            select(AIConversation.id).where(
                AIConversation.id == body.source_conversation_id,
                AIConversation.user_id == user_id,
            )
        ) is None:
            raise DecisionNotFound("Conversation not found")
        item = AIInvestmentDecision(
            user_id=user_id,
            decision_number=self._next_number(user_id),
            title=body.title,
            decision_type=body.decision_type,
            status="draft",
            primary_symbol=body.symbols[0] if body.symbols else None,
            symbols=body.symbols,
            portfolio_id=body.portfolio_id,
            decision_date=body.decision_date,
            time_horizon=body.time_horizon,
            target_review_at=body.target_review_at,
            action=body.action,
            position_intent=body.position_intent,
            target_weight=body.target_weight,
            target_quantity=body.target_quantity,
            target_price_min=body.target_price_min,
            target_price_max=body.target_price_max,
            thesis=body.thesis,
            catalysts=body.catalysts,
            risks=body.risks,
            invalidation_conditions=body.invalidation_conditions,
            assumptions=body.assumptions,
            open_questions=body.open_questions,
            structured_conditions=[value.model_dump(mode="json") for value in body.structured_conditions],
            confidence=body.confidence,
            priority=body.priority,
            source_conversation_id=body.source_conversation_id,
            source_user_message_id=body.source_user_message_id,
            source_assistant_message_id=body.source_assistant_message_id,
            supersedes_decision_id=supersedes_decision_id,
            merged_from_ids=merged_from_ids or [],
            resolution_type=resolution_type,
        )
        self.db.add(item)
        self.db.flush()
        for evidence in body.evidence[
            : get_settings().ai_investment_decision_max_evidence
        ]:
            self._add_evidence(item, evidence)
        self.db.commit()
        self.db.refresh(item)
        ai_memory_metrics.increment("decision", "draft")
        ai_memory_metrics.observe(
            "decision", "evidence_count", len(body.evidence)
        )
        audit_event(
            "decision.create",
            user_id=user_id,
            decision_id=item.id,
            status=item.status,
            decision_type=item.decision_type,
            symbols=list(item.symbols or []),
            conversation_id=item.source_conversation_id,
            message_id=item.source_user_message_id,
            evidence_count=len(body.evidence),
            review_due=decision_out(item).review_due,
        )
        evidence, reviews = self._load_related([item.id], user_id)
        return decision_out(
            item, evidence=evidence[item.id], reviews=reviews[item.id]
        )

    def _add_evidence(
        self, item: AIInvestmentDecision, evidence: EvidenceCreate
    ) -> bool:
        exists = self.db.scalar(
            select(AIInvestmentDecisionEvidence.id).where(
                AIInvestmentDecisionEvidence.decision_id == item.id,
                AIInvestmentDecisionEvidence.source_id == evidence.source_id,
            )
        )
        if exists:
            return False
        url = safe_external_url(evidence.url)
        self.db.add(
            AIInvestmentDecisionEvidence(
                user_id=item.user_id,
                decision_id=item.id,
                source_id=evidence.source_id,
                source_type=evidence.source_type,
                origin=evidence.origin,
                title=evidence.title,
                symbol=evidence.symbol,
                provider=evidence.provider,
                authority=evidence.authority,
                published_at=evidence.published_at,
                retrieved_at=evidence.retrieved_at,
                as_of=evidence.as_of,
                url=url,
                locator=(
                    evidence.locator
                    if evidence.locator
                    and not evidence.locator.startswith("/")
                    and ".." not in evidence.locator.split("/")
                    else None
                ),
                evidence_summary=evidence.evidence_summary,
                evidence_role=evidence.evidence_role,
                freshness_status="unknown",
            )
        )
        return True

    def add_evidence(
        self,
        decision_id: int,
        user_id: int,
        evidence: EvidenceCreate,
    ) -> DecisionOut:
        item = self._decision(decision_id, user_id)
        duplicate = self.db.scalar(
            select(AIInvestmentDecisionEvidence.id).where(
                AIInvestmentDecisionEvidence.decision_id == item.id,
                AIInvestmentDecisionEvidence.user_id == user_id,
                AIInvestmentDecisionEvidence.source_id == evidence.source_id,
            )
        )
        if duplicate:
            return self.detail(item.id, user_id)
        count = int(
            self.db.scalar(
                select(func.count(AIInvestmentDecisionEvidence.id)).where(
                    AIInvestmentDecisionEvidence.decision_id == item.id,
                    AIInvestmentDecisionEvidence.user_id == user_id,
                )
            )
            or 0
        )
        if count >= get_settings().ai_investment_decision_max_evidence:
            raise DecisionConflict("Decision evidence limit reached")
        added = self._add_evidence(item, evidence)
        self.db.commit()
        if added:
            ai_memory_metrics.observe("decision", "evidence_count", count + 1)
            audit_event(
                "decision.evidence_added",
                user_id=user_id,
                decision_id=item.id,
                status=item.status,
                decision_type=item.decision_type,
                symbols=list(item.symbols or []),
                evidence_count=count + 1,
            )
        return self.detail(item.id, user_id)

    def list(
        self,
        user_id: int,
        *,
        status: str | None = None,
        decision_type: str | None = None,
        symbol: str | None = None,
        search: str | None = None,
        time_horizon: str | None = None,
        portfolio_id: int | None = None,
        decision_date_from: date | None = None,
        decision_date_to: date | None = None,
        review_due: bool | None = None,
        min_confidence: float | None = None,
        source_conversation_id: int | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DecisionPage:
        filters = [
            AIInvestmentDecision.user_id == user_id,
            AIInvestmentDecision.deleted_at.is_(None),
        ]
        if status:
            filters.append(AIInvestmentDecision.status == status)
        if decision_type:
            filters.append(
                AIInvestmentDecision.decision_type == decision_type
            )
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    AIInvestmentDecision.title.ilike(term),
                    AIInvestmentDecision.action.ilike(term),
                    AIInvestmentDecision.primary_symbol.ilike(term),
                )
            )
        if time_horizon:
            filters.append(AIInvestmentDecision.time_horizon == time_horizon)
        if portfolio_id is not None:
            filters.append(AIInvestmentDecision.portfolio_id == portfolio_id)
        if decision_date_from:
            filters.append(
                AIInvestmentDecision.decision_date >= decision_date_from
            )
        if decision_date_to:
            filters.append(
                AIInvestmentDecision.decision_date <= decision_date_to
            )
        if min_confidence is not None:
            filters.append(AIInvestmentDecision.confidence >= min_confidence)
        if source_conversation_id:
            filters.append(
                AIInvestmentDecision.source_conversation_id
                == source_conversation_id
            )
        if cursor:
            try:
                filters.append(AIInvestmentDecision.decision_number > int(cursor))
            except ValueError:
                raise DecisionConflict("Invalid cursor") from None
        query = (
            select(AIInvestmentDecision)
            .where(*filters)
            .order_by(AIInvestmentDecision.decision_number.asc())
        )
        python_filter = bool(symbol or review_due is not None)
        rows = list(
            self.db.scalars(
                query
                if python_filter
                else query.limit(min(max(limit, 1), 100) + 1)
            )
        )
        if symbol:
            normalized_symbol = symbol.upper()
            rows = [
                row
                for row in rows
                if normalized_symbol
                in {str(value).upper() for value in row.symbols or []}
            ]
        related_evidence: dict[
            int, list[AIInvestmentDecisionEvidence]
        ] | None = None
        related_reviews: dict[int, list[AIInvestmentDecisionReview]] | None = None
        if review_due is not None:
            related_evidence, related_reviews = self._load_related(
                [row.id for row in rows], user_id
            )
            rows = [
                row
                for row in rows
                if decision_out(
                    row,
                    evidence=related_evidence[row.id],
                    reviews=related_reviews[row.id],
                ).review_due
                is review_due
            ]
        if python_filter:
            total = len(rows)
            rows = rows[: min(max(limit, 1), 100) + 1]
        else:
            total = int(
                self.db.scalar(
                    select(func.count(AIInvestmentDecision.id)).where(*filters)
                )
                or 0
            )
        next_cursor = str(rows[limit - 1].decision_number) if len(rows) > limit else None
        rows = rows[:limit]
        if related_evidence is None or related_reviews is None:
            evidence, reviews = self._load_related(
                [row.id for row in rows], user_id
            )
        else:
            evidence, reviews = related_evidence, related_reviews
        items = []
        for row in rows:
            output = decision_out(row, evidence=evidence[row.id], reviews=reviews[row.id])
            items.append(self._enrich(output, row, user_id))
        ai_memory_metrics.observe(
            "decision",
            "review_due_count",
            sum(1 for item in items if item.review_due),
        )
        return DecisionPage(
            items=items,
            total=total,
            limit=limit,
            cursor=next_cursor,
        )

    def detail(self, decision_id: int, user_id: int) -> DecisionOut:
        item = self._decision(decision_id, user_id)
        evidence, reviews = self._load_related([item.id], user_id)
        output = decision_out(
            item, evidence=evidence[item.id], reviews=reviews[item.id]
        )
        return self._enrich(output, item, user_id)

    def _enrich(self, output: DecisionOut, item: AIInvestmentDecision, user_id: int) -> DecisionOut:
        related_ids = list(dict.fromkeys([*(item.merged_from_ids or []), *([item.supersedes_decision_id] if item.supersedes_decision_id else [])]))
        if related_ids:
            output.related_decision_numbers = list(
                self.db.scalars(
                    select(AIInvestmentDecision.decision_number)
                    .where(AIInvestmentDecision.id.in_(related_ids), AIInvestmentDecision.user_id == user_id)
                    .order_by(AIInvestmentDecision.decision_number)
                )
            )
        symbol = item.primary_symbol
        live: dict[str, Any] = {"symbol": symbol, "conditions": []}
        quote = get_latest_persisted_price_snapshot(self.db, symbol) if symbol else None
        if quote:
            live["current_price"] = quote.last_price
            live["currency"] = quote.currency
            live["quote_time"] = (quote.market_timestamp or quote.fetched_at or quote.persisted_at)
        if symbol:
            position = self.db.scalar(
                select(PortfolioPosition)
                .join(Portfolio, Portfolio.id == PortfolioPosition.portfolio_id)
                .where(Portfolio.user_id == user_id, PortfolioPosition.symbol == symbol, PortfolioPosition.total_quantity > 0)
                .order_by(PortfolioPosition.updated_at.desc())
            )
            if position:
                live["current_quantity"] = position.total_quantity
                if item.target_quantity is not None:
                    live["quantity_to_target"] = float(position.total_quantity) - float(item.target_quantity)
                if item.target_weight is not None:
                    portfolio = self.db.scalar(
                        select(Portfolio).where(
                            Portfolio.id == position.portfolio_id,
                            Portfolio.user_id == user_id,
                        )
                    )
                    if portfolio:
                        summary = self._portfolio_summary_cache.get(portfolio.id)
                        if summary is None:
                            summary = build_portfolio_summary(
                                self.db, portfolio, cached_fx_only=True
                            )
                            self._portfolio_summary_cache[portfolio.id] = summary
                        position_view = next(
                            (
                                value
                                for value in summary["positions"]
                                if value["symbol"] == symbol
                            ),
                            None,
                        )
                        if position_view and position_view["portfolio_weight"] is not None:
                            current_weight = float(position_view["portfolio_weight"])
                            target_weight = float(item.target_weight) * 100
                            live["current_weight_percent"] = current_weight
                            live["target_weight_percent"] = target_weight
                            live["weight_to_target_percent"] = current_weight - target_weight
        current_price = float(quote.last_price) if quote else None
        today = date.today()
        for raw in item.structured_conditions or []:
            condition = dict(raw)
            annotation: dict[str, Any] = {"description": condition.get("description"), "category": condition.get("category"), "metric": condition.get("metric"), "triggered": None}
            threshold = condition.get("threshold")
            operator = condition.get("operator")
            if condition.get("metric") == "price" and threshold is not None and current_price is not None:
                threshold_value = float(threshold)
                annotation["current_value"] = current_price
                annotation["threshold"] = threshold_value
                annotation["distance"] = threshold_value - current_price
                annotation["distance_percent"] = ((threshold_value / current_price) - 1) * 100 if current_price else None
                annotation["triggered"] = {"gte": current_price >= threshold_value, "gt": current_price > threshold_value, "lte": current_price <= threshold_value, "lt": current_price < threshold_value}.get(operator)
            event_date = condition.get("event_date")
            if event_date:
                parsed = date.fromisoformat(str(event_date))
                annotation["event_date"] = parsed
                annotation["days_until"] = (parsed - today).days
                annotation["triggered"] = today >= parsed
            live["conditions"].append(annotation)
        if symbol:
            upcoming = list(self.db.scalars(
                select(InvestmentCalendarEvent)
                .where(InvestmentCalendarEvent.symbol == symbol, InvestmentCalendarEvent.status == "active", InvestmentCalendarEvent.event_date >= today)
                .order_by(InvestmentCalendarEvent.event_date)
                .limit(3)
            ))
            live["upcoming_events"] = [{"title": row.title, "event_type": row.event_type, "event_date": row.event_date, "days_until": (row.event_date - today).days} for row in upcoming]
        output.live_context = live
        return output

    def patch(
        self, decision_id: int, user_id: int, body: DecisionPatch
    ) -> DecisionOut:
        item = self._decision(decision_id, user_id)
        values = body.model_dump(exclude_unset=True)
        if item.status != "draft" and CORE_DECISION_FIELDS & values.keys():
            raise DecisionConflict(
                "Confirmed thesis is immutable; save material changes as a review"
            )
        if "portfolio_id" in values:
            self._portfolio(values["portfolio_id"], user_id)
        for key, value in values.items():
            if key == "structured_conditions":
                value = [entry.model_dump(mode="json") for entry in value]
            setattr(item, key, value)
        if "symbols" in values:
            item.primary_symbol = values["symbols"][0] if values["symbols"] else None
        item.updated_at = utcnow()
        self.db.commit()
        return self.detail(item.id, user_id)

    def confirm(self, decision_id: int, user_id: int) -> DecisionOut:
        item = self._decision(decision_id, user_id)
        if item.status != "draft":
            raise DecisionConflict("Only draft decisions can be confirmed")
        item.status = "active"
        item.updated_at = utcnow()
        self.db.commit()
        details = self.detail(item.id, user_id)
        ai_memory_metrics.increment("decision", "active")
        audit_event(
            "decision.confirmed",
            user_id=user_id,
            decision_id=item.id,
            status=item.status,
            decision_type=item.decision_type,
            symbols=list(item.symbols or []),
            evidence_count=len(details.evidence),
            review_due=details.review_due,
        )
        return details

    def transition(
        self, decision_id: int, user_id: int, status: str
    ) -> DecisionOut:
        item = self._decision(decision_id, user_id)
        allowed = {
            "cancelled": {"draft", "active"},
            "invalidated": {"active", "partially_executed", "executed"},
            "closed": {"active", "partially_executed", "executed"},
            "archived": {
                "active",
                "cancelled",
                "invalidated",
                "closed",
                "executed",
                "partially_executed",
            },
        }
        if item.status not in allowed.get(status, set()):
            raise DecisionConflict("Invalid decision state transition")
        now = utcnow()
        item.status = status
        item.updated_at = now
        if status == "invalidated":
            item.invalidated_at = now
        elif status == "closed":
            item.closed_at = now
        self.db.commit()
        details = self.detail(item.id, user_id)
        ai_memory_metrics.increment("decision", status)
        audit_event(
            f"decision.{status}",
            user_id=user_id,
            decision_id=item.id,
            status=item.status,
            decision_type=item.decision_type,
            symbols=list(item.symbols or []),
            review_due=details.review_due,
        )
        return details

    def execute(
        self,
        decision_id: int,
        user_id: int,
        body: ExecuteDecisionRequest,
    ) -> DecisionOut:
        item = self._decision(decision_id, user_id)
        if item.status != "active":
            raise DecisionConflict("Only active decisions can be marked executed")
        if body.trade_id:
            trade = self.db.scalar(
                select(TradeTransaction)
                .join(Portfolio, Portfolio.id == TradeTransaction.portfolio_id)
                .where(
                    TradeTransaction.id == body.trade_id,
                    Portfolio.user_id == user_id,
                )
            )
            if trade is None:
                raise DecisionNotFound("Trade not found")
            item.executed_trade_id = trade.id
        item.status = body.execution_status
        item.executed_at = utcnow()
        item.updated_at = item.executed_at
        self.db.commit()
        ai_memory_metrics.increment("decision", item.status)
        audit_event(
            f"decision.{item.status}",
            user_id=user_id,
            decision_id=item.id,
            status=item.status,
            decision_type=item.decision_type,
            symbols=list(item.symbols or []),
        )
        return self.detail(item.id, user_id)

    def delete(self, decision_id: int, user_id: int) -> None:
        item = self._decision(decision_id, user_id)
        item.deleted_at = utcnow()
        item.updated_at = item.deleted_at
        self.db.commit()
        ai_memory_metrics.increment("decision", "deleted")
        audit_event(
            "decision.deleted",
            user_id=user_id,
            decision_id=item.id,
            status=item.status,
            decision_type=item.decision_type,
            symbols=list(item.symbols or []),
        )

    def add_review(
        self, decision_id: int, user_id: int, body: ReviewCreate
    ):
        item = self._decision(decision_id, user_id)
        if body.linked_message_id:
            self._message(body.linked_message_id, user_id)
        if body.linked_conversation_id and self.db.scalar(
            select(AIConversation.id).where(
                AIConversation.id == body.linked_conversation_id,
                AIConversation.user_id == user_id,
            )
        ) is None:
            raise DecisionNotFound("Conversation not found")
        now = utcnow()
        row = AIInvestmentDecisionReview(
            user_id=user_id,
            decision_id=item.id,
            review_type=body.review_type,
            status=body.status,
            reviewed_at=now if body.status == "completed" else None,
            data_as_of=body.data_as_of,
            thesis_status=body.thesis_status,
            invalidation_status=body.invalidation_status,
            execution_status=body.execution_status,
            what_changed=body.what_changed,
            supporting_changes=body.supporting_changes,
            contradicting_changes=body.contradicting_changes,
            lessons=body.lessons,
            next_action=body.next_action,
            linked_message_id=body.linked_message_id,
            linked_conversation_id=body.linked_conversation_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        metric = (
            "review_completed" if row.status == "completed" else "review_draft"
        )
        ai_memory_metrics.increment("decision", metric)
        audit_event(
            f"decision.{metric}",
            user_id=user_id,
            decision_id=item.id,
            status=item.status,
            decision_type=item.decision_type,
            symbols=list(item.symbols or []),
            review_due=decision_out(item).review_due,
        )
        return self.detail(item.id, user_id).reviews[-1]

    def review_draft(
        self, decision_id: int, user_id: int, *, web_access_mode: str = "off"
    ):
        if web_access_mode.startswith("deep_"):
            raise DecisionConflict(
                "Deep Search review requires an explicit chat research request"
            )
        item = self._decision(decision_id, user_id)
        # A bounded, non-paid draft preserves the original thesis. The user can
        # ask the normal orchestrator for fresh tool-backed analysis and then
        # edit/confirm this independent review record.
        return self.add_review(
            item.id,
            user_id,
            ReviewCreate(
                status="draft",
                data_as_of=utcnow(),
                thesis_status="uncertain",
                invalidation_status="unknown",
                what_changed="等待用户使用站内只读工具复核原投资逻辑。",
                next_action="复核催化剂、风险与失效条件后再确认保存。",
            ),
        )

    def _evidence_from_assistant(self, assistant: AIMessage | None, user_id: int) -> list[EvidenceCreate]:
        evidence: list[EvidenceCreate] = []
        if assistant is None:
            return evidence
        citations = list(self.db.scalars(select(AIMessageCitation).where(
            AIMessageCitation.message_id == assistant.id,
            AIMessageCitation.user_id == user_id,
        )))
        for row in citations[: get_settings().ai_investment_decision_max_evidence]:
            evidence.append(EvidenceCreate(
                source_id=row.source_id, source_type=row.source_type,
                origin="deep_search" if assistant.web_access_mode.startswith("deep_") else ("web" if assistant.web_access_mode == "search" else "internal"),
                title=row.title, symbol=row.symbol, provider=row.provider, authority=row.authority,
                published_at=row.published_at, retrieved_at=row.retrieved_at, url=row.url,
                locator=row.locator, evidence_summary=row.title[:1000],
            ))
        return evidence

    async def preview_from_message(self, message_id: int, user_id: int) -> DecisionDraftPreview:
        message = self._message(message_id, user_id)
        assert message is not None
        if message.role == "assistant":
            assistant = message
            user_message = self._message(message.parent_message_id, user_id)
        else:
            user_message = message
            assistant = self.db.scalar(
                select(AIMessage)
                .where(
                    AIMessage.parent_message_id == message.id,
                    AIMessage.user_id == user_id,
                    AIMessage.role == "assistant",
                    AIMessage.deleted_at.is_(None),
                )
                .order_by(
                    AIMessage.generation_index.desc(), AIMessage.id.desc()
                )
            )
        conversation = self.db.scalar(select(AIConversation).where(AIConversation.id == message.conversation_id, AIConversation.user_id == user_id))
        recent_desc = list(self.db.scalars(
            select(AIMessage).where(
                AIMessage.conversation_id == message.conversation_id,
                AIMessage.user_id == user_id,
                AIMessage.id <= message.id,
                AIMessage.deleted_at.is_(None),
                AIMessage.status.in_(("completed", "partial", "cancelled")),
                AIMessage.content != "",
            ).order_by(AIMessage.id.desc()).limit(200)
        ))
        character_limit = max(8000, int(get_settings().ai_max_context_chars * 0.8))
        rows: list[AIMessage] = []
        characters = 0
        for row in recent_desc:
            if rows and characters + len(row.content) > character_limit:
                break
            rows.append(row)
            characters += len(row.content)
        rows.reverse()
        previous_summary = None
        if rows:
            previous_summary = self.db.scalar(
                select(AIConversationSummarySnapshot)
                .where(
                    AIConversationSummarySnapshot.conversation_id == message.conversation_id,
                    AIConversationSummarySnapshot.user_id == user_id,
                    AIConversationSummarySnapshot.status == "completed",
                    AIConversationSummarySnapshot.through_message_id < rows[0].id,
                    AIConversationSummarySnapshot.through_message_id <= message.id,
                )
                .order_by(AIConversationSummarySnapshot.version.desc())
                .limit(1)
            )
        extraction_messages = []
        if previous_summary:
            extraction_messages.append({
                "id": f"summary-{previous_summary.id}",
                "role": "conversation_summary",
                "created_at": previous_summary.completed_at,
                "content": previous_summary.summary_text,
                "structured_summary": previous_summary.structured_summary,
            })
        extraction_messages.extend(
            {"id": row.id, "role": row.role, "created_at": row.created_at, "content": row.content}
            for row in rows
        )
        extracted = await extract_conversation_decision(
            extraction_messages,
            model=(assistant.model if assistant else None) or (conversation.model if conversation else None),
        )
        if not getattr(extracted, "has_decision", True):
            raise DecisionConflict(
                extracted.no_decision_reason
                or "这段对话只有分析，尚未形成可保存的投资决策"
            )
        try:
            draft = extracted.decision()
        except ValueError as exc:
            raise DecisionConflict("AI 返回的证券代码或决策字段无效，请重试") from exc
        draft.source_conversation_id = message.conversation_id
        draft.source_user_message_id = user_message.id if user_message else None
        draft.source_assistant_message_id = assistant.id if assistant else None
        draft.evidence = self._evidence_from_assistant(assistant, user_id)
        symbols = {value.upper() for value in draft.symbols}
        conflicts: list[DecisionOut] = []
        if symbols:
            existing = list(self.db.scalars(select(AIInvestmentDecision).where(
                AIInvestmentDecision.user_id == user_id,
                AIInvestmentDecision.deleted_at.is_(None),
                AIInvestmentDecision.status.in_(("draft", "active", "executed", "partially_executed")),
            ).order_by(AIInvestmentDecision.decision_number)))
            for item in existing:
                if symbols.intersection({str(value).upper() for value in item.symbols or []}):
                    conflicts.append(self.detail(item.id, user_id))
        return DecisionDraftPreview(candidate=draft, conflicts=conflicts, conversation_summary=extracted.conversation_summary)

    async def resolve_preview(
        self, user_id: int, body: DecisionResolveRequest
    ) -> DecisionOut:
        conflicts = [self._decision(value, user_id) for value in list(dict.fromkeys(body.conflict_ids))]
        candidate_symbols = {value.upper() for value in body.candidate.symbols}
        if any(not candidate_symbols.intersection({str(value).upper() for value in row.symbols or []}) for row in conflicts):
            raise DecisionConflict("只能处理同一证券的重复决策")
        if body.resolution in {"replace_existing", "merge"} and not conflicts:
            raise DecisionConflict("没有可替换或合并的既有决策")
        merged = None
        if body.resolution == "merge":
            extracted = await merge_decisions(
                [self.detail(row.id, user_id).model_dump(mode="json", exclude={"evidence", "reviews", "live_context"}) for row in conflicts],
                body.candidate.model_dump(mode="json"),
                model=get_settings().model_medium,
            )
            if not getattr(extracted, "has_decision", True):
                raise DecisionConflict(
                    extracted.no_decision_reason or "这些决策无法形成一致的合并结论"
                )
            try:
                merged = extracted.decision()
            except ValueError as exc:
                raise DecisionConflict("AI 合并结果格式无效，请重试") from exc
            merged.source_conversation_id = body.candidate.source_conversation_id
            merged.source_user_message_id = body.candidate.source_user_message_id
            merged.source_assistant_message_id = body.candidate.source_assistant_message_id
            merged.evidence = body.candidate.evidence
        incoming = self.create(user_id, body.candidate, resolution_type="merge_source" if body.resolution == "merge" else body.resolution)
        incoming_row = self._decision(incoming.id, user_id)
        if body.resolution == "replace_existing":
            incoming_row.supersedes_decision_id = conflicts[-1].id
            for row in conflicts:
                row.status = "archived"
                row.updated_at = utcnow()
            self.db.commit()
            return self.detail(incoming.id, user_id)
        if body.resolution != "merge":
            return incoming
        assert merged is not None
        source_ids = [row.id for row in conflicts] + [incoming.id]
        result = self.create(user_id, merged, resolution_type="merge", merged_from_ids=source_ids)
        for row in [*conflicts, incoming_row]:
            row.status = "archived"
            row.updated_at = utcnow()
        self.db.commit()
        return self.detail(result.id, user_id)


def _symbols_from_text(text: str) -> list[str]:
    blocked = {"AI", "DCF", "FCF", "SEC", "ETF", "API", "USD"}
    values = re.findall(r"(?<![A-Z0-9])([A-Z]{1,5}(?:\.[A-Z]{1,3})?)(?![A-Z0-9])", text)
    return list(dict.fromkeys(value for value in values if value not in blocked))[:20]


def infer_memory_type(text: str) -> str:
    lowered = text.casefold()
    if any(value in lowered for value in ("仓位", "上限", "不超过", "weight")):
        return "portfolio_constraint"
    if any(value in lowered for value in ("估值", "dcf", "fcf", "市盈率")):
        return "valuation_preference"
    if any(value in lowered for value in ("长期投资", "短线", "投资风格")):
        return "investment_style"
    if any(value in lowered for value in ("市场", "美国", "日本", "美股", "日股")):
        return "market_preference"
    if any(value in lowered for value in ("详细", "简洁", "中文", "沟通")):
        return "communication_preference"
    if any(value in lowered for value in ("项目", "长期目标")):
        return "project_context"
    if any(value in lowered for value in ("工作流", "每次", "默认")):
        return "recurring_workflow"
    return "general_preference"


def extract_memory_candidates(text: str) -> list[MemoryCreate]:
    settings = get_settings()
    if (
        not settings.ai_memory_candidate_extraction_enabled
        or contains_sensitive_content(text)
        or is_transient_market_fact(text)
        or any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in INJECTION_PATTERNS
        )
    ):
        return []
    signals = (
        "我更喜欢",
        "我偏好",
        "我主要关注",
        "不要推荐",
        "以后分析",
        "以后默认",
        "从今以后",
        "单股",
        "长期目标",
        "I prefer",
        "please always",
        "from now on",
    )
    if not any(signal.casefold() in text.casefold() for signal in signals):
        return []
    symbols = _symbols_from_text(text)
    memory_type = infer_memory_type(text)
    scope = MemoryScope.global_
    scope_key = None
    if memory_type == "watchlist_interest" and symbols:
        scope, scope_key = MemoryScope.symbol, symbols[0]
    return [
        MemoryCreate(
            memory_type=memory_type,
            scope=scope,
            scope_key=scope_key,
            content=text[:4000],
            confidence=0.9,
            proposed=True,
            origin="conversation_extraction",
        )
    ][: settings.ai_memory_max_candidates_per_message]


def extract_decision_draft(text: str) -> DecisionCreate | None:
    if any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in INJECTION_PATTERNS
    ):
        return None
    lowered = text.casefold()
    mapping = [
        (("决定买", "准备买", "buy"), "buy"),
        (("加仓", "add"), "add"),
        (("继续持有", "持有", "hold"), "hold"),
        (("减仓", "reduce"), "reduce"),
        (("卖出", "清仓", "sell"), "sell"),
        (("暂时不买", "避免", "avoid"), "avoid"),
        (("观察", "watch"), "watch"),
        (("再平衡", "rebalance"), "rebalance"),
        (("对冲", "hedge"), "hedge"),
    ]
    decision_type = next(
        (value for signals, value in mapping if any(s in lowered for s in signals)),
        None,
    )
    explicit = any(
        signal in lowered
        for signal in (
            "我决定",
            "我准备",
            "继续持有",
            "暂时不买",
            "我的投资逻辑",
            "记成我的投资决策",
            "保存这个投资逻辑",
        )
    )
    if not decision_type or not explicit:
        return None
    symbols = _symbols_from_text(text)
    conditions = []
    if "如果" in text:
        conditions = [text[text.index("如果") :][:1000]]
    return DecisionCreate(
        title=f"{symbols[0] if symbols else '投资'} · {decision_type}",
        decision_type=decision_type,
        symbols=symbols,
        action=text[:4000],
        time_horizon="long_term" if "长期" in text else "unspecified",
        thesis=[text[:1000]],
        invalidation_conditions=conditions,
        confidence=0.7,
    )


def process_user_message(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    message_id: int,
    text: str,
) -> dict[str, list[int] | str | bool]:
    result: dict[str, list[int] | str | bool] = {
        "memory_ids": [],
        "decision_ids": [],
    }
    settings = get_settings()
    memory_service = AIMemoryService(db)
    normalized = text.strip()
    forget_match = re.match(
        r"^\s*(?:忘记|不要再记|forget)\s*[：:，,\s]*(.+)$",
        normalized,
        re.IGNORECASE,
    )
    if forget_match and settings.ai_memory_enabled:
        outcome = memory_service.forget(user_id, forget_match.group(1))
        result["forgot"] = outcome.changed
        result["forget_requires_selection"] = outcome.requires_selection
        return result
    explicit_match = re.match(
        r"^\s*(?:记住|请记住|以后都|从今以后|remember(?: that)?|from now on)\s*[：:，,\s]*(.+)$",
        normalized,
        re.IGNORECASE,
    )
    if explicit_match and settings.ai_memory_enabled:
        content = explicit_match.group(1).strip()
        if content:
            item = memory_service.create_memory(
                user_id,
                MemoryCreate(
                    memory_type=infer_memory_type(content),
                    content=content,
                    proposed=settings.ai_memory_explicit_save_requires_confirmation,
                    origin="explicit_user_request",
                    confidence=1.0,
                    source_conversation_id=conversation_id,
                    source_message_id=message_id,
                ),
            )
            result["memory_ids"] = [item.id]
    elif memory_service.settings(user_id).candidate_extraction_enabled:
        for candidate in extract_memory_candidates(text):
            candidate.source_conversation_id = conversation_id
            candidate.source_message_id = message_id
            try:
                item = memory_service.create_memory(user_id, candidate)
            except MemoryConflict:
                continue
            if item.status == "proposed":
                result["memory_ids"] = [
                    *result["memory_ids"],  # type: ignore[list-item]
                    item.id,
                ]
    if (
        settings.ai_investment_decisions_enabled
        and settings.ai_investment_decision_draft_suggestions
    ):
        draft = extract_decision_draft(text)
        if draft:
            draft.source_conversation_id = conversation_id
            draft.source_user_message_id = message_id
            item = InvestmentDecisionService(db).create(user_id, draft)
            result["decision_ids"] = [item.id]
    return result


def record_context_usage(
    db: Session,
    *,
    user_id: int,
    assistant_message_id: int,
    memory_ids: list[int],
    decision_ids: list[int],
) -> None:
    now = utcnow()
    unique_memory_ids = list(dict.fromkeys(memory_ids))
    memories = {
        row.id: row
        for row in db.scalars(
            select(AIUserMemory).where(
                AIUserMemory.id.in_(unique_memory_ids),
                AIUserMemory.user_id == user_id,
                AIUserMemory.status == "active",
                AIUserMemory.deleted_at.is_(None),
            )
        )
    }
    memory_service = AIMemoryService(db)
    for memory_id in unique_memory_ids:
        memory = memories.get(memory_id)
        if memory is None:
            continue
        db.add(
            AIMessageMemoryUsage(
                user_id=user_id,
                message_id=assistant_message_id,
                memory_id=memory_id,
                usage_type="context",
            )
        )
        before = _snapshot(memory)
        memory.last_used_at = now
        memory_service._event(
            memory,
            "used",
            before=before,
            message_id=assistant_message_id,
        )
    for decision_id in list(dict.fromkeys(decision_ids)):
        db.add(
            AIMessageDecisionUsage(
                user_id=user_id,
                message_id=assistant_message_id,
                decision_id=decision_id,
            )
        )
    if memories:
        ai_memory_metrics.increment_by("memory", "used", len(memories))
    db.flush()
