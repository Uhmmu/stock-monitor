"""Read-only semantic Options tools backed only by persisted aggregates."""

from typing import Literal

from pydantic import Field, field_validator

from app.research.security import normalize_symbol
from app.services.options.service import RANK_FIELDS, semantic_options_context

from ..schemas import AdapterResult, ToolArguments, ToolDefinition, ToolExecutionResult
from .base import BaseToolAdapter


class OptionsArguments(ToolArguments):
    scope: Literal["market", "sector", "watchlist"] = "market"
    ranking: str = Field("activity", max_length=32)

    @field_validator("ranking")
    @classmethod
    def valid_ranking(cls, value):
        if value not in RANK_FIELDS:
            raise ValueError("unsupported options ranking")
        return value


class OptionsSymbolArguments(ToolArguments):
    symbol: str = Field(min_length=1, max_length=32)

    @field_validator("symbol")
    @classmethod
    def clean_symbol(cls, value):
        return normalize_symbol(value)


class OptionsToolAdapter(BaseToolAdapter):
    def __init__(self, definition, arguments_model, action):
        self.definition, self.arguments_model, self.action = definition, arguments_model, action

    async def execute(self, args, context, gateway):
        if self.action == "symbol":
            data = semantic_options_context(gateway.db, symbol=args.symbol)
        else:
            data = semantic_options_context(gateway.db, scope=args.scope, ranking=args.ranking)
        unavailable = data.get("status") in {"NO_DATA", "insufficient_history"}
        return AdapterResult(
            data=data,
            summary="Returned bounded persisted Options analytics; no provider refresh or raw contract chain was requested.",
            sources=[{"provider": "yfinance", "source_type": "options_snapshot", "authority": "deterministic_aggregate"}],
            warnings=[{"code": "INSUFFICIENT_HISTORY", "message": "Historical comparisons are unavailable until daily snapshots accumulate.", "severity": "info"}] if unavailable else [],
            partial=unavailable,
        )


def build_options_adapters(disabled: set[str] | None = None):
    disabled = disabled or set()
    specs = [
        ("get_options_overview", "Market, sector, or watchlist Options analytics and rankings", OptionsArguments, "overview"),
        ("get_symbol_options_summary", "One symbol's Options metrics, quality, and bounded history", OptionsSymbolArguments, "symbol"),
    ]
    return [OptionsToolAdapter(ToolDefinition(
        name=name, domain="options", title=title,
        description=f"Read persisted {title.lower()} from stock-monitor. Returns structured metrics, timestamps, quality, and explicit gaps; never raw chains, provider refreshes, or trading advice.",
        input_schema=args_model.model_json_schema(), output_schema=ToolExecutionResult.model_json_schema(),
        contains_private_data=name == "get_options_overview", enabled=name not in disabled,
        cache_ttl_seconds=30, default_timeout_seconds=5, max_timeout_seconds=10, max_items=100,
        tags=["options", "read-only", "stored-data"],
    ), args_model, action) for name, title, args_model, action in specs]


__all__ = ["build_options_adapters"]
