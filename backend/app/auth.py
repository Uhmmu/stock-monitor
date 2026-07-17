import os
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)
_SECRET = os.getenv("JWT_SECRET", "change-me")
_ALG = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, remember: bool = False) -> str:
    expire = datetime.now(UTC) + timedelta(days=30 if remember else 7)
    return jwt.encode({"sub": str(user_id), "exp": expire}, _SECRET, algorithm=_ALG)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    try:
        payload = jwt.decode(creds.credentials, _SECRET, algorithms=[_ALG])
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
