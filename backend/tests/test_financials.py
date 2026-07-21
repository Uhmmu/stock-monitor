import pandas as pd

from app.services.financials import normalize_quarters
from app.services import market_data


def _row(year, quarter, end, revenue=None):
    return {"year": year, "quarter": quarter, "period": end, "revenue": revenue}


def test_keeps_only_recent_four_quarters_sorted():
    rows = [
        _row(2025, 3, "2025-09-30", 1),
        _row(2026, 2, "2026-06-30", 2),
        _row(2025, 4, "2025-12-31", 3),
        _row(2026, 1, "2026-03-31", 4),
        _row(2025, 2, "2025-06-30", 5),
    ]
    quarters = normalize_quarters(rows)
    assert len(quarters) == 4
    assert [q.period_end.isoformat() for q in quarters] == [
        "2026-06-30",
        "2026-03-31",
        "2025-12-31",
        "2025-09-30",
    ]
    assert quarters[0].label == "2026-Q2"


def test_missing_values_stay_none():
    quarters = normalize_quarters([_row(2026, 1, "2026-03-31")])
    assert quarters[0].revenue is None
    assert quarters[0].eps is None


def test_rows_without_period_are_skipped():
    assert normalize_quarters([{"year": 2026, "quarter": 1}]) == []


def test_normalizes_finnhub_quarterly_series_by_period():
    payload = {
        "symbol": "NVDA",
        "series": {
            "quarterly": {
                "eps": [
                    {"period": "2026-04-26", "v": 1.25},
                    {"period": "2026-01-25", "v": 1.1},
                ],
                "grossMargin": [
                    {"period": "2026-04-26", "v": 72.7},
                    {"period": "2026-01-25", "v": 71.2},
                ],
            }
        },
    }

    quarters = normalize_quarters(payload)

    assert [quarter.label for quarter in quarters] == ["2026-Q2", "2026-Q1"]
    assert quarters[0].eps == 1.25
    assert quarters[0].gross_margin == 72.7
    assert quarters[0].revenue is None
    assert quarters[0].raw_payload["eps"] == 1.25


def test_ignores_non_list_finnhub_series_values():
    payload = {"series": {"quarterly": {"eps": None, "grossMargin": "invalid"}}}
    assert normalize_quarters(payload) == []


def test_yahoo_statement_fetch_normalizes_aliases_and_calculates_fallbacks(monkeypatch):
    end = pd.Timestamp("2025-12-31")
    class FakeTicker:
        income_stmt = pd.DataFrame({end: [1000, 200, 100, 10]}, index=["Total Revenue", "Gross Profit", "Operating Income", "Diluted EPS"])
        balance_sheet = pd.DataFrame({end: [300, 120, 600]}, index=["Cash And Cash Equivalents", "Inventory", "Stockholders Equity"])
        cash_flow = pd.DataFrame({end: [160, -40, 20]}, index=["Operating Cash Flow", "Capital Expenditure", "Depreciation"])
        quarterly_income_stmt = income_stmt
        quarterly_balance_sheet = balance_sheet
        quarterly_cash_flow = cash_flow
    monkeypatch.setattr(market_data.yf, "Ticker", lambda _: FakeTicker())

    row = market_data.fetch_yf_financial_statements("TEST", "annual")[0]
    assert row["period_end"].isoformat() == "2025-12-31"
    assert row["income_statement"]["revenue"] == 1000
    assert row["income_statement"]["ebitda"] == 120
    assert row["balance_sheet"]["cash"] == 300
    assert row["cash_flow"]["free_cash_flow"] == 120
