import asyncio

import httpx
import pytest

from app.config import Settings
from app.integrations.ibkr.client_portal_client import IbkrClientPortalClient
from app.integrations.ibkr.exceptions import (
    IbkrApiError, IbkrAuthenticationRequiredError, IbkrFlexError,
    IbkrFlexNotConfiguredError, IbkrGatewayTimeoutError, IbkrGatewayUnavailableError,
    IbkrInvalidResponseError,
)
from app.integrations.ibkr.flex_client import IbkrFlexClient
from app.integrations.ibkr.redaction import sanitize, sanitize_xml
from app.integrations.ibkr.service import IbkrReadOnlyService
from app.integrations.ibkr.login_browser import IbkrCredentialStore


def run(value):
    return asyncio.run(value)


def settings(**overrides):
    values = {
        "ibkr_cp_enabled": True, "ibkr_cp_base_url": "https://127.0.0.1:5000/v1/api",
        "ibkr_flex_enabled": True, "ibkr_flex_token": "secret-token", "ibkr_flex_query_id": "123456",
        "ibkr_proxy_url": "socks5h://127.0.0.1:10808",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def cp_client(handler, **overrides):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://127.0.0.1:5000/v1/api")
    return IbkrClientPortalClient(settings(**overrides), http), http


def test_gateway_success_and_authentication_status():
    client, http = cp_client(lambda request: httpx.Response(200, json={"authenticated": True, "connected": True}))
    try:
        result = run(IbkrReadOnlyService(client).auth_status())
        assert result["normalized"] == {"authenticated": True, "connected": True, "competing": False, "message": None}
    finally:
        run(http.aclose())


def test_gateway_health_accepts_login_page_without_api_authentication():
    client, http = cp_client(lambda request: httpx.Response(404, text="login not initialized"))
    try:
        result = run(IbkrReadOnlyService(client).health())
        assert result["normalized"]["reachable"] is True
        assert result["status_code"] == 404
        assert "login not initialized" not in str(result["raw"])
    finally:
        run(http.aclose())


@pytest.mark.parametrize("exc_type,expected", [
    (httpx.ConnectError, IbkrGatewayUnavailableError),
    (httpx.ReadTimeout, IbkrGatewayTimeoutError),
])
def test_gateway_network_errors(exc_type, expected):
    def handler(request):
        raise exc_type("failed", request=request)
    client, http = cp_client(handler)
    try:
        with pytest.raises(expected):
            run(client.request("gateway_health", "GET", "/sso/validate"))
    finally:
        run(http.aclose())


def test_auth_error_non_json_and_api_error_are_distinct():
    for response, expected in [
        (httpx.Response(401, json={"error": "not authenticated"}), IbkrAuthenticationRequiredError),
        (httpx.Response(200, text="<html>bad</html>"), IbkrInvalidResponseError),
        (httpx.Response(500, json={"error": "upstream"}), IbkrApiError),
    ]:
        client, http = cp_client(lambda request, response=response: response)
        try:
            with pytest.raises(expected):
                run(client.request("test", "GET", "/sso/validate"))
        finally:
            run(http.aclose())


def test_gateway_404_before_login_is_authentication_required_for_auth_status():
    client, http = cp_client(lambda request: httpx.Response(404, json={"error": "not found"}))
    try:
        with pytest.raises(IbkrAuthenticationRequiredError):
            run(client.request("auth_status", "POST", "/iserver/auth/status"))
    finally:
        run(http.aclose())


def test_competing_session_is_not_taken_over():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"authenticated": False, "connected": True, "competing": True})
    client, http = cp_client(handler)
    try:
        from app.integrations.ibkr.exceptions import IbkrCompetingSessionError
        with pytest.raises(IbkrCompetingSessionError):
            run(IbkrReadOnlyService(client).initialize_session())
        assert calls == ["/v1/api/iserver/auth/status"]
    finally:
        run(http.aclose())


def test_multiple_accounts_and_paginated_positions():
    def handler(request):
        path = request.url.path.removeprefix("/v1/api")
        if path == "/portfolio/accounts":
            return httpx.Response(200, json=[{"accountId": "DU111"}, {"accountId": "U222"}])
        if path.endswith("/positions/0"):
            return httpx.Response(200, json=[{"ticker": "AAPL", "position": 2}])
        if path.endswith("/positions/1"):
            return httpx.Response(200, json=[{"symbol": "MSFT", "quantity": 3}])
        return httpx.Response(200, json=[])
    client, http = cp_client(handler)
    try:
        service = IbkrReadOnlyService(client)
        assert len(run(service.accounts())["normalized"]) == 2
        result = run(service.positions("U222"))
        assert [row["symbol"] for row in result["normalized"]] == ["AAPL", "MSFT"]
        assert len(result["raw"]) == 3
        with pytest.raises(IbkrAuthenticationRequiredError):
            run(service.positions("NOT-MINE"))
    finally:
        run(http.aclose())


