"""可解释的多模型交叉估值。

边界：Yahoo 提供分类和原始财务数据；Finnhub 提供同行关系；本模块只做确定性计算；
Luna 仅消费本模块生成的证据并解释结论，不参与任何数值计算。
"""
from __future__ import annotations

import logging
from math import pow
from statistics import median
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

FIELD_ALIASES = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "EBIT"],
    "pretax_income": ["Pretax Income", "Income Before Tax"],
    "tax_expense": ["Tax Provision", "Income Tax Expense"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
    "diluted_eps": ["Diluted EPS", "DilutedEPS"],
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "stockholders_equity": ["Stockholders Equity", "Common Stock Equity"],
    "retained_earnings": ["Retained Earnings"],
    "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"],
    "total_debt": ["Total Debt"],
    "long_term_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "operating_cash_flow": ["Operating Cash Flow", "Total Cash From Operating Activities"],
    "shares_issued": ["Ordinary Shares Number", "Share Issued"],
}

INCOME_FIELDS = {"revenue", "gross_profit", "operating_income", "pretax_income", "tax_expense", "net_income", "diluted_eps"}
BALANCE_FIELDS = set(FIELD_ALIASES) - INCOME_FIELDS - {"operating_cash_flow"}
CASHFLOW_FIELDS = {"operating_cash_flow"}


BASE_SCORES = {
    "forward_pe": 20, "peg": 15, "ev_sales": 10, "ev_ebitda": 15,
    "dcf": 20, "fcf_yield": 10, "price_to_book": 5, "rule_of_40": 5,
}

# adjustment 是满置信度分数；实际应用分 = adjustment × tag confidence。
TAG_ADJUSTMENTS = {
    "software": {"forward_pe": 5, "peg": 5, "ev_sales": 8, "rule_of_40": 8},
    "semiconductor": {"forward_pe": 8, "peg": 7, "dcf": 5, "ev_ebitda": 3},
    "bank": {"price_to_book": 25, "forward_pe": -5, "ev_sales": -10},
    "saas": {"ev_sales": 20, "rule_of_40": 25, "forward_pe": 5, "ev_ebitda": -10, "price_to_book": -20},
    "subscription": {"dcf": 10, "ev_sales": 5},
    "high_growth": {"peg": 15, "ev_sales": 10, "forward_pe": -5},
    "high_gross_margin": {"ev_sales": 3, "dcf": 3, "rule_of_40": 3},
    "profitable": {"forward_pe": 2, "peg": 2, "dcf": 2},
    "asset_light": {"dcf": 10, "fcf_yield": 10, "price_to_book": -15},
    "high_leverage": {"dcf": -5, "ev_ebitda": 10, "price_to_book": -5},
    "stable_fcf": {"dcf": 20, "fcf_yield": 15},
    "volatile_fcf": {"dcf": -20},
    "unprofitable": {"forward_pe": -100, "peg": -100, "ev_ebitda": -30, "ev_sales": 25},
}

TAG_LABELS = {
    "software": "Software（软件）", "semiconductor": "Semiconductor（半导体）", "bank": "Bank（银行）",
    "saas": "SaaS（软件即服务）", "subscription": "Subscription（订阅模式）",
    "high_growth": "High Growth（高增长）", "moderate_growth": "Moderate Growth（中等增长）",
    "low_growth": "Low Growth（低增长）", "high_gross_margin": "High Gross Margin（高毛利）",
    "profitable": "Profitable（已盈利）", "unprofitable": "Unprofitable（未盈利）",
    "asset_light": "Asset Light（轻资产）", "high_leverage": "High Leverage（高杠杆）",
    "stable_fcf": "Stable FCF（稳定自由现金流）", "volatile_fcf": "Volatile FCF（波动自由现金流）",
}

INDUSTRY_PROFILES = {
    "semiconductor": {"label": "Semiconductor / AI（半导体 / AI）", "primary": ["forward_pe", "peg", "dcf"], "secondary": ["ev_ebitda"], "focus": "Revenue Growth（收入增长）、R&D（研发投入）、FCF（自由现金流）"},
    "software": {"label": "Software / SaaS（软件 / SaaS）", "primary": ["ev_sales", "rule_of_40"], "secondary": ["dcf"], "focus": "ARR（年度经常性收入）、Gross Margin（毛利率）、FCF Margin（自由现金流利润率）"},
    "bank": {"label": "Bank（银行）", "primary": ["price_to_book"], "secondary": ["roe"], "focus": "NPL（不良贷款率）、Capital Ratio（资本充足率）、Dividend（股息）"},
    "insurance": {"label": "Insurance（保险）", "primary": ["price_to_book"], "secondary": ["roe"], "focus": "Combined Ratio（综合成本率）、承保利润"},
    "consumer": {"label": "Consumer（消费）", "primary": ["forward_pe", "dcf"], "secondary": ["roic"], "focus": "品牌力、Margin（利润率）、ROIC（投入资本回报率）"},
    "oil": {"label": "Energy（能源）", "primary": ["ev_ebitda"], "secondary": ["fcf_yield"], "focus": "Commodity Cycle（商品周期）、Capex（资本开支）、FCF"},
    "reit": {"label": "REIT（房地产信托）", "primary": [], "secondary": [], "focus": "AFFO Growth、Occupancy（出租率）、Dividend（股息）"},
    "general": {"label": "General（综合）", "primary": ["forward_pe", "dcf"], "secondary": ["peg", "ev_ebitda", "fcf_yield"], "focus": "Earnings Growth（盈利增长）、Cash Flow（现金流）、Capital Return（资本回报）"},
}

