import asyncio
import json

import pytest

from app.config import Settings
from app.services.realtime_market.contracts import ProviderError
from app.services.realtime_market.providers import AlpacaRealtimeProvider
from app.services.realtime_market.stream import StreamingSupervisor


class FakeWebsocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.incoming = [
            json.dumps([{"T": "success", "msg": "connected"}]),
            json.dumps([{"T": "success", "msg": "authenticated"}]),
        ]

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def close(self):
        self.closed = True

    async def recv(self):
        return self.incoming.pop(0)


def settings():
    return Settings(
        alpaca_api_key="paper-key",
        alpaca_api_secret="paper-secret",
        alpaca_trading_env="paper",
        alpaca_trading_base_url="https://paper-api.alpaca.markets",
        alpaca_market_data_base_url="https://data.alpaca.markets",
        alpaca_market_data_stream_url="wss://stream.data.alpaca.markets",
        alpaca_market_data_feed="iex",
        alpaca_market_data_symbol_limit=30,
    )


def test_alpaca_uses_paper_api_key_headers_for_market_data():
    provider = AlpacaRealtimeProvider(settings=settings())

    headers = asyncio.run(provider._headers())

    assert headers == {
        "APCA-API-KEY-ID": "paper-key",
        "APCA-API-SECRET-KEY": "paper-secret",
    }


def test_alpaca_websocket_uses_same_key_secret_auth_packet_and_paper_health_metadata():
    websocket = FakeWebsocket()
    calls = []

    async def factory(url, **kwargs):
        calls.append((url, kwargs))
        return websocket

    provider = AlpacaRealtimeProvider(settings=settings(), websocket_factory=factory)
    asyncio.run(provider.connect())
    health = asyncio.run(StreamingSupervisor(provider).health_check())

    assert calls[0][0] == "wss://stream.data.alpaca.markets/v2/iex"
    assert "additional_headers" not in calls[0][1]
    assert "extra_headers" not in calls[0][1]
    assert websocket.sent == [{"action": "auth", "key": "paper-key", "secret": "paper-secret"}]
    assert health.auth_type == "trading_api_key"
    assert health.environment == "paper_credentials"
    assert health.market_data_endpoint == "https://data.alpaca.markets"
    assert health.feed == "iex"
    assert health.stream_endpoint == "wss://stream.data.alpaca.markets/v2/iex"
    asyncio.run(provider.close())


def test_alpaca_connection_limit_is_retried_as_transient():
    websocket = FakeWebsocket()
    websocket.incoming = [json.dumps([{"T": "error", "code": 406, "msg": "connection limit exceeded"}])]

    async def factory(url, **kwargs):
        return websocket

    provider = AlpacaRealtimeProvider(settings=settings(), websocket_factory=factory)
    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider.connect())

    assert raised.value.status_code == 406
    assert raised.value.transient is True
    assert websocket.closed is True


def test_alpaca_does_not_subscribe_symbols_rejected_by_rest_market_data():
    websocket = FakeWebsocket()

    async def factory(url, **kwargs):
        return websocket

    provider = AlpacaRealtimeProvider(settings=settings(), websocket_factory=factory)
    provider._unsupported_symbols.add("1578.T")

    asyncio.run(provider.subscribe(["MSFT", "1578.T"]))

    assert websocket.sent == [
        {"action": "auth", "key": "paper-key", "secret": "paper-secret"},
        {"action": "subscribe", "trades": ["MSFT"], "quotes": ["MSFT"], "bars": ["MSFT"]},
    ]
    asyncio.run(provider.close())


def test_alpaca_respects_basic_plan_channel_symbol_limit():
    websocket = FakeWebsocket()

    async def factory(url, **kwargs):
        return websocket

    provider = AlpacaRealtimeProvider(settings=settings(), websocket_factory=factory)
    symbols = [f"SYM{index}" for index in range(21)]

    asyncio.run(provider.subscribe(symbols))

    assert websocket.sent[-1] == {
        "action": "subscribe",
        "quotes": symbols,
        "trades": symbols[:5],
        "bars": symbols[:4],
    }
    asyncio.run(provider.close())
