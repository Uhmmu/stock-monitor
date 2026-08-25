"""WP 0.2 — public provider fixture contract tests.

Fixtures under ``backend/tests/fixtures/crypto/`` are sanitized captures
(2026-08-25, VPS probes; see ``provider_reachability_20260825.json``).
These tests freeze the response shapes the Binance client must parse:
timestamps are epoch-milliseconds integers, numeric market fields are
decimal strings, and error envelopes follow the documented shape.
"""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "crypto"


def load_fixture(name: str):
    path = FIXTURE_DIR / name
    assert path.exists(), f"missing fixture {name}"
    return json.loads(path.read_text())


def assert_ms_timestamp(value, field: str) -> None:
    assert isinstance(value, int), f"{field} must be an integer epoch-ms value, got {type(value)}"
    assert 1_400_000_000_000 < value < 4_200_000_000_000, f"{field} out of sane epoch-ms range: {value}"


def assert_decimal_string(value, field: str) -> None:
    assert isinstance(value, str) and value != "", f"{field} must be a non-empty decimal string"
    try:
        Decimal(value)
    except InvalidOperation as exc:
        pytest.fail(f"{field} is not a valid decimal string: {value!r} ({exc})")


class TestSpotFixtures:
    def test_server_time(self):
        data = load_fixture("binance_spot_time.json")
        assert_ms_timestamp(data["serverTime"], "serverTime")

    def test_exchange_info_shape(self):
        data = load_fixture("binance_spot_exchange_info.json")
        assert data["timezone"] == "UTC"
        assert isinstance(data["symbols"], list) and data["symbols"]
        by_symbol = {s["symbol"]: s for s in data["symbols"]}
        btc = by_symbol["BTCUSDT"]
        assert btc["baseAsset"] == "BTC"
        assert btc["quoteAsset"] == "USDT"
        assert btc["status"] == "TRADING"
        for field in ("baseAssetPrecision", "quoteAssetPrecision"):
            assert isinstance(btc[field], int)
        filter_types = {f["filterType"] for f in btc["filters"]}
        assert {"PRICE_FILTER", "LOT_SIZE"} <= filter_types
        for f in btc["filters"]:
            if f["filterType"] in ("PRICE_FILTER", "LOT_SIZE", "MARKET_LOT_SIZE"):
                assert_decimal_string(f["tickSize"] if "tickSize" in f else f["stepSize"], "tick/step size")
        # rate limits document the weight budget the client must respect
        assert any(r["rateLimitType"] == "REQUEST_WEIGHT" for r in data["rateLimits"])

    def test_klines_rows_have_documented_columns(self):
        for interval in ("1h", "4h", "1d"):
            rows = load_fixture(f"binance_spot_klines_{interval}.json")
            assert isinstance(rows, list) and rows
            for row in rows:
                assert len(row) == 12, "kline rows must keep the documented 12 columns"
                assert_ms_timestamp(row[0], f"{interval} open time")
                assert_ms_timestamp(row[6], f"{interval} close time")
                for idx, label in ((1, "open"), (2, "high"), (3, "low"), (4, "close"), (5, "base volume")):
                    assert_decimal_string(row[idx], f"{interval} {label}")
                # high >= max(open, close) and low <= min(open, close) sanity
                assert Decimal(row[2]) >= max(Decimal(row[1]), Decimal(row[4]))
                assert Decimal(row[3]) <= min(Decimal(row[1]), Decimal(row[4]))
                assert Decimal(row[5]) >= 0
                # index 8 = number of trades, 9 = taker buy base volume, 10 = taker buy quote volume
                assert isinstance(row[8], int) and row[8] >= 0
                assert_decimal_string(row[9], "taker buy base volume")
                assert_decimal_string(row[10], "taker buy quote volume")

    def test_kline_history_depth_marker(self):
        row = load_fixture("binance_spot_klines_1d_earliest.json")[0]
        assert row[0] == 1_502_928_000_000, "earliest BTCUSDT 1d kline open time (2017-08-17T00:00:00Z)"

    def test_ticker_24hr_shape(self):
        data = load_fixture("binance_spot_ticker_24hr.json")
        assert data["symbol"] == "BTCUSDT"
        for field in ("lastPrice", "bidPrice", "askPrice", "highPrice", "lowPrice", "volume", "quoteVolume"):
            assert_decimal_string(data[field], field)
        assert_ms_timestamp(data["closeTime"], "closeTime")

    def test_book_ticker_shape(self):
        data = load_fixture("binance_spot_book_ticker.json")
        assert data["symbol"] == "BTCUSDT"
        for field in ("bidPrice", "bidQty", "askPrice", "askQty"):
            assert_decimal_string(data[field], field)
        assert Decimal(data["askPrice"]) >= Decimal(data["bidPrice"])


