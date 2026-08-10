import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.ai.config import close_provider_registry, get_provider_registry
from app.ai.conversations import router as ai_conversations_router
from app.ai.router import router as ai_router
from app.ai_tools.router import router as ai_tools_router
from app.ai_memory.router import router as ai_memory_router
from app.api.auth_routes import router as auth_router
from app.api.compare_routes import router as compare_router
from app.api.discovery_routes import router as discovery_router
from app.api.investment_routes import router as investment_router
from app.api.macro_routes import admin_router as macro_admin_router, router as macro_router
from app.api.market_routes import router as market_router
from app.api.portfolio_analysis_routes import router as portfolio_analysis_router
from app.api.portfolio_routes import router as portfolio_router
from app.api.routes import public_router, router
from app.api.sentiment_routes import router as sentiment_router
from app.auth import hash_password
from app.config import get_settings
from app.database import SessionLocal
from app.external_search.deep_search.runtime import deep_search_runtime
from app.external_search.deep_search.service import DeepSearchService
from app.external_search.registry import (
    close_external_search_registry,
    get_external_search_registry,
)
from app.external_search.router import router as external_search_router
from app.models import User
from app.integrations.ibkr import formal_router as ibkr_formal_router, router as ibkr_router
from app.integrations.ibkr.client_portal_client import close_client_portal_client
from app.integrations.ibkr.flex_client import close_flex_client
from app.research import router as research_router
from app.research.exceptions import ResearchError
from app.research.router import research_audit_middleware, research_error_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate explicit provider registration without requiring credentials or
    # making a paid/network health-check request.
    if get_settings().ai_enabled:
        get_provider_registry().get(get_settings().ai_provider)
    if get_settings().exa_enabled:
        get_external_search_registry().get("exa")
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.role == 'admin')):
            db.add(User(
                username=os.getenv('ADMIN_USERNAME', 'admin'),
                password_hash=hash_password(os.getenv('ADMIN_INIT_PASSWORD', 'zzjjll20050418')),
                role='admin',
                status='active',
            ))
            db.commit()
        if get_settings().exa_enabled and get_settings().exa_api_key:
            await DeepSearchService(db).recover_stale_runs(limit=100)
    try:
        yield
    finally:
        await deep_search_runtime.shutdown()
        await close_client_portal_client()
        await close_flex_client()
        if get_settings().ai_enabled:
            await close_provider_registry()
        if get_settings().exa_enabled:
            await close_external_search_registry()


app = FastAPI(title='股票监控 API', version='0.1.0', lifespan=lifespan)
app.middleware("http")(research_audit_middleware)
app.add_exception_handler(ResearchError, research_error_handler)
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(compare_router)
app.include_router(router)
app.include_router(portfolio_router)
app.include_router(portfolio_analysis_router)
app.include_router(discovery_router)
app.include_router(sentiment_router)
app.include_router(investment_router)
app.include_router(macro_router)
app.include_router(macro_admin_router)
app.include_router(market_router)
app.include_router(research_router)
app.include_router(ai_tools_router)
app.include_router(ai_router)
app.include_router(ai_conversations_router)
app.include_router(ai_memory_router)
app.include_router(external_search_router)
app.include_router(ibkr_router)
app.include_router(ibkr_formal_router)
