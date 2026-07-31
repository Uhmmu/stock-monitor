from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AIInvestmentDecision, AIUserMemory

from .service import AIMemoryService


@dataclass
class RelevantMemoryResult:
    memories: list[AIUserMemory] = field(default_factory=list)
    decisions: list[AIInvestmentDecision] = field(default_factory=list)
    text: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def memory_ids(self) -> list[int]:
        return [item.id for item in self.memories]

    @property
    def decision_ids(self) -> list[int]:
        return [item.id for item in self.decisions]


def _terms(value: str) -> set[str]:
    latin = re.findall(r"[a-z0-9][a-z0-9._-]{1,31}", value.casefold())
    han = re.findall(r"[\u4e00-\u9fff]{2,8}", value)
    return set(latin + han)


class RelevantMemoryRetriever:
    def __init__(self, db: Session):
        self.db = db

    def retrieve(
        self,
        *,
        user_id: int,
        message: str,
        active_symbol: str | None = None,
        active_symbols: list[str] | None = None,
        portfolio_id: int | None = None,
        page_context: str | None = None,
        max_items: int | None = None,
        max_chars: int | None = None,
        include_decisions: bool = True,
        web_access_mode: str = "off",
    ) -> RelevantMemoryResult:
        settings = get_settings()
        try:
            preference = AIMemoryService(self.db).settings(user_id)
        except SQLAlchemyError:
            self.db.rollback()
            return RelevantMemoryResult()
        if not preference.enabled or not preference.use_in_context:
            return RelevantMemoryResult()
        # The existing external-search tool arguments are model-authored. Until
        # a deterministic query firewall can prove that saved private context
        # was not copied into an Exa query, memory is deliberately omitted from
        # web/deep turns.
        if web_access_mode != "off":
            return RelevantMemoryResult(
                warnings=[
                    "Saved memory was not injected into a web-enabled turn."
                ]
            )
        AIMemoryService(self.db).refresh_lifecycle(user_id)
        symbols = {
            value.upper()
            for value in ([active_symbol] if active_symbol else [])
            + list(active_symbols or [])
        }
        symbols.update(
            value.upper()
            for value in re.findall(
                r"(?<![A-Z0-9])([A-Z]{1,5}(?:\.[A-Z]{1,3})?)(?![A-Z0-9])",
                message,
            )
        )
        scope_filters = [AIUserMemory.scope == "global"]
        if symbols:
            scope_filters.append(
                (AIUserMemory.scope == "symbol")
                & (AIUserMemory.scope_key.in_(symbols))
            )
        if portfolio_id is not None:
            scope_filters.append(
                (AIUserMemory.scope == "portfolio")
                & (AIUserMemory.scope_key == str(portfolio_id))
            )
        if page_context:
            scope_filters.extend(
                [
                    (AIUserMemory.scope == "page_context")
                    & (AIUserMemory.scope_key == page_context),
                    (AIUserMemory.scope == "project")
                    & (AIUserMemory.scope_key == page_context),
                ]
            )
        rows = list(
            self.db.scalars(
                select(AIUserMemory).where(
                    AIUserMemory.user_id == user_id,
                    AIUserMemory.status == "active",
                    AIUserMemory.deleted_at.is_(None),
                    or_(*scope_filters),
                )
            )
        )
        query_terms = _terms(message) | {value.casefold() for value in symbols}

        def memory_score(item: AIUserMemory) -> tuple[int, int, int]:
            overlap = len(query_terms & _terms(item.content))
            scoped = 2 if item.scope != "global" else 0
            return (scoped + overlap, item.importance, item.id)

        rows.sort(key=memory_score, reverse=True)
        item_limit = min(
            max_items or settings.ai_memory_context_max_items, 12
        )
        char_limit = min(
            max_chars or settings.ai_memory_context_max_chars, 8000
        )
        selected: list[AIUserMemory] = []
        chars = 0
        for row in rows:
            size = len(row.content) + 120
            if len(selected) >= item_limit or chars + size > char_limit:
                continue
            selected.append(row)
            chars += size

        decisions: list[AIInvestmentDecision] = []
        if include_decisions:
            decision_rows = list(
                self.db.scalars(
                    select(AIInvestmentDecision)
                    .where(
                        AIInvestmentDecision.user_id == user_id,
                        AIInvestmentDecision.status.in_(
                            ("active", "partially_executed", "executed")
                        ),
                        AIInvestmentDecision.deleted_at.is_(None),
                    )
                    .order_by(
                        AIInvestmentDecision.priority.desc(),
                        AIInvestmentDecision.updated_at.desc(),
                    )
                    .limit(25)
                )
            )
            for row in decision_rows:
                row_symbols = {str(value).upper() for value in row.symbols or []}
                if symbols and not (symbols & row_symbols):
                    continue
                if not symbols and not (
                    _terms(message)
                    & _terms(
                        " ".join(
                            [
                                row.title,
                                row.action,
                                *list(row.thesis or []),
                            ]
                        )
                    )
                ):
                    continue
                decisions.append(row)
                if len(decisions) >= 5:
                    break

        blocks = []
        if selected:
            lines = [
                "Saved user context (explicitly saved or confirmed; newer user instructions take precedence):"
            ]
            for index, row in enumerate(selected, 1):
                confirmed = (
                    row.last_confirmed_at.date().isoformat()
                    if row.last_confirmed_at
                    else "unknown"
                )
                lines.append(
                    f"- [M{index}] {row.memory_type}/{row.scope}: "
                    f"{row.content} (confirmed {confirmed})"
                )
            blocks.append("\n".join(lines))
        if decisions:
            lines = [
                "Relevant user-confirmed investment decisions (historical judgments, not live market facts):"
            ]
            for index, row in enumerate(decisions, 1):
                lines.append(
                    f"- [D{index}] {row.decision_date.isoformat()} "
                    f"{row.decision_type} {'/'.join(row.symbols or [])}: "
                    f"{row.action}; thesis={'; '.join(row.thesis or [])}; "
                    f"invalidation={'; '.join(row.invalidation_conditions or [])}"
                )
            blocks.append("\n".join(lines))
        return RelevantMemoryResult(
            memories=selected,
            decisions=decisions,
            text="\n\n".join(blocks),
        )
