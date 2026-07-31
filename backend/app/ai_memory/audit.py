import logging
from typing import Any

logger = logging.getLogger("app.ai_memory.audit")


def audit_event(event: str, **fields: Any) -> None:
    """Log identifiers and state only; never log memory or thesis content."""
    safe = {
        key: value
        for key, value in fields.items()
        if key
        in {
            "user_id",
            "conversation_id",
            "message_id",
            "snapshot_id",
            "memory_id",
            "decision_id",
            "version",
            "status",
            "event_type",
            "memory_type",
            "scope",
            "origin",
            "decision_type",
            "symbols",
            "review_due",
            "source_message_count",
            "source_character_count",
            "evidence_count",
            "provider",
            "model",
            "duration_ms",
            "error_code",
        }
    }
    logger.info("ai_memory_event event=%s fields=%s", event, safe)