MODEL_NAMES = {
    "forward_pe": "Forward P/E（预期市盈率）", "peg": "PEG（市盈增长比）", "ev_sales": "EV/Sales（企业价值营收比）",
    "ev_ebitda": "EV/EBITDA（企业价值息税折旧前利润比）", "dcf": "DCF（现金流折现）",
    "fcf_yield": "FCF Yield（自由现金流收益率）", "price_to_book": "P/B（市净率）",
    "rule_of_40": "Rule of 40（40法则）", "roe": "ROE（净资产收益率）", "roic": "ROIC（投入资本回报率）",
    "current_ratio": "Current Ratio（流动比率）", "piotroski": "Piotroski F-Score（皮奥特罗斯基评分）",
    "altman_z": "Altman Z-Score（奥特曼Z值）", "net_debt": "Net Debt（净负债）",
    "revenue_growth": "Revenue Growth（营收增长率）", "eps_growth": "EPS Growth（每股盈利增长率）",
}

MODEL_GUIDE = {
    "forward_pe": ("Price ÷ Forward EPS（股价 ÷ 未来12个月每股盈利）", "没有通用安全区间；成熟公司常见 15–25×，成长公司应优先与同行中位数比较。", "衡量市场为未来盈利支付多少倍价格。高增长公司可以更高，但必须由增长和现金流支撑。"),
    "peg": ("Forward P/E ÷ Expected EPS Growth %", "经验参考 0.8–1.5；低于 1 可能较便宜，高于 2 需更强增长质量支撑。", "把估值倍数和盈利增速放在一起看。增长预测不稳定时，PEG 也会很不稳定。"),
    "ev_sales": ("Enterprise Value ÷ TTM Revenue", "成熟公司常见 1–5×；高毛利 SaaS 可更高，应结合 Rule of 40 和同行。", "适合利润尚不稳定但收入有意义的公司，不能忽略毛利率和未来利润空间。"),
    "ev_ebitda": ("Enterprise Value ÷ EBITDA", "成熟非金融企业常见约 8–15×；周期行业必须跨周期比较。", "消除资本结构与折旧政策的部分差异，金融公司通常不适用。"),
    "dcf": ("Present Value of Future FCF（未来自由现金流现值）", "不存在固定推荐区间；重点看 Bear/Base/Bull 与现价的距离和敏感性。", "DCF 对增长率、折现率和永续增长率非常敏感，因此情景区间比单一数字更重要。"),
    "fcf_yield": ("TTM Free Cash Flow ÷ Market Cap", "成熟公司 3%–6% 常具参考意义；越高不一定越好，需排除周期峰值和一次性现金流。", "表示每一元市值对应多少自由现金流。"),
    "price_to_book": ("Price ÷ Book Value Per Share", "银行常结合同行比较，约 1–2×较常见；非金融企业适用性较弱。", "衡量市场价格相对账面净资产的倍数。"),
    "rule_of_40": ("Revenue Growth % + FCF Margin %", "≥40% 通常视为优秀，30%–40% 尚可，低于 30% 需要解释。", "SaaS 常用指标，用来平衡增长速度和现金流质量。"),
    "roe": ("Net Income ÷ Average Equity", "持续高于 15% 通常较强，但高杠杆也会人为抬高 ROE。", "衡量股东资本的盈利效率。"),
    "roic": ("NOPAT ÷ Invested Capital", "长期高于资本成本且超过 10%–15%通常较好。", "衡量经营资产创造回报的能力；缺少投入资本口径时不应拿 ROA 替代。"),
    "current_ratio": ("Current Assets ÷ Current Liabilities", "一般 1.5–3.0 较稳健；行业差异很大，过高也可能意味着资金效率低。", "衡量短期偿债能力。"),
    "piotroski": ("9 binary accounting signals（九项财务信号加总）", "7–9 较强，4–6 中性，0–3 较弱。", "综合盈利、杠杆、流动性和经营效率；需要完整历史财报。"),
    "altman_z": ("1.2A + 1.4B + 3.3C + 0.6D + 1.0E", ">3 通常较安全，1.8–3 灰色区，<1.8 风险较高；金融公司不适用。", "经典破产风险筛查模型。"),
    "net_debt": ("Total Debt − Cash", "负数代表净现金；正数需结合 EBITDA 和现金流偿债能力。", "公司债务扣除可用现金后的净额。"),
    "revenue_growth": ("(Current Revenue ÷ Prior Revenue) − 1", "成长公司通常希望 >15%；必须结合行业成熟度与利润质量。", "当前使用 Yahoo 的同比营收增长率，不冒充严格三年 CAGR。"),
    "eps_growth": ("(Current EPS ÷ Prior EPS) − 1", ">15%通常属于较高增长，但分析师预测可能快速变化。", "当前使用 Yahoo 盈利增长数据，作为预期增长参考。"),
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> float | None:
    value = _number(value)
    if value is None:
        return None
    return value * 100 if abs(value) <= 1.5 else value


def derive_classification_tags(info: dict[str, Any]) -> dict[str, float]:
    tags: dict[str, float] = {}
    sector, industry = info.get("sectorKey"), info.get("industryKey")
    if sector: tags[f"sector:{sector}"] = 1.0
    if industry: tags[f"industry:{industry}"] = 1.0
    mapping = {
        "software-application": {"software": .95, "application_software": .90},
        "software-infrastructure": {"software": .95, "infrastructure_software": .90},
        "semiconductors": {"semiconductor": .95}, "banks-regional": {"bank": .95},
        "banks-diversified": {"bank": .95}, "insurance-diversified": {"insurance": .95},
        "reit-specialty": {"reit": .90},
    }
    tags.update(mapping.get(industry, {}))
    return tags


def derive_financial_tags(m: dict[str, Any]) -> dict[str, float]:
    tags: dict[str, float] = {}
    growth, margin = _pct(m.get("revenue_growth")), _pct(m.get("gross_margin"))
    if growth is not None: tags["high_growth" if growth >= 15 else "moderate_growth" if growth >= 10 else "low_growth"] = 1.0
    if margin is not None and margin >= 70: tags["high_gross_margin"] = 1.0
    income = _number(m.get("net_income"))
    if income is not None: tags["profitable" if income > 0 else "unprofitable"] = 1.0
    debt_ebitda = _number(m.get("net_debt_to_ebitda"))
    if debt_ebitda is not None and debt_ebitda >= 3: tags["high_leverage"] = 1.0
    if m.get("fcf_positive_periods", 0) >= 4: tags["stable_fcf"] = .70
    return tags


def derive_business_model_tags(info: dict[str, Any], metrics: dict[str, Any]) -> dict[str, float]:
    text = (info.get("longBusinessSummary") or "").lower()
    saas = .15 if info.get("industryKey") in {"software-application", "software-infrastructure"} else 0
    for word, score in {"software as a service": .60, "saas": .50, "subscription-based": .40, "subscription services": .35, "recurring revenue": .30, "cloud-based platform": .25}.items():
        if word in text: saas += score
    if (_pct(metrics.get("gross_margin")) or 0) >= 70: saas += .10
    saas = min(saas, 1.0)
    return {"saas": saas, "subscription": min(saas, .8)} if saas >= .5 else {}


def calculate_model_weight_details(tags: dict[str, float]) -> tuple[dict[str, float], list[dict]]:
    scores = {key: float(value) for key, value in BASE_SCORES.items()}
    evidence = {key: [] for key in scores}
    for tag, confidence in tags.items():
        for model, raw in TAG_ADJUSTMENTS.get(tag, {}).items():
            applied = round(raw * confidence, 2)
            scores[model] = scores.get(model, 0) + applied
            evidence.setdefault(model, []).append({"tag": tag, "label": TAG_LABELS.get(tag, tag.replace("_", " ").title()), "confidence": round(confidence, 2), "raw_adjustment": raw, "applied_adjustment": applied})
    scores = {model: max(score, 0) for model, score in scores.items()}
    total = sum(scores.values())
    weights = {model: round(score / total, 4) for model, score in scores.items()} if total else {}
    if weights:
        # 各项四舍五入后仍保证总权重严格为 1，避免快照出现 100.01%。
        last_positive = next((model for model in reversed(weights) if weights[model] > 0), None)
        if last_positive:
            weights[last_positive] = round(weights[last_positive] + 1 - sum(weights.values()), 4)
    details = [{"key": model, "label": MODEL_NAMES.get(model, model), "base_score": BASE_SCORES.get(model, 0), "adjustments": evidence.get(model, []), "final_score": round(score, 2), "weight": weights.get(model, 0)} for model, score in scores.items()]
    return weights, details


def calculate_model_weights(tags: dict[str, float]) -> dict[str, float]:
    return calculate_model_weight_details(tags)[0]


def industry_profile(info: dict[str, Any], tags: dict[str, float]) -> str:
    text = f"{(info.get('industryKey') or '').lower()} {(info.get('industry') or '').lower()}"
    if "semiconductor" in text: return "semiconductor"
    if "bank" in text: return "bank"
    if "insurance" in text: return "insurance"
    if "reit" in text: return "reit"
    if any(x in text for x in ("oil", "energy", "oil-gas")): return "oil"
    if "software" in text or tags.get("saas", 0) >= .5: return "software"
    if any(x in text for x in ("consumer", "retail", "beverage", "restaurant")): return "consumer"
    return "general"


def _column_date(column: Any) -> str:
    """将 pandas Timestamp/datetime/字符串统一成可排序的财报日期。"""
    try:
        return column.date().isoformat()
    except AttributeError:
        return str(column)[:10]


def _canonical_label(value: Any) -> str:
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _statement_values(statement: Any, fields: set[str]) -> dict[str, dict[str, float]]:
    if statement is None or getattr(statement, "empty", True):
        return {}
    result: dict[str, dict[str, float]] = {}
    # yfinance 0.2.x 实际索引通常是 CamelCase，文档/旧版本也可能是带空格名称。
    rows = {_canonical_label(row): row for row in statement.index}
    for column in statement.columns:
        period = result.setdefault(_column_date(column), {})
        for field in fields:
            for alias in FIELD_ALIASES[field]:
                row = rows.get(_canonical_label(alias))
                if row is None:
                    continue
                raw = statement.loc[row, column]
                # Yahoo 偶尔返回重复行；只取第一个有效值。
                if hasattr(raw, "iloc"):
                    raw = next((_number(value) for value in raw if _number(value) is not None), None)
                value = _number(raw)
                if value is not None:
                    period[field] = value
                    break
    return result


def normalize_financial_statements(income: Any, balance: Any, cashflow: Any) -> dict[str, Any]:
    """按财报日合并 Yahoo 年度三表，同时保留字段来源和缺口。"""
    merged: dict[str, dict[str, float]] = {}
    for statement, fields in ((income, INCOME_FIELDS), (balance, BALANCE_FIELDS), (cashflow, CASHFLOW_FIELDS)):
        for period, values in _statement_values(statement, fields).items():
            merged.setdefault(period, {}).update(values)
    periods = [{"date": period, **merged[period]} for period in sorted(merged, reverse=True)]
    return {"source": "yfinance_annual", "periods": periods}


def effective_tax_rate(tax_expense: float | None, pretax_income: float | None) -> tuple[float, bool]:
    if tax_expense is None or pretax_income is None or pretax_income <= 0:
        return .21, True
    return min(max(tax_expense / pretax_income, 0), .35), False


def _missing(period: dict[str, Any] | None, fields: list[str], suffix: str = "") -> list[str]:
    return [f"{field}{suffix}" for field in fields if period is None or _number(period.get(field)) is None]


def calculate_roic_metric(financials: dict[str, Any]) -> dict[str, Any]:
    periods = financials.get("periods") or []
    now = periods[0] if periods else None
    prev = periods[1] if len(periods) > 1 else None
    required = ["operating_income", "total_debt", "stockholders_equity", "cash"]
    missing = _missing(now, required)
    if missing:
        return {"value": None, "status": "insufficient", "missing_fields": missing, "inputs": {}, "warnings": []}
    tax_rate, used_default = effective_tax_rate(
        _number(now.get("tax_expense")), _number(now.get("pretax_income"))
    )
    invested_now = now["total_debt"] + now["stockholders_equity"] - now["cash"]
    previous_fields = ["total_debt", "stockholders_equity", "cash"]
    previous_missing = _missing(prev, previous_fields, "_previous")
    if previous_missing:
        invested_capital = invested_now
    else:
        invested_prev = prev["total_debt"] + prev["stockholders_equity"] - prev["cash"]
        invested_capital = (invested_now + invested_prev) / 2
    warnings = []
    if used_default:
        warnings.append("税前利润或所得税费用不可用，采用美国联邦默认税率 21%。")
    if previous_missing:
        warnings.append("上一年度投入资本字段不完整，使用期末投入资本而非两年平均值。")
    if invested_capital <= 0:
        return {"value": None, "status": "insufficient", "missing_fields": ["positive_invested_capital"],
                "inputs": {"invested_capital": invested_capital}, "warnings": warnings}
    nopat = now["operating_income"] * (1 - tax_rate)
    return {
        "value": nopat / invested_capital * 100,
        "status": "available",
        "missing_fields": [],
        "formula_version": "nopat_average_invested_capital_v1" if not previous_missing else "nopat_ending_invested_capital_v1",
        "inputs": {"period": now.get("date"), "operating_income": now["operating_income"], "tax_rate": tax_rate,
                   "nopat": nopat, "invested_capital": invested_capital},
        "warnings": warnings,
    }


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return numerator / denominator if numerator is not None and denominator not in (None, 0) else None


def calculate_piotroski_metric(financials: dict[str, Any]) -> dict[str, Any]:
    periods = financials.get("periods") or []
    now = periods[0] if periods else {}
    prev = periods[1] if len(periods) > 1 else {}
    older = periods[2] if len(periods) > 2 else {}
    warnings: list[str] = []

    assets_now, assets_prev, assets_older = (_number(now.get("total_assets")), _number(prev.get("total_assets")), _number(older.get("total_assets")))
    avg_assets_now = (assets_now + assets_prev) / 2 if assets_now is not None and assets_prev is not None else assets_now
    avg_assets_prev = (assets_prev + assets_older) / 2 if assets_prev is not None and assets_older is not None else assets_prev
    if assets_prev is not None and assets_older is None:
        warnings.append("缺少第三年总资产，上一年度 ROA 和资产周转率采用期末资产简化口径。")
    roa_now = _ratio(_number(now.get("net_income")), avg_assets_now)
    roa_prev = _ratio(_number(prev.get("net_income")), avg_assets_prev)
    leverage_now = _ratio(_number(now.get("long_term_debt")), assets_now)
    leverage_prev = _ratio(_number(prev.get("long_term_debt")), assets_prev)
    current_ratio_now = _ratio(_number(now.get("current_assets")), _number(now.get("current_liabilities")))
    current_ratio_prev = _ratio(_number(prev.get("current_assets")), _number(prev.get("current_liabilities")))
    gross_margin_now = _ratio(_number(now.get("gross_profit")), _number(now.get("revenue")))
    gross_margin_prev = _ratio(_number(prev.get("gross_profit")), _number(prev.get("revenue")))
    turnover_now = _ratio(_number(now.get("revenue")), avg_assets_now)
    turnover_prev = _ratio(_number(prev.get("revenue")), avg_assets_prev)
    cfo_now, income_now = _number(now.get("operating_cash_flow")), _number(now.get("net_income"))
    shares_now, shares_prev = _number(now.get("shares_issued")), _number(prev.get("shares_issued"))

    def compare(left: float | None, right: float | None, op: str = "gt") -> bool | None:
        if left is None or right is None:
            return None
        return left > right if op == "gt" else left < right

    components: dict[str, bool | None] = {
        "positive_roa": None if roa_now is None else roa_now > 0,
        "positive_cfo": None if cfo_now is None else cfo_now > 0,
        "improving_roa": compare(roa_now, roa_prev),
        "cfo_above_net_income": compare(cfo_now, income_now),
        "lower_leverage": compare(leverage_now, leverage_prev, "lt"),
        "higher_current_ratio": compare(current_ratio_now, current_ratio_prev),
        "no_new_shares": None if shares_now is None or shares_prev is None else shares_now <= shares_prev * 1.01,
        "higher_gross_margin": compare(gross_margin_now, gross_margin_prev),
        "higher_asset_turnover": compare(turnover_now, turnover_prev),
    }
    available = sum(value is not None for value in components.values())
    score = sum(value is True for value in components.values())
    missing_components = [name for name, value in components.items() if value is None]
    requirements = {
        "positive_roa": _missing(now, ["net_income", "total_assets"]),
        "positive_cfo": _missing(now, ["operating_cash_flow"]),
        "improving_roa": _missing(now, ["net_income", "total_assets"]) + _missing(prev, ["net_income", "total_assets"], "_previous"),
        "cfo_above_net_income": _missing(now, ["operating_cash_flow", "net_income"]),
        "lower_leverage": _missing(now, ["long_term_debt", "total_assets"]) + _missing(prev, ["long_term_debt", "total_assets"], "_previous"),
        "higher_current_ratio": _missing(now, ["current_assets", "current_liabilities"]) + _missing(prev, ["current_assets", "current_liabilities"], "_previous"),
        "no_new_shares": _missing(now, ["shares_issued"]) + _missing(prev, ["shares_issued"], "_previous"),
        "higher_gross_margin": _missing(now, ["gross_profit", "revenue"]) + _missing(prev, ["gross_profit", "revenue"], "_previous"),
        "higher_asset_turnover": _missing(now, ["revenue", "total_assets"]) + _missing(prev, ["revenue", "total_assets"], "_previous"),
    }
    missing_fields = list(dict.fromkeys(field for component in missing_components for field in requirements[component]))
    return {
        "value": float(score) if available else None,
        "status": "available" if available == 9 else "partial" if available else "insufficient",
        "display": f"{score}/{available}" if available else None,
        "available_components": available,
        "total_components": 9,
        "components": components,
        "missing_components": missing_components,
        "missing_fields": missing_fields,
        "formula_version": "piotroski_9_signal_annual_v1",
        "inputs": {"period": now.get("date"), "previous_period": prev.get("date")},
        "warnings": warnings + (["未增发股票使用 1% 容差。"] if shares_now is not None and shares_prev is not None else []),
    }


def calculate_altman_metric(financials: dict[str, Any], market_cap: float | None, profile_key: str) -> dict[str, Any]:
    if profile_key in {"bank", "insurance"}:
        return {"value": None, "status": "not_applicable", "missing_fields": [], "inputs": {},
                "warnings": ["金融企业不适用经典上市制造业 Altman Z 模型。"], "applicability": "not_applicable"}
    periods = financials.get("periods") or []
    now = periods[0] if periods else None
    fields = ["current_assets", "current_liabilities", "retained_earnings", "operating_income", "revenue", "total_assets", "total_liabilities"]
    missing = _missing(now, fields)
    if market_cap is None:
        missing.append("market_cap")
    applicability = "low" if profile_key in {"software", "reit"} else "medium"
    if missing:
        return {"value": None, "status": "insufficient", "missing_fields": missing, "inputs": {}, "warnings": [], "applicability": applicability}
    if now["total_assets"] <= 0 or now["total_liabilities"] <= 0:
        return {"value": None, "status": "insufficient", "missing_fields": ["positive_total_assets", "positive_total_liabilities"],
                "inputs": {}, "warnings": [], "applicability": applicability}
    working_capital = now["current_assets"] - now["current_liabilities"]
    value = (1.2 * working_capital / now["total_assets"] + 1.4 * now["retained_earnings"] / now["total_assets"]
             + 3.3 * now["operating_income"] / now["total_assets"] + .6 * market_cap / now["total_liabilities"]
             + now["revenue"] / now["total_assets"])
    return {"value": value, "status": "available", "missing_fields": [], "formula_version": "altman_public_manufacturing_v1",
            "inputs": {"period": now.get("date"), "working_capital": working_capital, "retained_earnings": now["retained_earnings"],
                       "ebit": now["operating_income"], "market_cap": market_cap, "revenue": now["revenue"],
                       "total_assets": now["total_assets"], "total_liabilities": now["total_liabilities"]},
            "warnings": ["市值使用当前 marketCap，并非财报期末历史市值。", "经典上市制造业 Altman Z，仅作参考。"],
            "applicability": applicability}


def _raw_values(info: dict[str, Any]) -> dict[str, float | None]:
    enterprise, revenue = _number(info.get("enterpriseValue")), _number(info.get("totalRevenue"))
    fcf, market_cap = _number(info.get("freeCashflow")), _number(info.get("marketCap"))
    growth = _pct(info.get("revenueGrowth"))
    return {
        "forward_pe": _number(info.get("forwardPE")), "peg": _number(info.get("pegRatio")),
        "ev_sales": enterprise / revenue if enterprise and revenue else None,
        "ev_ebitda": enterprise / _number(info.get("ebitda")) if enterprise and _number(info.get("ebitda")) else None,
        "fcf_yield": fcf / market_cap * 100 if fcf is not None and market_cap else None,
        "price_to_book": _number(info.get("priceToBook")),
        "rule_of_40": growth + fcf / revenue * 100 if growth is not None and fcf is not None and revenue else None,
        "roe": _pct(info.get("returnOnEquity")), "roic": _pct(info.get("returnOnInvestedCapital")),
        "current_ratio": _number(info.get("currentRatio")), "revenue_growth": growth,
        "eps_growth": _pct(info.get("earningsGrowth")),
    }


def _peer_medians(peer_infos: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, int]]:
    buckets: dict[str, list[float]] = {}
    for info in peer_infos:
        for key, value in _raw_values(info).items():
            if value is not None and value > 0:
                buckets.setdefault(key, []).append(value)
    return ({key: round(median(values), 2) for key, values in buckets.items()}, {key: len(values) for key, values in buckets.items()})


