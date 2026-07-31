import re
from pathlib import Path
from urllib.parse import urlsplit

from .enums import ResearchErrorCode
from .exceptions import ResearchError

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,31}$")


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ResearchError(ResearchErrorCode.invalid_symbol, "symbol format is invalid", field="symbol", status_code=422)
    return symbol


def safe_external_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else None


def resolve_safe_file(root: Path, stored_path: str, allowed_extensions: set[str], *, max_bytes: int = 15 * 1024 * 1024) -> Path:
    root_path = root.resolve()
    candidate = Path(stored_path)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root_path):
        raise ResearchError(ResearchErrorCode.file_access_denied, "stored file is outside the configured data directory", status_code=403)
    if resolved.suffix.lower() not in {suffix.lower() for suffix in allowed_extensions}:
        raise ResearchError(ResearchErrorCode.file_access_denied, "stored file type is not allowed", status_code=403)
    if not resolved.is_file():
        raise ResearchError(ResearchErrorCode.file_not_found, "stored research file is unavailable", status_code=404)
    if resolved.stat().st_size > max_bytes:
        raise ResearchError(ResearchErrorCode.file_access_denied, "stored research file exceeds the read limit", status_code=413)
    return resolved
