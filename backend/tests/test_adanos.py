import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services.adanos import (
    build_stock_sentiment_insights,
    configured_api_keys,
    get_stock_sentiment_insights,
    normalize_source_insight,
    source_alignment,
)


def config(**overrides):
    values = {
        "adanos_api_key": "test-key",
        "adanos_api_keys": "",
        "adanos_api_base_url": "https://adanos.test",
        "adanos_proxy_url": "socks5h://proxy.test:10808",
        "adanos_request_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://adanos.test/compare")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        source = url.split("/")[3]
        response = self.responses[source]
        return response() if callable(response) else response


def test_normalizes_numeric_strings_and_rejects_incomplete_rows():
    insight = normalize_source_insight("reddit", {
        "ticker": "AAPL", "company_name": "Apple", "buzz_score": "72.45",
        "bullish_pct": "64", "trend": "rising", "mentions": "1240",
    })
    assert insight is not None
    assert insight.buzz_score == 72.5
    assert insight.bullish_pct == 64
    assert insight.metric_value == 1240
    assert normalize_source_insight("news", {"buzz_score": 50}) is None


def test_configured_key_pool_is_ordered_and_legacy_only_fills_an_empty_pool():
    assert configured_api_keys(config(
        adanos_api_keys=" key-a, key-b;key-a ",
        adanos_api_key="legacy-key",
    )) == ["key-a", "key-b"]
    assert configured_api_keys(config(adanos_api_keys="", adanos_api_key="legacy-key")) == ["legacy-key"]
    assert configured_api_keys(config(adanos_api_keys="key-a,key-b,key-c")) == []


@pytest.mark.parametrize(("values", "expected"), [
    ([], "No sentiment mix"),
    ([62], "Single-source view"),
    ([65, 70], "Bullish alignment"),
    ([32, 38], "Bearish alignment"),
    ([48, 54], "Tight alignment"),
    ([30, 70], "Wide divergence"),
    ([50, 68], "Mixed"),
])
def test_source_alignment(values, expected):
    assert source_alignment(values) == expected


def test_builds_aggregate_from_only_available_sources():
    reddit = normalize_source_insight("reddit", {
        "company_name": "Tesla", "buzz_score": 80, "bullish_pct": 70,
        "trend": "rising", "mentions": 2000,
    })
    news = normalize_source_insight("news", {
        "company_name": "Tesla", "buzz_score": 60, "bullish_pct": 50,
        "trend": "stable", "mentions": 100,
    })
    result = build_stock_sentiment_insights("tsla", [reddit, None, news], period_days=14)
    assert result is not None
    assert result["symbol"] == "TSLA"
    assert result["company_name"] == "Tesla"
    assert result["average_buzz"] == 70
    assert result["bullish_average"] == 60
    assert result["available_sources"] == 2
    assert result["period_days"] == 14
    assert build_stock_sentiment_insights("MSFT", [None, None]) is None


def test_fetches_four_sources_and_keeps_partial_success():
    payload = lambda source, metric, value: Response({"stocks": [{
        "ticker": "AAPL", "company_name": "Apple", "buzz_score": value,
        "bullish_pct": 65, "trend": "rising", metric: 100,
    }]})
    client = Client({
        "reddit": payload("reddit", "mentions", 80),
        "x": Response({}, 500),
        "news": payload("news", "mentions", 60),
        "polymarket": payload("polymarket", "trade_count", 40),
    })
    result = asyncio.run(get_stock_sentiment_insights(
        " aapl ", 99, config=config(), client=client, use_cache=False,
    ))
    assert result is not None
    assert result["period_days"] == 30
    assert result["available_sources"] == 3
    assert {source["source"] for source in result["sources"]} == {"reddit", "news", "polymarket"}
    assert len(client.calls) == 4
    assert all(call[1]["headers"] == {"X-API-Key": "test-key"} for call in client.calls)
    assert all(call[1]["params"] == {"tickers": "AAPL", "days": 30} for call in client.calls)


def test_primary_success_never_calls_secondary():
    payload = Response({"stocks": [{
        "ticker": "AAPL", "company_name": "Apple", "buzz_score": 70,
        "bullish_pct": 55, "trend": "stable", "mentions": 100, "trade_count": 20,
    }]})
    primary = Client({source: payload for source in ("reddit", "x", "news", "polymarket")})
    secondary = Client({})
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL",
        config=config(adanos_api_keys="key-a,key-b", adanos_api_key=""),
        client=primary,
        secondary_client=secondary,
        use_cache=False,
    ))
    assert result is not None and result["available_sources"] == 4
    assert len(primary.calls) == 4
    assert all(call[1]["headers"] == {"X-API-Key": "key-a"} for call in primary.calls)
    assert secondary.calls == []