def _metric(key: str, value: float | None, unit: str = "multiple", peer_median: float | None = None, peer_count: int = 0,
            note: str | None = None, details: dict[str, Any] | None = None) -> dict:
    formula, recommended, explanation = MODEL_GUIDE[key]
    delta = ((value / peer_median) - 1) * 100 if value is not None and peer_median else None
    comparison = None
    if delta is not None:
        comparison = f"低于同行 {abs(delta):.0f}%" if delta < 0 else f"高于同行 {delta:.0f}%"
    result = {"key": key, "label": MODEL_NAMES[key], "value": round(value, 2) if value is not None else None, "unit": unit,
            "status": "available" if value is not None else "insufficient", "peer_median": peer_median, "peer_count": peer_count,
            "peer_delta_percent": round(delta, 1) if delta is not None else None, "comparison": comparison,
            "formula": formula, "recommended_range": recommended, "explanation": explanation, "note": note}
    if details:
        result.update(details)
        result["value"] = round(value, 2) if value is not None else None
    return result


def _dcf_value(fcf: float, shares: float, growth: float, discount: float, terminal: float) -> float:
    pv = sum(fcf * pow(1 + growth, year) / pow(1 + discount, year) for year in range(1, 6))
    pv += fcf * pow(1 + growth, 5) * (1 + terminal) / (discount - terminal) / pow(1 + discount, 5)
    return pv / shares


