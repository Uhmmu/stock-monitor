from __future__ import annotations

import pytest

from execution_agent.errors import SecurityError
from execution_agent.security import (
    build_auth_headers,
    canonical_request,
    ensure_secure_directory,
    ensure_secure_file,
    sign_request,
    validate_binance_origin,
)


def test_canonical_signature_golden() -> None:
    body = b'{"b":2,"a":1}'
    expected = "\n".join(
        (
            "POST",
            "/api/execution-agent/v1/events",
            "a=1&b=2",
            "sha256-placeholder",
            "1700000000",
            "nonce-1",
        )
    )
    import hashlib

    expected = expected.replace("sha256-placeholder", hashlib.sha256(body).hexdigest())
    assert canonical_request("post", "/api/execution-agent/v1/events?b=2&a=1", body, "1700000000", "nonce-1") == expected
    assert sign_request("secret", "post", "/api/execution-agent/v1/events?b=2&a=1", body, "1700000000", "nonce-1")


def test_auth_headers_include_raw_token_and_signature() -> None:
    headers = build_auth_headers("t" * 40, "agent-1", "GET", "/lease", timestamp=1700000000, nonce="n")
    assert headers["X-Execution-Agent-Token"] == "t" * 40
    assert headers["X-Execution-Agent-Signature"] == sign_request("t" * 40, "GET", "/lease", b"", "1700000000", "n")


def test_origin_is_pinned_and_test_override_is_explicit() -> None:
    assert validate_binance_origin() == "https://demo-fapi.binance.com"
    with pytest.raises(SecurityError):
        validate_binance_origin("https://other.example")
    assert validate_binance_origin("http://127.0.0.1:9999", allow_test_server=True) == "http://127.0.0.1:9999"


def test_weak_permissions_are_rejected(tmp_path) -> None:
    root = tmp_path / "agent"
    root.mkdir(mode=0o700)
    ensure_secure_directory(root)
    file = root / "secret"
    ensure_secure_file(file, create=True, content=b"x")
    file.chmod(0o644)
    with pytest.raises(SecurityError):
        ensure_secure_file(file)
    root.chmod(0o755)
    with pytest.raises(SecurityError):
        ensure_secure_directory(root)
