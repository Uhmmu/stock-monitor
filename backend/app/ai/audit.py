from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)


def audit_ai_request(*, request_id: str, user_id: int, provider: str, model: str, request, result=None, duration_ms: int, error_code: str | None = None, invalid_citation_count: int = 0, citation_repair_attempted: bool = False) -> None:
    message_hash = hashlib.sha256(request.message.encode()).hexdigest()[:16]
    logger.info(
        "ai_orchestrator request_id=%s user_id=%s provider=%s model=%s page_context=%s active_symbol=%s "
        "message_chars=%s message_hash=%s selected_tool_calls=%s model_rounds=%s input_tokens=%s output_tokens=%s "
        "duration_ms=%s citations=%s invalid_citations=%s citation_repair_attempted=%s status=%s error_code=%s",
        request_id, user_id, provider, model, request.page_context, request.active_symbol,
        len(request.message), message_hash, len(result.tool_calls) if result else 0,
        result.usage.model_rounds if result else 0, result.usage.input_tokens if result else 0,
        result.usage.output_tokens if result else 0, duration_ms, len(result.citations) if result else 0,
        invalid_citation_count, citation_repair_attempted, result.status if result else "error", error_code,
    )