def _dcf_scenarios(price: float | None, fcf: float | None, shares: float | None, growth_pct: float | None) -> dict:
    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return {"bear": None, "base": None, "bull": None, "current": price, "assumptions": {}}
    base_g = min(max((growth_pct or 5) / 100, 0), .15)
    settings = {"bear": (max(base_g * .5, .01), .12, .02), "base": (base_g, .10, .03), "bull": (min(base_g * 1.25, .20), .09, .04)}
    values = {name: round(_dcf_value(fcf, shares, *args), 2) for name, args in settings.items()}
    values.update({"current": round(price, 2) if price is not None else None, "assumptions": {name: {"growth": round(args[0] * 100, 1), "discount_rate": args[1] * 100, "terminal_growth": args[2] * 100} for name, args in settings.items()}})
    return values


def _reverse_dcf_growth(price: float | None, fcf: float | None, shares: float | None) -> float | None:
    if not price or not fcf or fcf <= 0 or not shares: return None
    low, high = -.20, .35
    for _ in range(50):
        mid = (low + high) / 2
        if _dcf_value(fcf, shares, mid, .10, .03) < price: low = mid
        else: high = mid
    return round((low + high) / 2 * 100, 1)


def _stars(ratio: float | None) -> int:
    if ratio is None: return 0
    if ratio <= .75: return 5
    if ratio <= .90: return 4
    if ratio <= 1.10: return 3
    if ratio <= 1.30: return 2
    return 1