def test_empty_positions():
    def handler(request):
        if request.url.path.endswith("/portfolio/accounts"):
            return httpx.Response(200, json=[{"accountId": "DU1"}])
        return httpx.Response(200, json=[])
    client, http = cp_client(handler)
    try:
        assert run(IbkrReadOnlyService(client).positions("DU1"))["normalized"] == []
    finally:
        run(http.aclose())


def test_summary_unwraps_ibkr_amount_objects():
    def handler(request):
        path = request.url.path.removeprefix("/v1/api")
        if path == "/portfolio/accounts":
            return httpx.Response(200, json=[{"accountId": "DU1"}])
        if path.endswith("/summary"):
            return httpx.Response(200, json={"netliquidation": {"amount": 1234.5}, "buyingpower": {"amount": 500}})
        return httpx.Response(200, json={"BASE": {"cashbalance": 42, "currency": "USD"}})
    client, http = cp_client(handler)
    try:
        result = run(IbkrReadOnlyService(client).summary("DU1"))
        assert result["normalized"]["net_liquidation"] == 1234.5
        assert result["normalized"]["base_currency"] == "USD"
    finally:
        run(http.aclose())


def flex_client(responses, **overrides):
    queue = list(responses)
    transport = httpx.MockTransport(lambda request: queue.pop(0))
    http = httpx.AsyncClient(transport=transport)
    return IbkrFlexClient(settings(**overrides), http), http


def test_flex_not_configured():
    client, http = flex_client([], ibkr_flex_token="")
    try:
        with pytest.raises(IbkrFlexNotConfiguredError):
            run(client.initiate_report())
    finally:
        run(http.aclose())


def test_flex_initiate_pending_then_complete_with_missing_sections():
    initiated = '<FlexStatementResponse><Status>Success</Status><ReferenceCode>999</ReferenceCode></FlexStatementResponse>'
    pending = '<FlexStatementResponse><Status>Fail</Status><ErrorCode>1019</ErrorCode><ErrorMessage>in progress</ErrorMessage></FlexStatementResponse>'
    report = '<FlexQueryResponse><FlexStatements><FlexStatement><AccountInformation accountId="U1"/><OpenPositions><OpenPosition symbol="AAPL"/></OpenPositions></FlexStatement></FlexStatements></FlexQueryResponse>'
    client, http = flex_client([httpx.Response(200, text=initiated), httpx.Response(200, text=pending), httpx.Response(200, text=report)])
    try:
        result = run(client.run_query(max_attempts=2, interval_seconds=0))
        assert result["normalized"]["open_positions"] == [{"symbol": "AAPL"}]
        assert result["normalized"]["trades"] == []
        assert any("trades" in warning for warning in result["warnings"])
    finally:
        run(http.aclose())


def test_flex_invalid_xml():
    client, http = flex_client([httpx.Response(200, text="not xml")])
    try:
        with pytest.raises(IbkrFlexError):
            run(client.initiate_report())
    finally:
        run(http.aclose())


def test_sensitive_fields_are_redacted_recursively():
    clean = sanitize({"token": "abc", "nested": {"Cookie": "sid=1", "account": "U123"}, "url": "?token=abc"})
    assert clean["token"] == "[REDACTED]"
    assert clean["nested"]["Cookie"] == "[REDACTED]"
    assert "abc" not in clean["url"]
    assert "999" not in sanitize_xml("<ReferenceCode>999</ReferenceCode>")


class FakeRedis:
    def __init__(self): self.values = {}
    def set(self, key, value): self.values[key] = value
    def get(self, key): return self.values.get(key)
    def delete(self, key): self.values.pop(key, None)


def test_ibkr_credentials_are_encrypted_and_can_be_deleted():
    cache = FakeRedis()
    store = IbkrCredentialStore(settings(ibkr_credential_encryption_key="test-only-key"), cache)
    store.save("demo-user", "top-secret")
    encrypted = next(iter(cache.values.values()))
    assert b"demo-user" not in encrypted
    assert b"top-secret" not in encrypted
    assert store.load().password == "top-secret"
    assert store.status() == {"saved": True, "username_hint": "de*****er"}
    store.delete()
    assert store.status()["saved"] is False
