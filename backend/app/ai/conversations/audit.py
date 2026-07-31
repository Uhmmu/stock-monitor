from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("ai.conversations.audit")


def audit_conversation_action(action: str, *, request_id: str, user_id: int, **fields: Any) -> None:
    safe = {
        key: value
        for key, value in fields.items()
        if key not in {"message", "answer", "content", "system_prompt", "tool_result", "arguments"}
    }
    logger.info(
        "ai_conversation_audit %s",
        json.dumps({"action": action, "request_id": request_id, "user_id": user_id, **safe}, ensure_ascii=False, default=str),
    )
