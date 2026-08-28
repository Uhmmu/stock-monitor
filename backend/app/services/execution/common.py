from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


TEST_ENVIRONMENT = "test"
DEFAULT_VENUE = "binance_usdm"
DEFAULT_AGENT_SCOPES = ["lease:read", "event:write", "heartbeat"]


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def canonical_json(value: Any) -> str:
    def default(item: Any) -> str:
        if isinstance(item, datetime):
            return (item if item.tzinfo else item.replace(tzinfo=UTC)).isoformat()
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=default)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    try:
        parsed = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive trust-boundary guard
        raise ValueError("数值无效") from exc
    if not parsed.is_finite():
        raise ValueError("数值无效")
    return parsed
