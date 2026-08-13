from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.options.analytics import compute_options_analytics
from app.services.options.provider import fetch_options_chain
from app.services.options.universe import (
    MARKET_ETFS,
    SECONDARY_ETFS,
    SECTOR_ETFS,
    build_options_universe,
    map_ticker_to_sector,
    sector_etf_mapping,
)


def _chain(*, empty: bool = False):
    if empty:
        return SimpleNamespace(calls=[], puts=[])
    return SimpleNamespace(
        calls=[
            {"contractSymbol": "SPY260820C00100", "strike": 100, "lastPrice": 2, "bid": 1.9, "ask": 2.1, "volume": 100, "openInterest": 1000, "impliedVolatility": .2},
            {"contractSymbol": "SPY260820C00110", "strike": 110, "volume": None, "openInterest": 100, "impliedVolatility": float("nan")},
        ],
        puts=[
            {"contractSymbol": "SPY260820P00100", "strike": 100, "volume": 50, "openInterest": 500, "impliedVolatility": .22},
            {"contractSymbol": "SPY260820P00090", "strike": 90, "volume": 20, "openInterest": 100, "impliedVolatility": .4},
        ],
    )


class _Ticker:
    options = ("2099-08-20", "2099-09-17", "2099-10-15")
    fast_info = {"lastPrice": 100}

    def option_chain(self, expiration):
        return _chain()


def test_universe_uses_canonical_registry_and_level_one_mapping():
    rows = build_options_universe([{"ticker": "NVDA", "official_sector": "Technology", "name": "NVIDIA"}])
    assert set(MARKET_ETFS) <= {row["symbol"] for row in rows}
    assert set(SECTOR_ETFS) <= {row["symbol"] for row in rows}
    assert set(SECONDARY_ETFS) <= {row["symbol"] for row in rows}
    nvda = next(row for row in rows if row["symbol"] == "NVDA")
    assert nvda["sector_id"] == "base.technology"
    assert nvda["primary_etf"] == "XLK"
    assert "SMH" in nvda["secondary_etfs"]
    assert sector_etf_mapping()["base.technology"]["primary_etf"] == "XLK"


def test_universe_keeps_unclassified_watchlist_explicit():
    row = map_ticker_to_sector("UNKNOWN", {"category": "ideas"})
    assert row["mapping_status"] == "unclassified"
    assert row["primary_etf"] is None
    assert map_ticker_to_sector("MSFT", {"official_sector": "Information Technology"})["sector_id"] == "base.technology"


def test_provider_normalizes_dynamic_chain_and_limits_expirations():
    payload = fetch_options_chain("SPY", ticker_factory=lambda _: _Ticker(), timeout_seconds=.2)
    assert payload["status"] == "OK"
    assert len(payload["expirations"]) == 2
    assert payload["expirations"][0]["contract_count"] == 4
    assert payload["calls"][1]["implied_volatility"] is None


def test_provider_no_options_and_empty_expiration():
    class NoOptions:
        options = ()

    assert fetch_options_chain("SPY", ticker_factory=lambda _: NoOptions())["status"] == "NO_OPTIONS"

    class EmptyExpiration:
        options = ("2000-01-01",)

    assert fetch_options_chain("SPY", ticker_factory=lambda _: EmptyExpiration())["status"] == "NO_VALID_EXPIRATION"


def test_provider_timeout_is_bounded_status():
    class Slow:
        @property
        def options(self):
            import time
            time.sleep(.2)
            return ("2099-08-20",)

    payload = fetch_options_chain("SPY", ticker_factory=lambda _: Slow(), timeout_seconds=.01, retries=0)
    assert payload["status"] == "PROVIDER_ERROR"
    assert payload["error_code"] == "TIMEOUT"


def test_provider_invalid_symbol_rejected():
    with pytest.raises(ValueError):
        fetch_options_chain("not a ticker")


def test_analytics_ratios_atm_skew_and_history_status():
    payload = {
        "symbol": "SPY", "underlying_price": 100, "fetched_at": "2099-08-14T12:00:00+00:00",
        "expirations": [{"expiration": "2099-08-20", "days_to_expiration": 6, "calls": _chain().calls, "puts": _chain().puts}],
    }
    row = compute_options_analytics(payload, history=[{"atm_iv": .18, "total_volume": 50}])
    assert row["put_call_volume_ratio"] == pytest.approx(70 / 100)
    assert row["put_call_oi_ratio"] == pytest.approx(600 / 1100)
    assert row["atm_iv"] == pytest.approx(.21)
    assert row["downside_skew"] == pytest.approx(.19)
    assert row["iv_change"] == pytest.approx(.03)
    assert row["activity_status"] == "high"
    assert row["metrics_json"]["skew_method"] == "moneyness_proxy"


def test_analytics_missing_liquidity_is_not_zero_filled():
    row = compute_options_analytics({
        "symbol": "IHI", "underlying_price": 100,
        "expirations": [{"expiration": "2099-08-20", "calls": [{"strike": 100, "impliedVolatility": .3}], "puts": [{"strike": 100, "impliedVolatility": .32}]}],
    })
    assert row["call_volume"] is None and row["put_open_interest"] is None
    assert row["status"] == "INSUFFICIENT_LIQUIDITY"
    assert "missing_volume_and_open_interest" in row["warnings"]