def _signal(key: str, ratio: float | None, detail: str) -> dict:
    stars = _stars(ratio)
    verdict = "数据不足" if not stars else "低估" if stars >= 4 else "合理" if stars == 3 else "偏贵"
    return {"key": key, "label": MODEL_NAMES[key], "verdict": verdict, "stars": stars, "detail": detail}


def _fallback_opinion(signals: list[dict], rule40: float | None, dcf: dict, reverse_growth: float | None) -> str:
    available = [item for item in signals if item["stars"]]
    if not available: return "关键估值数据不足，暂时无法形成可靠的模型交叉结论。"
    positions = {item["verdict"] for item in available}
    lead = "模型之间存在分歧。" if len(positions) > 1 else f"主要模型总体指向{available[0]['verdict']}。"
    parts = [lead, "；".join(f"{item['label']}认为{item['verdict']}" for item in available) + "。"]
    if rule40 is not None: parts.append(f"Rule of 40 为 {rule40:.0f}%，反映增长与现金流的综合质量。")
    if dcf.get("base") is not None: parts.append("DCF 应结合 Bear/Base/Bull 区间理解，结论对增长率和终值假设较敏感。")
    if reverse_growth is not None: parts.append(f"当前价格隐含未来五年自由现金流增长约 {reverse_growth:.1f}%。")
    return "".join(parts)


