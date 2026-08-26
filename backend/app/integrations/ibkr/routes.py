from __future__ import annotations

from datetime import UTC, datetime
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth import get_admin_user
from app.config import get_settings
from .client_portal_client import get_client_portal_client
from .exceptions import IbkrError
from .flex_client import get_flex_client
from .service import IbkrReadOnlyService
from .login_browser import IbkrCredentialStore, IbkrLoginError, login_with_browser
from .schemas import IbkrLoginRequest

router = APIRouter(prefix="/api/admin/integrations/ibkr", tags=["admin-ibkr"], dependencies=[Depends(get_admin_user)])


def _error(operation: str, exc: IbkrError) -> JSONResponse:
    now = datetime.now(UTC).isoformat()
    return JSONResponse(status_code=exc.status_code, content={"success": False, "operation": operation,
        "timestamp": now, "started_at": now, "completed_at": now, "duration_ms": 0,
        "request": {"method": "", "path": "", "query": {}}, "status_code": exc.status_code,
        "normalized": None, "raw": None, "warnings": [],
        "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}})


async def _cp(operation: str, call: Callable[[IbkrReadOnlyService], Awaitable[dict]]):
    try:
        return await call(_service())
    except IbkrError as exc:
        return _error(operation, exc)


_read_only_service: IbkrReadOnlyService | None = None


def _service() -> IbkrReadOnlyService:
    global _read_only_service
    if _read_only_service is None:
        _read_only_service = IbkrReadOnlyService(get_client_portal_client())
    return _read_only_service


@router.get("/config")
def config():
    settings = get_settings()
    login = urlsplit(settings.ibkr_cp_login_url)
    safe_login_url = settings.ibkr_cp_login_url if login.scheme == "https" and login.hostname in {"localhost", "127.0.0.1"} and login.port == 5000 else "https://localhost:5000"
    return {"cp_enabled": settings.ibkr_cp_enabled, "cp_login_url": safe_login_url,
            "cp_verify_ssl": settings.ibkr_cp_verify_ssl, "username_hint": settings.ibkr_username_hint,
            "cp_account_id_configured": bool(settings.ibkr_cp_account_id),
            "flex_enabled": settings.ibkr_flex_enabled,
            "flex_configured": bool(settings.ibkr_flex_token and settings.ibkr_flex_query_id),
            "proxy_enforced": settings.ibkr_proxy_url in {"socks5h://127.0.0.1:10808", "socks5h://host.docker.internal:10808"}, "read_only": True,
            "credential_storage_enabled": bool(settings.ibkr_credential_encryption_key),
            "warnings": ["Client Portal Gateway 专用客户端已关闭 TLS 校验；此设置仅允许用于本机自签名 Gateway。"] if not settings.ibkr_cp_verify_ssl else []}


@router.get("/login/credentials")
def credential_status():
    try:
        return IbkrCredentialStore().status()
    except IbkrLoginError as exc:
        return JSONResponse(status_code=400, content={"saved": False, "username_hint": "", "error": {"code": exc.code, "message": str(exc)}})


@router.delete("/login/credentials")
def delete_credentials():
    IbkrCredentialStore().delete()
    return {"success": True}


@router.post("/login")
async def login(payload: IbkrLoginRequest):
    store = IbkrCredentialStore()
    try:
        username, password = payload.username.strip(), payload.password
        if not username and not password:
            saved = store.load()
            if not saved:
                raise IbkrLoginError("CREDENTIALS_REQUIRED", "没有已保存的 IBKR 凭据")
            username, password = saved.username, saved.password
        elif not username or not password:
            raise IbkrLoginError("CREDENTIALS_REQUIRED", "用户名和密码必须同时填写")
        result = await login_with_browser(username, password)
        if payload.save_credentials:
            store.save(username, password)
        return {"success": True, **result}
    except IbkrLoginError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": {"code": exc.code, "message": str(exc)}})


@router.get("/gateway/health")
async def health(): return await _cp("gateway_health", lambda service: service.health())


@router.get("/auth/status")
async def auth_status(): return await _cp("auth_status", lambda service: service.auth_status())


@router.post("/session/initialize")
async def initialize(): return await _cp("initialize_session", lambda service: service.initialize_session())


@router.post("/tickle")
async def tickle(): return await _cp("tickle", lambda service: service.tickle())


@router.get("/accounts")
async def accounts(): return await _cp("get_accounts", lambda service: service.accounts(force=True))


@router.get("/accounts/{account_id}/summary")
async def summary(account_id: str): return await _cp("get_account_summary", lambda service: service.summary(account_id))


@router.get("/accounts/{account_id}/positions")
async def positions(account_id: str): return await _cp("get_positions", lambda service: service.positions(account_id))


@router.get("/accounts/{account_id}/orders")
async def orders(account_id: str): return await _cp("get_open_orders", lambda service: service.orders(account_id))


@router.get("/accounts/{account_id}/trades")
async def trades(account_id: str): return await _cp("get_trades", lambda service: service.trades(account_id))


@router.get("/flex/status")
async def flex_status():
    try:
        return get_flex_client().status()
    except IbkrError as exc:
        return _error("flex_status", exc)


@router.post("/flex/test")
async def flex_test():
    try:
        client = get_flex_client()
        initiated = await client.initiate_report()
        return {"success": True, "operation": "flex_test", "timestamp": datetime.now(UTC),
                "duration_ms": initiated["duration_ms"], "status_code": initiated["status_code"],
                "normalized": {"reference_code_received": True}, "raw": {"xml": initiated["raw_xml"]}, "warnings": []}
    except IbkrError as exc: return _error("flex_test", exc)


@router.post("/flex/run")
async def flex_run():
    try:
        client = get_flex_client()
        return await client.run_query()
    except IbkrError as exc: return _error("flex_run", exc)
