from __future__ import annotations

from pathlib import PurePath

from app.ai.orchestrator import TOOL_DISPLAY_NAMES
from app.ai.schemas import Citation
from app.models import AIConversation, AIMessage, AIMessageCitation, AIToolCallRecord
from app.research.security import safe_external_url

from .repository import normalized_preview
from .schemas import ConversationOut, MessageOut, ToolCallRecordOut


def conversation_out(item: AIConversation, preview: str | None = None) -> ConversationOut:
    return ConversationOut(
        id=item.id,
        title=item.title,
        title_source=item.title_source,
        status=item.status,
        active_symbol=item.active_symbol,
        active_symbols=list(item.active_symbols or []),
        active_portfolio_id=item.active_portfolio_id,
        page_context=item.page_context,
        model=item.model,
        web_access_mode=item.web_access_mode,
        message_count=item.message_count,
        completed_message_count=item.completed_message_count,
        last_message_preview=normalized_preview(preview),
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_message_at=item.last_message_at,
        archived_at=item.archived_at,
        deleted_at=item.deleted_at,
    )


def citation_out(item: AIMessageCitation) -> Citation:
    locator = item.locator
    if locator and (locator.startswith("/") or ".." in PurePath(locator).parts):
        locator = None
    return Citation(
        key=item.citation_key,
        source_id=item.source_id,
        title=item.title,
        source_type=item.source_type,
        symbol=item.symbol,
        provider=item.provider,
        authority=item.authority,
        published_at=item.published_at,
        retrieved_at=item.retrieved_at,
        locator=locator,
        url=safe_external_url(item.url),
    )


def tool_call_out(item: AIToolCallRecord) -> ToolCallRecordOut:
    display = TOOL_DISPLAY_NAMES.get(item.tool_name, "正在读取研究数据")
    return ToolCallRecordOut(
        id=item.id,
        tool_call_id=item.tool_call_id,
        tool_name=item.tool_name,
        display_name=display.removeprefix("正在"),
        status=item.status,
        summary=item.summary,
        warning_codes=list(item.warning_codes or []),
        returned_item_count=item.returned_item_count,
        cache_hit=item.cache_hit,
        truncated=item.truncated,
        reused=item.reused,
        external_provider=item.external_provider,
        external_run_id=item.external_run_id,
        cost_usd=float(item.cost_usd) if item.cost_usd is not None else None,
        cost_estimated=item.cost_estimated,
        created_at=item.created_at,
        completed_at=item.completed_at,
    )


def message_out(
    item: AIMessage,
    citations: list[AIMessageCitation] | None = None,
    tool_calls: list[AIToolCallRecord] | None = None,
    *,
    include_rich_content: bool = True,
) -> MessageOut:
    return MessageOut(
        id=item.id,
        conversation_id=item.conversation_id,
        role=item.role,
        status=item.status,
        content=item.content,
        content_format=item.content_format,
        content_schema_version=(
            item.content_schema_version if include_rich_content else None
        ),
        content_parts=(
            item.content_parts if include_rich_content else None
        ),
        parent_message_id=item.parent_message_id,
        reply_to_message_id=item.reply_to_message_id,
        regenerated_from_message_id=item.regenerated_from_message_id,
        generation_index=item.generation_index,
        model=item.model,
        input_tokens=item.input_tokens,
        output_tokens=item.output_tokens,
        total_tokens=item.total_tokens,
        tool_call_count=item.tool_call_count,
        citation_count=item.citation_count,
        web_access_mode=item.web_access_mode,
        external_search_call_count=item.external_search_call_count,
        deep_search_run_id=(item.deep_search_run.public_id if getattr(item, "deep_search_run", None) else None),
        external_search_cost_usd=float(item.external_search_cost_usd) if item.external_search_cost_usd is not None else None,
        error_code=item.error_code,
        error_message_safe=item.error_message_safe,
        has_partial_content=bool(item.content and item.status in {"partial", "cancelled", "failed"}),
        citations=[citation_out(value) for value in (citations or [])],
        tool_calls=[tool_call_out(value) for value in (tool_calls or [])],
        created_at=item.created_at,
        started_at=item.started_at,
        completed_at=item.completed_at,
        cancelled_at=item.cancelled_at,
        updated_at=item.updated_at,
    )
