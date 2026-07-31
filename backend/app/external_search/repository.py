from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AIMessage, ExternalSearchRun, ExternalSearchRunEvent


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExternalSearchRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_user(self, public_id: str, user_id: int) -> ExternalSearchRun | None:
        return self.db.scalar(select(ExternalSearchRun).where(ExternalSearchRun.public_id == public_id, ExternalSearchRun.user_id == user_id))

    def get_by_idempotency(self, key: str, user_id: int) -> ExternalSearchRun | None:
        return self.db.scalar(select(ExternalSearchRun).where(ExternalSearchRun.idempotency_key == key, ExternalSearchRun.user_id == user_id))

    def create(self, **values) -> ExternalSearchRun:
        row = ExternalSearchRun(**values)
        self.db.add(row)
        self.db.flush()
        if row.assistant_message_id:
            assistant = self.db.scalar(select(AIMessage).where(AIMessage.id == row.assistant_message_id, AIMessage.user_id == row.user_id))
            if assistant is not None:
                assistant.deep_search_run_id = row.id
        return row

    def add_event(self, row: ExternalSearchRun, event_type: str, *, provider_event_id: str | None = None, status: str | None = None, data: dict | None = None) -> None:
        if provider_event_id and self.db.scalar(select(ExternalSearchRunEvent.id).where(ExternalSearchRunEvent.run_id == row.id, ExternalSearchRunEvent.provider_event_id == provider_event_id)):
            return
        self.db.add(ExternalSearchRunEvent(
            run_id=row.id,
            provider_event_id=provider_event_id,
            event_type=event_type[:64],
            status=status[:16] if status else None,
            safe_payload=dict(data or {}),
        ))
        if provider_event_id:
            row.last_event_id = provider_event_id[:128]

    def list_events(self, row: ExternalSearchRun) -> list[ExternalSearchRunEvent]:
        return list(self.db.scalars(select(ExternalSearchRunEvent).where(ExternalSearchRunEvent.run_id == row.id).order_by(ExternalSearchRunEvent.created_at, ExternalSearchRunEvent.id)))
