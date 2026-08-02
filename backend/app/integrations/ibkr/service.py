from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

from .client_portal_client import IbkrClientPortalClient
from .exceptions import IbkrAuthenticationRequiredError, IbkrBrokerageSessionError, IbkrCompetingSessionError
from .schemas import IbkrAccount, IbkrAccountSummary, IbkrPosition


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            if isinstance(value, dict):
                for nested in ("amount", "value", "rawValue"):
                    if value.get(nested) is not None:
                        return value[nested]
            return value
    return None


class IbkrReadOnlyService:
    def __init__(self, client: IbkrClientPortalClient):
        self.client = client
        self._account_cache: list[dict[str, Any]] = []
        self._account_cache_at = 0.0

    async def health(self):
        return await self.client.probe()

    async def auth_status(self):
        result = await self.client.request("auth_status", "POST", "/iserver/auth/status")
        raw = result["raw"] if isinstance(result["raw"], dict) else {}
        competing = bool(raw.get("competing"))
        result["normalized"] = {
            "authenticated": bool(raw.get("authenticated")), "connected": bool(raw.get("connected")),
            "competing": competing, "message": raw.get("message"),
        }
        return result

    async def initialize_session(self):
        current = await self.auth_status()
        if current["normalized"]["competing"]:
            raise IbkrCompetingSessionError("检测到其他 IBKR 客户端正在占用 Brokerage Session")
        result = await self.client.request(
            "initialize_session", "POST", "/iserver/auth/ssodh/init", json={"publish": True, "compete": False},
        )
        raw = result["raw"] if isinstance(result["raw"], dict) else {}
        if raw.get("competing"):
            raise IbkrCompetingSessionError("IBKR 拒绝初始化：存在 competing session")
        result["normalized"] = {"authenticated": bool(raw.get("authenticated")), "connected": bool(raw.get("connected"))}
        return result

    async def tickle(self):
        result = await self.client.request("tickle", "POST", "/tickle")
        result["normalized"] = {"session": (result["raw"] or {}).get("session") if isinstance(result["raw"], dict) else None}
        return result

    async def accounts(self, *, force: bool = False):
        if not force and self._account_cache and time.monotonic() - self._account_cache_at < 60:
            now = datetime.now(UTC)
            return {"success": True, "operation": "get_accounts", "timestamp": now, "started_at": now,
                    "completed_at": now, "duration_ms": 0,
                    "request": {"method": "GET", "path": "/portfolio/accounts", "query": {}},
                    "status_code": 200, "normalized": self._account_cache, "raw": None,
                    "warnings": ["使用 60 秒内的账户 allowlist 缓存以遵守 IBKR pacing 限制"]}
        result = await self.client.request("get_accounts", "GET", "/portfolio/accounts")
        rows = result["raw"] if isinstance(result["raw"], list) else []
        result["normalized"] = [IbkrAccount(**{
            "account_id": _first(row, "accountId", "id", "accountVan"),
            "display_name": _first(row, "displayName", "accountAlias", "accountTitle"),
            "currency": row.get("currency"), "brokerage_access": row.get("brokerageAccess"),
        }).model_dump() for row in rows if isinstance(row, dict) and _first(row, "accountId", "id", "accountVan")]
        self._account_cache = result["normalized"]
        self._account_cache_at = time.monotonic()
        return result

    async def _validated_account(self, account_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", account_id):
            raise IbkrAuthenticationRequiredError("账户 ID 格式无效")
        accounts = await self.accounts()
        allowed = {row["account_id"] for row in accounts["normalized"]}
        if account_id not in allowed:
            raise IbkrAuthenticationRequiredError("账户不在当前 IBKR 会话返回的账户列表中")

    async def summary(self, account_id: str):
        await self._validated_account(account_id)
        summary = await self.client.request("get_account_summary", "GET", f"/portfolio/{account_id}/summary")
        ledger = await self.client.request("get_account_ledger", "GET", f"/portfolio/{account_id}/ledger")
        sraw = summary["raw"] if isinstance(summary["raw"], dict) else {}
        currencies = ledger["raw"] if isinstance(ledger["raw"], dict) else {}
        base = currencies.get("BASE", {}) if isinstance(currencies.get("BASE"), dict) else {}
        normalized = IbkrAccountSummary(**{
            "account_id": account_id,
            "net_liquidation": _first(sraw, "netliquidation", "netLiquidation", "net_liquidation"),
            "total_cash": _first(base, "cashbalance", "cashBalance", "totalcashvalue"),
            "buying_power": _first(sraw, "buyingpower", "buyingPower"),
            "available_funds": _first(sraw, "availablefunds", "availableFunds"),
            "excess_liquidity": _first(sraw, "excessliquidity", "excessLiquidity"),
            "initial_margin": _first(sraw, "initmarginreq", "initialMargin", "initialmargin"),
            "maintenance_margin": _first(sraw, "maintmarginreq", "maintenanceMargin", "maintmargin"),
            "unrealized_pnl": _first(base, "unrealizedpnl", "unrealizedPnl"),
            "realized_pnl": _first(base, "realizedpnl", "realizedPnl"),
            "base_currency": _first(base, "currency", "baseCurrency"),
        }).model_dump()
        summary["operation"] = "get_account_summary"
        summary["normalized"] = normalized
        summary["raw"] = {"summary": summary["raw"], "ledger": ledger["raw"]}
        summary["duration_ms"] += ledger["duration_ms"]
        return summary

    async def positions(self, account_id: str):
        await self._validated_account(account_id)
        all_rows, pages, result = [], [], None
        for page in range(100):
            current = await self.client.request("get_positions", "GET", f"/portfolio/{account_id}/positions/{page}")
            result = result or current
            rows = current["raw"] if isinstance(current["raw"], list) else []
            pages.append(rows)
            all_rows.extend(row for row in rows if isinstance(row, dict))
            if not rows:
                break
        assert result is not None
        result["raw"] = pages
        result["normalized"] = [IbkrPosition(**{
            "symbol": _first(row, "ticker", "symbol", "contractDesc"), "conid": _first(row, "conid", "conId"),
            "asset_class": _first(row, "assetClass", "secType"), "exchange": _first(row, "listingExchange", "exchange"),
            "currency": row.get("currency"), "position": _first(row, "position", "quantity"),
            "average_cost": _first(row, "avgCost", "averageCost"), "market_price": _first(row, "mktPrice", "marketPrice"),
            "market_value": _first(row, "mktValue", "marketValue"), "unrealized_pnl": _first(row, "unrealizedPnl", "unrealizedPNL"),
            "realized_pnl": _first(row, "realizedPnl", "realizedPNL"), "account_id": account_id,
        }).model_dump() for row in all_rows]
        result["warnings"] = ["持仓分页达到安全上限"] if len(pages) == 100 and pages[-1] else []
        return result

    async def orders(self, account_id: str):
        await self._validated_account(account_id)
        result = await self.client.request("get_open_orders", "GET", "/iserver/account/orders")
        raw = result["raw"] if isinstance(result["raw"], dict) else {}
        rows = raw.get("orders", []) if isinstance(raw.get("orders", []), list) else []
        result["normalized"] = [row for row in rows if _first(row, "acct", "account", "accountId") in {None, account_id}]
        return result

    async def trades(self, account_id: str):
        await self._validated_account(account_id)
        result = await self.client.request("get_trades", "GET", "/iserver/account/trades", query={"days": 1})
        rows = result["raw"] if isinstance(result["raw"], list) else []
        result["normalized"] = [row for row in rows if isinstance(row, dict) and _first(row, "acctId", "account", "accountId") in {None, account_id}]
        return result
