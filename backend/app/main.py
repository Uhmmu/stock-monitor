import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.ai.config import close_provider_registry, get_provider_registry
from app.ai.conversations import router as ai_conversations_router
from app.ai.router import router as ai_router
from app.ai_tools.router import router as ai_tools_router
from app.ai_memory.router import router as ai_memory_router
from app.api.auth_routes import router as auth_router
from app.api.client_capabilities import router as client_capabilities_router
from app.api.compare_routes import router as compare_router
from app.api.crypto_routes import router as crypto_router
from app.api.agent_gateway_routes import router as agent_gateway_router
from app.api.discovery_routes import router as discovery_router
from app.api.execution_admin_routes import router as execution_admin_router
from app.api.execution_agent_routes import router as execution_agent_router
from app.api.investment_routes import router as investment_router
from app.api.industry_pulse_routes import router as industry_pulse_router
from app.api.macro_routes import admin_router as macro_admin_router, router as macro_router
from app.api.market_routes import router as market_router
from app.api.mood_routes import router as mood_router
from app.api.mood_validation_routes import router as mood_validation_router
from app.api.options_routes import router as options_router
from app.api.quant_routes import router as quant_router
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
from app.models import MoodDailyRun, User
from app.integrations.ibkr import formal_router as ibkr_formal_router, router as ibkr_router
from app.integrations.ibkr.client_portal_client import close_client_portal_client
from app.integrations.ibkr.flex_client import close_flex_client
from app.services.industry_pulse.service import ensure_seed_data
from app.services.market_calendar import expected_latest_market_session
from app.auth import resolve_jwt_secret
from app.research import router as research_router
from app.research.exceptions import ResearchError
from app.research.router import research_audit_middleware, research_error_handler


logger = logging.getLogger(__name__)


def ensure_admin_user(db) -> None:
    """Bootstrap the initial admin if none exists; fail closed without a password."""
    if db.scalar(select(User).where(User.role == 'admin')):
        return
    init_password = os.getenv('ADMIN_INIT_PASSWORD', '').strip()
    if not init_password:
        raise RuntimeError(
            '数据库中不存在管理员，且未设置 ADMIN_INIT_PASSWORD；'
            '必须在环境变量中提供初始管理员密码后才能启动'
        )
    db.add(User(
        username=os.getenv('ADMIN_USERNAME', 'admin'),
        password_hash=hash_password(init_password),
        role='admin',
        status='active',
    ))
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed: refuse to serve with the historical default/empty JWT secret
    # unless APP_ENV explicitly marks a development/test environment.
    resolve_jwt_secret()
    # Validate explicit provider registration without requiring credentials or
    # making a paid/network health-check request.
    if get_settings().ai_enabled:
        get_provider_registry().get(get_settings().ai_provider)
    if get_settings().exa_enabled:
        get_external_search_registry().get("exa")
    with SessionLocal() as db:
        ensure_seed_data(db)
        db.commit()
        latest_session = expected_latest_market_session()
        if latest_session and not db.scalar(select(MoodDailyRun.id).where(
            MoodDailyRun.trading_date == latest_session,
            MoodDailyRun.calculation_version == "mood_v1",
            MoodDailyRun.status == "COMPLETED",
        ).limit(1)):
            logger.warning("mood_eod_history_missing trading_date=%s", latest_session)
        ensure_admin_user(db)
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
app.include_router(client_capabilities_router)
app.include_router(auth_router)
app.include_router(compare_router)
app.include_router(crypto_router)
app.include_router(quant_router)
app.include_router(router)
app.include_router(portfolio_router)
app.include_router(portfolio_analysis_router)
app.include_router(discovery_router)
app.include_router(execution_admin_router)
app.include_router(execution_agent_router)
app.include_router(agent_gateway_router)
app.include_router(sentiment_router)
app.include_router(investment_router)
app.include_router(industry_pulse_router)
app.include_router(macro_router)
app.include_router(macro_admin_router)
app.include_router(market_router)
app.include_router(mood_router)
app.include_router(mood_validation_router)
app.include_router(options_router)
app.include_router(research_router)
app.include_router(ai_tools_router)
app.include_router(ai_router)
app.include_router(ai_conversations_router)
app.include_router(ai_memory_router)
app.include_router(external_search_router)
app.include_router(ibkr_router)
app.include_router(ibkr_formal_router)
