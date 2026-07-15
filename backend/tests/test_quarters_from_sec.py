from app.services.financials import quarters_from_sec


def _filing(end, year, quarter, revenue, cost, net, op, ocf, capex, start=None):
    return {
        "year": year, "quarter": quarter, "endDate": end, "filedDate": end,
        "startDate": start or end,
        "report": {
            "ic": [
                {"concept": "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "value": revenue},
                {"concept": "us-gaap_CostOfRevenue", "value": cost},
                {"concept": "us-gaap_NetIncomeLoss", "value": net},
                {"concept": "us-gaap_OperatingIncomeLoss", "value": op},
            ],
            "cf": [
                {"concept": "us-gaap_NetCashProvidedByUsedInOperatingActivities", "value": ocf},
                {"concept": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "value": capex},
            ],
        },
    }


def test_extracts_absolute_values_from_sec():
    q = quarters_from_sec([_filing("2025-12-31", 2026, 2, 400.0, 150.0, 229.0, -192.0, 214.0, 720.0)])
    assert len(q) == 1
    row = q[0]
    assert row.revenue == 400.0
    assert row.net_income == 229.0
    assert row.operating_income == -192.0
    assert row.operating_cash_flow == 214.0
    assert row.free_cash_flow == 214.0 - 720.0  # OCF - CapEx
    assert abs(row.gross_margin - (400.0 - 150.0) / 400.0 * 100) < 1e-6
    assert abs(row.net_margin - 229.0 / 400.0 * 100) < 1e-6
    assert row.fiscal_period == "Q2"


def test_series_supplies_eps():
    series = {"series": {"quarterly": {"eps": [{"period": "2025-12-31", "v": 1.5}]}}}
    q = quarters_from_sec([_filing("2025-12-31", 2026, 2, 400.0, 150.0, 229.0, -192.0, 214.0, 720.0)], series)
    assert q[0].eps == 1.5


def test_sorts_and_limits_to_four():
    filings = [_filing(f"2025-0{m}-30", 2025, m, 100.0, 40.0, 10.0, 5.0, 8.0, 3.0) for m in range(1, 6)]
    q = quarters_from_sec(filings)
    assert len(q) == 4
    assert q[0].period_end.isoformat() == "2025-05-30"


def test_decumulates_ytd_filings():
    # 真实 IREN：财年7月起，Q1(7-9月)单季，Q2 报表是7-12月半年累计
    q1 = _filing("2025-09-30", 2026, 1, 240.0, 90.0, 100.0, -50.0, 120.0, 300.0, start="2025-07-01")
    q2_ytd = _filing("2025-12-31", 2026, 2, 425.0, 150.0, 229.0, -192.0, 214.0, 720.0, start="2025-07-01")
    quarters = quarters_from_sec([q1, q2_ytd])
    by_period = {q.fiscal_period: q for q in quarters}
    # Q2 单季 = YTD - Q1
    assert abs(by_period["Q2"].revenue - (425.0 - 240.0)) < 1e-6
    assert abs(by_period["Q2"].net_income - (229.0 - 100.0)) < 1e-6
    assert abs(by_period["Q2"].operating_cash_flow - (214.0 - 120.0)) < 1e-6
    # Q1 span≤100 天，直接用原值
    assert by_period["Q1"].revenue == 240.0


def test_ytd_without_prior_quarter_yields_none():
    # 只有 Q2 半年累计、缺 Q1 → 无法去累计 → None（绝不错显累计值）
    q2_only = _filing("2025-12-31", 2026, 2, 425.0, 150.0, 229.0, -192.0, 214.0, 720.0, start="2025-07-01")
    quarters = quarters_from_sec([q2_only])
    assert quarters[0].revenue is None
    assert quarters[0].net_income is None


def test_missing_revenue_yields_none_margins():
    filing = {"year": 2026, "quarter": 1, "endDate": "2026-03-31", "report": {"ic": [], "cf": []}}
    q = quarters_from_sec([filing])
    assert q[0].revenue is None
    assert q[0].gross_margin is None
    assert q[0].net_margin is None
