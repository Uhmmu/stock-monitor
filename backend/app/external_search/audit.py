from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger("external_search.audit")


def audit_external_search(action: str, **values: Any) -> None:
    if not get_settings().exa_audit_enabled:
        return
    safe = {key: value for key, value in values.items() if key not in {"query", "api_key", "raw_payload", "output_text"}}
    logger.info("external_search action=%s data=%s", action, safe)
