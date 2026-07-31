import json
import logging
from hashlib import sha256
from typing import Any

logger = logging.getLogger(__name__)


EXTERNAL_SEARCH_TOOLS = {
    "search_web", "search_latest_news_web", "search_official_company_sources",
    "search_financial_reports_web", "search_publications_web", "run_deep_web_research",
}


def argument_summary(arguments: dict[str, Any], *, tool_name: str | None = None) -> str:
    blocked = {"authorization", "token", "api_key", "credentials", "user_id", "raw_payload"}
    safe = {str(key): value for key, value in arguments.items() if str(key).lower() not in blocked}
    if tool_name in EXTERNAL_SEARCH_TOOLS and "query" in safe:
        query = str(safe.pop("query") or "")
        safe["query_hash"] = sha256(query.encode()).hexdigest()
        safe["query_length"] = len(query)
    return json.dumps(safe, ensure_ascii=False, default=str, separators=(",", ":"))[:1000]


def audit_tool_execution(*, context, result, arguments: dict[str, Any]) -> None:
    warning_codes = [item.get("code") if isinstance(item, dict) else getattr(item, "code", None) for item in result.warnings]
    source_types = sorted({item.get("source_type") if isinstance(item, dict) else getattr(item, "source_type", None) for item in result.sources} - {None})
    logger.info("ai_tool_execution tool_call_id=%s request_id=%s user_id=%s caller=%s tool=%s version=%s arguments=%s status=%s duration_ms=%s cache_hit=%s result_mode=%s original_items=%s returned_items=%s output_chars=%s estimated_tokens=%s truncated=%s source_types=%s warning_codes=%s error_code=%s",
        result.tool_call_id, context.request_id, context.user_id, context.caller, result.tool_name, result.tool_version,
        argument_summary(arguments, tool_name=result.tool_name), result.status.value, result.stats.duration_ms, result.stats.cache_hit,
        result.stats.result_mode.value, result.stats.original_item_count, result.stats.returned_item_count,
        result.stats.estimated_output_chars, result.stats.estimated_output_tokens, result.stats.truncated,
        source_types, warning_codes, result.error.code if result.error else None)
