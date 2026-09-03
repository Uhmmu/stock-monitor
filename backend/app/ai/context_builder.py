from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .budgets import OrchestratorBudget, estimate_tokens
from .enums import AIErrorCode
from .exceptions import AIError
from .prompt_builder import build_initial_messages
from .providers.schemas import ProviderMessage
from .schemas import AIRespondRequest
from .tool_selector import ToolSelector, resolve_tool_intent_message


class BuiltContext(BaseModel):
    messages: list[ProviderMessage]
    allowed_tool_names: list[str]
    estimated_chars: int
    estimated_tokens: int | None
    warnings: list[str] = Field(default_factory=list)


class ContextBuilder:
    def __init__(self, selector: ToolSelector):
        self.selector = selector

    def build(
        self,
        request: AIRespondRequest,
        budget: OrchestratorBudget,
        *,
        history: list[ProviderMessage] | None = None,
        application_context: list[str] | None = None,
        selection_message: str | None = None,
    ) -> BuiltContext:
        intent_message = selection_message or resolve_tool_intent_message(
            request.message,
            [
                item.content
                for item in (history or [])
                if item.role == "user" and item.content
            ],
        )
        try:
            selection = self.selector.select(
                message=intent_message, page_context=request.page_context,
                active_symbol=request.active_symbol, allowed_tools=set(request.allowed_tools) if request.allowed_tools is not None else None,
                denied_tools=set(request.denied_tools),
                web_access_mode=request.web_access_mode,
            )
        except ValueError as exc:
            raise AIError(AIErrorCode.tool_selection, "Tool selection failed for this request.", status_code=422) from exc
        initial = build_initial_messages(
            message=request.message, page_context=request.page_context,
            active_symbols=request.active_symbols, active_portfolio_id=request.active_portfolio_id,
            web_access_mode=request.web_access_mode,
        )
        safe_history = [
            message.model_copy(deep=True)
            for message in (history or [])
            if message.role in {"user", "assistant"} and message.content
        ]
        supplied_context = [
            ProviderMessage(role="user", content=value)
            for value in (application_context or [])
            if value
        ]
        messages = [initial[0], *safe_history, *supplied_context, initial[1]]
        chars = len(json.dumps([message.model_dump(mode="json") for message in messages], ensure_ascii=False))
        if chars > budget.max_context_chars:
            raise AIError(AIErrorCode.context_too_large, "The request context is too large.", status_code=422)
        return BuiltContext(messages=messages, allowed_tool_names=selection.tool_names, estimated_chars=chars, estimated_tokens=estimate_tokens("".join(m.content or "" for m in messages)), warnings=selection.warnings)
