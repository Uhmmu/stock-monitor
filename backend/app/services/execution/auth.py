from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ExecutionAgent, ExecutionRequestNonce, User
from app.services.execution.common import DEFAULT_AGENT_SCOPES, TEST_ENVIRONMENT, now_utc


class AgentAuthError(ValueError):
    """Machine-auth failure carrying the stable HTTP status the API should use."""

    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8"), usedforsecurity=True).hexdigest()


def token_fingerprint(token: str) -> str:
    return hash_agent_token(token)[:16]


def canonical_request(
    method: str,
    path: str,
    query: str = "",
    body: bytes | str = b"",
    timestamp: str | int | float = "",
    nonce: str = "",
) -> bytes:
    """Canonical bytes signed by a TEST agent.

    Query parameters are sorted and encoded, while the body is represented by
    its SHA-256 digest.  Credentials and raw signed material never enter the
    resulting event payload.
    """

    if isinstance(body, str):
        body = body.encode("utf-8")
    normalized_query = urlencode(sorted(parse_qsl(query, keep_blank_values=True)))
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(
        [str(method).upper(), path or "/", normalized_query, body_hash, str(timestamp), nonce]
    ).encode("utf-8")


def sign_request(
    token: str,
    method: str,
    path: str,
    query: str = "",
    body: bytes | str = b"",
    timestamp: str | int | float = "",
    nonce: str = "",
) -> str:
    """Return an HMAC-SHA256 signature.

    The presented one-time token is the HMAC key. The server stores only its
    SHA-256 lookup hash and never logs or returns the token again.
    """

    return hmac.new(
        token.encode("utf-8"),
        canonical_request(method, path, query, body, timestamp, nonce),
        hashlib.sha256,
    ).hexdigest()


def _header(request: Request, *names: str) -> str | None:
    for name in names:
        value = request.headers.get(name)
        if value is not None:
            return value.strip()
    return None


def create_agent(
    db: Session,
    owner_id: int,
    name: str,
    scopes: list[str] | None = None,
    account_ids: list[int] | None = None,
    venues: list[str] | None = None,
) -> tuple[ExecutionAgent, str]:
    owner = db.get(User, owner_id)
    if owner is None:
        raise ValueError("用户不存在")
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("agent 名称不能为空")
    chosen_scopes = sorted({str(scope).strip() for scope in (scopes or DEFAULT_AGENT_SCOPES) if str(scope).strip()})
    if not chosen_scopes:
        raise ValueError("agent scope 不能为空")
    bound_accounts = sorted({int(account_id) for account_id in (account_ids or [])})
    if any(account_id <= 0 for account_id in bound_accounts):
        raise ValueError("agent account scope 无效")
    bound_venues = sorted({str(venue).strip() for venue in (venues or ["binance_usdm"]) if str(venue).strip()})
    if bound_venues != ["binance_usdm"]:
        raise ValueError("仅允许 Binance TEST venue")
    token = secrets.token_urlsafe(48)
    agent = ExecutionAgent(
        owner_id=owner_id,
        name=clean_name,
        environment=TEST_ENVIRONMENT,
        scopes=chosen_scopes,
        account_ids=bound_accounts,
        venues=bound_venues,
        token_hash=hash_agent_token(token),
        token_fingerprint=token_fingerprint(token),
        status="active",
    )
    try:
        with db.begin_nested():
            db.add(agent)
            db.flush()
    except IntegrityError as exc:
        raise ValueError("agent 名称已存在") from exc
    return agent, token


def _parse_timestamp(raw: str | None) -> datetime:
    if raw is None:
        raise AgentAuthError("缺少请求时间戳")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise AgentAuthError("请求时间戳无效") from exc
    # Accept seconds (the wire format) and reject millisecond confusion.
    if abs(value) > 10_000_000_000:
        value /= 1000
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise AgentAuthError("请求时间戳无效") from exc


def authenticate_request(
    db: Session,
    request: Request,
    body: bytes,
    required_scope: str | None = None,
) -> ExecutionAgent:
    """Authenticate and consume one persistent request nonce.

    A nonce is flushed in a savepoint before route work.  The route owns the
    outer commit; a duplicate nonce therefore fails even when the operation is
    later rejected by business validation.
    """

    settings = get_settings()
    if not getattr(settings, "execution_control_enabled", False):
        raise AgentAuthError("执行控制平面当前已暂停", 503)
    token = _header(request, "X-Execution-Agent-Token", "X-Agent-Token")
    timestamp_raw = _header(request, "X-Execution-Agent-Timestamp", "X-Agent-Timestamp")
    nonce = _header(request, "X-Execution-Agent-Nonce", "X-Agent-Nonce")
    signature = _header(request, "X-Execution-Agent-Signature", "X-Agent-Signature")
    if not token or not nonce or not signature:
        raise AgentAuthError("机器认证请求头不完整")
    if len(nonce) > 128 or len(signature) != 64:
        raise AgentAuthError("机器认证请求头无效")
    agent = db.scalar(
        select(ExecutionAgent).where(
            ExecutionAgent.token_hash == hash_agent_token(token),
            ExecutionAgent.environment == TEST_ENVIRONMENT,
            ExecutionAgent.status == "active",
        )
    )
    if agent is None:
        raise AgentAuthError("agent 不存在或已撤销")
    timestamp = _parse_timestamp(timestamp_raw)
    skew = max(1, int(getattr(settings, "execution_agent_clock_skew_seconds", 300)))
    if abs((now_utc() - timestamp).total_seconds()) > skew:
        raise AgentAuthError("请求已过期", 401)
    canonical = canonical_request(
        request.method,
        request.url.path,
        request.url.query,
        body,
        timestamp_raw or "",
        nonce,
    )
    expected_signature = hmac.new(token.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected_signature):
        raise AgentAuthError("签名无效")
    if required_scope and required_scope not in (agent.scopes or []):
        raise AgentAuthError("agent scope 不足", 403)
    max_per_minute = max(1, int(getattr(settings, "execution_agent_max_requests_per_minute", 120)))
    recent_cutoff = now_utc().replace(microsecond=0)
    # The nonce table is the durable rate counter; this is intentionally a
    # bounded indexed count and needs no Redis dependency.
    from datetime import timedelta

    recent_count = db.scalar(
        select(func.count(ExecutionRequestNonce.id)).where(
            ExecutionRequestNonce.agent_id == agent.id,
            ExecutionRequestNonce.created_at >= recent_cutoff - timedelta(minutes=1),
        )
    ) or 0
    if recent_count >= max_per_minute:
        raise AgentAuthError("agent 请求频率超限", 429)
    nonce_row = ExecutionRequestNonce(
        agent_id=agent.id,
        nonce=nonce,
        request_timestamp=timestamp,
    )
    try:
        with db.begin_nested():
            db.add(nonce_row)
            db.flush()
    except IntegrityError as exc:
        raise AgentAuthError("请求 nonce 已使用", 409) from exc
    agent.last_seen_at = now_utc()
    db.flush()
    # Authentication is its own durable boundary: a valid signed request
    # consumes its nonce even when the later route-level scope/business check
    # rejects the operation.
    db.commit()
    return agent
