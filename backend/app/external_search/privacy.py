from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class SanitizedExternalQuery:
    query: str
    query_hash: str
    query_length: int
    safe_preview: str | None
    symbols: list[str]


class ExternalQueryPrivacyFilter:
    _email = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    _secret = re.compile(r"\b(?:sk|pk|api|token|key)[-_][A-Za-z0-9_-]{12,}\b", re.IGNORECASE)
    _uuid = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE)
    _internal_url = re.compile(r"\b(?:https?://)?(?:localhost|127(?:\.\d+){3}|10(?:\.\d+){3}|192\.168(?:\.\d+){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d+){2})(?:[:/]\S*)?", re.IGNORECASE)
    _path = re.compile(r"(?<!\w)(?:/[\w.-]+){3,}")
    _private_fact = re.compile(
        r"(?i)(?:持仓(?:数量|成本|市值)?|成本价|账户余额|浮动盈亏|realized pnl|unrealized pnl|account balance|cost basis)\s*[:：=]?\s*[-+$¥￥€]?\d[\d,.]*%?"
    )
    _symbols = re.compile(r"\b[A-Z][A-Z0-9.\-]{0,9}\b")

    def sanitize(self, query: str, context=None) -> SanitizedExternalQuery:
        if not isinstance(query, str):
            query = ""
        value = query[:12000]
        for pattern, replacement in (
            (self._email, "[redacted email]"),
            (self._secret, "[redacted credential]"),
            (self._uuid, "[redacted identifier]"),
            (self._internal_url, "[redacted internal address]"),
            (self._path, "[redacted local path]"),
            (self._private_fact, "[redacted private portfolio detail]"),
        ):
            value = pattern.sub(replacement, value)
        # Explicit identifier labels are removed; bare numbers are left intact
        # because they are commonly years, prices, form numbers, or dates.
        value = re.sub(r"(?i)\b(?:user|conversation|message)[-_ ]?id\s*[:=]\s*[A-Za-z0-9_.:-]+", "[redacted identifier]", value)
        value = re.sub(r"\s+", " ", value).strip()
        digest = sha256(value.encode("utf-8")).hexdigest()
        symbols = list(dict.fromkeys(self._symbols.findall(value)))[:20]
        preview = re.sub(r"\[[^\]]*redacted[^\]]*\]", "[已脱敏]", value, flags=re.IGNORECASE)[:240] or None
        return SanitizedExternalQuery(value, digest, len(value), preview, symbols)
