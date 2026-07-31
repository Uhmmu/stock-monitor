from __future__ import annotations

from pydantic import Field

from app.ai_tools.adapters.base import BaseToolAdapter
from app.ai_tools.schemas import (
    AdapterResult,
    ToolArguments,
    ToolDefinition,
    ToolExecutionResult,
)
from app.database import SessionLocal

from .context import RelevantMemoryRetriever
from .service import AIMemoryService, InvestmentDecisionService, MemoryNotFound


class RelevantArguments(ToolArguments):
    message: str = Field(min_length=1, max_length=1000)
    active_symbol: str | None = Field(None, max_length=32)
    active_symbols: list[str] = Field(default_factory=list, max_length=20)
    portfolio_id: int | None = Field(None, gt=0)
    page_context: str | None = Field(None, max_length=64)
    limit: int = Field(10, ge=1, le=12)


class MemoryListArguments(ToolArguments):
    memory_type: str | None = Field(None, max_length=40)
    scope: str | None = Field(None, max_length=24)
    limit: int = Field(20, ge=1, le=50)


class MemoryIdArguments(ToolArguments):
    memory_id: int = Field(gt=0)


class DecisionListArguments(ToolArguments):
    status: str | None = Field(None, max_length=24)
    symbol: str | None = Field(None, max_length=32)
    limit: int = Field(20, ge=1, le=50)


class DecisionIdArguments(ToolArguments):
    decision_id: int = Field(gt=0)


class MemoryToolAdapter(BaseToolAdapter):
    def __init__(
        self,
        definition: ToolDefinition,
        arguments_model: type[ToolArguments],
    ):
        self.definition = definition
        self.arguments_model = arguments_model

    async def execute(self, args, context, gateway):
        del gateway
        with SessionLocal() as db:
            if self.definition.name == "get_relevant_user_memories":
                result = RelevantMemoryRetriever(db).retrieve(
                    user_id=context.user_id,
                    message=args.message,
                    active_symbol=args.active_symbol or context.active_symbol,
                    active_symbols=args.active_symbols,
                    portfolio_id=args.portfolio_id or context.active_portfolio_id,
                    page_context=args.page_context,
                    max_items=args.limit,
                    include_decisions=False,
                    web_access_mode=context.web_access_mode,
                )
                data = [
                    {
                        "memory_type": row.memory_type,
                        "scope": row.scope,
                        "scope_key": row.scope_key,
                        "content": row.content,
                        "last_confirmed_at": row.last_confirmed_at,
                    }
                    for row in result.memories
                ]
                return AdapterResult(
                    data=data,
                    summary=f"Returned {len(data)} relevant confirmed memories.",
                )
            if self.definition.name == "list_user_memories":
                page = AIMemoryService(db).list_memories(
                    context.user_id,
                    status="active",
                    memory_type=args.memory_type,
                    scope=args.scope,
                    limit=args.limit,
                )
                return AdapterResult(
                    data=[
                        item.model_dump(mode="json")
                        for item in page.items
                    ],
                    summary=f"Returned {len(page.items)} user-owned memories.",
                )
            if self.definition.name == "get_user_memory":
                item = AIMemoryService(db).detail(
                    args.memory_id, context.user_id
                )
                if item.status != "active":
                    raise MemoryNotFound("Active memory not found")
                return AdapterResult(
                    data=item.model_dump(mode="json"),
                    summary="Returned one user-owned memory and its audit history.",
                )
            if self.definition.name in {
                "list_investment_decisions",
                "get_decisions_for_symbol",
            }:
                page = InvestmentDecisionService(db).list(
                    context.user_id,
                    status=args.status,
                    symbol=args.symbol,
                    limit=args.limit,
                )
                return AdapterResult(
                    data=[
                        item.model_dump(mode="json")
                        for item in page.items
                    ],
                    summary=f"Returned {len(page.items)} saved investment decisions.",
                )
            if self.definition.name == "get_investment_decision":
                item = InvestmentDecisionService(db).detail(
                    args.decision_id, context.user_id
                )
                return AdapterResult(
                    data=item.model_dump(mode="json"),
                    summary="Returned one user-owned investment decision with bounded evidence.",
                )
            if self.definition.name == "get_investment_decision_reviews":
                item = InvestmentDecisionService(db).detail(
                    args.decision_id, context.user_id
                )
                return AdapterResult(
                    data=[
                        row.model_dump(mode="json")
                        for row in item.reviews
                    ],
                    summary=f"Returned {len(item.reviews)} saved decision reviews.",
                )
        raise RuntimeError("unsupported AI memory tool")


def build_memory_adapters(
    disabled: set[str] | None = None,
) -> list[MemoryToolAdapter]:
    disabled = disabled or set()
    specs: list[tuple[str, str, type[ToolArguments]]] = [
        (
            "get_relevant_user_memories",
            "Retrieve a bounded set of active, explicitly saved or user-confirmed memories relevant to the current private request. It is read-only, user-scoped, excludes stale or rejected entries, and never performs vector search or sends data to the public web.",
            RelevantArguments,
        ),
        (
            "list_user_memories",
            "List bounded user-owned long-term memory records by lifecycle state and structured type. It is read-only and cannot confirm, edit, archive, restore, or delete a memory on the model's behalf.",
            MemoryListArguments,
        ),
        (
            "get_user_memory",
            "Read one user-owned long-term memory with its transparent lifecycle events. It is read-only, requires current-user ownership, and cannot change confirmation or retention state.",
            MemoryIdArguments,
        ),
        (
            "list_investment_decisions",
            "List bounded user-owned investment decision journal records and review-due state. It reads historical judgments only and never creates a decision, changes a status, executes a trade, or starts paid research.",
            DecisionListArguments,
        ),
        (
            "get_investment_decision",
            "Read one user-owned investment decision, bounded evidence metadata, and saved reviews. It is read-only, preserves the original thesis, and never refreshes data or performs a trade.",
            DecisionIdArguments,
        ),
        (
            "get_investment_decision_reviews",
            "Read reviews already saved for one user-owned investment decision. It is read-only and does not generate a new review, call public search, modify the original thesis, or execute a trade.",
            DecisionIdArguments,
        ),
        (
            "get_decisions_for_symbol",
            "List saved user-owned investment decisions for one symbol with bounded evidence metadata. It is read-only and does not infer, create, confirm, invalidate, or execute a decision.",
            DecisionListArguments,
        ),
    ]
    return [
        MemoryToolAdapter(
            ToolDefinition(
                name=name,
                domain="memory",
                title=name.replace("_", " ").title(),
                description=description,
                input_schema=arguments_model.model_json_schema(),
                output_schema=ToolExecutionResult.model_json_schema(),
                contains_private_data=True,
                enabled=name not in disabled,
                cache_ttl_seconds=0,
                max_items=50,
                default_timeout_seconds=5,
                max_timeout_seconds=10,
                tags=["memory", "read-only", "private"],
            ),
            arguments_model,
        )
        for name, description, arguments_model in specs
    ]
