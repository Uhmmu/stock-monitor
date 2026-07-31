from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    AIConversationSummarySnapshot,
    AIInvestmentDecision,
    AIMessage,
    AIMessageDecisionUsage,
    AIMessageMemoryUsage,
    AIUserMemory,
)

from .schemas import (
    DecisionCreate,
    DecisionOut,
    DecisionPage,
    DecisionPatch,
    EvidenceCreate,
    ExecuteDecisionRequest,
    ForgetRequest,
    ForgetResult,
    MemoryCreate,
    MemoryDetailOut,
    MemoryOut,
    MemoryPage,
    MemoryPatch,
    MemorySettingsOut,
    MemorySettingsPatch,
    MessageMemoryUsageOut,
    ReviewCreate,
    ReviewOut,
    SummaryHistoryOut,
    SummarySnapshotOut,
)
from .service import (
    AIMemoryService,
    DecisionConflict,
    DecisionNotFound,
    InvestmentDecisionService,
    MemoryConflict,
    MemoryNotFound,
    decision_out,
    extract_memory_candidates,
)
from .summaries.service import ConversationSummaryService, SummaryError

router = APIRouter(
    prefix="/api/ai/v1",
    tags=["ai-memory"],
    dependencies=[Depends(get_current_user)],
)
user_dependency = Depends(get_current_user)
db_dependency = Depends(get_db)


