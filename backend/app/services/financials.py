from dataclasses import dataclass, field
from datetime import date


@dataclass
class QuarterData:
    fiscal_year: int
    fiscal_period: str
    period_end: date
    filed_at: date | None = None
    currency: str | None = None
    revenue: float | None = None
    eps: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    raw_payload: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.fiscal_year}-{self.fiscal_period}"


def _to_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: dict, *keys: str):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


_CONCEPTS = {
    "revenue": ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap_RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap_Revenues", "us-gaap_SalesRevenueNet"),
    "cost_of_revenue": ("us-gaap_CostOfRevenue", "us-gaap_CostOfGoodsAndServicesSold"),
    "net_income": ("us-gaap_NetIncomeLoss", "us-gaap_ProfitLoss"),
    "operating_income": ("us-gaap_OperatingIncomeLoss",),
    "operating_cash_flow": ("us-gaap_NetCashProvidedByUsedInOperatingActivities",
                            "us-gaap_NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "capex": ("us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
              "us-gaap_PaymentsToAcquireProductiveAssets"),
}


def _from_report(section: list[dict], concepts: tuple[str, ...]) -> float | None:
    for concept in concepts:
        for item in section:
            if item.get("concept") == concept:
                val = _num(item.get("value"))
                if val is not None:
                    return val
    return None


def _series_rows(payload: dict) -> list[dict]:
    quarterly = payload.get("series", {}).get("quarterly", {})
    if not isinstance(quarterly, dict):
        return []

    by_period: dict[str, dict] = {}
    for metric, values in quarterly.items():
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict) or not value.get("period"):
                continue
            period = str(value["period"])[:10]
            row = by_period.setdefault(period, {"period": period})
            row[metric] = value.get("v")

    return list(by_period.values())


_FLOW_FIELDS = ("revenue", "cost_of_revenue", "net_income", "operating_income", "operating_cash_flow", "capex")


def _extract_flows(filing: dict) -> dict:
    """抽单个 filing 的原始 flow 值（可能是 YTD 累计）+ 元数据。"""
    report = filing.get("report") or {}
    ic = report.get("ic") or []
    cf = report.get("cf") or []
    raw = {
        "revenue": _from_report(ic, _CONCEPTS["revenue"]),
        "cost_of_revenue": _from_report(ic, _CONCEPTS["cost_of_revenue"]),
        "net_income": _from_report(ic, _CONCEPTS["net_income"]) or _from_report(cf, _CONCEPTS["net_income"]),
        "operating_income": _from_report(ic, _CONCEPTS["operating_income"]),
        "operating_cash_flow": _from_report(cf, _CONCEPTS["operating_cash_flow"]),
        "capex": _from_report(cf, _CONCEPTS["capex"]),
    }
    return {
        "period_end": _to_date(filing.get("endDate")),
        "start_date": _to_date(filing.get("startDate")),
        "fiscal_year": filing.get("year"),
        "quarter": filing.get("quarter"),
        "filed_at": _to_date(filing.get("filedDate")),
        "currency": filing.get("currency"),
        "raw": raw,
        "filing": filing,
    }


