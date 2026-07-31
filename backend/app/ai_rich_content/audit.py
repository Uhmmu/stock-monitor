from __future__ import annotations

import logging

from .schemas import CompositionResult

logger = logging.getLogger(__name__)


def log_composition(
    *,
    request_id: str,
    result: CompositionResult,
) -> None:
    """Log bounded structural metadata; never log financial payloads."""
    block_types = [
        part.block.block_type
        for part in result.document.parts
        if part.type == "block"
    ]
    logger.info(
        "ai_rich_content_composed request_id=%s schema=%s candidates=%s "
        "blocks=%s block_types=%s invalid=%s duplicate=%s auto=%s duration_ms=%s",
        request_id,
        result.document.schema_version,
        result.candidate_block_count,
        result.used_block_count,
        ",".join(block_types),
        result.invalid_placeholder_count,
        result.duplicate_placeholder_count,
        result.auto_inserted_count,
        result.duration_ms,
    )
