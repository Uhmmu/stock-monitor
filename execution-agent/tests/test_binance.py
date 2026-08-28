from __future__ import annotations

import httpx
import pytest
from decimal import Decimal

from execution_agent.binance import BinanceClient
from execution_agent.errors import BinanceProtocolError, BinanceRedirectError, UnresolvedOrderError
from execution_agent.security import SecurityError


def test_production_origin_override_is_impossible() -> None:
    with pytest.raises(SecurityError):
        BinanceClient("k", "s", _test_base_url="https://other.example")


def test_redirect_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"Location": "https://other.example"})

    client = BinanceClient.for_test(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BinanceRedirectError):
            client.server_time()
    finally:
        client.close()


def test_timeout_queries_client_id_before_any_retry() -> None:
    calls: list[tuple[str, str]] = []
    timed_out = True

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal timed_out
        calls.append((request.method, request.url.path))
        if request.url.path == "/fapi/v1/order" and request.method == "POST" and timed_out:
            timed_out = False
            raise httpx.ReadTimeout("simulated timeout")
        if request.url.path == "/fapi/v1/order" and request.method == "GET":
            return httpx.Response(200, json={"orderId": 9, "clientOrderId": "EA1", "status": "FILLED", "executedQty": "1"})
        return httpx.Response(200, json={})

    client = BinanceClient.for_test(transport=httpx.MockTransport(handler))
    try:
        result = client.place_with_recovery(symbol="BTCUSDT", side="BUY", quantity=Decimal("1"), client_order_id="EA1")
        assert result["status"] == "FILLED"
        assert calls.count(("POST", "/fapi/v1/order")) == 1
        assert calls.count(("GET", "/fapi/v1/order")) == 1
    finally:
        client.close()


def test_unresolved_ambiguous_order_does_not_resubmit() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method + request.url.path)
        if request.method == "POST":
            raise httpx.ReadTimeout("simulated timeout")
        return httpx.Response(404, json={"code": -2013, "msg": "Order does not exist."})

    client = BinanceClient.for_test(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(UnresolvedOrderError):
            client.place_with_recovery(symbol="BTCUSDT", side="BUY", quantity=Decimal("1"), client_order_id="EA1")
        assert calls == ["POST/fapi/v1/order", "GET/fapi/v1/order"]
    finally:
        client.close()


def test_account_config_rejects_hedge_or_trading_permissions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/accountConfig":
            return httpx.Response(200, json={"canTrade": True, "dualSidePosition": True, "multiAssetsMargin": False, "canWithdraw": False})
        return httpx.Response(200, json={})

    client = BinanceClient.for_test(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BinanceProtocolError):
            client.account_snapshot()
    finally:
        client.close()