def quarters_from_sec(reported: list[dict], series: dict | None = None) -> list["QuarterData"]:
    """从 SEC get_reported_financials 抽绝对值，series(basic_financials) 补 EPS。
    10-Q 的利润表/现金流是年初至今累计(YTD)，需去累计：同财年内 Qn 单季 = YTD_n − YTD_{n-1}。
    同财年 YTD filing 共享 startDate，据此配对上一季。"""
    ratios = {row["period"]: row for row in _series_rows(series or {})}
    parsed = [_extract_flows(f) for f in reported if _to_date(f.get("endDate"))]
    parsed.sort(key=lambda p: p["period_end"])

    quarters: list[QuarterData] = []
    for entry in parsed:
        raw = entry["raw"]
        start, end = entry["start_date"], entry["period_end"]
        span_days = (end - start).days if start and end else 0
        if span_days <= 100:
            single = dict(raw)  # 已是单季（通常 Q1）
        else:
            # YTD 累计：减去同 startDate、endDate 更早的最近一季
            prior = None
            for cand in parsed:
                if cand is entry or cand["start_date"] != start or cand["period_end"] >= end:
                    continue
                if prior is None or cand["period_end"] > prior["period_end"]:
                    prior = cand
            single = {}
            for field_name in _FLOW_FIELDS:
                cur = raw.get(field_name)
                pv = prior["raw"].get(field_name) if prior else None
                # 有上一季才能去累计；无上一季则该单季不可靠 → None
                single[field_name] = (cur - pv) if (cur is not None and pv is not None) else None

        revenue, cost = single.get("revenue"), single.get("cost_of_revenue")
        net_income, operating_income = single.get("net_income"), single.get("operating_income")
        ocf, capex = single.get("operating_cash_flow"), single.get("capex")
        fcf = (ocf - capex) if ocf is not None and capex is not None else None
        gross_margin = ((revenue - cost) / revenue * 100) if revenue and cost is not None else None
        net_margin = (net_income / revenue * 100) if revenue and net_income is not None else None
        ratio = ratios.get(end.isoformat(), {})
        year = entry["fiscal_year"] or end.year
        quarter = entry["quarter"]
        fiscal_period = f"Q{quarter}" if quarter else f"Q{(end.month - 1) // 3 + 1}"
        quarters.append(QuarterData(
            fiscal_year=int(year), fiscal_period=fiscal_period, period_end=end,
            filed_at=entry["filed_at"], currency=entry["currency"],
            revenue=revenue, eps=_num(ratio.get("eps")), net_income=net_income,
            operating_income=operating_income, gross_margin=gross_margin,
            net_margin=net_margin if net_margin is not None else _num(ratio.get("netMargin")),
            operating_cash_flow=ocf, free_cash_flow=fcf, raw_payload=entry["filing"],
        ))
    quarters.sort(key=lambda item: item.period_end, reverse=True)
    return quarters[:4]


def quarters_from_yf(rows: list[dict]) -> list["QuarterData"]:
    """yfinance 季度财报（单季值）→ QuarterData。按日历季度标注（period_end 推导）。"""
    quarters: list[QuarterData] = []
    for row in rows:
        end = _to_date(row.get("period_end"))
        if not end:
            continue
        revenue = _num(row.get("revenue"))
        cost = _num(row.get("cost_of_revenue"))
        gross_profit = _num(row.get("gross_profit"))
        net_income = _num(row.get("net_income"))
        operating_income = _num(row.get("operating_income"))
        ocf = _num(row.get("operating_cash_flow"))
        fcf = _num(row.get("free_cash_flow"))
        if gross_profit is not None and revenue:
            gross_margin = gross_profit / revenue * 100
        elif cost is not None and revenue:
            gross_margin = (revenue - cost) / revenue * 100
        else:
            gross_margin = None
        net_margin = (net_income / revenue * 100) if revenue and net_income is not None else None
        eps = _num(row.get("eps"))
        quarters.append(QuarterData(
            fiscal_year=end.year, fiscal_period=f"Q{(end.month - 1) // 3 + 1}", period_end=end,
            filed_at=None, currency=None, revenue=revenue, eps=eps, net_income=net_income,
            operating_income=operating_income, gross_margin=gross_margin, net_margin=net_margin,
            operating_cash_flow=ocf, free_cash_flow=fcf, raw_payload=row,
        ))
    quarters.sort(key=lambda item: item.period_end, reverse=True)
    return quarters[:4]


def normalize_quarters(payload: list[dict] | dict) -> list[QuarterData]:
    rows = _series_rows(payload) if isinstance(payload, dict) else payload
    quarters: list[QuarterData] = []
    for row in rows:
        period_end = _to_date(_first(row, "period", "endDate", "period_end"))
        if not period_end:
            continue
        quarter = _first(row, "quarter", "fiscal_period")
        year = _first(row, "year", "fiscal_year") or period_end.year
        if quarter:
            fiscal_period = str(quarter) if str(quarter).startswith("Q") else f"Q{quarter}"
        else:
            fiscal_period = f"Q{(period_end.month - 1) // 3 + 1}"
        quarters.append(
            QuarterData(
                fiscal_year=int(year),
                fiscal_period=fiscal_period,
                period_end=period_end,
                filed_at=_to_date(_first(row, "filed", "filedDate")),
                currency=row.get("currency"),
                revenue=_num(row.get("revenue")),
                eps=_num(_first(row, "eps", "epsActual")),
                net_income=_num(_first(row, "netIncome", "net_income")),
                gross_margin=_num(_first(row, "grossMargin", "gross_margin")),
                operating_cash_flow=_num(_first(row, "operatingCashFlow", "operating_cash_flow")),
                free_cash_flow=_num(_first(row, "freeCashFlow", "free_cash_flow")),
                raw_payload=row,
            )
        )
    quarters.sort(key=lambda item: item.period_end, reverse=True)
    return quarters[:4]
