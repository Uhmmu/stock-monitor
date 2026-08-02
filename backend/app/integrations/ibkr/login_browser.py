from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import redis
from cryptography.fernet import Fernet, InvalidToken
if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright
try:
    from playwright.async_api import async_playwright
except ImportError:  # Credential storage and parser tests do not require Chromium.
    async_playwright = None

from app.config import Settings, get_settings


_CREDENTIAL_KEY = "ibkr:client-portal:credentials:v1"
_login_lock = asyncio.Lock()


class IbkrLoginError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SavedCredentials:
    username: str
    password: str


class IbkrCredentialStore:
    def __init__(self, settings: Settings | None = None, client=None):
        self.settings = settings or get_settings()
        self.client = client or redis.Redis.from_url(
            self.settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )

    def _fernet(self) -> Fernet:
        secret = self.settings.ibkr_credential_encryption_key.strip()
        if not secret:
            raise IbkrLoginError("CREDENTIAL_STORAGE_DISABLED", "服务端尚未配置 IBKR 凭据加密密钥")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        return Fernet(key)

    def save(self, username: str, password: str) -> None:
        payload = json.dumps({"username": username, "password": password}).encode()
        self.client.set(_CREDENTIAL_KEY, self._fernet().encrypt(payload))

    def load(self) -> SavedCredentials | None:
        encrypted = self.client.get(_CREDENTIAL_KEY)
        if not encrypted:
            return None
        try:
            payload = json.loads(self._fernet().decrypt(encrypted))
            return SavedCredentials(str(payload["username"]), str(payload["password"]))
        except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IbkrLoginError("CREDENTIAL_DECRYPTION_FAILED", "已保存的 IBKR 凭据无法解密") from exc

    def delete(self) -> None:
        self.client.delete(_CREDENTIAL_KEY)

    def status(self) -> dict[str, object]:
        saved = self.load()
        if not saved:
            return {"saved": False, "username_hint": ""}
        name = saved.username
        hint = name[:2] + "*" * max(2, len(name) - 4) + name[-2:] if len(name) > 4 else "****"
        return {"saved": True, "username_hint": hint}


def _gateway_login_url(settings: Settings) -> str:
    parsed = urlsplit(settings.ibkr_cp_base_url)
    if parsed.scheme != "https" or parsed.port != 5000:
        raise IbkrLoginError("INVALID_GATEWAY_URL", "Gateway 登录地址配置无效")
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


async def _authenticated(page) -> bool:
    try:
        return bool(await page.evaluate("""async () => {
            try {
              const response = await fetch('/v1/api/iserver/auth/status', {method: 'POST'});
              if (!response.ok) return false;
              const body = await response.json();
              return Boolean(body.authenticated);
            } catch (_) { return false; }
        }"""))
    except Exception:
        pass
    return False


async def login_with_browser(username: str, password: str, settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    if not settings.ibkr_cp_enabled:
        raise IbkrLoginError("GATEWAY_DISABLED", "IBKR Client Portal Gateway 尚未启用")
    if not username.strip() or not password:
        raise IbkrLoginError("CREDENTIALS_REQUIRED", "请输入 IBKR 用户名和密码")
    if async_playwright is None:
        raise IbkrLoginError("LOGIN_BROWSER_UNAVAILABLE", "服务端未安装 Chromium 自动登录运行时")

    async with _login_lock:
        playwright: Any | None = None
        browser: Any | None = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                executable_path=settings.ibkr_login_browser_executable,
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    f"--proxy-server={settings.ibkr_proxy_url.replace('socks5h://', 'socks5://')}",
                    "--proxy-bypass-list=host.docker.internal;127.0.0.1;localhost",
                ],
            )
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            await page.goto(_gateway_login_url(settings), wait_until="domcontentloaded", timeout=30_000)
            await page.locator(".xyz-username").wait_for(state="visible", timeout=30_000)
            await page.locator(".xyz-username").fill(username.strip())
            await page.locator(".xyz-password").fill(password)
            await page.locator(".xyzform-username").evaluate("form => form.requestSubmit()")

            deadline = asyncio.get_running_loop().time() + settings.ibkr_login_timeout_seconds
            saw_second_factor = False
            while asyncio.get_running_loop().time() < deadline:
                if await _authenticated(page):
                    return {"authenticated": True, "second_factor_approved": saw_second_factor}
                try:
                    saw_second_factor = saw_second_factor or await page.locator(
                        ".xyzblock-notification,.xyzform-silver,.xyzform-gold,.xyzblock-qrcode"
                    ).first.is_visible()
                    error_box = page.locator(".xyz-errormessage").first
                    message = (await error_box.text_content() or "").strip() if await error_box.is_visible() else ""
                    if message and not saw_second_factor:
                        raise IbkrLoginError("LOGIN_REJECTED", message[:300])
                except IbkrLoginError:
                    raise
                except Exception:
                    pass
                await page.wait_for_timeout(2_000)
            code = "SECOND_FACTOR_TIMEOUT" if saw_second_factor else "LOGIN_TIMEOUT"
            raise IbkrLoginError(code, "等待手机 IB Key 批准超时，请重新点击登录")
        except IbkrLoginError:
            raise
        except Exception as exc:
            raise IbkrLoginError("LOGIN_BROWSER_FAILED", f"Gateway 自动登录失败：{type(exc).__name__}") from exc
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