class TestUsdmFixtures:
    def test_exchange_info_shape(self):
        data = load_fixture("binance_fapi_exchange_info.json")
        assert data["timezone"] == "UTC"
        by_symbol = {s["symbol"]: s for s in data["symbols"]}
        btc = by_symbol["BTCUSDT"]
        assert btc["contractType"] == "PERPETUAL"
        assert btc["baseAsset"] == "BTC"
        assert btc["marginAsset"] == "USDT"
        assert btc["quoteAsset"] == "USDT"
        assert btc["status"] == "TRADING"
        assert_ms_timestamp(btc["onboardDate"], "onboardDate")
        # PERPETUAL contracts use the sentinel max delivery date, not a real one
        assert btc["deliveryDate"] == 4_133_404_800_000
        filter_types = {f["filterType"] for f in btc["filters"]}
        assert {"PRICE_FILTER", "LOT_SIZE", "MIN_NOTIONAL"} <= filter_types
        assert any(a["asset"] in ("BTC", "USDT") for a in data["assets"])

    def test_premium_index_shape(self):
        data = load_fixture("binance_fapi_premium_index.json")
        assert data["symbol"] == "BTCUSDT"
        for field in ("markPrice", "indexPrice", "lastFundingRate"):
            assert_decimal_string(data[field], field)
        assert_ms_timestamp(data["nextFundingTime"], "nextFundingTime")
        assert_ms_timestamp(data["time"], "time")

    def test_funding_rate_rows(self):
        rows = load_fixture("binance_fapi_funding_rate.json")
        assert rows
        for row in rows:
            assert_ms_timestamp(row["fundingTime"], "fundingTime")
            assert_decimal_string(row["fundingRate"], "fundingRate")
            assert_decimal_string(row["markPrice"], "markPrice")

    def test_funding_rate_old_records_have_empty_mark_price(self):
        rows = load_fixture("binance_fapi_funding_rate_2020.json")
        assert rows
        for row in rows:
            assert_ms_timestamp(row["fundingTime"], "fundingTime")
            # older records legitimately carry an empty markPrice; the parser
            # must map that to an explicit null, never to a guessed price
            if row["markPrice"] == "":
                continue
            assert_decimal_string(row["markPrice"], "markPrice")

    def test_open_interest_shape(self):
        data = load_fixture("binance_fapi_open_interest.json")
        assert data["symbol"] == "BTCUSDT"
        assert_decimal_string(data["openInterest"], "openInterest")
        assert_ms_timestamp(data["time"], "time")

    def test_open_interest_hist_rows(self):
        rows = load_fixture("binance_fapi_open_interest_hist.json")
        assert rows
        for row in rows:
            assert_ms_timestamp(row["timestamp"], "timestamp")
            assert_decimal_string(row["sumOpenInterest"], "sumOpenInterest")
            assert_decimal_string(row["sumOpenInterestValue"], "sumOpenInterestValue")


class TestErrorAndReachability:
    def test_error_cases_include_rate_limit_ban_and_timeout(self):
        cases = load_fixture("binance_error_cases.json")
        assert cases["http_429_rate_limit"]["status_code"] == 429
        assert cases["http_429_rate_limit"]["headers"]["Retry-After"] == "60"
        assert cases["http_418_ip_ban"]["status_code"] == 418
        assert cases["network_timeout"]["status_code"] is None
        assert cases["network_timeout"]["body"] is None
        assert cases["http_400_invalid_param"]["body"]["code"] == -1130

    def test_reachability_metadata_records_vps_location_and_windows(self):
        meta = load_fixture("provider_reachability_20260825.json")
        assert meta["probe_location"].startswith("production VPS")
        assert meta["binance"]["spot"]["endpoints"]["GET /api/v3/time"]["status"] == 200
        assert meta["binance"]["usdm_futures"]["history_window"]["openInterestHist"].startswith(
            "startTime older than ~30 days rejected"
        )
        for provider in ("coingecko", "defillama", "coin_metrics"):
            assert provider in meta and "plan_gate" in meta[provider]

    def test_no_credential_fields_in_fixtures(self):
        for path in sorted(FIXTURE_DIR.glob("*.json")):
            text = path.read_text().lower()
            for forbidden in ("x-mbx-api-key", "x-api-key", "authorization", "signature", "api_secret", "apikey"):
                assert forbidden not in text, f"{path.name} mentions credential header {forbidden}"

    def test_other_provider_fixtures_parse(self):
        assert load_fixture("coingecko_ping.json") == {"gecko_says": "(V3) To the Moon!"}
        markets = load_fixture("coingecko_markets.json")
        assert {m["id"] for m in markets} >= {"bitcoin"}
        prices = load_fixture("defillama_prices.json")
        assert "coins" in prices
