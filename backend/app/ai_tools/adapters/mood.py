"""Read-only semantic Mood tools backed only by persisted snapshots."""

from typing import Literal

from pydantic import Field

from app.services.mood import latest_mood_payload, mood_history_payload
from app.services.mood_validation import validation_study_payload

from ..schemas import AdapterResult, ToolArguments, ToolDefinition, ToolExecutionResult
from .base import BaseToolAdapter


class MoodOverviewArguments(ToolArguments):
    scope_type: Literal["market", "sector", "ai_chain", "watchlist"] | None = None
    scope_key: str | None = Field(None, max_length=192)


class MoodHistoryArguments(ToolArguments):
    scope_type: Literal["market", "sector", "ai_chain", "watchlist"]
    scope_key: str = Field(min_length=1, max_length=192)
    days: int = Field(60, ge=7, le=180)


class MoodValidationArguments(ToolArguments):
    study: Literal["overview", "states", "transitions", "divergences", "confidence", "agreement", "evidence", "ablation"] = "overview"
    scope_type: Literal["market", "sector", "ai_chain", "watchlist"] | None = None
    limit: int = Field(60, ge=1, le=100)


class MoodToolAdapter(BaseToolAdapter):
    def __init__(self, definition, arguments_model, action):
        self.definition, self.arguments_model, self.action = definition, arguments_model, action

    async def execute(self, args, context, gateway):
        if self.action == "validation":
            data = validation_study_payload(gateway.db, args.study, args.scope_type, args.limit)
        elif self.action == "history":
            data = mood_history_payload(gateway.db, args.scope_type, args.scope_key, days=args.days)
        else:
            data = latest_mood_payload(gateway.db, scope_type=args.scope_type, scope_key=args.scope_key)
        unavailable = data.get("status") in {"unavailable", "insufficient_data"}
        return AdapterResult(
            data=data,
            summary="Returned deterministic persisted Mood state, evidence, transitions, and divergences; no refresh or model call was requested.",
            sources=[{"provider": "stock-monitor", "source_type": "mood_snapshot", "authority": "deterministic_aggregate"}],
            warnings=[{"code": "INSUFFICIENT_DATA", "message": "Some stored signal sources are missing or stale.", "severity": "info"}] if unavailable else [],
            partial=unavailable,
        )


def build_mood_adapters(disabled: set[str] | None = None):
    disabled = disabled or set()
    specs = [
        ("get_mood_overview", "Market, sector, AI-chain, and watchlist Mood states", MoodOverviewArguments, "overview"),
        ("get_mood_history", "One scope's Mood history, transitions, evidence, and divergences", MoodHistoryArguments, "history"),
        ("get_mood_validation", "Bounded Mood state, transition, divergence, confidence, and ablation validation results", MoodValidationArguments, "validation"),
    ]
    return [MoodToolAdapter(ToolDefinition(
        name=name, domain="mood", title=title,
        description=f"Read persisted {title.lower()} from stock-monitor. The deterministic state is authoritative; missing and stale sources remain explicit.",
        input_schema=args_model.model_json_schema(), output_schema=ToolExecutionResult.model_json_schema(),
        contains_private_data=True, enabled=name not in disabled, cache_ttl_seconds=30,
        default_timeout_seconds=5, max_timeout_seconds=10, max_items=100,
        tags=["mood", "read-only", "stored-data"],
    ), args_model, action) for name, title, args_model, action in specs]


__all__ = ["build_mood_adapters"]
