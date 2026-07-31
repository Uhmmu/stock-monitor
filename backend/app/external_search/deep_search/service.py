from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from hashlib import sha256
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import AIConversation, AIMessage, ExternalSearchRun

from ..audit import audit_external_search
from ..budgets import enforce_deep_budget, estimated_effort_cost
from ..enums import (
    TERMINAL_RUN_STATUSES,
    AgentRunStatus,
    DeepSearchEffort,
    WebAccessMode,
)
from ..exceptions import ExternalSearchError
from ..metrics import external_search_metrics
from ..privacy import ExternalQueryPrivacyFilter
from ..registry import get_external_search_registry
from ..repository import ExternalSearchRepository, utcnow
from ..schemas import (
    AgentRun,
    AgentRunCreateRequest,
    DeepRunEventOut,
    DeepRunOut,
    ExternalGroundingSource,
)
from .runtime import deep_search_runtime


def _enabled_effort(effort: DeepSearchEffort) -> bool:
    settings = get_settings()
    return bool(getattr(settings, f"exa_deep_{effort.value}_enabled", False))


def _output_schema(effort: DeepSearchEffort) -> dict:
    if effort in {DeepSearchEffort.minimal, DeepSearchEffort.low}:
        return {
            "type": "object",
            "properties": {
                "executive_summary": {"type": "string"},
                "confirmed_facts": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
                "uncertainties": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
            },
            "required": ["executive_summary", "confirmed_facts", "uncertainties"],
        }
    return {
        "type": "object",
        "properties": {
            "executive_summary": {"type": "string"},
            "confirmed_facts": {
                "type": "array", "maxItems": 12,
                "items": {"type": "object", "properties": {
                    "fact": {"type": "string"}, "date": {"type": ["string", "null"]},
                    "affected_symbols": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
                }, "required": ["fact", "affected_symbols"]},
            },
            "company_impacts": {
                "type": "array", "maxItems": 10,
                "items": {"type": "object", "properties": {
                    "symbol": {"type": "string"},
                    "positive_factors": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
                    "negative_factors": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
                    "uncertainties": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
                }, "required": ["symbol", "positive_factors", "negative_factors", "uncertainties"]},
            },
            "source_conflicts": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "open_questions": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        },
        "required": ["executive_summary", "confirmed_facts", "company_impacts", "source_conflicts", "open_questions"],
    }