def build_cross_model(ticker: str, info: dict[str, Any], quarters: list[dict[str, Any]], peer_infos: list[dict[str, Any]] | None = None,
                      peer_symbols: list[str] | None = None, financials: dict[str, Any] | None = None,
                      graham: dict[str, Any] | None = None) -> dict:
    peer_infos, peer_symbols = peer_infos or [], peer_symbols or []
    values = _raw_values(info); medians, counts = _peer_medians(peer_infos)
    financials = financials or {"source": "yfinance_annual", "periods": []}
    annual_periods = financials["periods"]
    annual_now = annual_periods[0] if annual_periods else {}
    annual_prev = annual_periods[1] if len(annual_periods) > 1 else {}
    price = _number(info.get("currentPrice") or info.get("regularMarketPrice"))
    market_cap = _number(info.get("marketCap"))
    revenue = _number(info.get("totalRevenue")) or _number(annual_now.get("revenue"))
    net_income = _number(info.get("netIncomeToCommon")) or _number(annual_now.get("net_income"))
    ebitda = _number(info.get("ebitda"))
    debt = _number(info.get("totalDebt")) if _number(info.get("totalDebt")) is not None else _number(annual_now.get("total_debt"))
    cash = _number(info.get("totalCash")) if _number(info.get("totalCash")) is not None else _number(annual_now.get("cash"))
    if values["current_ratio"] is None:
        values["current_ratio"] = _ratio(_number(annual_now.get("current_assets")), _number(annual_now.get("current_liabilities")))
    if values["roe"] is None:
        equity_now, equity_prev = _number(annual_now.get("stockholders_equity")), _number(annual_prev.get("stockholders_equity"))
        average_equity = (equity_now + equity_prev) / 2 if equity_now is not None and equity_prev is not None else equity_now
        roe = _ratio(_number(annual_now.get("net_income")), average_equity)
        values["roe"] = roe * 100 if roe is not None else None
    if values["revenue_growth"] is None:
        annual_growth = _ratio(_number(annual_now.get("revenue")), _number(annual_prev.get("revenue")))
        values["revenue_growth"] = (annual_growth - 1) * 100 if annual_growth is not None else None
    fcf = _number(info.get("freeCashflow"))
    positive_periods = 0
    if quarters:
        q_fcf = [_number(q.get("free_cash_flow")) for q in quarters]
        positive_periods = sum(1 for value in q_fcf if value is not None and value > 0)
        recent_fcf = sum(value or 0 for value in q_fcf)
        if recent_fcf: fcf = recent_fcf
    metrics_for_tags = {"revenue_growth": values["revenue_growth"], "gross_margin": _pct(info.get("grossMargins")), "net_income": net_income,
                        "net_debt_to_ebitda": ((debt - cash) / ebitda if debt is not None and cash is not None and ebitda else None), "fcf_positive_periods": positive_periods}
    tags = derive_classification_tags(info); tags.update(derive_financial_tags(metrics_for_tags)); tags.update(derive_business_model_tags(info, metrics_for_tags))
    profile_key = industry_profile(info, tags); profile = INDUSTRY_PROFILES[profile_key]
    roic_result = calculate_roic_metric(financials)
    piotroski_result = calculate_piotroski_metric(financials)
    altman_result = calculate_altman_metric(financials, market_cap, profile_key)
    # 原始三表计算优先；旧 Yahoo summary 字段只作为无三表快照时的兼容回退。
    if roic_result["value"] is None and not financials["periods"] and values["roic"] is not None:
        roic_result = {"value": values["roic"], "status": "available", "missing_fields": [], "inputs": {},
                       "warnings": ["年度三表不可用，使用 Yahoo summary 的 returnOnInvestedCapital。"], "formula_version": "yahoo_summary_fallback"}
    weights, weight_details = calculate_model_weight_details(tags)
    shares = _number(info.get("sharesOutstanding")); growth = values["revenue_growth"]
    dcf = _dcf_scenarios(price, fcf, shares, growth)
    reverse_growth = _reverse_dcf_growth(price, fcf, shares)
    forward_eps = _number(info.get("forwardEps"))
    consensus_items: list[dict] = []
    if dcf.get("base") is not None: consensus_items.append({"key": "dcf", "label": "DCF Base（DCF基准）", "value": dcf["base"]})
    if forward_eps and medians.get("forward_pe"): consensus_items.append({"key": "relative_pe", "label": "Relative P/E（相对市盈率）", "value": round(forward_eps * medians["forward_pe"], 2)})
    if shares and revenue and medians.get("ev_sales"):
        equity = medians["ev_sales"] * revenue - (debt or 0) + (cash or 0)
        if equity > 0: consensus_items.append({"key": "industry_multiple", "label": "Industry Multiple（行业倍数）", "value": round(equity / shares, 2)})
    if forward_eps and values["eps_growth"] and medians.get("peg"):
        implied_pe = medians["peg"] * values["eps_growth"]
        consensus_items.append({"key": "peg_fair_value", "label": "PEG Fair Value（PEG公允价值）", "value": round(forward_eps * implied_pe, 2)})
    consensus_value = round(median([item["value"] for item in consensus_items]), 2) if consensus_items else None
    dcf_ratio = price / dcf["base"] if price and dcf.get("base") else None
    pe_ratio = values["forward_pe"] / medians["forward_pe"] if values["forward_pe"] and medians.get("forward_pe") else None
    evs_ratio = values["ev_sales"] / medians["ev_sales"] if values["ev_sales"] and medians.get("ev_sales") else None
    peg_ratio = values["peg"] / medians["peg"] if values["peg"] and medians.get("peg") else None
    signals = [_signal("dcf", dcf_ratio, "现价与 DCF Base 比较"), _signal("forward_pe", pe_ratio, "与同行 Forward P/E 中位数比较"),
               _signal("ev_sales", evs_ratio, "与同行 EV/Sales 中位数比较"), _signal("peg", peg_ratio, "与同行 PEG 中位数比较")]
    valuation = [_metric("forward_pe", values["forward_pe"], peer_median=medians.get("forward_pe"), peer_count=counts.get("forward_pe", 0)),
                 _metric("peg", values["peg"], peer_median=medians.get("peg"), peer_count=counts.get("peg", 0)),
                 _metric("ev_sales", values["ev_sales"], peer_median=medians.get("ev_sales"), peer_count=counts.get("ev_sales", 0)),
                 _metric("ev_ebitda", values["ev_ebitda"], peer_median=medians.get("ev_ebitda"), peer_count=counts.get("ev_ebitda", 0)),
                 _metric("dcf", dcf.get("base"), "USD/share", note="Bear/Base/Bull 使用不同增长、折现率和永续增长率。"),
                 _metric("fcf_yield", fcf / market_cap * 100 if fcf is not None and market_cap else None, "%", medians.get("fcf_yield"), counts.get("fcf_yield", 0)),
                 _metric("price_to_book", values["price_to_book"], peer_median=medians.get("price_to_book"), peer_count=counts.get("price_to_book", 0))]
    growth_items = [_metric("rule_of_40", values["rule_of_40"], "%", medians.get("rule_of_40"), counts.get("rule_of_40", 0)),
                    _metric("revenue_growth", values["revenue_growth"], "%", medians.get("revenue_growth"), counts.get("revenue_growth", 0)),
                    _metric("eps_growth", values["eps_growth"], "%", medians.get("eps_growth"), counts.get("eps_growth", 0))]
    health = [_metric("roe", values["roe"], "%", medians.get("roe"), counts.get("roe", 0)),
              _metric("roic", roic_result["value"], "%", medians.get("roic"), counts.get("roic", 0), "由 Yahoo 年度三表计算 NOPAT 与投入资本。", roic_result),
              _metric("current_ratio", values["current_ratio"], peer_median=medians.get("current_ratio"), peer_count=counts.get("current_ratio", 0)),
              _metric("piotroski", piotroski_result["value"], "score", note="缺失信号不计为 0，分母显示实际可计算项数。", details=piotroski_result),
              _metric("altman_z", altman_result["value"], "score", note="经典上市制造业模型；金融企业禁用，软件与 REIT 适用性较低。", details=altman_result),
              _metric("net_debt", (debt - cash) / 1e9 if debt is not None and cash is not None else None, "USD bn")]
    fallback = _fallback_opinion(signals, values["rule_of_40"], dcf, reverse_growth)
    return {"ticker": ticker, "company": info.get("shortName") or info.get("longName") or ticker,
            "classification": {"sector": info.get("sector"), "industry": info.get("industry"), "industry_key": info.get("industryKey"), "profile": profile_key, **profile},
            "peers": {"source": "Finnhub /stock/peers", "symbols": peer_symbols, "coverage": len(peer_infos), "medians": medians},
            "tags": [{"name": name, "label": TAG_LABELS.get(name, name), "confidence": value} for name, value in sorted(tags.items())],
            "weights": weights, "weight_details": weight_details, "valuation": valuation, "growth": growth_items, "health": health,
            "graham": graham,
            "dcf_scenarios": dcf, "reverse_dcf": {"implied_fcf_growth": reverse_growth, "unit": "%"},
            "consensus": {"items": consensus_items, "value": consensus_value, "current": round(price, 2) if price is not None else None},
            "model_signals": signals, "model_conflict": len({item["verdict"] for item in signals if item["stars"]}) > 1,
            "ai_opinion": fallback, "ai_model": None, "as_of": info.get("regularMarketTime")}