def _not_found(message: str = "Resource not found") -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def _memory_call(call):
    try:
        return call()
    except (MemoryNotFound, DecisionNotFound, LookupError) as exc:
        raise _not_found() from exc
    except (MemoryConflict, DecisionConflict, SummaryError) as exc:
        status = (
            503
            if isinstance(exc, SummaryError)
            and exc.code == "AI_SUMMARY_DISABLED"
            else 409
        )
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get(
    "/conversations/{conversation_id}/summary",
    response_model=SummarySnapshotOut,
)
def get_summary(
    conversation_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    row = _memory_call(
        lambda: ConversationSummaryService(db).current(
            conversation_id, user.id
        )
    )
    if row is None:
        raise _not_found("Conversation summary not found")
    return SummarySnapshotOut.model_validate(row)


@router.post(
    "/conversations/{conversation_id}/summary/refresh",
    response_model=SummarySnapshotOut,
)
def refresh_summary(
    conversation_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    row = _memory_call(
        lambda: ConversationSummaryService(db).enqueue(
            conversation_id, user.id, force=True
        )
    )
    return SummarySnapshotOut.model_validate(row)


@router.get(
    "/conversations/{conversation_id}/summary/history",
    response_model=SummaryHistoryOut,
)
def summary_history(
    conversation_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    rows = _memory_call(
        lambda: ConversationSummaryService(db).history(
            conversation_id, user.id
        )
    )
    return SummaryHistoryOut(
        items=[SummarySnapshotOut.model_validate(row) for row in rows]
    )


@router.get("/memory-settings", response_model=MemorySettingsOut)
def get_memory_settings(
    user: Any = user_dependency, db: Session = db_dependency
):
    return AIMemoryService(db).settings(user.id)


@router.patch("/memory-settings", response_model=MemorySettingsOut)
def patch_memory_settings(
    body: MemorySettingsPatch,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return AIMemoryService(db).update_settings(user.id, body)


@router.get("/memories", response_model=MemoryPage)
def list_memories(
    status: str | None = None,
    memory_type: str | None = None,
    scope: str | None = None,
    scope_key: str | None = None,
    source_conversation_id: int | None = Query(None, gt=0),
    created_after: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: AIMemoryService(db).list_memories(
            user.id,
            status=status,
            memory_type=memory_type,
            scope=scope,
            scope_key=scope_key,
            source_conversation_id=source_conversation_id,
            created_after=created_after,
            limit=limit,
            cursor=cursor,
        )
    )


@router.post("/memories", response_model=MemoryOut)
def create_memory(
    body: MemoryCreate,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(lambda: AIMemoryService(db).create_memory(user.id, body))


@router.post("/memories/forget", response_model=ForgetResult)
def forget_memory(
    body: ForgetRequest,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return AIMemoryService(db).forget(user.id, body.query, delete=body.delete)


@router.get("/memory-candidates", response_model=MemoryPage)
def list_memory_candidates(
    conversation_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=100),
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return AIMemoryService(db).list_memories(
        user.id,
        status="proposed",
        source_conversation_id=conversation_id,
        limit=limit,
    )


@router.post(
    "/messages/{message_id}/memory-candidates", response_model=MemoryPage
)
def candidates_from_message(
    message_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    message = db.scalar(
        select(AIMessage).where(
            AIMessage.id == message_id,
            AIMessage.user_id == user.id,
            AIMessage.deleted_at.is_(None),
        )
    )
    if message is None:
        raise _not_found()
    created: list[MemoryOut] = []
    for candidate in extract_memory_candidates(message.content):
        candidate.source_conversation_id = message.conversation_id
        candidate.source_message_id = message.id
        try:
            item = AIMemoryService(db).create_memory(user.id, candidate)
        except MemoryConflict:
            continue
        if item.status == "proposed":
            created.append(item)
    return MemoryPage(
        items=created, total=len(created), limit=len(created), cursor=None
    )


@router.get("/memories/{memory_id}", response_model=MemoryDetailOut)
def get_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(lambda: AIMemoryService(db).detail(memory_id, user.id))


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
def patch_memory(
    memory_id: int,
    body: MemoryPatch,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: AIMemoryService(db).patch_memory(memory_id, user.id, body)
    )


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    _memory_call(lambda: AIMemoryService(db).delete(memory_id, user.id))
    return Response(status_code=204)


def _memory_transition(name: str, memory_id: int, user_id: int, db: Session):
    service = AIMemoryService(db)
    return _memory_call(lambda: getattr(service, name)(memory_id, user_id))


@router.post("/memories/{memory_id}/confirm", response_model=MemoryOut)
def confirm_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_transition("confirm", memory_id, user.id, db)


@router.post("/memories/{memory_id}/reconfirm", response_model=MemoryOut)
def reconfirm_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_transition("confirm", memory_id, user.id, db)


@router.post("/memories/{memory_id}/reject", response_model=MemoryOut)
def reject_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_transition("reject", memory_id, user.id, db)


@router.post("/memories/{memory_id}/archive", response_model=MemoryOut)
def archive_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_transition("archive", memory_id, user.id, db)


@router.post("/memories/{memory_id}/restore", response_model=MemoryOut)
def restore_memory(
    memory_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_transition("restore", memory_id, user.id, db)


@router.get("/investment-decisions", response_model=DecisionPage)
def list_decisions(
    status: str | None = None,
    decision_type: str | None = None,
    symbol: str | None = None,
    search: str | None = Query(None, max_length=200),
    time_horizon: str | None = None,
    portfolio_id: int | None = Query(None, gt=0),
    decision_date_from: date | None = None,
    decision_date_to: date | None = None,
    review_due: bool | None = None,
    min_confidence: float | None = Query(None, ge=0, le=1),
    source_conversation_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).list(
            user.id,
            status=status,
            decision_type=decision_type,
            symbol=symbol,
            search=search,
            time_horizon=time_horizon,
            portfolio_id=portfolio_id,
            decision_date_from=decision_date_from,
            decision_date_to=decision_date_to,
            review_due=review_due,
            min_confidence=min_confidence,
            source_conversation_id=source_conversation_id,
            limit=limit,
            cursor=cursor,
        )
    )


@router.post("/investment-decisions", response_model=DecisionOut)
def create_decision(
    body: DecisionCreate,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).create(user.id, body)
    )


@router.post(
    "/messages/{message_id}/investment-decision-draft",
    response_model=DecisionOut,
)
def decision_from_message(
    message_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).from_message(
            message_id, user.id
        )
    )


@router.get(
    "/investment-decisions/{decision_id}", response_model=DecisionOut
)
def get_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).detail(decision_id, user.id)
    )


@router.patch(
    "/investment-decisions/{decision_id}", response_model=DecisionOut
)
def patch_decision(
    decision_id: int,
    body: DecisionPatch,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).patch(
            decision_id, user.id, body
        )
    )


@router.delete("/investment-decisions/{decision_id}", status_code=204)
def delete_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    _memory_call(
        lambda: InvestmentDecisionService(db).delete(decision_id, user.id)
    )
    return Response(status_code=204)


@router.post(
    "/investment-decisions/{decision_id}/confirm",
    response_model=DecisionOut,
)
def confirm_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).confirm(decision_id, user.id)
    )


