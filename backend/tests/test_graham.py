import math

import httpx
import pytest

from app.services.graham import (
    FRED_CACHE_KEY,
    FRED_LAST_GOOD_KEY,
    apply_graham_overrides,
    build_graham_from_sources,
    calculate_cagr,
    calculate_graham_growth_value,
    calculate_graham_number,
    calculate_margin_of_safety,
    data_point,
    evaluate_graham_applicability,
    get_latest_aaa_corporate_bond_yield,
    resolve_bvps,
    resolve_eps_ttm,
)


@pytest.mark.parametrize("eps,bvps", [(None, 10), (2, None), (-2, 10), (2, -10), (0, 10), (2, 0)])
def test_graham_number_rejects_missing_or_non_positive_inputs(eps, bvps):
    assert calculate_graham_number(eps, bvps) is None


def test_graham_number_normal_value():
    assert calculate_graham_number(4, 10) == pytest.approx(30)


def test_growth_formula_normal_and_clamps_growth():
    assert calculate_graham_growth_value(4, 10, 5.5) == pytest.approx(4 * 28.5 * 4.4 / 5.5)
    assert calculate_graham_growth_value(4, 99, 5.5) == calculate_graham_growth_value(4, 15, 5.5)
    assert calculate_graham_growth_value(4, -99, 5.5) == calculate_graham_growth_value(4, -4, 5.5)


@pytest.mark.parametrize("eps,growth,yield_pct", [(-1, 5, 5), (2, 5, 0), (2, 5, None), (2, math.nan, 5), (2, math.inf, 5), (math.nan, 5, 5)])
def test_growth_formula_rejects_invalid_inputs(eps, growth, yield_pct):
    assert calculate_graham_growth_value(eps, growth, yield_pct) is None


def test_margin_of_safety_cases():
    assert calculate_margin_of_safety(100, 80) == pytest.approx(.2)
    assert calculate_margin_of_safety(100, 120) == pytest.approx(-.2)
    assert calculate_margin_of_safety(100, 100) == 0
    assert calculate_margin_of_safety(0, 100) is None
    assert calculate_margin_of_safety(None, 100) is None
    assert calculate_margin_of_safety(100, None) is None


def test_cagr_cases():
    assert calculate_cagr(100, 121, 2) == pytest.approx(10)
    assert calculate_cagr(100, 81, 2) == pytest.approx(-10)
    assert calculate_cagr(0, 100, 2) is None
    assert calculate_cagr(-1, 100, 2) is None
    assert calculate_cagr(100, -1, 2) is None
    assert calculate_cagr(100, 121, 0) is None


def test_yfinance_missing_uses_finnhub_then_financial_calculation():
    finnhub_eps = resolve_eps_ttm({}, {"epsTTM": 6.2}, [], {})
    assert finnhub_eps["value"] == 6.2
    assert finnhub_eps["source"] == "finnhub"
    finnhub_bvps = resolve_bvps({}, {"bookValuePerShareQuarterly": 18}, {})
    assert finnhub_bvps["value"] == 18
    calculated_bvps = resolve_bvps({}, {}, {"periods": [{"date": "2025-12-31", "stockholders_equity": 500, "shares_issued": 25}]})
    assert calculated_bvps["value"] == 20
    calculated_eps = resolve_eps_ttm(
        {"sharesOutstanding": 10}, {},
        [{"period_end": f"2025-0{quarter}-30", "net_income": value} for quarter, value in enumerate((10, 20, 30, 40), 1)], {},
    )
    assert calculated_eps["value"] == 10
    assert calculated_eps["quality"] == "calculated"


def test_all_source_inputs_missing_returns_unavailable_models():
    result = build_graham_from_sources("MISS", {}, {}, [], {}, None, None)
    assert result["graham_number"]["available"] is False
    assert result["growth_formula"]["base"]["available"] is False
    assert result["overall_status"] == "not_applicable"


class FakeCache:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class FakeResponse:
    text = "DATE,DAAA\n2026-07-16,.\n2026-07-17,5.73\n"

    def raise_for_status(self):
        return None


def test_fred_uses_latest_non_empty_and_caches_it():
    cache = FakeCache()
    result = get_latest_aaa_corporate_bond_yield(cache, lambda *args, **kwargs: FakeResponse())
    assert result["value"] == 5.73
    assert result["as_of"] == "2026-07-17"
    assert FRED_CACHE_KEY in cache.values
    assert FRED_LAST_GOOD_KEY in cache.values


def test_fred_failure_uses_last_good_cache():
    cached = '{"value": 5.5, "source": "FRED_DAAA", "quality": "market_data", "as_of": "2026-07-15"}'
    cache = FakeCache({FRED_LAST_GOOD_KEY: cached})

    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    result = get_latest_aaa_corporate_bond_yield(cache, fail)
    assert result["value"] == 5.5
    assert result["cache_status"] == "stale_fallback"


@pytest.mark.parametrize(
    "sector,industry,eps,bvps,status",
    [
        ("Industrials", "Tools", -1, 10, "not_applicable"),
        ("Industrials", "Tools", 2, -10, "limited"),
        ("Financial Services", "Banks - Regional", 2, 10, "limited"),
        ("Real Estate", "REIT - Retail", 2, 10, "limited"),
        ("Industrials", "Tools", 2, 10, "applicable"),
    ],
)
def test_applicability_rules(sector, industry, eps, bvps, status):
    assert evaluate_graham_applicability(sector, industry, eps, bvps)["status"] == status


def test_user_override_is_clamped_and_preserves_original_input():
    original = build_graham_from_sources(
        "TEST", {"currentPrice": 80, "trailingEps": 5, "bookValue": 20, "forwardEps": 5.5, "currency": "USD"},
        {}, [], {}, None, data_point(5.5, "FRED_DAAA", quality="market_data"),
    )
    overridden = apply_graham_overrides(original, growth_rate=15, normalized_eps=6)
    assert overridden["inputs"]["growth_rate"]["source"] == "user_override"
    assert overridden["inputs"]["eps_ttm"]["original"]["value"] == 5
    assert original["inputs"]["eps_ttm"]["value"] == 5
