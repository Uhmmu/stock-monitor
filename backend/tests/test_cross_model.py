import pandas as pd

from app.services.cross_model import (
    build_cross_model,
    calculate_altman_metric,
    calculate_model_weight_details,
    calculate_model_weights,
    calculate_piotroski_metric,
    calculate_roic_metric,
    derive_business_model_tags,
    derive_classification_tags,
    industry_profile,
    normalize_financial_statements,
)


def test_software_classification_and_saas_evidence():
    info = {"sectorKey": "technology", "industryKey": "software-application", "longBusinessSummary": "A cloud-based platform with recurring subscription revenue."}
    tags = derive_classification_tags(info)
    tags.update(derive_business_model_tags(info, {"gross_margin": 75, "capex_to_revenue": .04}))
    assert tags["software"] == .95
    assert tags["saas"] >= .5
    assert industry_profile(info, tags) == "software"


def test_unprofitable_models_are_disabled_and_weights_normalize():
    weights = calculate_model_weights({"unprofitable": 1.0})
    assert weights["forward_pe"] == 0
    assert weights["peg"] == 0
    assert round(sum(weights.values()), 4) == 1


def test_weight_details_explain_tag_adjustments():
    weights, details = calculate_model_weight_details({"high_growth": 1.0, "software": .8})
    peg = next(item for item in details if item["key"] == "peg")
    assert peg["base_score"] == 15
    assert any(item["tag"] == "high_growth" and item["applied_adjustment"] == 15 for item in peg["adjustments"])
    assert peg["weight"] == weights["peg"]


def test_peer_medians_dcf_scenarios_and_consensus_are_exposed():
    info = {
        "shortName": "Example SaaS", "sector": "Technology", "sectorKey": "technology",
        "industry": "Software - Application", "industryKey": "software-application",
        "longBusinessSummary": "Cloud-based software as a service with recurring revenue.",
        "currentPrice": 100, "marketCap": 10_000_000_000, "enterpriseValue": 10_500_000_000,
        "totalRevenue": 1_000_000_000, "freeCashflow": 200_000_000, "ebitda": 250_000_000,
        "sharesOutstanding": 100_000_000, "forwardEps": 4, "forwardPE": 20, "pegRatio": 1.0,
        "revenueGrowth": .20, "earningsGrowth": .25, "grossMargins": .75,
        "totalDebt": 1_000_000_000, "totalCash": 500_000_000,
    }
    peers = [
        {"forwardPE": 22, "pegRatio": 1.2, "enterpriseValue": 12_000, "totalRevenue": 1_000, "revenueGrowth": .18, "freeCashflow": 100, "marketCap": 10_000},
        {"forwardPE": 26, "pegRatio": 1.4, "enterpriseValue": 16_000, "totalRevenue": 1_000, "revenueGrowth": .22, "freeCashflow": 120, "marketCap": 12_000},
    ]
    payload = build_cross_model("TEST", info, [], peers, ["AAA", "BBB"])
    forward_pe = next(item for item in payload["valuation"] if item["key"] == "forward_pe")
    assert forward_pe["peer_median"] == 24
    assert forward_pe["comparison"] == "低于同行 17%"
    assert payload["dcf_scenarios"]["bear"] < payload["dcf_scenarios"]["base"] < payload["dcf_scenarios"]["bull"]
    assert payload["consensus"]["value"] is not None
    assert payload["reverse_dcf"]["implied_fcf_growth"] is not None


def _annual_financials():
    return {"source": "yfinance_annual", "periods": [
        {"date": "2025-12-31", "revenue": 1200, "gross_profit": 720, "operating_income": 240,
         "pretax_income": 200, "tax_expense": 30, "net_income": 160, "total_assets": 1000,
         "current_assets": 400, "current_liabilities": 200, "total_liabilities": 450,
         "stockholders_equity": 550, "retained_earnings": 300, "cash": 100, "total_debt": 150,
         "long_term_debt": 100, "operating_cash_flow": 190, "shares_issued": 100},
        {"date": "2024-12-31", "revenue": 1000, "gross_profit": 550, "operating_income": 180,
         "net_income": 120, "total_assets": 900, "current_assets": 320, "current_liabilities": 200,
         "stockholders_equity": 500, "cash": 80, "total_debt": 180, "long_term_debt": 130,
         "operating_cash_flow": 130, "shares_issued": 100},
        {"date": "2023-12-31", "total_assets": 850},
    ]}


def test_yahoo_statement_aliases_are_normalized_and_sorted_by_date():
    newer, older = pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")
    income = pd.DataFrame({older: [1000, 120], newer: [1200, 160]}, index=["OperatingRevenue", "NetIncomeCommonStockholders"])
    balance = pd.DataFrame({older: [900], newer: [1000]}, index=["TotalAssets"])
    cashflow = pd.DataFrame({older: [130], newer: [190]}, index=["OperatingCashFlow"])
    normalized = normalize_financial_statements(income, balance, cashflow)
    assert [period["date"] for period in normalized["periods"]] == ["2025-12-31", "2024-12-31"]
    assert normalized["periods"][0]["revenue"] == 1200
    assert normalized["periods"][0]["operating_cash_flow"] == 190


def test_annual_statements_fill_roic_piotroski_and_altman():
    financials = _annual_financials()
    roic = calculate_roic_metric(financials)
    assert roic["status"] == "available"
    assert round(roic["value"], 2) == 34.0
    assert roic["inputs"]["tax_rate"] == .15

    f_score = calculate_piotroski_metric(financials)
    assert f_score["status"] == "available"
    assert f_score["display"] == "9/9"
    assert f_score["value"] == 9

    altman = calculate_altman_metric(financials, market_cap=2000, profile_key="general")
    assert altman["status"] == "available"
    assert altman["value"] > 2.99
    assert altman["applicability"] == "medium"


def test_piotroski_missing_signals_are_not_scored_as_failures():
    financials = _annual_financials()
    del financials["periods"][0]["shares_issued"]
    result = calculate_piotroski_metric(financials)
    assert result["status"] == "partial"
    assert result["available_components"] == 8
    assert result["display"] == "8/8"
    assert result["components"]["no_new_shares"] is None
    assert result["missing_fields"] == ["shares_issued"]


def test_altman_is_disabled_for_financial_companies():
    result = calculate_altman_metric(_annual_financials(), market_cap=2000, profile_key="bank")
    assert result["status"] == "not_applicable"
    assert result["value"] is None


def test_build_payload_exposes_missing_fields_instead_of_generic_insufficient():
    payload = build_cross_model("TEST", {"shortName": "Test", "marketCap": 1000}, [], financials={"source": "yfinance_annual", "periods": []})
    roic = next(item for item in payload["health"] if item["key"] == "roic")
    assert roic["status"] == "insufficient"
    assert "operating_income" in roic["missing_fields"]