@router.post(
    "/investment-decisions/{decision_id}/execute",
    response_model=DecisionOut,
)
def execute_decision(
    decision_id: int,
    body: ExecuteDecisionRequest,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).execute(
            decision_id, user.id, body
        )
    )


def _decision_transition(
    status: str, decision_id: int, user_id: int, db: Session
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).transition(
            decision_id, user_id, status
        )
    )


@router.post(
    "/investment-decisions/{decision_id}/cancel",
    response_model=DecisionOut,
)
def cancel_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _decision_transition("cancelled", decision_id, user.id, db)


@router.post(
    "/investment-decisions/{decision_id}/invalidate",
    response_model=DecisionOut,
)
def invalidate_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _decision_transition("invalidated", decision_id, user.id, db)


@router.post(
    "/investment-decisions/{decision_id}/close",
    response_model=DecisionOut,
)
def close_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _decision_transition("closed", decision_id, user.id, db)


@router.post(
    "/investment-decisions/{decision_id}/archive",
    response_model=DecisionOut,
)
def archive_decision(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _decision_transition("archived", decision_id, user.id, db)


@router.post(
    "/investment-decisions/{decision_id}/evidence",
    response_model=DecisionOut,
)
def add_decision_evidence(
    decision_id: int,
    body: EvidenceCreate,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).add_evidence(
            decision_id, user.id, body
        )
    )


@router.get(
    "/investment-decisions/{decision_id}/reviews",
    response_model=list[ReviewOut],
)
def list_reviews(
    decision_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).detail(
            decision_id, user.id
        ).reviews
    )


@router.post(
    "/investment-decisions/{decision_id}/reviews",
    response_model=ReviewOut,
)
def create_review(
    decision_id: int,
    body: ReviewCreate,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).add_review(
            decision_id, user.id, body
        )
    )


@router.post(
    "/investment-decisions/{decision_id}/review-draft",
    response_model=ReviewOut,
)
def create_review_draft(
    decision_id: int,
    web_access_mode: str = "off",
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    return _memory_call(
        lambda: InvestmentDecisionService(db).review_draft(
            decision_id, user.id, web_access_mode=web_access_mode
        )
    )


@router.get(
    "/messages/{message_id}/memory-usage",
    response_model=MessageMemoryUsageOut,
)
def message_memory_usage(
    message_id: int,
    user: Any = user_dependency,
    db: Session = db_dependency,
):
    message = db.scalar(
        select(AIMessage).where(
            AIMessage.id == message_id,
            AIMessage.user_id == user.id,
            AIMessage.deleted_at.is_(None),
        )
    )
    if message is None:
        raise _not_found()
    memory_ids = list(
        db.scalars(
            select(AIMessageMemoryUsage.memory_id).where(
                AIMessageMemoryUsage.message_id == message_id,
                AIMessageMemoryUsage.user_id == user.id,
            )
        )
    )
    decision_ids = list(
        db.scalars(
            select(AIMessageDecisionUsage.decision_id).where(
                AIMessageDecisionUsage.message_id == message_id,
                AIMessageDecisionUsage.user_id == user.id,
            )
        )
    )
    memories = list(
        db.scalars(
            select(AIUserMemory).where(
                AIUserMemory.id.in_(memory_ids),
                AIUserMemory.user_id == user.id,
            )
        )
    ) if memory_ids else []
    decisions = list(
        db.scalars(
            select(AIInvestmentDecision).where(
                AIInvestmentDecision.id.in_(decision_ids),
                AIInvestmentDecision.user_id == user.id,
            )
        )
    ) if decision_ids else []
    decision_service = InvestmentDecisionService(db)
    evidence, reviews = decision_service._load_related(decision_ids, user.id)
    snapshot = (
        db.scalar(
            select(AIConversationSummarySnapshot).where(
                AIConversationSummarySnapshot.id == message.summary_snapshot_id,
                AIConversationSummarySnapshot.user_id == user.id,
            )
        )
        if message.summary_snapshot_id
        else None
    )
    return MessageMemoryUsageOut(
        memories=[MemoryOut.model_validate(row) for row in memories],
        decisions=[
            decision_out(
                row,
                evidence=evidence.get(row.id, []),
                reviews=reviews.get(row.id, []),
            )
            for row in decisions
        ],
        summary_snapshot=(
            SummarySnapshotOut.model_validate(snapshot) if snapshot else None
        ),
    )
