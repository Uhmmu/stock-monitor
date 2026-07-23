from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_token, get_admin_user, get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(prefix='/api/auth')


REDDIT_OAUTH_CALLBACK_PAGE = '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Reddit OAuth Callback</title>
  <style>
    :root {
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
      color: #1d1d1f;
      background: #f5f5f7;
      font-synthesis: none;
      -webkit-font-smoothing: antialiased;
    }
    * { box-sizing: border-box; }
    body {
      min-width: 320px;
      min-height: 100vh;
      min-height: 100svh;
      margin: 0;
      padding: 24px;
      display: grid;
      place-items: center;
    }
    main {
      width: min(100%, 560px);
      padding: clamp(32px, 7vw, 52px);
      text-align: center;
      background: #fff;
      border: 1px solid rgba(0, 0, 0, .08);
      border-radius: 24px;
      box-shadow: 0 16px 48px rgba(0, 0, 0, .07);
    }
    h1 {
      margin: 0;
      font-size: clamp(28px, 6vw, 38px);
      line-height: 1.1;
      letter-spacing: -.035em;
    }
    p {
      margin: 20px 0 0;
      color: #6e6e73;
      font-size: 16px;
      line-height: 1.6;
    }
    p + p {
      margin-top: 8px;
      color: #8e8e93;
      font-size: 14px;
    }
    @media (prefers-color-scheme: dark) {
      :root { color: #f5f5f7; background: #111113; }
      main {
        background: #1c1c1e;
        border-color: rgba(255, 255, 255, .1);
        box-shadow: 0 16px 48px rgba(0, 0, 0, .24);
      }
      p { color: #aeaeb2; }
      p + p { color: #8e8e93; }
    }
    @media (prefers-contrast: more) {
      main { border-color: currentColor; box-shadow: none; }
    }
  </style>
</head>
<body>
  <main>
    <h1>Reddit OAuth Callback</h1>
    <p>This endpoint is reserved for Reddit OAuth authentication.</p>
    <p>No user action is required.</p>
  </main>
</body>
</html>'''


class LoginReq(BaseModel):
    username: str
    password: str
    remember: bool = False


class RegisterReq(BaseModel):
    username: str
    password: str


@router.get('/reddit/callback', response_class=HTMLResponse)
def reddit_oauth_callback():
    return HTMLResponse(
        REDDIT_OAUTH_CALLBACK_PAGE,
        headers={'Cache-Control': 'no-store'},
    )


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