def test_rate_limited_key_fails_over_to_alternate_key():
    primary = Client({source: Response({}, 429) for source in ("reddit", "x", "news", "polymarket")})
    secondary = Client({source: Response({"stocks": [{
        "ticker": "AAPL", "buzz_score": 60, "bullish_pct": 50,
        "trend": "stable", "mentions": 100, "trade_count": 20,
    }]}) for source in ("reddit", "x", "news", "polymarket")})
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL",
        config=config(adanos_api_keys="key-a,key-b", adanos_api_key=""),
        client=primary,
        secondary_client=secondary,
        use_cache=False,
    ))
    assert result is not None and result["available_sources"] == 4
    assert len(primary.calls) == len(secondary.calls) == 4
    assert all(call[1]["headers"] == {"X-API-Key": "key-a"} for call in primary.calls)
    assert all(call[1]["headers"] == {"X-API-Key": "key-b"} for call in secondary.calls)


@pytest.mark.parametrize("status", [401, 403, 404, 500, 502, 503, 504])
def test_non_quota_failures_never_use_secondary(status):
    primary = Client({source: Response({}, status) for source in ("reddit", "x", "news", "polymarket")})
    secondary = Client({})
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL", config=config(adanos_api_keys="key-a,key-b"),
        client=primary, secondary_client=secondary, use_cache=False,
    ))
    assert result is None
    assert secondary.calls == []


def test_primary_connection_failure_never_uses_secondary():
    class BrokenPrimary(Client):
        async def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            raise httpx.ConnectError("failed", request=httpx.Request("GET", url))

    primary = BrokenPrimary({})
    secondary = Client({})
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL", config=config(adanos_api_keys="key-a,key-b"),
        client=primary, secondary_client=secondary, use_cache=False,
    ))
    assert result is None
    assert len(primary.calls) == 4
    assert secondary.calls == []


@pytest.mark.parametrize("proxy_url", ["", "http://proxy.test:10808", "socks5h://proxy.test:bad"])
def test_invalid_proxy_disables_secondary_without_direct_fallback(proxy_url):
    primary = Client({source: Response({}, 429) for source in ("reddit", "x", "news", "polymarket")})
    secondary = Client({})
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL", config=config(adanos_api_keys="key-a,key-b", adanos_proxy_url=proxy_url),
        client=primary, secondary_client=secondary, use_cache=False,
    ))
    assert result is None
    assert secondary.calls == []


def test_owned_clients_bind_secondary_to_socks5h(monkeypatch):
    clients = []

    class OwnedClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            self.closed = False
            clients.append(self)

        async def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if "proxy" not in self.kwargs:
                return Response({}, 429)
            source = url.split("/")[3]
            metric = "trade_count" if source == "polymarket" else "mentions"
            return Response({"stocks": [{
                "ticker": "AAPL", "buzz_score": 60, "bullish_pct": 50,
                "trend": "stable", metric: 100,
            }]})

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr("app.services.adanos.httpx.AsyncClient", OwnedClient)
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL", config=config(adanos_api_keys="key-a,key-b"), use_cache=False,
    ))
    assert result is not None and result["available_sources"] == 4
    assert len(clients) == 2
    assert clients[0].kwargs["trust_env"] is False and "proxy" not in clients[0].kwargs
    assert clients[1].kwargs["trust_env"] is False
    assert clients[1].kwargs["proxy"] == "socks5h://proxy.test:10808"
    assert all(client.closed for client in clients)


def test_single_key_never_creates_secondary_client(monkeypatch):
    clients = []

    class OwnedClient(Client):
        def __init__(self, **kwargs):
            payload = Response({"stocks": [{
                "ticker": "AAPL", "buzz_score": 60, "bullish_pct": 50,
                "trend": "stable", "mentions": 100, "trade_count": 20,
            }]})
            super().__init__({source: payload for source in ("reddit", "x", "news", "polymarket")})
            self.kwargs = kwargs
            clients.append(self)

        async def aclose(self):
            return None

    monkeypatch.setattr("app.services.adanos.httpx.AsyncClient", OwnedClient)
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL", config=config(adanos_api_keys="", adanos_api_key="key-a"), use_cache=False,
    ))
    assert result is not None
    assert len(clients) == 1 and "proxy" not in clients[0].kwargs


def test_missing_key_returns_null_without_http():
    client = Client({})
    result = asyncio.run(get_stock_sentiment_insights(
        "AAPL", config=config(adanos_api_key="", adanos_api_keys=""), client=client, use_cache=False,
    ))
    assert result is None
    assert client.calls == []
