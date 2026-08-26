"""WP 2.1 — Binance public client tests (fixture-driven, no network).

Uses the WP 0.2 sanitized fixtures through httpx MockTransport; asserts
normalized DTOs, error classification, bounded Retry-After-aware retries,
weight observation and that no credential header is ever sent.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.services.crypto.providers.binance import (
    BinancePublicClient,
    BinancePublicError,
    parse_kline_row,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "crypto"


def fixture_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


class Recorder(httpx.BaseTransport):
    """Records every request; serves scripted responses in order."""

    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


def client_with(recorder: Recorder, **kwargs) -> BinancePublicClient:
    return BinancePublicClient(transport=httpx.MockTransport(recorder.handle_request), backoff_seconds=0, **kwargs)


class TestDtoParsing:
    def test_kline_rows_parse_from_fixture(self):
        for interval in ("1h", "4h", "1d"):
            rows = fixture_json(f"binance_spot_klines_{interval}.json")
            kline = parse_kline_row("spot", "BTCUSDT", interval, rows[0], received_at="2026-08-25T15:40:00+00:00")
            assert kline.symbol == "BTCUSDT" and kline.interval == interval
            assert isinstance(kline.open, Decimal) and isinstance(kline.base_volume, Decimal)
            assert kline.high >= kline.open and kline.low <= kline.open
            assert kline.taker_buy_base_volume <= kline.base_volume
            assert kline.closed is True  # fixture candles are historical

    def test_kline_rejects_malformed_row(self):
        with pytest.raises(BinancePublicError) as excinfo:
            parse_kline_row("spot", "BTCUSDT", "1h", [1, 2, 3])
        assert excinfo.value.kind == "permanent"

    def test_exchange_info_spot(self):
        from app.services.crypto.providers.binance import parse_exchange_info

        info = parse_exchange_info("spot", fixture_json("binance_spot_exchange_info.json"))
        assert info.timezone == "UTC"
        btc = next(s for s in info.symbols if s.provider_symbol == "BTCUSDT")
        assert btc.status == "trading" and btc.kind == "spot"
        assert btc.base_asset == "BTC" and btc.quote_asset == "USDT"
        assert btc.filters["PRICE_FILTER"]["tickSize"] == "0.01000000"
        assert btc.base_asset_precision == 8

    def test_exchange_info_usdm_marks_perpetual(self):
        from app.services.crypto.providers.binance import parse_exchange_info

        info = parse_exchange_info("usdm", fixture_json("binance_fapi_exchange_info.json"))
        btc = next(s for s in info.symbols if s.provider_symbol == "BTCUSDT")
        assert btc.kind == "perpetual" and btc.contract_type == "PERPETUAL"
        assert btc.margin_asset == "USDT"
        assert btc.status == "trading"
        assert btc.onboard_date_ms == 1_567_965_300_000
        assert btc.delivery_date_ms == 4_133_404_800_000
        assert btc.filters["MIN_NOTIONAL"]["notional"] == "50"


class TestRequests:
    def test_server_time_and_weight_observation(self):
        recorder = Recorder([
            httpx.Response(200, json=fixture_json("binance_spot_time.json"),
                           headers={"x-mbx-used-weight-1m": "7"}),
        ])
        client = client_with(recorder)
        server_time = client.server_time("spot")
        assert server_time.server_time_ms == 1_787_671_966_831
        assert client.last_weight is not None
        assert client.last_weight.max_weight == 7
        assert client.last_weight.market == "spot"

    def test_klines_request_params_and_no_auth_headers(self):
        recorder = Recorder([httpx.Response(200, json=fixture_json("binance_spot_klines_1h.json"))])
        client = client_with(recorder)
        klines = client.klines("spot", "BTCUSDT", "1h", start_time_ms=1_500_000_000_000, end_time_ms=1_500_000_900_000, limit=3)
        assert len(klines) == 3 and klines[0].market == "spot"
        request = recorder.requests[0]
        assert request.url.path == "/api/v3/klines"
        params = dict(request.url.params)
        assert params["symbol"] == "BTCUSDT" and params["interval"] == "1h"
        assert params["startTime"] == "1500000000000" and params["endTime"] == "1500000900000"
        # no credential header is ever attached
        for header in ("authorization", "x-mbx-api-key", "x-api-key"):
            assert header not in request.headers

    def test_usdm_routes_to_fapi_host(self):
        recorder = Recorder([httpx.Response(200, json=fixture_json("binance_fapi_open_interest.json"))])
        client = client_with(recorder)
        client._request("usdm", "ticker_24h", {"symbol": "BTCUSDT"})
        assert recorder.requests[0].url.host == "fapi.binance.com"

    def test_ticker_and_book_ticker_dtos(self):
        recorder = Recorder([
            httpx.Response(200, json=fixture_json("binance_spot_ticker_24hr.json")),
            httpx.Response(200, json=fixture_json("binance_spot_book_ticker.json")),
        ])
        client = client_with(recorder)
        ticker = client.ticker_24h("spot", "BTCUSDT")
        assert ticker.symbol == "BTCUSDT"
        assert isinstance(ticker.base_volume, Decimal)
        assert ticker.close_time_ms == 1_787_671_969_010
        book = client.book_ticker("spot", "BTCUSDT")
        assert book.ask_price >= book.bid_price
        assert isinstance(book.bid_qty, Decimal)

    def test_usdm_price_authorities_and_derivative_methods(self):
        responses = [
            httpx.Response(200, json=fixture_json("binance_spot_klines_1h.json")),
            httpx.Response(200, json=fixture_json("binance_spot_klines_1h.json")),
            httpx.Response(200, json=fixture_json("binance_fapi_premium_index.json")),
            httpx.Response(200, json=fixture_json("binance_fapi_funding_rate_2020.json")),
            httpx.Response(200, json=fixture_json("binance_fapi_open_interest.json")),
            httpx.Response(200, json=fixture_json("binance_fapi_open_interest_hist.json")),
            httpx.Response(200, json=[{
                "symbol": "BTCUSDT", "longShortRatio": "1.2", "longAccount": "0.55",
                "shortAccount": "0.45", "timestamp": 1_787_671_960_000,
            }]),
            httpx.Response(200, json=[{
                "symbol": "BTCUSDT", "buyVol": "120", "sellVol": "100",
                "buySellRatio": "1.2", "timestamp": 1_787_671_960_000,
            }]),
        ]
        recorder = Recorder(responses)
        client = client_with(recorder)
        mark = client.mark_price_klines("BTCUSDT", "1h", limit=1)[0]
        assert mark.price_type == "mark" and recorder.requests[0].url.path == "/fapi/v1/markPriceKlines"
        index = client.index_price_klines("BTCUSDT", "1h", limit=1)[0]
        assert index.price_type == "index"
        assert recorder.requests[1].url.params.get("pair") == "BTCUSDT"
        assert "symbol" not in recorder.requests[1].url.params
        premium = client.premium_index("BTCUSDT")
        assert premium.mark_price > 0 and premium.index_price > 0
        funding = client.funding_rate_history("BTCUSDT")
        assert funding[0].mark_price is None  # old Binance rows legitimately omit it
        assert client.open_interest("BTCUSDT").open_interest > 0
        assert client.open_interest_history("BTCUSDT")[0].sum_open_interest > 0
        assert client.global_long_short_ratio("BTCUSDT")[0].long_account == Decimal("0.55")
        assert client.taker_buy_sell_volume("BTCUSDT")[0].buy_volume == Decimal("120")
        assert all("authorization" not in request.headers for request in recorder.requests)

    def test_usdm_24h_ticker_allows_absent_bid_and_ask(self):
        recorder = Recorder([httpx.Response(200, json={
            "symbol": "BTCUSDT", "lastPrice": "100", "highPrice": "110", "lowPrice": "90",
            "volume": "12", "quoteVolume": "1200", "openTime": 1, "closeTime": 2,
        })])
        ticker = client_with(recorder).ticker_24h("usdm", "BTCUSDT")
        assert ticker.bid_price is None and ticker.ask_price is None


class TestErrorHandling:
    def test_429_retries_and_respects_retry_after(self):
        error = fixture_json("binance_error_cases.json")["http_429_rate_limit"]
        recorder = Recorder([
            httpx.Response(429, json=error["body"], headers={"retry-after": "0", "x-mbx-used-weight-1m": "6000"}),
            httpx.Response(200, json=fixture_json("binance_spot_time.json")),
        ])
        client = client_with(recorder)
        result = client.server_time("spot")
        assert result.server_time_ms == 1_787_671_966_831
        assert len(recorder.requests) == 2

    def test_418_ip_ban_fails_fast(self):
        error = fixture_json("binance_error_cases.json")["http_418_ip_ban"]
        recorder = Recorder([httpx.Response(418, json=error["body"], headers={"retry-after": "0"})])
        client = client_with(recorder)
        with pytest.raises(BinancePublicError) as excinfo:
            client.server_time("spot")
        assert excinfo.value.kind == "ip_banned"
        assert len(recorder.requests) == 1  # never retried

    def test_5xx_retries_bounded_then_raises(self):
        recorder = Recorder([
            httpx.Response(503, json={"code": -1000, "msg": "unavailable"}),
            httpx.Response(503, json={"code": -1000, "msg": "unavailable"}),
            httpx.Response(503, json={"code": -1000, "msg": "unavailable"}),
        ])
        client = client_with(recorder, max_retries=2)
        with pytest.raises(BinancePublicError) as excinfo:
            client.server_time("spot")
        assert excinfo.value.kind == "retryable"
        assert len(recorder.requests) == 3  # initial + 2 retries

    def test_timeout_is_classified_and_retried(self):
        class TimeoutTransport(httpx.BaseTransport):
            count = 0

            def handle_request(self, request):
                TimeoutTransport.count += 1
                raise httpx.TimeoutException("timed out")

        client = BinancePublicClient(transport=httpx.MockTransport(TimeoutTransport().handle_request), max_retries=1, backoff_seconds=0)
        with pytest.raises(BinancePublicError) as excinfo:
            client.server_time("spot")
        assert excinfo.value.kind == "timeout"
        assert TimeoutTransport.count == 2

    def test_400_is_permanent_without_retry(self):
        error = fixture_json("binance_error_cases.json")["http_400_invalid_param"]
        recorder = Recorder([httpx.Response(400, json=error["body"])])
        client = client_with(recorder)
        with pytest.raises(BinancePublicError) as excinfo:
            client.klines("spot", "BTCUSDT", "1h", start_time_ms=1)
        assert excinfo.value.kind == "permanent"
        assert excinfo.value.provider_code == -1130
        assert len(recorder.requests) == 1

    def test_unknown_market_rejected(self):
        client = BinancePublicClient()
        with pytest.raises(ValueError):
            client.server_time("coinm")

    def test_error_str_contains_no_url_or_body(self):
        recorder = Recorder([httpx.Response(400, json={"code": -1130, "msg": "bad param"})])
        client = client_with(recorder)
        with pytest.raises(BinancePublicError) as excinfo:
            client.server_time("spot")
        text = str(excinfo.value)
        assert "api.binance.com" not in text and "http" not in text.lower()
