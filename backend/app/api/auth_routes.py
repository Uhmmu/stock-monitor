from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_token, get_admin_user, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(prefix='/api/auth')


class LoginReq(BaseModel):
    username: str
    password: str
    remember: bool = False


class RegisterReq(BaseModel):
    username: str
    password: str


@router.post('/login')
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == req.username))
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, '用户名或密码错误')
    if user.status == 'pending':
        raise HTTPException(status.HTTP_403_FORBIDDEN, '账号审核中，请等待管理员激活')
    if user.status != 'active':
        raise HTTPException(status.HTTP_403_FORBIDDEN, '账号已被禁用')
    return {'token': create_token(user.id, req.remember), 'role': user.role, 'username': user.username}


@router.post('/register', status_code=201)
def register(req: RegisterReq, db: Session = Depends(get_db)):
    if len(req.username) < 2 or len(req.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, '用户名至少2位，密码至少6位')
    if db.scalar(select(User).where(User.username == req.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, '用户名已存在')
    db.add(User(username=req.username, password_hash=hash_password(req.password)))
    db.commit()
    return {'message': '注册申请已提交，等待管理员审核'}


@router.get('/me')
def me(user: User = Depends(get_current_user)):
    return {'id': user.id, 'username': user.username, 'role': user.role}


@router.get('/admin/users')
def list_users(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).order_by(User.created_at)).all()
    return [{'id': u.id, 'username': u.username, 'role': u.role, 'status': u.status,
             'created_at': u.created_at.isoformat()} for u in rows]


@router.post('/admin/users/{uid}/approve')
def approve(uid: int, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, '用户不存在')
    u.status = 'active'
    db.commit()
    return {'message': '已激活'}


@router.delete('/admin/users/{uid}')
def delete_user(uid: int, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, '用户不存在')
    if u.id == admin.id:
        raise HTTPException(400, '不能删除自己')
    db.delete(u)
    db.commit()
    return {'message': '已删除'}
