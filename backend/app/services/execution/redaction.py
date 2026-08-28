from __future__ import annotations

from typing import Any


_FORBIDDEN = (
    "token",
    "signature",
    "password",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "raw_signed_body",
    "signed_body",
)


def _forbidden_key(key: str) -> bool:
    lowered = key.replace("-", "_").lower()
    return any(part in lowered for part in _FORBIDDEN)


def redact(value: Any) -> Any:
    """Recursively redact credentials and signed material before persistence."""

    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _forbidden_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def redacted_event_payload(value: dict | None) -> dict:
    return redact(value or {})
