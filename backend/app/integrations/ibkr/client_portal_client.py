from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings, get_settings

from .exceptions import (
    IbkrApiError, IbkrAuthenticationRequiredError, IbkrBrokerageSessionError, IbkrCompetingSessionError, IbkrDisabledError,
    IbkrConfigurationError, IbkrGatewayTimeoutError, IbkrGatewayUnavailableError, IbkrInvalidResponseError,
)
from .redaction import sanitize


class IbkrClientPortalClient:
    """Dedicated local-only client. It never accepts a caller-controlled URL or path."""

    ALLOWED_PATHS = {
        "/sso/validate", "/iserver/auth/status", "/iserver/auth/ssodh/init", "/tickle",
        "/portfolio/accounts", "/iserver/account/orders", "/iserver/account/trades",
    }
    ACCOUNT_SUFFIXES = {"summary", "ledger", "positions"}

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        parsed = urlsplit(self.settings.ibkr_cp_base_url)
        if parsed.scheme != "https" or parsed.hostname not in {"127.0.0.1", "localhost", "host.docker.internal"} or parsed.port != 5000:
            raise IbkrConfigurationError("IBKR_CP_BASE_URL 必须是本机或受控 Docker host gateway 的 HTTPS Gateway 地址")
        self.gateway_origin = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        self._owned = client is None
        self.client = client or httpx.AsyncClient(
            base_url=self.settings.ibkr_cp_base_url.rstrip("/"),
            verify=self.settings.ibkr_cp_verify_ssl,
            timeout=httpx.Timeout(
                self.settings.ibkr_cp_read_timeout_seconds,
                connect=self.settings.ibkr_cp_connect_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            trust_env=False,
        )

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()

    async def probe(self) -> dict[str, Any]:
        """Probe only the fixed Gateway origin; authentication is tested separately."""
        if not self.settings.ibkr_cp_enabled:
            raise IbkrDisabledError("IBKR Client Portal Gateway 未启用")
        started = datetime.now(UTC)
        began = time.perf_counter()
        try:
            response = await self.client.get(self.gateway_origin + "/")
        except httpx.TimeoutException as exc:
            raise IbkrGatewayTimeoutError("访问 Client Portal Gateway 超时") from exc
        except httpx.RequestError as exc:
            raise IbkrGatewayUnavailableError("无法连接 VPS 本机的 Client Portal Gateway") from exc
        completed = datetime.now(UTC)
        return {
            "success": True, "operation": "gateway_health", "timestamp": completed,
            "started_at": started, "completed_at": completed,
            "duration_ms": round((time.perf_counter() - began) * 1000),
            "request": {"method": "GET", "path": "/", "query": {}},
            "status_code": response.status_code,
            "normalized": {"reachable": True},
            "raw": {"content_type": response.headers.get("content-type", ""), "body_returned": bool(response.content)},
            "warnings": ["Gateway 尚未认证时，根页面网络探测与认证状态是两个独立结果"],
        }

    @classmethod
    def _validate_path(cls, path: str) -> None:
        if path in cls.ALLOWED_PATHS:
            return
        parts = path.strip("/").split("/")
        if len(parts) in {3, 4} and parts[:1] == ["portfolio"] and parts[1] and parts[2] in cls.ACCOUNT_SUFFIXES:
            if len(parts) == 3 or (parts[2] == "positions" and parts[3].isdigit()):
                return
        raise ValueError("IBKR 请求路径不在只读 allowlist 中")

    async def request(self, operation: str, method: str, path: str, *, query: dict[str, Any] | None = None,
                      json: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.ibkr_cp_enabled:
            raise IbkrDisabledError("IBKR Client Portal Gateway 未启用")
        self._validate_path(path)
        started = datetime.now(UTC)
        began = time.perf_counter()
        try:
            response = await self.client.request(method, path, params=query, json=json)
        except httpx.TimeoutException as exc:
            raise IbkrGatewayTimeoutError("访问 Client Portal Gateway 超时") from exc
        except httpx.RequestError as exc:
            raise IbkrGatewayUnavailableError("无法连接 VPS 本机的 Client Portal Gateway") from exc
        completed = datetime.now(UTC)
        content_type = response.headers.get("content-type", "")
        try:
            raw: Any = response.json()
        except ValueError:
            raw = {"content_type": content_type, "text_summary": response.text[:4000]}
            if response.is_success:
                raise IbkrInvalidResponseError("Gateway 返回了无法解析的非 JSON 响应")
        raw = sanitize(raw)
        duration = round((time.perf_counter() - began) * 1000)
        raw_message = " ".join(str(raw.get(key, "")) for key in ("error", "message", "fail") if isinstance(raw, dict)).lower()
        if response.status_code in {401, 403} or (operation == "auth_status" and response.status_code == 404):
            raise IbkrAuthenticationRequiredError("Client Portal Gateway 尚未完成认证")
        if not response.is_success:
            if "competing" in raw_message:
                raise IbkrCompetingSessionError("检测到 competing brokerage session")
            if "brokerage session" in raw_message or "no bridge" in raw_message:
                raise IbkrBrokerageSessionError("Brokerage Session 尚未连接")
            if "auth" in raw_message or "login" in raw_message:
                raise IbkrAuthenticationRequiredError("Client Portal Gateway 尚未完成认证")
            raise IbkrApiError("IBKR API 请求失败", detail=f"HTTP {response.status_code}")
        return {
            "success": True, "operation": operation, "timestamp": completed,
            "started_at": started, "completed_at": completed, "duration_ms": duration,
            "request": {"method": method, "path": path, "query": sanitize(query or {})},
            "status_code": response.status_code, "normalized": None, "raw": raw, "warnings": [],
        }


_client_portal_client: IbkrClientPortalClient | None = None


def get_client_portal_client() -> IbkrClientPortalClient:
    global _client_portal_client
    if _client_portal_client is None:
        _client_portal_client = IbkrClientPortalClient()
    return _client_portal_client


async def close_client_portal_client() -> None:
    global _client_portal_client
    if _client_portal_client is not None:
        await _client_portal_client.close()
        _client_portal_client = None
