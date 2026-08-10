"""Persisted, deterministic stock comparison.

This module is deliberately read-only.  It consumes the evidence already
stored by the market/financial jobs; it never asks a provider for a value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isclose, isfinite, sqrt
from statistics import mean, median, stdev
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    CompanyProfile,
    FinancialStatementSnapshot,
    HistoricalPrice,
    PriceSnapshot,
    Security,
    StockProfile,
    ValuationSnapshot,
)


CATEGORY_LABELS = {
    "price_performance": "行情与表现", "valuation": "估值", "growth": "增长",
    "profitability": "盈利能力", "capital_efficiency": "资本效率",
    "cash_flow": "现金流", "balance_sheet": "资产负债与健康", "technical": "技术与动量",
}
METRIC_LABELS = {
    "price": "当前价格", "day_change_pct": "当日涨跌", "return_1m_pct": "1 个月收益",
    "return_3m_pct": "3 个月收益", "return_6m_pct": "6 个月收益", "return_1y_pct": "1 年收益",
    "volatility_90d_pct": "90 日年化波动", "distance_52w_high_pct": "距 52 周高点",
    "forward_pe": "Forward P/E", "peg": "PEG", "ev_sales": "EV/Sales", "ev_ebitda": "EV/EBITDA",
    "price_to_book": "P/B", "fcf_yield_pct": "FCF 收益率", "consensus_upside_pct": "估值共识空间",
    "dcf_upside_pct": "DCF 基准空间", "consensus_fair_value": "模型估值共识", "dcf_base_value": "DCF 基准价值",
    "valuation_model_agreement_pct": "估值模型一致度", "revenue_growth_pct": "营收增长", "eps_growth_pct": "EPS 增长",
    "revenue_cagr_3y_pct": "营收 3 年 CAGR", "rule_of_40_pct": "Rule of 40",
    "gross_margin_pct": "毛利率", "operating_margin_pct": "营业利润率", "net_margin_pct": "净利率",
    "fcf_margin_pct": "FCF 利润率", "roe_pct": "ROE", "roic_pct": "ROIC", "roa_pct": "ROA",
    "operating_cash_flow_margin_pct": "经营现金流利润率", "fcf_positive_years": "正 FCF 年数",
    "current_ratio": "流动比率", "debt_to_equity": "债务 / 权益", "net_debt_to_ebitda": "净债务 / EBITDA",
    "altman_z": "Altman Z", "piotroski_score": "Piotroski F-Score",
    "relative_volume_20d": "20 日相对成交量", "momentum_90d_pct": "90 日动量",
}
METRIC_TOOLTIPS = {
    "price": "最新持久化市场价格；不同币种的绝对价格不代表公司优劣。",
    "day_change_pct": "相对前收盘价的单日百分比变化。",
    "return_1m_pct": "最新收盘价相对至少 30 天前最近交易日的收益率。",
    "return_3m_pct": "最新收盘价相对至少 90 天前最近交易日的收益率。",
    "return_6m_pct": "最新收盘价相对至少 180 天前最近交易日的收益率。",
    "return_1y_pct": "最新收盘价相对至少 365 天前最近交易日的收益率。",
    "volatility_90d_pct": "最近约 90 个交易日的日收益标准差年化；越低仅代表波动较小。",
    "distance_52w_high_pct": "现价相对最近 252 个交易日最高收盘价的距离，属于情境指标。",
    "forward_pe": "股价相对未来 12 个月预期每股盈利的倍数。",
    "peg": "Forward P/E 相对预期 EPS 增长的倍数，对预测稳定性敏感。",
    "ev_sales": "企业价值相对营收的倍数；需结合毛利率与行业解释。",
    "ev_ebitda": "企业价值相对 EBITDA 的倍数；金融企业通常不适用。",
    "price_to_book": "股价相对每股账面净资产的倍数；银行等资产型行业更有参考性。",
    "fcf_yield_pct": "自由现金流相对市值的收益率，需排除周期峰值和一次性现金流。",
    "consensus_upside_pct": "已存多模型估值共识相对快照现价的差值，不是收益承诺。",
    "dcf_upside_pct": "DCF 基准情景相对快照现价的差值，对假设高度敏感。",
    "consensus_fair_value": "已存独立估值模型公允价值的中位共识。",
    "dcf_base_value": "已存 DCF 基准情景每股价值；应结合悲观与乐观区间。",
    "valuation_model_agreement_pct": "有有效信号的估值模型中，占比最高的低估/合理/偏贵方向所占比例。",
    "revenue_growth_pct": "最近两个已存年度财报的营收同比变化。",
    "eps_growth_pct": "最近两个已存年度财报的 EPS 同比变化。",
    "revenue_cagr_3y_pct": "最近一期与三年前年度营收计算的复合增长率。",
    "rule_of_40_pct": "年度营收增长率与 FCF 利润率之和，跨行业解释需谨慎。",
    "gross_margin_pct": "毛利润占营收比例，行业商业模式差异显著。",
    "operating_margin_pct": "营业利润占营收比例。",
    "net_margin_pct": "净利润占营收比例。",
    "fcf_margin_pct": "自由现金流占营收比例。",
    "roe_pct": "净利润相对平均股东权益；杠杆可能抬高该值。",
    "roic_pct": "税后营业利润相对投入资本；金融企业不适用。",
    "roa_pct": "净利润相对总资产。",
    "operating_cash_flow_margin_pct": "经营现金流占营收比例。",
    "fcf_positive_years": "当前已存年度序列中自由现金流为正的期数。",
    "current_ratio": "流动资产相对流动负债；过高不一定更优，因此不排名。",
    "debt_to_equity": "总债务相对股东权益的倍数。",
    "net_debt_to_ebitda": "总债务扣除现金后相对 EBITDA 的倍数。",
    "altman_z": "已存 Altman Z 结果；金融、REIT 等类型适用性有限。",
    "piotroski_score": "已存 Piotroski 九项财务信号得分；缺失项不会当作零。",
    "relative_volume_20d": "当日成交量相对 20 日均量，属于情境指标。",
    "momentum_90d_pct": "与 3 个月收益同源的压缩动量指标。",
}


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    category: str
    unit: str
    format: str
    source: str
    direction: str = "neutral"
    sortable: bool = True
    percentile_eligible: bool = True
    rank_eligible: bool = True
    supports_history: bool = False
    cross_industry_comparable: bool = True
    missing_policy: str = "show_missing"
    period: str = "latest"
    freshness_days: int | None = None
    tooltip: str = ""
    comparison_strategy: str = "absolute"
    adapter: str = ""

    def as_dict(self) -> dict[str, Any]:
        # Public DTO is intentionally smaller/stable than the internal adapter
        # metadata.  The adapter name never becomes part of the API contract.
        return {
            "key": self.key,
            "label": METRIC_LABELS.get(self.key, self.label),
            "category": CATEGORY_LABELS.get(self.category, self.category),
            "unit": self.unit,
            "format": self.format,
            "source": self.source,
            "direction": self.direction,
            "sortable": self.sortable,
            "supports_rank": self.rank_eligible,
            "supports_percentile": self.percentile_eligible,
            "supports_history": self.supports_history,
            "cross_industry_comparable": self.cross_industry_comparable,
            "comparison_mode": {"percentage_points": "percentage_point"}.get(self.comparison_strategy, self.comparison_strategy),
            "missing_policy": "show" if self.missing_policy == "show_missing" else self.missing_policy,
            "period_type": self.period,
            "freshness_days": self.freshness_days,
            "description": self.tooltip or METRIC_TOOLTIPS.get(self.key, ""),
            "tooltip": self.tooltip or METRIC_TOOLTIPS.get(self.key, ""),
        }


def _m(
    key: str,
    label: str,
    category: str,
    unit: str,
    source: str,
    adapter: str,
    *,
    direction: str = "higher_better",
    format: str = "number",
    sortable: bool = True,
    percentile_eligible: bool | None = None,
    rank_eligible: bool | None = None,
    supports_history: bool = False,
    cross_industry_comparable: bool = True,
    period: str = "latest",
    freshness_days: int | None = None,
    tooltip: str = "",
    comparison_strategy: str = "absolute",
) -> MetricDefinition:
    if percentile_eligible is None:
        percentile_eligible = direction != "neutral" and sortable
    if rank_eligible is None:
        rank_eligible = direction != "neutral" and sortable
    return MetricDefinition(
        key=key,
        label=label,
        category=category,
        unit=unit,
        format=format,
        source=source,
        direction=direction,
        sortable=sortable,
        percentile_eligible=percentile_eligible,
        rank_eligible=rank_eligible,
        supports_history=supports_history,
        cross_industry_comparable=cross_industry_comparable,
        period=period,
        freshness_days=freshness_days,
        tooltip=tooltip,
        comparison_strategy=comparison_strategy,
        adapter=adapter,
    )


# Adding a definition and an adapter name is enough to expose a metric in all
# three outputs (catalog, current comparison, and history when supported).
METRIC_REGISTRY: tuple[MetricDefinition, ...] = (
    _m("price", "Price", "price_performance", "currency", "price_snapshot", "price", direction="neutral", sortable=False, supports_history=True, freshness_days=7),
    _m("day_change_pct", "Day change", "price_performance", "%", "price_snapshot", "day_change_pct", format="percent", supports_history=False, freshness_days=7, comparison_strategy="percentage_points"),
    _m("return_1m_pct", "1M return", "price_performance", "%", "historical_price", "return_1m", format="percent", freshness_days=10, comparison_strategy="percentage_points"),
    _m("return_3m_pct", "3M return", "price_performance", "%", "historical_price", "return_3m", format="percent", freshness_days=10, comparison_strategy="percentage_points"),
    _m("return_6m_pct", "6M return", "price_performance", "%", "historical_price", "return_6m", format="percent", freshness_days=10, comparison_strategy="percentage_points"),
    _m("return_1y_pct", "1Y return", "price_performance", "%", "historical_price", "return_1y", format="percent", freshness_days=14, comparison_strategy="percentage_points"),
    _m("volatility_90d_pct", "90D volatility", "technical", "%", "historical_price", "volatility_90d", format="percent", direction="lower_better", freshness_days=14, comparison_strategy="percentage_points"),
    _m("distance_52w_high_pct", "Distance from 52W high", "technical", "%", "historical_price", "distance_52w_high", format="percent", direction="neutral", freshness_days=14, comparison_strategy="percentage_points"),
    _m("forward_pe", "Forward P/E", "valuation", "multiple", "valuation_snapshot", "payload_forward_pe", direction="lower_better", supports_history=True, freshness_days=45, comparison_strategy="percent"),
    _m("peg", "PEG", "valuation", "multiple", "valuation_snapshot", "payload_peg", direction="lower_better", supports_history=True, freshness_days=45, comparison_strategy="percent"),
    _m("ev_sales", "EV/Sales", "valuation", "multiple", "valuation_snapshot", "payload_ev_sales", direction="lower_better", supports_history=True, freshness_days=45, cross_industry_comparable=False, comparison_strategy="percent"),
    _m("ev_ebitda", "EV/EBITDA", "valuation", "multiple", "valuation_snapshot", "payload_ev_ebitda", direction="lower_better", supports_history=True, freshness_days=45, cross_industry_comparable=False, comparison_strategy="percent"),
    _m("price_to_book", "Price/Book", "valuation", "multiple", "valuation_snapshot", "payload_price_to_book", direction="lower_better", supports_history=True, freshness_days=45, cross_industry_comparable=False, comparison_strategy="percent"),
    _m("fcf_yield_pct", "FCF yield", "valuation", "%", "valuation_snapshot", "payload_fcf_yield", format="percent", supports_history=True, freshness_days=45, comparison_strategy="percentage_points"),
    _m("consensus_upside_pct", "Consensus upside", "valuation", "%", "valuation_snapshot", "payload_consensus_upside", format="percent", supports_history=True, freshness_days=45, comparison_strategy="percentage_points"),
    _m("dcf_upside_pct", "DCF upside", "valuation", "%", "valuation_snapshot", "payload_dcf_upside", format="percent", supports_history=True, freshness_days=45, comparison_strategy="percentage_points"),
    _m("consensus_fair_value", "Consensus fair value", "valuation", "USD/share", "valuation_snapshot", "payload_consensus_fair_value", direction="neutral", supports_history=True, freshness_days=45, cross_industry_comparable=False),
    _m("dcf_base_value", "DCF base value", "valuation", "USD/share", "valuation_snapshot", "payload_dcf_base_value", direction="neutral", supports_history=True, freshness_days=45, cross_industry_comparable=False),
    _m("valuation_model_agreement_pct", "Valuation model agreement", "valuation", "%", "valuation_snapshot", "payload_model_agreement", format="percent", direction="neutral", supports_history=True, freshness_days=45, comparison_strategy="percentage_points"),
    _m("revenue_growth_pct", "Revenue growth", "growth", "%", "financial_statement_snapshot", "statement_revenue_growth", format="percent", supports_history=True, freshness_days=550, comparison_strategy="percentage_points"),
    _m("eps_growth_pct", "EPS growth", "growth", "%", "financial_statement_snapshot", "statement_eps_growth", format="percent", supports_history=True, freshness_days=550, comparison_strategy="percentage_points"),
    _m("revenue_cagr_3y_pct", "Revenue 3Y CAGR", "growth", "%", "financial_statement_snapshot", "statement_revenue_cagr", format="percent", supports_history=True, freshness_days=550, comparison_strategy="percentage_points"),
    _m("rule_of_40_pct", "Rule of 40", "growth", "%", "financial_statement_snapshot", "statement_rule40", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("gross_margin_pct", "Gross margin", "profitability", "%", "financial_statement_snapshot", "statement_gross_margin", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("operating_margin_pct", "Operating margin", "profitability", "%", "financial_statement_snapshot", "statement_operating_margin", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("net_margin_pct", "Net margin", "profitability", "%", "financial_statement_snapshot", "statement_net_margin", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("fcf_margin_pct", "FCF margin", "cash_flow", "%", "financial_statement_snapshot", "statement_fcf_margin", format="percent", supports_history=True, freshness_days=550, comparison_strategy="percentage_points"),
    _m("roe_pct", "ROE", "capital_efficiency", "%", "financial_statement_snapshot", "statement_roe", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("roic_pct", "ROIC", "capital_efficiency", "%", "financial_statement_snapshot", "statement_roic", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("roa_pct", "ROA", "capital_efficiency", "%", "financial_statement_snapshot", "statement_roa", format="percent", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percentage_points"),
    _m("operating_cash_flow_margin_pct", "Operating cash-flow margin", "cash_flow", "%", "financial_statement_snapshot", "statement_ocf_margin", format="percent", supports_history=True, freshness_days=550, comparison_strategy="percentage_points"),
    _m("fcf_positive_years", "Positive FCF years", "cash_flow", "years", "financial_statement_snapshot", "statement_fcf_positive_years", direction="higher_better", supports_history=True, freshness_days=550),
    _m("current_ratio", "Current ratio", "balance_sheet", "multiple", "financial_statement_snapshot", "statement_current_ratio", direction="neutral", supports_history=True, freshness_days=550, cross_industry_comparable=False),
    _m("debt_to_equity", "Debt/Equity", "balance_sheet", "multiple", "financial_statement_snapshot", "statement_debt_equity", direction="lower_better", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percent"),
    _m("net_debt_to_ebitda", "Net debt/EBITDA", "balance_sheet", "multiple", "financial_statement_snapshot", "statement_net_debt_ebitda", direction="lower_better", supports_history=True, freshness_days=550, cross_industry_comparable=False, comparison_strategy="percent"),
    _m("altman_z", "Altman Z", "balance_sheet", "score", "valuation_snapshot", "payload_altman", direction="higher_better", supports_history=False, freshness_days=45, cross_industry_comparable=False),
    _m("piotroski_score", "Piotroski F-score", "balance_sheet", "score", "valuation_snapshot", "payload_piotroski", direction="higher_better", supports_history=False, freshness_days=45, cross_industry_comparable=False),
    _m("relative_volume_20d", "Relative volume", "technical", "multiple", "price_snapshot", "relative_volume", direction="neutral", sortable=False, supports_history=False, freshness_days=7),
    _m("momentum_90d_pct", "90D momentum", "technical", "%", "historical_price", "return_3m", format="percent", freshness_days=14, comparison_strategy="percentage_points"),
)

METRICS_BY_KEY = {item.key: item for item in METRIC_REGISTRY}
def get_metric_registry() -> list[dict[str, Any]]:
    return [item.as_dict() for item in METRIC_REGISTRY]


def metric_catalog() -> dict[str, Any]:
    return {
        "metrics": get_metric_registry(),
        "categories": [CATEGORY_LABELS.get(key, key) for key in dict.fromkeys(item.category for item in METRIC_REGISTRY)],
    }


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        value = str(raw or "").strip().upper()
        if not value or len(value) > 32 or not value.replace("-", "").replace(".", "").isalnum():
            raise ValueError("股票代码格式无效")
        if value not in seen:
            result.append(value)
            seen.add(value)
    if not 2 <= len(result) <= 6:
        raise ValueError("比较需要 2 至 6 个不同股票代码")
    return result


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _key(value: Any) -> str:
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)[:32] if value is not None else None


def _age_days(value: Any) -> int | None:
    item = _date(value)
    return (date.today() - item).days if item else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "total revenue", "operating revenue", "totalrevenue", "operatingrevenue"),
    "gross_profit": ("gross profit", "grossprofit"),
    "operating_income": ("operating income", "ebit", "operatingincome"),
    "net_income": ("net income", "net income common stockholders", "netincome", "netincomecommonstockholders"),
    "eps": ("eps", "diluted eps", "dilutedeps", "diluted eps common stockholders"),
    "ebitda": ("ebitda", "normalized ebitda"),
    "tax_expense": ("tax provision", "income tax expense", "taxexpense", "taxprovision"),
    "pretax_income": ("pretax income", "income before tax", "pretaxincome", "incomebeforetax"),
    "total_assets": ("total assets", "totalassets"),
    "current_assets": ("current assets", "total current assets", "currentassets", "totalcurrentassets"),
    "current_liabilities": ("current liabilities", "total current liabilities", "currentliabilities", "totalcurrentliabilities"),
    "total_liabilities": ("total liabilities", "total liabilities net minority interest", "totalliabilities", "totalliabilitiesnetminorityinterest"),
    "stockholders_equity": ("stockholders equity", "common stock equity", "stockholdersequity", "commonstockequity"),
    "cash": ("cash", "cash and cash equivalents", "cash cash equivalents and short term investments", "cashandequivalents", "cashcashequivalentsandshortterminvestments"),
    "total_debt": ("total debt", "totaldebt"),
    "long_term_debt": ("long term debt", "longtermdebt", "long term debt and capital lease obligation"),
    "shares_issued": ("ordinary shares number", "share issued", "shares issued", "ordinarysharesnumber", "shareissued", "sharesissued"),
    "operating_cash_flow": ("operating cash flow", "total cash from operating activities", "operatingcashflow", "totalcashfromoperatingactivities"),
    "capital_expenditure": ("capital expenditure", "capital expenditures", "capitalexpenditure", "capitalexpenditures"),
    "free_cash_flow": ("free cash flow", "freecashflow"),
}
_ALIASES = {field: tuple(_key(value) for value in aliases) for field, aliases in _ALIASES.items()}


def _statement_values(row: FinancialStatementSnapshot) -> dict[str, float | None]:
    merged: dict[str, Any] = {}
    for component in (row.income_statement, row.balance_sheet, row.cash_flow):
        if not isinstance(component, dict):
            continue
        for raw_key, value in component.items():
            merged.setdefault(_key(raw_key), value)
    result: dict[str, float | None] = {}
    for field, aliases in _ALIASES.items():
        result[field] = next((_number(merged.get(alias)) for alias in aliases if _number(merged.get(alias)) is not None), None)
    if result.get("free_cash_flow") is None and result.get("operating_cash_flow") is not None and result.get("capital_expenditure") is not None:
        capex = result["capital_expenditure"]
        result["free_cash_flow"] = result["operating_cash_flow"] + capex if capex < 0 else result["operating_cash_flow"] - capex
    return result


def _payload_metric(payload: dict[str, Any], key: str) -> float | None:
    aliases = {key, key.removesuffix("_pct"), key.replace("_pct", ""), key.replace("_yield_pct", "_yield")}
    groups: list[Any] = [payload.get("valuation"), payload.get("growth"), payload.get("health")]
    for group in groups:
        if isinstance(group, list):
            for item in group:
                if not isinstance(item, dict) or str(item.get("key")) not in aliases:
                    continue
                value = _number(item.get("value"))
                if value is not None:
                    return value
    direct = payload.get(key)
    if direct is None:
        for alias in aliases:
            direct = payload.get(alias)
            if direct is not None:
                break
    if isinstance(direct, dict):
        direct = direct.get("value")
    return _number(direct)


def _context(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    rows = {symbol: {"symbol": symbol, "security": None, "stock_profile": None, "company_profile": None, "price": None, "history": [], "statements": [], "valuations": []} for symbol in symbols}
    security_filters = [column.in_(symbols) for column in (
        Security.display_symbol, Security.local_symbol, Security.yahoo_symbol, Security.finnhub_symbol,
    )]
    for row in db.scalars(select(Security).where(or_(*security_filters))).all():
        keys = {str(getattr(row, name, "") or "").upper() for name in ("display_symbol", "local_symbol", "yahoo_symbol", "finnhub_symbol")}
        for symbol in symbols:
            if symbol in keys and rows[symbol]["security"] is None:
                rows[symbol]["security"] = row
    for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all():
        rows[row.ticker.upper()]["stock_profile"] = row
    for row in db.scalars(select(CompanyProfile).where(CompanyProfile.symbol.in_(symbols))).all():
        rows[row.symbol.upper()]["company_profile"] = row
    prices = db.scalars(select(PriceSnapshot).where(PriceSnapshot.symbol.in_(symbols))).all()
    for row in prices:
        symbol = row.symbol.upper()
        if symbol not in rows:
            continue
        current = rows[symbol]["price"]
        if current is None or tuple(_iso(getattr(row, field, None)) or "" for field in ("market_timestamp", "fetched_at", "persisted_at")) > tuple(_iso(getattr(current, field, None)) or "" for field in ("market_timestamp", "fetched_at", "persisted_at")):
            rows[symbol]["price"] = row
    histories = db.scalars(select(HistoricalPrice).where(HistoricalPrice.symbol.in_(symbols))).all()
    by_symbol: dict[str, list[HistoricalPrice]] = {}
    for row in histories:
        by_symbol.setdefault(row.symbol.upper(), []).append(row)
    for symbol, values in by_symbol.items():
        preferred = "fmp" if any(str(item.source).lower() == "fmp" for item in values) else "yahoo"
        rows[symbol]["history"] = sorted((item for item in values if str(item.source).lower() == preferred), key=lambda item: item.date)
    statements = db.scalars(select(FinancialStatementSnapshot).where(FinancialStatementSnapshot.ticker.in_(symbols), FinancialStatementSnapshot.frequency == "annual")).all()
    for row in statements:
        rows[row.ticker.upper()]["statements"].append(row)
    for symbol in symbols:
        rows[symbol]["statements"].sort(key=lambda item: item.period_end, reverse=True)
    valuations = db.scalars(select(ValuationSnapshot).where(ValuationSnapshot.ticker.in_(symbols)).order_by(ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc())).all()
    for row in valuations:
        rows[row.ticker.upper()]["valuations"].append(row)
    return rows


def _industry(ctx: dict[str, Any]) -> str | None:
    profile, company = ctx.get("stock_profile"), ctx.get("company_profile")
    return (getattr(profile, "official_industry", None) or getattr(company, "industry", None) or getattr(profile, "official_sector", None) or getattr(company, "sector", None) or None)


def _price_value(ctx: dict[str, Any]) -> tuple[float | None, str | None, Any, str | None]:
    row = ctx.get("price")
    return ((_number(row.last_price), f"price_snapshot:{row.provider or 'unknown'}", row.market_timestamp or row.trading_date or row.fetched_at, "latest") if row else (None, None, None, None))


def _history_closes(ctx: dict[str, Any]) -> list[tuple[date, float]]:
    return [(item.date, value) for item in ctx.get("history", []) if (value := _number(item.close)) is not None and value > 0]


def _return(closes: list[tuple[date, float]], days: int) -> float | None:
    if len(closes) < 2:
        return None
    end_date, end = closes[-1]
    prior = [item for item in closes[:-1] if (end_date - item[0]).days >= days]
    if not prior:
        return None
    start = prior[-1][1]
    return (end / start - 1) * 100 if start else None


def _statement_periods(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for row in ctx.get("statements", []):
        result.append({"date": row.period_end, "fiscal_year": row.fiscal_year, "fiscal_period": row.fiscal_period, **_statement_values(row)})
    return result


def _statement_metric(periods: list[dict[str, Any]], adapter: str) -> float | None:
    if not periods:
        return None
    now, prev = periods[0], periods[1] if len(periods) > 1 else {}
    revenue, net_income = now.get("revenue"), now.get("net_income")
    def ratio(a: Any, b: Any) -> float | None:
        return a / b if _number(a) is not None and _number(b) not in (None, 0) else None
    if adapter == "statement_revenue_growth":
        value = ratio(revenue, prev.get("revenue")); return (value - 1) * 100 if value is not None else None
    if adapter == "statement_eps_growth":
        value = ratio(now.get("eps"), prev.get("eps")); return (value - 1) * 100 if value is not None else None
    if adapter == "statement_revenue_cagr":
        if len(periods) < 4 or _number(revenue) is None or _number(periods[3].get("revenue")) is None or revenue <= 0 or periods[3]["revenue"] <= 0: return None
        return ((revenue / periods[3]["revenue"]) ** .3333333333333333 - 1) * 100
    if adapter == "statement_gross_margin": return (ratio(now.get("gross_profit"), revenue) or 0) * 100 if ratio(now.get("gross_profit"), revenue) is not None else None
    if adapter == "statement_operating_margin": return (ratio(now.get("operating_income"), revenue) or 0) * 100 if ratio(now.get("operating_income"), revenue) is not None else None
    if adapter == "statement_net_margin": return (ratio(net_income, revenue) or 0) * 100 if ratio(net_income, revenue) is not None else None
    fcf = now.get("free_cash_flow")
    if adapter == "statement_fcf_margin": return (ratio(fcf, revenue) or 0) * 100 if ratio(fcf, revenue) is not None else None
    if adapter == "statement_roe":
        equity = now.get("stockholders_equity"); previous_equity = prev.get("stockholders_equity")
        average_equity = (equity + previous_equity) / 2 if equity is not None and previous_equity is not None else equity
        return (ratio(net_income, average_equity) or 0) * 100 if ratio(net_income, average_equity) is not None else None
    if adapter == "statement_roa": return (ratio(net_income, now.get("total_assets")) or 0) * 100 if ratio(net_income, now.get("total_assets")) is not None else None
    if adapter == "statement_roic":
        debt, equity, cash, operating = (now.get(name) for name in ("total_debt", "stockholders_equity", "cash", "operating_income"))
        if any(value is None for value in (debt, equity, cash, operating)):
            return None
        invested = debt + equity - cash
        tax_rate = ratio(now.get("tax_expense"), now.get("pretax_income"))
        tax_rate = min(max(tax_rate, 0), .35) if tax_rate is not None else .21
        return operating * (1 - tax_rate) / invested * 100 if operating is not None and invested > 0 else None
    if adapter == "statement_ocf_margin": return (ratio(now.get("operating_cash_flow"), revenue) or 0) * 100 if ratio(now.get("operating_cash_flow"), revenue) is not None else None
    if adapter == "statement_fcf_positive_years":
        values = [_number(item.get("free_cash_flow")) for item in periods]
        values = [value for value in values if value is not None]
        return float(sum(value > 0 for value in values)) if values else None
    if adapter == "statement_current_ratio": return ratio(now.get("current_assets"), now.get("current_liabilities"))
    if adapter == "statement_debt_equity": return ratio(now.get("total_debt"), now.get("stockholders_equity"))
    if adapter == "statement_net_debt_ebitda":
        return ratio((now.get("total_debt") or 0) - (now.get("cash") or 0), now.get("ebitda"))
    if adapter == "statement_rule40":
        growth = _statement_metric(periods, "statement_revenue_growth"); margin = _statement_metric(periods, "statement_fcf_margin")
        return growth + margin if growth is not None and margin is not None else None
    return None


def _valuation_value(ctx: dict[str, Any], adapter: str) -> tuple[float | None, Any, str | None]:
    row = ctx.get("valuations", [None])[0] if ctx.get("valuations") else None
    if not row:
        return None, None, None
    payload = _dict(row.payload)
    key = adapter.removeprefix("payload_")
    if key == "consensus_upside":
        consensus, current = _dict(payload.get("consensus")), _number(_dict(payload.get("consensus")).get("current"))
        value = _number(consensus.get("value")); value = (value / current - 1) * 100 if value is not None and current else None
    elif key == "consensus_fair_value":
        value = _number(_dict(payload.get("consensus")).get("value"))
    elif key == "dcf_upside":
        dcf = _dict(payload.get("dcf_scenarios")); current = _number(dcf.get("current")); base = _number(dcf.get("base")); value = (base / current - 1) * 100 if base is not None and current else None
    elif key == "dcf_base_value":
        value = _number(_dict(payload.get("dcf_scenarios")).get("base"))
    elif key == "model_agreement":
        verdicts = [str(item.get("verdict")) for item in payload.get("model_signals", []) if isinstance(item, dict) and _number(item.get("stars"))]
        value = max((verdicts.count(verdict) for verdict in set(verdicts)), default=0) / len(verdicts) * 100 if verdicts else None
    elif key == "fcf_yield":
        value = _payload_metric(payload, "fcf_yield_pct")
    elif key == "altman":
        value = _payload_metric(payload, "altman_z")
    elif key == "piotroski":
        value = _payload_metric(payload, "piotroski")
    else:
        value = _payload_metric(payload, key)
    return value, row.snapshot_date, "valuation_snapshot:" + str(row.source_version or "cross-model")


def _metric_value(ctx: dict[str, Any], definition: MetricDefinition) -> tuple[float | None, str | None, Any, str | None, str | None]:
    adapter = definition.adapter
    if adapter == "price":
        value, source, as_of, period = _price_value(ctx); return value, source, as_of, period, None
    if adapter == "day_change_pct":
        row = ctx.get("price")
        if not row: return None, None, None, None, None
        value = _number(row.price_change_percent)
        if value is None and row.previous_close and row.last_price is not None: value = (row.last_price / row.previous_close - 1) * 100
        return value, f"price_snapshot:{row.provider or 'unknown'}", row.market_timestamp or row.trading_date or row.fetched_at, "latest", None
    if adapter == "relative_volume":
        row = ctx.get("price"); return ((_number(row.relative_volume_20d), f"price_snapshot:{row.provider or 'unknown'}", row.market_timestamp or row.trading_date or row.fetched_at, "latest", None) if row else (None, None, None, None, None))
    if adapter.startswith("return_") or adapter in {"volatility_90d", "distance_52w_high"}:
        closes = _history_closes(ctx); value = None
        if adapter.startswith("return_"):
            value = _return(closes, {"return_1m": 30, "return_3m": 90, "return_6m": 180, "return_1y": 365}.get(adapter, 90))
        elif adapter == "distance_52w_high" and closes:
            high = max(value for _, value in closes[-252:]); value = (closes[-1][1] / high - 1) * 100 if high else None
        elif adapter == "volatility_90d" and len(closes) >= 3:
            changes = [closes[index][1] / closes[index - 1][1] - 1 for index in range(max(1, len(closes) - 90), len(closes))]
            value = stdev(changes) * sqrt(252) * 100 if len(changes) > 1 else None
        return value, "historical_price:" + str(ctx.get("history", [None])[0].source if ctx.get("history") else ""), closes[-1][0] if closes else None, "daily", None
    if adapter.startswith("payload_"):
        value, as_of, source = _valuation_value(ctx, adapter); return value, source, as_of, _iso(as_of), None
    periods = _statement_periods(ctx); value = _statement_metric(periods, adapter)
    latest_statement = ctx.get("statements", [None])[0] if ctx.get("statements") else None
    period = (f"FY{periods[0].get('fiscal_year')} · {_iso(periods[0].get('date'))}" if periods and periods[0].get("fiscal_year") else (_iso(periods[0].get("date")) if periods else None))
    return value, "financial_statement_snapshot:" + str(latest_statement.source if latest_statement else ""), latest_statement.synced_at if latest_statement else None, period, None


def _unsupported(definition: MetricDefinition, ctx: dict[str, Any]) -> bool:
    text = f"{_industry(ctx) or ''} {getattr(ctx.get('security'), 'instrument_type', '') or ''}".lower()
    return definition.key in {"altman_z", "ev_ebitda", "roic_pct"} and any(token in text for token in ("bank", "insurance", "reit", "etf", "fund"))


def _status(value: float | None, as_of: Any, definition: MetricDefinition, ctx: dict[str, Any], override: str | None = None) -> str:
    if override:
        return override
    if _unsupported(definition, ctx):
        return "unsupported"
    if value is None:
        return "missing"
    age = _age_days(as_of)
    if definition.freshness_days is not None and age is not None and age > definition.freshness_days:
        return "stale"
    return "available"


def _percentile(values: list[float], value: float, direction: str) -> float:
    if len(values) <= 1:
        return 100.0
    ordered = sorted(values)
    positions = [index + 1 for index, item in enumerate(ordered) if isclose(item, value, rel_tol=1e-9, abs_tol=1e-9)]
    result = (mean(positions) - 1) / (len(ordered) - 1) * 100
    return round(100 - result if direction == "lower_better" else result, 2)


def _relative(value: float, middle: float, strategy: str) -> float | None:
    if strategy == "percentage_points":
        return round(value - middle, 6)
    if strategy == "percent":
        return round((value / middle - 1) * 100, 6) if middle else None
    return round(value - middle, 6)


def _rank(values: list[tuple[str, float]], value: float, direction: str) -> int:
    if direction == "lower_better":
        return 1 + sum(item < value for _, item in values)
    return 1 + sum(item > value for _, item in values)


def _trend(points: list[dict[str, Any]], direction: str) -> str:
    values = [_number(item.get("value")) for item in points]
    values = [item for item in values if item is not None]
    if len(values) < 2:
        return "insufficient"
    delta = values[-1] - values[0]
    threshold = max(abs(values[0]) * .05, .01)
    if abs(delta) <= threshold:
        return "stable"
    if direction == "neutral":
        return "rising" if delta > 0 else "falling"
    improving = delta > 0 if direction == "higher_better" else delta < 0
    return "improving" if improving else "deteriorating"


def _price_history(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    points = _history_closes(ctx)
    base = points[0][1] if points else None
    return [{"date": day.isoformat(), "period": None, "value": value, "indexed": round(value / base * 100, 4) if base else None} for day, value in points]


def _statement_history(ctx: dict[str, Any], definition: MetricDefinition) -> list[dict[str, Any]]:
    periods = _statement_periods(ctx)
    if not periods:
        return []
    points = [{"date": _iso(item["date"]), "period": f"FY{item.get('fiscal_year')}" if item.get("fiscal_year") else _iso(item["date"]), "value": _statement_metric(periods[index:], definition.adapter), "indexed": None} for index, item in enumerate(periods)]
    return list(reversed(points))


def _valuation_history(ctx: dict[str, Any], definition: MetricDefinition) -> list[dict[str, Any]]:
    points = []
    for row in reversed(ctx.get("valuations", [])):
        old_ctx = dict(ctx); old_ctx["valuations"] = [row]
        value, _, _, _, _ = _metric_value(old_ctx, definition)
        points.append({"date": _iso(row.snapshot_date), "period": _iso(row.snapshot_date), "value": value, "indexed": None})
    return points


def compare_history(db: Session, symbols: Iterable[str], metric: str) -> dict[str, Any]:
    normalized = normalize_symbols(symbols)
    definition = METRICS_BY_KEY.get(metric)
    if definition is None:
        raise ValueError("未知比较指标")
    if not definition.supports_history:
        raise ValueError("该指标不支持历史序列")
    contexts = _context(db, normalized)
    series = []
    for symbol in normalized:
        ctx = contexts[symbol]
        try:
            if definition.source == "historical_price" or definition.adapter == "price":
                points = _price_history(ctx)
            elif definition.source == "valuation_snapshot":
                points = _valuation_history(ctx, definition)
            else:
                points = _statement_history(ctx, definition)
        except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
            points = []
        points = [item for item in points if item.get("value") is not None]
        series.append({"symbol": symbol, "points": points})
    mode = "indexed" if definition.source == "historical_price" or definition.adapter == "price" else "raw"
    if mode == "indexed":
        starts = [item["points"][0]["date"] for item in series if item["points"]]
        if starts:
            common_start = max(starts)
            for item in series:
                item["points"] = [point for point in item["points"] if point["date"] >= common_start]
                base = item["points"][0]["value"] if item["points"] else None
                for point in item["points"]:
                    point["indexed"] = round(point["value"] / base * 100, 4) if base else None
    return {"metric": definition.as_dict(), "mode": mode, "series": series, "limitations": ["历史序列仅来自已持久化的 FMP/Yahoo/估值快照；不会补抓数据。"]}


def _history_points_for_current(ctx: dict[str, Any], definition: MetricDefinition) -> list[dict[str, Any]]:
    if not definition.supports_history:
        return []
    if definition.source == "historical_price" or definition.adapter == "price":
        return _price_history(ctx)
    if definition.source == "valuation_snapshot":
        return _valuation_history(ctx, definition)
    return _statement_history(ctx, definition)


def compare_symbols(db: Session, symbols: Iterable[str]) -> dict[str, Any]:
    normalized = normalize_symbols(symbols)
    contexts = _context(db, normalized)
    industry_values = [_industry(contexts[symbol]) for symbol in normalized]
    industries = {value for value in industry_values if value}
    cross_industry_uncertain = len(industries) != 1 or any(value is None for value in industry_values)
    metrics = []
    category_counts: dict[str, dict[str, int]] = {}
    strengths: dict[str, list[str]] = {symbol: [] for symbol in normalized}
    weaknesses: dict[str, list[str]] = {symbol: [] for symbol in normalized}
    mixed_period_metrics = []
    category_evidence: dict[str, dict[str, list[dict[str, Any]]]] = {}
    category_tradeoffs: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for definition in METRIC_REGISTRY:
        cells = []
        usable: list[tuple[str, float]] = []
        available_count = 0
        period_values: set[str] = set()
        for symbol in normalized:
            try:
                value, source, as_of, period, override = _metric_value(contexts[symbol], definition)
                status = _status(value, as_of, definition, contexts[symbol], override)
            except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
                value, source, as_of, period, status = None, definition.source, None, None, "calculation_failed"
            if status == "unsupported":
                value = None
            if period:
                period_values.add(str(period))
            cell = {"symbol": symbol, "value": value, "status": status, "source": source, "as_of": _iso(as_of), "period": period, "rank": None, "percentile": None, "relative_to_median": None, "is_best": False, "is_worst": False, "trend": None}
            cells.append(cell)
            if value is not None:
                available_count += 1
            if value is not None and status == "available" and definition.rank_eligible:
                usable.append((symbol, value))
        if len(period_values) > 1:
            mixed_period_metrics.append(definition.key)
        values = [item[1] for item in usable]
        middle = median(values) if values else None
        for cell in cells:
            value = _number(cell["value"])
            if value is None or cell["status"] != "available":
                continue
            if definition.rank_eligible:
                cell["rank"] = _rank(usable, value, definition.direction)
            if definition.percentile_eligible:
                cell["percentile"] = _percentile(values, value, definition.direction)
            if middle is not None:
                cell["relative_to_median"] = _relative(value, middle, definition.comparison_strategy)
        best: list[str] = []
        worst: list[str] = []
        warning = None
        if definition.direction != "neutral" and len(usable) >= 2 and min(values) != max(values):
            best_value = min(values) if definition.direction == "lower_better" else max(values)
            worst_value = max(values) if definition.direction == "lower_better" else min(values)
            best = [symbol for symbol, value in usable if value == best_value]
            worst = [symbol for symbol, value in usable if value == worst_value]
            if not definition.cross_industry_comparable and cross_industry_uncertain:
                warning = "所选股票行业不同或分类缺失，该指标仅展示原始值，不判定最佳/最差。"
                best, worst = [], []
            if best:
                category_counts.setdefault(definition.category, {})
            for symbol in best:
                category_counts[definition.category][symbol] = category_counts[definition.category].get(symbol, 0) + 1
                strengths[symbol].append(definition.key)
                category_evidence.setdefault(definition.category, {}).setdefault(symbol, []).append({"key": definition.key, "label": METRIC_LABELS.get(definition.key, definition.label), "rank": 1})
            for symbol in worst:
                weaknesses[symbol].append(definition.key)
                category_tradeoffs.setdefault(definition.category, {}).setdefault(symbol, []).append({"key": definition.key, "label": METRIC_LABELS.get(definition.key, definition.label), "rank": len(usable)})
        period_mismatch = len(period_values) > 1
        spread = None
        if len(values) > 1 and definition.sortable and definition.direction != "neutral":
            raw_spread = max(values) - min(values)
            spread = raw_spread / 100 if definition.comparison_strategy == "percentage_points" else raw_spread / max(abs(middle or 0), max(abs(value) for value in values) * .1, 1e-9)
        is_differentiator = spread is not None and spread >= .15
        for cell in cells:
            value = _number(cell.get("value"))
            if value is not None and middle is not None:
                kind = {"percentage_points": "percentage_point", "percent": "percent"}.get(definition.comparison_strategy, "absolute")
                relative_value = _relative(value, middle, definition.comparison_strategy)
                cell["relative"] = ({"kind": kind, "value": relative_value, "unit": "%" if kind == "percent" else ("pct" if kind == "percentage_point" else definition.unit)} if relative_value is not None else None)
            else:
                cell["relative"] = None
            if cell["symbol"] in best:
                cell["is_best"] = True
            if cell["symbol"] in worst:
                cell["is_worst"] = True
            try:
                history_points = _history_points_for_current(contexts[cell["symbol"]], definition)
            except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
                history_points = []
            trend = _trend(history_points, definition.direction) if history_points else None
            cell["trend"] = None if trend == "insufficient" else trend
            if value is not None:
                cell["value"] = round(value, 6)
        metrics.append({"definition": definition.as_dict(), "cells": {cell.pop("symbol"): cell for cell in cells}, "available_count": available_count, "dispersion": round(spread, 6) if spread is not None else None, "is_differentiator": is_differentiator, "period_mismatch": period_mismatch, "comparison_warning": warning or ("财报/估值期间不一致，请结合 period 与 as_of 解读。" if period_mismatch else None)})
    category_winners = []
    for category, counts in category_counts.items():
        if not counts:
            continue
        top = max(counts.values())
        winners = sorted(symbol for symbol, count in counts.items() if count == top)
        category_winners.append({"category": CATEGORY_LABELS.get(category, category), "symbol": winners[0] if len(winners) == 1 else None, "ties": winners if len(winners) > 1 else [], "evidence": [item for symbol in winners for item in category_evidence.get(category, {}).get(symbol, [])[:3]], "tradeoffs": [item for symbol in winners for item in category_tradeoffs.get(category, {}).get(symbol, [])[:3]]})
    suggested: list[str] = []
    for symbol in normalized:
        peers = _dict(ctx := contexts[symbol].get("valuations", [None])[0].payload if contexts[symbol].get("valuations") else {}).get("peers", {})
        raw = peers.get("official_symbols") or peers.get("symbols") or []
        for item in raw:
            candidate = str(item).upper()
            if candidate not in normalized and candidate not in suggested:
                suggested.append(candidate)
            if len(suggested) >= 12:
                break
    return {
        "securities": [{"symbol": symbol, "name": getattr(contexts[symbol].get("security"), "display_name", None) or getattr(contexts[symbol].get("stock_profile"), "company_name", None) or getattr(contexts[symbol].get("company_profile"), "company_name", None) or symbol, "sector": getattr(contexts[symbol].get("stock_profile"), "official_sector", None) or getattr(contexts[symbol].get("company_profile"), "sector", None), "industry": _industry(contexts[symbol]), "currency": getattr(contexts[symbol].get("security"), "currency", None) or getattr(contexts[symbol].get("company_profile"), "currency", None), "instrument_type": getattr(contexts[symbol].get("security"), "instrument_type", None)} for symbol in normalized],
        "metrics": metrics,
        "categories": list(dict.fromkeys(CATEGORY_LABELS.get(definition.category, definition.category) for definition in METRIC_REGISTRY)),
        "highlights": [{"symbol": symbol, "strengths": [{"key": key, "label": METRIC_LABELS.get(key, METRICS_BY_KEY[key].label)} for key in strengths[symbol][:5]], "weaknesses": [{"key": key, "label": METRIC_LABELS.get(key, METRICS_BY_KEY[key].label)} for key in weaknesses[symbol][:5]]} for symbol in normalized],
        "category_winners": category_winners,
        "suggested_peers": suggested,
        "limitations": ["所有结果只读已持久化的 Security、价格、财报和估值快照；不会调用外部 provider、AI 或任务队列。", "percentile 只表示本次比较集合内的位置，不是行业或市场百分位。", "缺失和过期数据保留在单元格中，不会被填充或伪装成零。"] + (["部分指标的财报/估值期间不同，横向比较请结合 period/as_of。"] if mixed_period_metrics else []) + (["所选股票行业不同或分类缺失，行业不可比指标已抑制最佳/最差判定。"] if cross_industry_uncertain else []),
        "generated_at": datetime.now(UTC).isoformat(),
    }


# Small smoke check for the non-DB math used by callers/tests.
if __name__ == "__main__":  # pragma: no cover
    assert _relative(20, 10, "percentage_points") == 10
    assert _relative(20, 10, "percent") == 100
