from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

from .constants import BINANCE_TEST_ORIGIN, MAX_RECV_WINDOW_MS
from .errors import (
    AmbiguousOrderError,
    BinanceError,
    BinanceProtocolError,
    BinanceRedirectError,
    BinanceTimeout,
    BinanceTransportError,
    UnresolvedOrderError,
)
from .security import redact, validate_binance_origin


def _decimal(value: object, fallback: Decimal = Decimal("0")) -> Decimal:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else fallback
    except (InvalidOperation, TypeError, ValueError):
        return fallback


def decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


@dataclass(frozen=True)
class ExchangeFilter:
    symbol: str
    step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None
    min_notional: Decimal | None


@dataclass(frozen=True)
class BinanceAccount:
    available_balance_usdt: Decimal | None
    equity_usdt: Decimal | None
    gross_notional_usdt: Decimal | None
    net_notional_usdt: Decimal | None
    positions: Mapping[str, Decimal]
    open_orders: int | None
    as_of: float
    daily_loss_usdt: Decimal | None = None
    drawdown_usdt: Decimal | None = None
    last_order_at: float | None = None


class BinanceClient:
    """Narrow Binance Futures Demo adapter.

    There is intentionally no generic base URL setting. Tests may use the
    explicit ``for_test`` constructor with an httpx MockTransport/local server;
    runtime construction is pinned to ``BINANCE_TEST_ORIGIN``.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        clock=time.time,
        _test_base_url: str | None = None,
        _test_only: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.clock = clock
        self.server_offset_ms = 0
        self._owns_client = True
        base_url = validate_binance_origin(_test_base_url, allow_test_server=_test_only)
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            verify=True,
        )

    @classmethod
    def for_test(
        cls,
        api_key: str = "test-key",
        api_secret: str = "test-secret",
        *,
        base_url: str = "http://testserver",
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        clock=time.time,
    ) -> "BinanceClient":
        """Explicit test-only constructor; production config cannot select it."""

        return cls(
            api_key,
            api_secret,
            transport=transport,
            timeout=timeout,
            clock=clock,
            _test_base_url=base_url,
            _test_only=True,
        )

    @property
    def origin(self) -> str:
        return str(self._client.base_url).rstrip("/")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        signed: bool = False,
    ) -> object:
        query: dict[str, object] = dict(params or {})
        headers = {"Accept": "application/json"}
        if signed:
            query.setdefault("timestamp", int(self.clock() * 1000) + self.server_offset_ms)
            query.setdefault("recvWindow", MAX_RECV_WINDOW_MS)
            if int(query["recvWindow"]) > MAX_RECV_WINDOW_MS:
                raise BinanceProtocolError("recvWindow exceeds 5000ms")
            query_string = urlencode(query, doseq=True)
            import hashlib
            import hmac

            query["signature"] = hmac.new(
                self.api_secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            headers["X-MBX-APIKEY"] = self.api_key
        try:
            response = self._client.request(method, path, params=query, headers=headers)
        except httpx.TimeoutException as exc:
            raise BinanceTimeout("Binance request timed out") from exc
        except httpx.TransportError as exc:
            raise BinanceTransportError("Binance transport failed") from exc
        if 300 <= response.status_code < 400:
            raise BinanceRedirectError("Binance redirect rejected")
        try:
            payload: object = response.json()
        except ValueError:
            payload = {"message": response.text[:500]}
        if not response.is_success:
            info = payload if isinstance(payload, Mapping) else {}
            code = info.get("code")
            message = str(info.get("msg", info.get("message", "Binance request failed")))
            try:
                code_value = int(code) if code is not None else None
            except (TypeError, ValueError):
                code_value = None
            raise BinanceError(str(redact(message, secrets_to_redact=(self.api_key, self.api_secret))), status_code=response.status_code, code=code_value)
        return payload

    def server_time(self) -> int:
        payload = self._request("GET", "/fapi/v1/time")
        if not isinstance(payload, Mapping) or payload.get("serverTime") is None:
            raise BinanceProtocolError("Binance time response is malformed")
        server_ms = int(payload["serverTime"])
        self.server_offset_ms = server_ms - int(self.clock() * 1000)
        return server_ms

    def exchange_filters(self, symbol: str) -> ExchangeFilter:
        payload = self._request("GET", "/fapi/v1/exchangeInfo")
        if not isinstance(payload, Mapping):
            raise BinanceProtocolError("exchangeInfo response is malformed")
        wanted = symbol.upper()
        for item in payload.get("symbols", []):
            if not isinstance(item, Mapping) or str(item.get("symbol", "")).upper() != wanted:
                continue
            if str(item.get("status", "")) != "TRADING":
                raise BinanceProtocolError("instrument is not trading")
            filters = {str(row.get("filterType")): row for row in item.get("filters", []) if isinstance(row, Mapping)}
            lot = filters.get("LOT_SIZE", {})
            notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
            result = ExchangeFilter(
                symbol=wanted,
                step_size=_decimal(lot.get("stepSize")),
                min_quantity=_decimal(lot.get("minQty")),
                max_quantity=_decimal(lot.get("maxQty")) if lot.get("maxQty") else None,
                min_notional=_decimal(notional.get("notional"), Decimal("0")) if notional.get("notional") else None,
            )
            if result.step_size <= 0 or result.min_quantity <= 0:
                raise BinanceProtocolError("exchange filters are incomplete")
            return result
        raise BinanceProtocolError("instrument is absent from exchangeInfo")

    def mark_price(self, symbol: str) -> tuple[Decimal, float]:
        payload = self._request("GET", "/fapi/v1/premiumIndex", params={"symbol": symbol.upper()})
        if not isinstance(payload, Mapping) or payload.get("markPrice") is None:
            raise BinanceProtocolError("mark price response is malformed")
        price = _decimal(payload.get("markPrice"))
        if price <= 0:
            raise BinanceProtocolError("mark price is not positive")
        return price, self.clock()

    def account_config(self) -> Mapping[str, object]:
        payload = self._request("GET", "/fapi/v1/accountConfig", signed=True)
        if not isinstance(payload, Mapping):
            raise BinanceProtocolError("accountConfig response is malformed")
        required = {
            "canTrade": False,
            "dualSidePosition": False,
            "multiAssetsMargin": False,
        }
        for key, expected in required.items():
            if payload.get(key) is not expected:
                raise BinanceProtocolError(f"Binance accountConfig is not safe: {key}")
        if "canWithdraw" in payload and payload.get("canWithdraw") is not False:
            raise BinanceProtocolError("Binance accountConfig withdrawal permission is enabled")
        return payload

    def account_snapshot(self) -> BinanceAccount:
        self.account_config()
        payload = self._request("GET", "/fapi/v3/account", signed=True)
        positions_payload = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        open_orders = self._request("GET", "/fapi/v1/openOrders", signed=True)
        if not isinstance(payload, Mapping) or not isinstance(positions_payload, list) or not isinstance(open_orders, list):
            raise BinanceProtocolError("account response is malformed")
        # This executor models one signed net position per symbol. Hedge-mode
        # legs would make target deltas ambiguous, so fail closed instead of
        # guessing which leg an order belongs to.
        if any(str(item.get("positionSide", "")) != "BOTH" for item in positions_payload if isinstance(item, Mapping)):
            raise BinanceProtocolError("Binance account contains hedge-mode positions")
        assets = [item for item in payload.get("assets", []) if isinstance(item, Mapping)]
        usdt = next((item for item in assets if item.get("asset") == "USDT"), {})
        positions: dict[str, Decimal] = {}
        gross = Decimal("0")
        net = Decimal("0")
        for item in positions_payload:
            if not isinstance(item, Mapping):
                continue
            symbol = str(item.get("symbol", "")).upper()
            amount = _decimal(item.get("positionAmt"))
            if symbol:
                positions[symbol] = amount
            mark = _decimal(item.get("markPrice"))
            gross += abs(amount * mark)
            net += amount * mark
        update_ms = payload.get("updateTime") or max((int(item.get("updateTime", 0)) for item in positions_payload if isinstance(item, Mapping)), default=0)
        return BinanceAccount(
            available_balance_usdt=_decimal(usdt.get("availableBalance"), None),
            equity_usdt=_decimal(payload.get("totalWalletBalance"), None),
            gross_notional_usdt=gross,
            net_notional_usdt=net,
            positions=positions,
            open_orders=len(open_orders),
            as_of=float(update_ms) / 1000 if update_ms else self.clock(),
            daily_loss_usdt=None,
            drawdown_usdt=None,
        )

    def place_market_order(self, *, symbol: str, side: str, quantity: Decimal, client_order_id: str) -> Mapping[str, object]:
        if len(client_order_id) > 36 or not client_order_id:
            raise BinanceProtocolError("client order ID must be 1-36 characters")
        if side.upper() not in {"BUY", "SELL"} or quantity <= 0:
            raise BinanceProtocolError("market order is malformed")
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": decimal_string(quantity),
            "newClientOrderId": client_order_id,
        }
        try:
            payload = self._request("POST", "/fapi/v1/order", params=params, signed=True)
        except BinanceTimeout as exc:
            raise AmbiguousOrderError(client_order_id, "order request timed out; exchange acceptance is unknown") from exc
        except BinanceTransportError as exc:
            raise AmbiguousOrderError(client_order_id, "order transport disconnected; exchange acceptance is unknown") from exc
        except BinanceError as exc:
            if exc.status_code == 503:
                raise AmbiguousOrderError(client_order_id, "exchange returned ambiguous 503; order acceptance is unknown", status_code=503) from exc
            raise
        if not isinstance(payload, Mapping):
            raise BinanceProtocolError("order response is malformed")
        return payload

    def query_order(self, *, symbol: str, client_order_id: str) -> Mapping[str, object] | None:
        try:
            payload = self._request(
                "GET",
                "/fapi/v1/order",
                params={"symbol": symbol.upper(), "origClientOrderId": client_order_id},
                signed=True,
            )
        except BinanceError as exc:
            if exc.status_code == 404 or exc.code == -2013:
                return None
            raise
        if not isinstance(payload, Mapping):
            raise BinanceProtocolError("order query response is malformed")
        return payload

    def place_with_recovery(self, *, symbol: str, side: str, quantity: Decimal, client_order_id: str) -> Mapping[str, object]:
        try:
            return self.place_market_order(symbol=symbol, side=side, quantity=quantity, client_order_id=client_order_id)
        except AmbiguousOrderError as exc:
            # Never blindly resubmit. The only safe next operation is a client-ID query.
            found = self.query_order(symbol=symbol, client_order_id=exc.client_order_id)
            if found is not None:
                return found
            raise UnresolvedOrderError(client_order_id, "ambiguous order remains unresolved after client-ID query") from exc

    def cancel_order(self, *, symbol: str, client_order_id: str) -> Mapping[str, object]:
        payload = self._request(
            "DELETE",
            "/fapi/v1/order",
            params={"symbol": symbol.upper(), "origClientOrderId": client_order_id},
            signed=True,
        )
        if not isinstance(payload, Mapping):
            raise BinanceProtocolError("cancel response is malformed")
        return payload

    def user_trades(self, *, symbol: str, from_id: int | None = None, limit: int = 100) -> list[Mapping[str, object]]:
        params: dict[str, object] = {"symbol": symbol.upper(), "limit": min(max(int(limit), 1), 1000)}
        if from_id is not None:
            params["fromId"] = int(from_id)
        payload = self._request("GET", "/fapi/v1/userTrades", params=params, signed=True)
        if not isinstance(payload, list):
            raise BinanceProtocolError("userTrades response is malformed")
        return [item for item in payload if isinstance(item, Mapping)]
