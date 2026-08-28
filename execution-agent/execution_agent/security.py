from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from .constants import BINANCE_TEST_ORIGIN
from .errors import InstanceAlreadyRunning, SecurityError


_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "secret",
        "secret_key",
        "token",
        "agent_token",
        "authorization",
        "signature",
        "x-execution-agent-token",
        "x-mbx-apikey",
    }
)


def _mode(path: Path) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        raise SecurityError(f"missing secure path: {path}") from None


def ensure_secure_directory(path: Path, *, create: bool = True) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise SecurityError(f"secure directory must not be a symlink: {path}")
    if not path.exists():
        if not create:
            raise SecurityError(f"secure directory does not exist: {path}")
        path.mkdir(parents=True, mode=0o700)
    if not path.is_dir():
        raise SecurityError(f"secure path is not a directory: {path}")
    mode = _mode(path)
    if mode & 0o077 or mode & 0o700 != 0o700:
        raise SecurityError(f"directory permissions must be 0700: {path}")
    return path


def ensure_secure_file(path: Path, *, create: bool = False, content: bytes = b"") -> Path:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise SecurityError(f"secure file must not be a symlink: {path}")
    if not path.exists():
        if not create:
            raise SecurityError(f"secure file does not exist: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        old_umask = os.umask(0o077)
        try:
            fd = os.open(path, flags, 0o600)
            try:
                if content:
                    os.write(fd, content)
            finally:
                os.close(fd)
        finally:
            os.umask(old_umask)
    if not path.is_file():
        raise SecurityError(f"secure path is not a regular file: {path}")
    mode = _mode(path)
    if mode & 0o077 or mode & 0o600 != 0o600:
        raise SecurityError(f"file permissions must be 0600: {path}")
    return path


def read_secure_file(path: Path) -> bytes:
    ensure_secure_file(path)
    return Path(path).read_bytes()


def validate_high_entropy_token(token: str, *, minimum_length: int = 32) -> str:
    value = str(token or "")
    if len(value) < minimum_length or any(char.isspace() for char in value):
        raise SecurityError("machine token must be high entropy and at least 32 characters")
    return value


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(method: str, path_query: str, body: bytes, timestamp: str, nonce: str) -> str:
    parsed = urlsplit(path_query or "/")
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    normalized_query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return "\n".join((method.upper(), path, normalized_query, body_sha256(body), str(timestamp), str(nonce)))


def sign_request(token: str, method: str, path_query: str, body: bytes, timestamp: str, nonce: str) -> str:
    message = canonical_request(method, path_query, body, timestamp, nonce).encode("utf-8")
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_auth_headers(
    token: str,
    agent_id: str,
    method: str,
    path_query: str,
    body: bytes = b"",
    *,
    timestamp: str | int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    request_nonce = secrets.token_hex(16) if nonce is None else str(nonce)
    return {
        "X-Execution-Agent-Id": agent_id,
        # The server hashes this presented value; it is never logged.
        "X-Execution-Agent-Token": token,
        "X-Execution-Agent-Timestamp": ts,
        "X-Execution-Agent-Nonce": request_nonce,
        "X-Execution-Agent-Signature": sign_request(token, method, path_query, body, ts, request_nonce),
    }


def redact(value: object, *, secrets_to_redact: tuple[str, ...] = ()) -> object:
    """Return bounded, JSON-safe diagnostic data without credentials."""

    secret_values = tuple(item for item in secrets_to_redact if item)
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            result[str(key)] = "[REDACTED]" if normalized in _SECRET_KEYS else redact(item, secrets_to_redact=secret_values)
        return result
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets_to_redact=secret_values) for item in value]
    if isinstance(value, str):
        text = value
        for secret in secret_values:
            text = text.replace(secret, "[REDACTED]")
        return text[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:2000]


def redact_json(value: object, *, secrets_to_redact: tuple[str, ...] = ()) -> str:
    return json.dumps(redact(value, secrets_to_redact=secrets_to_redact), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_control_url(url: str, *, allow_test_server: bool = False) -> str:
    parsed = urlsplit(str(url).strip())
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        raise SecurityError("control API URL must have a host and no user info")
    if parsed.scheme == "https":
        return str(url).rstrip("/")
    if allow_test_server and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return str(url).rstrip("/")
    raise SecurityError("control API requires HTTPS; HTTP is test-only")


def validate_binance_origin(url: str | None = None, *, allow_test_server: bool = False) -> str:
    if url is None:
        return BINANCE_TEST_ORIGIN
    parsed = urlsplit(str(url).strip())
    if allow_test_server:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise SecurityError("test Binance URL is malformed")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise SecurityError("test Binance URL must be an origin")
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if str(url).rstrip("/") != BINANCE_TEST_ORIGIN:
        raise SecurityError("only the compiled Binance Futures Demo origin is permitted")
    return BINANCE_TEST_ORIGIN


class InstanceLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> None:
        import fcntl

        ensure_secure_file(self.path, create=True)
        self._fd = os.open(self.path, os.O_RDWR)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd)
            self._fd = None
            raise InstanceAlreadyRunning("another execution-agent instance already holds the lock") from None

    def release(self) -> None:
        if self._fd is None:
            return
        import fcntl

        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class KillSwitch:
    def __init__(self, path: Path):
        self.path = Path(path)

    def is_active(self) -> bool:
        return self.path.exists()

    def reason(self) -> str | None:
        if not self.is_active():
            return None
        try:
            ensure_secure_file(self.path)
            return self.path.read_text(encoding="utf-8")[:500]
        except SecurityError:
            return "kill switch permissions are invalid"

    def trip(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            ensure_secure_file(self.path)
            return
        ensure_secure_file(self.path, create=True, content=str(reason)[:500].encode("utf-8"))

    def clear(self) -> None:
        if not self.path.exists():
            return
        ensure_secure_file(self.path)
        self.path.unlink()
