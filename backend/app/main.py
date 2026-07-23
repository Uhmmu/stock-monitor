import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.api.auth_routes import router as auth_router
from app.api.portfolio_routes import router as portfolio_router
from app.api.discovery_routes import router as discovery_router
from app.api.routes import public_router, router
from app.auth import hash_password
from app.database import SessionLocal
from app.models import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.role == 'admin')):
            db.add(User(
                username=os.getenv('ADMIN_USERNAME', 'admin'),
                password_hash=hash_password(os.getenv('ADMIN_INIT_PASSWORD', 'zzjjll20050418')),
                role='admin',
                status='active',
            ))
            db.commit()
    yield


app = FastAPI(title='股票监控 API', version='0.1.0', lifespan=lifespan)
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(router)
app.include_router(portfolio_router)
app.include_router(discovery_router)