class DeepSearchService:
    def __init__(self, db: Session, provider=None):
        self.db = db
        self.repository = ExternalSearchRepository(db)
        self.provider = provider or get_external_search_registry().get("exa")
        self.privacy = ExternalQueryPrivacyFilter()

    @staticmethod
    def _ensure_available(effort: DeepSearchEffort, *, role: str, confirmation: bool) -> None:
        settings = get_settings()
        if not settings.exa_enabled or not settings.exa_deep_search_enabled:
            raise ExternalSearchError("DEEP_SEARCH_DISABLED", "Deep Search is disabled.", status_code=503)
        if not settings.exa_api_key:
            raise ExternalSearchError("WEB_SEARCH_PROVIDER_NOT_CONFIGURED", "External search is not configured.", status_code=503)
        if role not in {item.strip() for item in settings.exa_allowed_roles.split(",") if item.strip()}:
            raise ExternalSearchError("DEEP_SEARCH_NOT_ALLOWED", "Deep Search is not allowed for this account.", status_code=403)
        if not _enabled_effort(effort):
            raise ExternalSearchError("DEEP_SEARCH_NOT_ALLOWED", "Selected Deep Search mode is disabled.", status_code=403)
        requires = (effort == DeepSearchEffort.high and settings.exa_deep_high_confirmation_required) or (effort == DeepSearchEffort.xhigh and settings.exa_deep_xhigh_confirmation_required)
        if requires and not confirmation:
            raise ExternalSearchError("DEEP_SEARCH_CONFIRMATION_REQUIRED", "Selected Deep Search mode requires confirmation.", status_code=409)

    @staticmethod
    def _idempotency(*, user_id: int, conversation_id: int | None, user_message_id: int | None, mode: WebAccessMode, generation_index: int) -> str:
        return sha256(f"{user_id}:{conversation_id}:{user_message_id}:{mode.value}:{generation_index}".encode()).hexdigest()

    async def create_run(
        self, *, user_id: int, role: str, conversation_id: int | None,
        user_message_id: int | None, assistant_message_id: int | None,
        query: str, mode: WebAccessMode, generation_index: int = 1,
        confirmation: bool = False, context=None,
    ) -> ExternalSearchRun:
        effort = mode.effort
        if effort is None:
            raise ExternalSearchError("DEEP_SEARCH_INVALID_EFFORT", "A Deep Search mode is required.", status_code=422)
        self._ensure_available(effort, role=role, confirmation=confirmation)
        if conversation_id is not None and self.db.scalar(select(AIConversation.id).where(AIConversation.id == conversation_id, AIConversation.user_id == user_id)) is None:
            raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Conversation not found.", status_code=404)
        for message_id in (user_message_id, assistant_message_id):
            if message_id is not None and self.db.scalar(select(AIMessage.id).where(AIMessage.id == message_id, AIMessage.user_id == user_id, AIMessage.conversation_id == conversation_id)) is None:
                raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Message not found.", status_code=404)
        key = self._idempotency(user_id=user_id, conversation_id=conversation_id, user_message_id=user_message_id, mode=mode, generation_index=generation_index)
        existing = self.repository.get_by_idempotency(key, user_id)
        if existing is not None:
            return existing
        enforce_deep_budget(self.db, user_id=user_id, effort=effort)
        sanitized = self.privacy.sanitize(query, context)
        if not sanitized.query:
            raise ExternalSearchError("DEEP_SEARCH_CREATE_FAILED", "Deep Search query is empty after privacy filtering.", status_code=422)
        row = self.repository.create(
            public_id=f"dsr_{uuid4().hex}", idempotency_key=key, user_id=user_id,
            conversation_id=conversation_id, user_message_id=user_message_id,
            assistant_message_id=assistant_message_id, provider=self.provider.provider_name,
            mode=mode.value, effort=effort.value, query_hash=sanitized.query_hash,
            query_preview_safe=sanitized.safe_preview if get_settings().exa_query_logging_enabled else None,
            status=AgentRunStatus.pending.value, grounding=[], usage={},
            cost_usd=estimated_effort_cost(effort), cost_estimated=True,
        )
        self.repository.add_event(row, "deep_search.created", status=row.status, data={"stage": "preparing"})
        self.db.commit()
        try:
            created = await self.provider.create_agent_run(AgentRunCreateRequest(
                query=sanitized.query,
                effort=effort,
                output_schema=_output_schema(effort),
                system_prompt=(
                    "Research only public information. Prefer official government, regulator, SEC, company filing and investor-relations sources, then high-quality financial reporting. "
                    "Use explicit dates, distinguish confirmed facts from inference, retain material source conflicts, and never seek contact details."
                ),
                metadata={"application": "stock-monitor", "mode": mode.value},
            ), stream=False)
            if not isinstance(created, AgentRun):
                raise ExternalSearchError("DEEP_SEARCH_CREATE_FAILED", "Deep Search provider returned an invalid run.")
        except ExternalSearchError as exc:
            self.db.rollback()
            row = self.repository.get_for_user(row.public_id, user_id)
            if row is not None:
                row.status = AgentRunStatus.failed.value
                row.error_code = exc.code
                row.error_message_safe = exc.message[:500]
                row.updated_at = utcnow()
                row.completed_at = utcnow()
                self.repository.add_event(row, "deep_search.failed", status=row.status, data={"message": exc.message})
                self.db.commit()
            raise
        row = self.repository.get_for_user(row.public_id, user_id)
        if row is None:
            raise ExternalSearchError("DEEP_SEARCH_CREATE_FAILED", "Deep Search run could not be persisted.")
        row.provider_run_id = created.id
        row.status = created.status.value
        row.started_at = created.created_at if created.status == AgentRunStatus.running else None
        row.last_synced_at = utcnow()
        row.updated_at = utcnow()
        self.repository.add_event(row, f"deep_search.{created.status.value}", status=row.status, data={"stage": "searching"})
        self.db.commit()
        audit_external_search("deep.create", local_run_id=row.public_id, user_id=user_id, conversation_id=conversation_id, effort=effort.value, query_hash=sanitized.query_hash, query_length=sanitized.query_length, status=row.status)
        return row

    @staticmethod
    def _apply_provider_run(db: Session, row: ExternalSearchRun, run: AgentRun) -> ExternalSearchRun:
        repo = ExternalSearchRepository(db)
        now = utcnow()
        previous_status = row.status
        row.status = run.status.value
        row.termination_reason = run.stop_reason
        row.last_synced_at = now
        row.updated_at = now
        if run.status == AgentRunStatus.running and row.started_at is None:
            row.started_at = run.created_at or now
        if run.status == AgentRunStatus.completed:
            row.output_text = (run.output_text or "")[:100000] or None
            row.output_structured = run.output_structured
            row.grounding = [item.model_dump(mode="json") for item in run.grounding][:200]
            row.usage = run.usage
            row.completed_at = run.completed_at or now
            row.error_code = None
            row.error_message_safe = None
        elif run.status == AgentRunStatus.failed:
            row.error_code = run.error_code or "DEEP_SEARCH_FAILED"
            row.error_message_safe = run.error_message_safe or "Deep research failed."
            row.completed_at = run.completed_at or now
        elif run.status == AgentRunStatus.cancelled:
            row.cancelled_at = run.completed_at or now
        if run.cost_usd is not None:
            row.cost_usd = run.cost_usd
            row.cost_estimated = False
        state_changed = previous_status != row.status
        if state_changed or run.status in TERMINAL_RUN_STATUSES:
            event_name = f"deep_search.{run.status.value}"
            repo.add_event(row, event_name, status=row.status, data={
                "stage": "complete" if run.status == AgentRunStatus.completed else run.status.value,
                "source_count": len(run.grounding),
                "cost_usd": str(row.cost_usd) if row.cost_usd is not None else None,
                "cost_estimated": row.cost_estimated,
            })
        if row.assistant_message_id:
            assistant = db.scalar(select(AIMessage).where(AIMessage.id == row.assistant_message_id, AIMessage.user_id == row.user_id))
            if assistant is not None:
                assistant.deep_search_run_id = row.id
                assistant.external_search_call_count = max(assistant.external_search_call_count, 1)
                assistant.external_search_cost_usd = row.cost_usd
                if run.status == AgentRunStatus.cancelled and assistant.status in {"pending", "streaming"}:
                    assistant.status = "cancelled"
                    assistant.cancelled_at = now
                    assistant.updated_at = now
                    assistant.error_code = "DEEP_SEARCH_CANCELLED"
                    assistant.error_message_safe = "Deep research was cancelled."
        db.commit()
        if state_changed or run.status in TERMINAL_RUN_STATUSES:
            external_search_metrics.record("deep", row.status, effort=row.effort)
        return row

    @classmethod
    async def _poll_background(cls, public_id: str, user_id: int, provider=None) -> None:
        settings = get_settings()
        provider = provider or get_external_search_registry().get("exa")
        deadline = asyncio.get_running_loop().time() + min(max(settings.exa_agent_timeout_seconds, 30), 3600)
        while asyncio.get_running_loop().time() < deadline:
            with SessionLocal() as db:
                row = ExternalSearchRepository(db).get_for_user(public_id, user_id)
                if row is None or row.status in {status.value for status in TERMINAL_RUN_STATUSES}:
                    return
                provider_run_id = row.provider_run_id
            if not provider_run_id:
                return
            try:
                run = await provider.get_agent_run(provider_run_id)
            except ExternalSearchError:
                await asyncio.sleep(min(max(settings.exa_agent_poll_interval_seconds, 0.5), 30))
                continue
            with SessionLocal() as db:
                row = ExternalSearchRepository(db).get_for_user(public_id, user_id)
                if row is None:
                    return
                cls._apply_provider_run(db, row, run)
                if run.status in TERMINAL_RUN_STATUSES:
                    return
            await asyncio.sleep(min(max(settings.exa_agent_poll_interval_seconds, 0.5), 30))
        with SessionLocal() as db:
            row = ExternalSearchRepository(db).get_for_user(public_id, user_id)
            if row is not None and row.status not in {status.value for status in TERMINAL_RUN_STATUSES}:
                row.error_code = "DEEP_SEARCH_SYNC_FAILED"
                row.error_message_safe = "Deep research is still running; refresh later to resume status synchronization."
                row.last_synced_at = utcnow()
                db.commit()

    async def ensure_background(self, row: ExternalSearchRun) -> asyncio.Task | None:
        if row.status in {status.value for status in TERMINAL_RUN_STATUSES}:
            return None
        return await deep_search_runtime.start(
            row.public_id, self._poll_background(row.public_id, row.user_id, self.provider)
        )

    async def run_and_wait(self, **kwargs) -> ExternalSearchRun:
        row = await self.create_run(**kwargs)
        task = await self.ensure_background(row)
        if task is not None:
            # Shielding ensures a browser disconnect does not cancel a paid run.
            await asyncio.shield(task)
        self.db.expire_all()
        result = self.repository.get_for_user(row.public_id, row.user_id)
        if result is None:
            raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Deep Search run not found.", status_code=404)
        return result

    async def sync_run(self, public_id: str, user_id: int) -> ExternalSearchRun:
        row = self.repository.get_for_user(public_id, user_id)
        if row is None:
            raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Deep Search run not found.", status_code=404)
        if row.status not in {status.value for status in TERMINAL_RUN_STATUSES} and row.provider_run_id:
            run = await self.provider.get_agent_run(row.provider_run_id)
            row = self._apply_provider_run(self.db, row, run)
            if row.status not in {status.value for status in TERMINAL_RUN_STATUSES}:
                await self.ensure_background(row)
        return row

    async def cancel_run(self, public_id: str, user_id: int) -> ExternalSearchRun:
        row = self.repository.get_for_user(public_id, user_id)
        if row is None:
            raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Deep Search run not found.", status_code=404)
        if row.status in {status.value for status in TERMINAL_RUN_STATUSES}:
            return row
        if not row.provider_run_id:
            row.status = AgentRunStatus.cancelled.value
            row.cancelled_at = utcnow()
            self.repository.add_event(row, "deep_search.cancelled", status=row.status)
            self.db.commit()
            return row
        try:
            run = await self.provider.cancel_agent_run(row.provider_run_id)
        except ExternalSearchError:
            run = await self.provider.get_agent_run(row.provider_run_id)
        return self._apply_provider_run(self.db, row, run)

    def get_run_for_user(self, public_id: str, user_id: int) -> ExternalSearchRun:
        row = self.repository.get_for_user(public_id, user_id)
        if row is None:
            raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Deep Search run not found.", status_code=404)
        return row

    async def recover_stale_runs(self, *, user_id: int | None = None, limit: int = 100) -> list[str]:
        query = select(ExternalSearchRun).where(
            ExternalSearchRun.status.in_(status.value for status in (AgentRunStatus.pending, AgentRunStatus.queued, AgentRunStatus.running))
        )
        if user_id is not None:
            query = query.where(ExternalSearchRun.user_id == user_id)
        rows = list(self.db.scalars(query.order_by(ExternalSearchRun.created_at).limit(min(max(limit, 1), 500))))
        recovered = []
        for row in rows:
            if row.provider_run_id:
                await self.ensure_background(row)
                recovered.append(row.public_id)
        if recovered:
            external_search_metrics.record("deep", "recovered")
        return recovered

    async def replay_provider_events(self, public_id: str, user_id: int) -> list[DeepRunEventOut]:
        row = self.get_run_for_user(public_id, user_id)
        if not row.provider_run_id:
            return self.events(public_id, user_id)
        provider_events = await self.provider.list_agent_run_events(
            row.provider_run_id, after_event_id=row.last_event_id
        )
        for event in provider_events:
            self.repository.add_event(
                row, event.event_type, provider_event_id=event.event_id,
                status=event.status.value if event.status else None,
                data={"source_count": event.source_count} if event.source_count is not None else {},
            )
            if event.run is not None:
                row = self._apply_provider_run(self.db, row, event.run)
        self.db.commit()
        return self.events(public_id, user_id)

    async def stream_run(self, public_id: str, user_id: int) -> AsyncIterator[DeepRunEventOut]:
        """Yield stable local lifecycle events; never forward raw Provider SSE."""
        last_id = 0
        settings = get_settings()
        while True:
            row = await self.sync_run(public_id, user_id)
            for event in self.events(public_id, user_id):
                if event.id > last_id:
                    last_id = event.id
                    yield event
            if row.status in {status.value for status in TERMINAL_RUN_STATUSES}:
                return
            await asyncio.sleep(min(max(settings.exa_agent_poll_interval_seconds, 0.5), 30))

    def events(self, public_id: str, user_id: int) -> list[DeepRunEventOut]:
        row = self.repository.get_for_user(public_id, user_id)
        if row is None:
            raise ExternalSearchError("DEEP_SEARCH_RUN_NOT_FOUND", "Deep Search run not found.", status_code=404)
        return [DeepRunEventOut(id=item.id, event_type=item.event_type, status=item.status, data=item.safe_payload or {}, created_at=item.created_at) for item in self.repository.list_events(row)]

    @staticmethod
    def out(row: ExternalSearchRun) -> DeepRunOut:
        sources = []
        for raw in row.grounding or []:
            try:
                sources.append(ExternalGroundingSource.model_validate(raw))
            except ValidationError:
                continue
        structured = row.output_structured
        return DeepRunOut(
            run_id=row.public_id, conversation_id=row.conversation_id,
            user_message_id=row.user_message_id, assistant_message_id=row.assistant_message_id,
            provider=row.provider, mode=row.mode, effort=row.effort, status=row.status,
            termination_reason=row.termination_reason, text=row.output_text,
            structured=structured, sources=sources, usage=row.usage or {}, cost_usd=row.cost_usd,
            cost_estimated=row.cost_estimated, error_code=row.error_code,
            error_message_safe=row.error_message_safe, created_at=row.created_at,
            started_at=row.started_at, completed_at=row.completed_at,
            cancelled_at=row.cancelled_at, last_synced_at=row.last_synced_at,
        )
