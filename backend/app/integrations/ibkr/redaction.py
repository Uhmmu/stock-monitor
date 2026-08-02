from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {
    "authorization", "cookie", "set-cookie", "token", "access_token", "refresh_token",
    "password", "passwd", "secret", "query_id", "queryid", "q", "t",
    "session", "session_id", "reference_code", "referencecode", "credential",
}


def redact_account_id(value: str | None) -> str | None:
    if not value:
        return value
    return value[:2] + "*" * max(4, len(value) - 4) + value[-2:]


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).lower().replace("-", "_") in SENSITIVE_KEYS else sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(token|password|authorization|cookie)=([^&\s]+)", r"\1=[REDACTED]", value)
        return value[:200_000]
    return value


def sanitize_xml(value: str) -> str:
    value = re.sub(
        r"(?is)<(ReferenceCode|Token|QueryId|QueryID|Session)(?:\s[^>]*)?>.*?</\1>",
        lambda match: f"<{match.group(1)}>[REDACTED]</{match.group(1)}>",
        value,
    )
    return value[:200_000]