def fetch_cross_model_inputs(ticker: str, peer_symbols: list[str]) -> tuple[dict, list[dict], dict[str, Any]]:
    """每日任务调用；页面不直接访问 Yahoo，保证显示的是持久化快照。"""
    stock = yf.Ticker(ticker)
    try: info = stock.get_info()
    except Exception as exc:
        logger.warning("%s Yahoo info 获取失败: %s", ticker, exc)
        info = {}
    try:
        fast_info = stock.fast_info
        info["fastInfoLastPrice"] = fast_info.last_price
        if info.get("previousClose") is None:
            info["previousClose"] = fast_info.previous_close
    except Exception as exc:
        logger.warning("%s Yahoo fast_info 获取失败: %s", ticker, exc)
    try:
        financials = normalize_financial_statements(
            stock.get_income_stmt(freq="yearly"),
            stock.get_balance_sheet(freq="yearly"),
            stock.get_cash_flow(freq="yearly"),
        )
    except Exception as exc:
        logger.warning("%s Yahoo 年度财报获取失败: %s", ticker, exc)
        financials = {"source": "yfinance_annual", "periods": []}
    peer_infos: list[dict] = []
    for symbol in peer_symbols[:10]:
        try:
            peer_info = yf.Ticker(symbol).get_info()
            if peer_info: peer_infos.append(peer_info)
        except Exception:
            continue
    return info, peer_infos, financials


def opinion_evidence(payload: dict) -> str:
    """仅把计算结果交给 Luna，避免让模型自行推导。"""
    lines = [f"标的：{payload['ticker']}", f"行业：{payload['classification']['label']}", f"同行：{', '.join(payload['peers']['symbols']) or '数据不足'}"]
    for group in ("valuation", "growth", "health"):
        for item in payload[group]:
            if item["value"] is not None:
                lines.append(f"{item['label']}: 公司={item['value']} {item['unit']}, 同行中位数={item['peer_median']}, 比较={item['comparison']}")
    lines.append(f"DCF情景：{payload['dcf_scenarios']}")
    lines.append(f"Reverse DCF隐含增长：{payload['reverse_dcf']['implied_fcf_growth']}%")
    lines.append(f"Consensus：{payload['consensus']}")
    lines.append(f"模型信号：{payload['model_signals']}")
    return "\n".join(lines)
