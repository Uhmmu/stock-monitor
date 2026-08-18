import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthSession, User

_bearer = HTTPBearer(auto_error=False)
_ALG = "HS256"

# Fail-closed secret policy: production refuses the historical default secret.
# Explicit dev/test environments may opt into the insecure default via APP_ENV.
_INSECURE_SECRETS = {"", "change-me"}
_DEV_ENVIRONMENTS = {"dev", "development", "local", "test", "testing", "pytest"}
_resolved_secret: str | None = None


def resolve_jwt_secret() -> str:
    global _resolved_secret
    if _resolved_secret is not None:
        return _resolved_secret
    secret = os.getenv("JWT_SECRET", "").strip()
    environment = os.getenv("APP_ENV", "production").strip().lower()
    if secret not in _INSECURE_SECRETS:
        _resolved_secret = secret
        return _resolved_secret
    if environment in _DEV_ENVIRONMENTS:
        _resolved_secret = "change-me"
        return _resolved_secret
    raise RuntimeError(
        "JWT_SECRET 未配置或仍为默认值；生产环境（APP_ENV 未设为 dev/test）必须设置强随机 JWT_SECRET 后才能启动"
    )


def _access_ttl_minutes(remember: bool) -> int | None:
    raw = os.getenv("ACCESS_TOKEN_TTL_MINUTES", "").strip()
    if not raw:
        return None  # legacy 7/30 day behaviour keeps existing web clients working
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, remember: bool = False) -> str:
    override = _access_ttl_minutes(remember)
    if override is not None:
        expire = datetime.now(UTC) + timedelta(minutes=override)
    else:
        expire = datetime.now(UTC) + timedelta(days=30 if remember else 7)
    return jwt.encode({"sub": str(user_id), "exp": expire}, resolve_jwt_secret(), algorithm=_ALG)


def access_token_expiry(remember: bool = False) -> datetime:
    override = _access_ttl_minutes(remember)
    if override is not None:
        return datetime.now(UTC) + timedelta(minutes=override)
    return datetime.now(UTC) + timedelta(days=30 if remember else 7)


def create_refresh_token() -> tuple[str, str]:
    """Return (plaintext token, sha256 hash). Only the hash is persisted."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_expiry(remember: bool) -> datetime:
    return datetime.now(UTC) + timedelta(days=30 if remember else 7)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; normalise to UTC for comparisons."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_auth_session(db: Session, user_id: int, remember: bool, family_id: str | None = None) -> tuple[str, AuthSession]:
    """Create an un-committed session row; callers own the transaction."""
    token, token_hash = create_refresh_token()
    session = AuthSession(
        user_id=user_id,
        token_hash=token_hash,
        family_id=family_id or str(uuid.uuid4()),
        expires_at=refresh_expiry(remember),
        remember=remember,
    )
    db.add(session)
    purge_stale_auth_sessions(db)
    return token, session


def purge_stale_auth_sessions(db: Session) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=7)
    db.query(AuthSession).filter(
        (AuthSession.expires_at < cutoff) | (AuthSession.revoked_at.isnot(None) & (AuthSession.revoked_at < cutoff))
    ).delete(synchronize_session=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    try:
        payload = jwt.decode(creds.credentials, resolve_jwt_secret(), algorithms=[_ALG])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的认证令牌")
    user = db.get(User, user_id)
    if not user or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或未激活")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user
