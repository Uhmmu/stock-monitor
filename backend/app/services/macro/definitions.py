from __future__ import annotations

from copy import deepcopy
from typing import Any


SOURCE_NAME = "Alpha Vantage 宏观经济接口"


def _series(
    key: str,
    function: str,
    name_zh: str,
    name_en: str,
    description: str,
    unit: str,
    frequency: str,
    category: str,
    *,
    params: dict[str, str] | None = None,
    why: str = "用于观察美国宏观环境，不应脱离其他指标单独解读。",
    rising: str = "上升通常表示该指标本身变强或变高，但市场含义取决于增长、通胀和利率背景。",
    falling: str = "下降通常表示该指标本身变弱或变低，但市场含义取决于增长、通胀和利率背景。",
    bullish: list[str] | None = None,
    bearish: list[str] | None = None,
    notes: list[str] | None = None,
    affected: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "series_key": key,
        "provider": "alpha_vantage",
        "provider_function": function,
        "provider_parameters": params or {},
        "country_code": "US",
        "display_name_zh": name_zh,
        "display_name_en": name_en,
        "description_zh": description,
        "unit": unit,
        "frequency": frequency,
        "category": category,
        "source_name": SOURCE_NAME,
        "is_derived": False,
        "enabled": True,
        "why_it_matters": why,
        "rising_interpretation": rising,
        "falling_interpretation": falling,
        "bullish_scenarios": bullish or ["数据改善且没有推高通胀或利率压力时，通常可能支持风险资产。"],
        "bearish_scenarios": bearish or ["数据恶化或引发更高利率预期时，通常可能压制部分风险资产。"],
        "context_notes": notes or ["市场反应取决于实际数据、历史趋势和市场预期；本模块未接入一致预期数据。"],
        "affected_assets": affected or {
            "broad_market": "依赖情境",
            "growth_stocks": "依赖情境",
            "value_stocks": "依赖情境",
            "bonds": "依赖情境",
            "usd": "依赖情境",
            "gold": "依赖情境",
        },
    }


RAW_SERIES: list[dict[str, Any]] = [
    _series("us_real_gdp", "REAL_GDP", "实际 GDP", "Real GDP", "经通胀调整后的美国国内生产总值，反映经济总体实际产出；原始值不是增长率。", "currency", "quarterly", "growth", why="用于判断实际经济产出及其增长速度。", notes=["原始序列是 GDP 水平，环比和同比由本地根据相邻观察值计算。"]),
    _series("us_real_gdp_per_capita", "REAL_GDP_PER_CAPITA", "人均实际 GDP", "Real GDP per Capita", "经通胀调整后按人口折算的人均产出，用于观察居民平均产出水平的长期变化。", "currency_per_capita", "quarterly", "growth", notes=["五年复合增长趋势需要足够季度历史；不足时显示数据不足。"]),
    _series("us_treasury_3m", "TREASURY_YIELD", "美国 3 个月国债收益率", "US 3-Month Treasury Yield", "短端无风险利率的代表，通常对货币政策预期较敏感。", "percent", "daily", "rates", params={"interval": "daily", "maturity": "3month"}, affected={"broad_market": "依赖情境", "growth_stocks": "通常偏利空（若上行）", "banks": "混合", "bonds": "通常偏利空（若上行）", "usd": "通常偏利多（若上行）", "gold": "通常偏利空（若上行）"}),
    _series("us_treasury_2y", "TREASURY_YIELD", "美国 2 年期国债收益率", "US 2-Year Treasury Yield", "对政策利率路径预期较敏感的中短端收益率。", "percent", "daily", "rates", params={"interval": "daily", "maturity": "2year"}, affected={"broad_market": "依赖情境", "growth_stocks": "通常偏利空（若上行）", "banks": "混合", "bonds": "通常偏利空（若上行）", "usd": "通常偏利多（若上行）", "gold": "通常偏利空（若上行）"}),
    _series("us_treasury_5y", "TREASURY_YIELD", "美国 5 年期国债收益率", "US 5-Year Treasury Yield", "中端收益率，连接政策路径与较长期增长/通胀预期。", "percent", "daily", "rates", params={"interval": "daily", "maturity": "5year"}),
    _series("us_treasury_10y", "TREASURY_YIELD", "美国 10 年期国债收益率", "US 10-Year Treasury Yield", "长期基准收益率，常用于资产定价、抵押贷款和长久期股票估值。", "percent", "daily", "rates", params={"interval": "daily", "maturity": "10year"}, affected={"broad_market": "依赖情境", "growth_stocks": "通常偏利空（若上行）", "value_stocks": "混合", "real_estate": "通常偏利空（若上行）", "bonds": "通常偏利空（若上行）", "usd": "依赖情境", "gold": "通常偏利空（若上行）"}),
    _series("us_treasury_30y", "TREASURY_YIELD", "美国 30 年期国债收益率", "US 30-Year Treasury Yield", "超长期收益率，反映长期通胀、财政供给和期限溢价等因素的综合定价。", "percent", "daily", "rates", params={"interval": "daily", "maturity": "30year"}),
    _series("us_federal_funds_rate", "FEDERAL_FUNDS_RATE", "联邦基金利率", "Federal Funds Rate", "美国短期政策利率序列；方向主要由近期变化和持续时间判断，不依据绝对水平简单贴标签。", "percent", "daily", "rates", why="用于观察货币政策方向和金融条件。", notes=["政策环境标签由近一个月、三个月变化和变化持续时间规则化生成。"]),
    _series("us_cpi", "CPI", "消费者价格指数（CPI）", "Consumer Price Index", "美国总体消费价格指数水平；它是价格水平，不是通胀率本身。", "index", "monthly", "inflation", why="用于计算月环比、同比和三个月年化通胀变化。", rising="指数上升表示价格水平上升；如果增速加快，可能推高利率预期。", falling="指数仍可能上升但增速放缓；只有结合变化率才能判断通胀是否降温。", bullish=["CPI 增速温和回落且增长、就业没有明显恶化时，可能减轻进一步加息压力。"], bearish=["CPI 增速再次加快时，可能推高利率预期并压制高估值成长股。"], notes=["单月变化可能受能源、食品和基数效应影响。模块未接入核心 CPI 或一致预期。"], affected={"broad_market": "依赖情境", "growth_stocks": "通常偏利空（若增速加快）", "value_stocks": "混合", "bonds": "通常偏利空（若增速加快）", "usd": "通常偏利多（若增速加快）", "gold": "混合"}),
    _series("us_annual_inflation", "INFLATION", "年度通胀率", "Annual Inflation", "低频年度通胀背景序列，用于长期历史比较，不作为当前月度通胀判断的主要依据。", "percent", "annual", "inflation"),
    _series("us_retail_sales", "RETAIL_SALES", "零售销售", "Retail Sales", "名义零售销售序列，观察消费支出活动；原始数据没有自动剔除通胀影响。", "currency", "monthly", "consumer", why="用于观察消费需求和经济活动的一个侧面。", rising="上升可能来自实际消费增长，也可能部分来自价格上涨。", falling="下降可能表示需求降温，也可能受价格、季节性和构成变化影响。", notes=["零售销售上升可能来自实际消费增长，也可能部分来自价格上涨，因此不应孤立解读。"]),
    _series("us_durable_goods_orders", "DURABLES", "耐用品订单", "Durable Goods Orders", "耐用消费品和设备订单，常用于观察制造业与资本支出意愿。", "currency", "monthly", "consumer", why="用于观察工业投资和大额消费需求，但月度波动通常较大。", notes=["单月数据可能受飞机和大型设备订单影响，不应根据一个月作强结论。"]),
    _series("us_unemployment_rate", "UNEMPLOYMENT", "失业率", "Unemployment Rate", "劳动力市场中失业人口占劳动力的比例。", "percent", "monthly", "labor", why="用于观察就业市场松紧和经济周期风险。", rising="失业率上升通常表示就业市场降温；若持续上行，可能增加衰退风险。", falling="失业率下降通常表示就业市场稳健，但过热也可能让通胀压力更持久。", bullish=["失业率稳定且没有明显推升通胀时，通常有利于消费和风险资产。"], bearish=["失业率持续上升并触发简化 Sahm Rule 风险提示时，通常不利于周期性资产。"], notes=["简化 Sahm Rule 仅是规则化风险信号，不等于正式宣布经济衰退，也不是百分之百准确的预测。"], affected={"broad_market": "依赖情境", "growth_stocks": "混合", "value_stocks": "通常偏利空（若快速上升）", "banks": "通常偏利空（若快速上升）", "consumer_discretionary": "通常偏利空（若快速上升）", "bonds": "依赖情境", "usd": "依赖情境", "gold": "依赖情境"}),
    _series("us_nonfarm_payroll_total", "NONFARM_PAYROLL", "非农就业总人数", "Total Nonfarm Payroll", "美国非农就业总人数序列；它不是新闻中常说的当月新增非农。", "persons", "monthly", "labor", why="用于观察就业总量，并由本地计算新增/减少人数。", notes=["前端主要显示新增非农；详情同时显示总就业人数。"]),
]


DERIVED_SERIES: list[dict[str, Any]] = [
    {"series_key": "us_real_gdp_qoq", "display_name_zh": "实际 GDP 季度环比", "display_name_en": "Real GDP QoQ", "unit": "percent", "frequency": "quarterly", "category": "growth", "description_zh": "根据实际 GDP 水平计算的季度环比变化。", "is_derived": True},
    {"series_key": "us_real_gdp_yoy", "display_name_zh": "实际 GDP 同比", "display_name_en": "Real GDP YoY", "unit": "percent", "frequency": "quarterly", "category": "growth", "description_zh": "根据实际 GDP 水平计算的四季度同比变化。", "is_derived": True},
    {"series_key": "us_real_gdp_per_capita_yoy", "display_name_zh": "人均实际 GDP 同比", "display_name_en": "Real GDP per Capita YoY", "unit": "percent", "frequency": "quarterly", "category": "growth", "description_zh": "根据人均实际 GDP 水平计算的同比变化。", "is_derived": True},
    {"series_key": "us_real_gdp_per_capita_5y_cagr", "display_name_zh": "人均实际 GDP 五年复合增长", "display_name_en": "Real GDP per Capita 5Y CAGR", "unit": "percent", "frequency": "quarterly", "category": "growth", "description_zh": "根据季度人均实际 GDP 计算的五年复合增长趋势。", "is_derived": True},
    {"series_key": "us_cpi_mom", "display_name_zh": "CPI 月环比", "display_name_en": "CPI MoM", "unit": "percent", "frequency": "monthly", "category": "inflation", "description_zh": "CPI 指数相对上月的百分比变化。", "is_derived": True},
    {"series_key": "us_cpi_yoy", "display_name_zh": "CPI 同比", "display_name_en": "CPI YoY", "unit": "percent", "frequency": "monthly", "category": "inflation", "description_zh": "CPI 指数相对十二个月前的百分比变化。", "is_derived": True},
    {"series_key": "us_cpi_3m_annualized", "display_name_zh": "CPI 三个月年化", "display_name_en": "CPI 3M Annualized", "unit": "percent", "frequency": "monthly", "category": "inflation", "description_zh": "基于最近三个月指数变化并按复合方式年化的变化率。", "is_derived": True},
    {"series_key": "us_retail_sales_mom", "display_name_zh": "零售销售月环比", "display_name_en": "Retail Sales MoM", "unit": "percent", "frequency": "monthly", "category": "consumer", "description_zh": "零售销售相对上月的百分比变化。", "is_derived": True},
    {"series_key": "us_retail_sales_yoy", "display_name_zh": "零售销售同比", "display_name_en": "Retail Sales YoY", "unit": "percent", "frequency": "monthly", "category": "consumer", "description_zh": "零售销售相对十二个月前的百分比变化。", "is_derived": True},
    {"series_key": "us_durable_goods_orders_mom", "display_name_zh": "耐用品订单月环比", "display_name_en": "Durable Goods Orders MoM", "unit": "percent", "frequency": "monthly", "category": "consumer", "description_zh": "耐用品订单相对上月的百分比变化。", "is_derived": True},
    {"series_key": "us_durable_goods_orders_yoy", "display_name_zh": "耐用品订单同比", "display_name_en": "Durable Goods Orders YoY", "unit": "percent", "frequency": "monthly", "category": "consumer", "description_zh": "耐用品订单相对十二个月前的百分比变化。", "is_derived": True},
    {"series_key": "us_nonfarm_payroll_change", "display_name_zh": "非农就业月度新增", "display_name_en": "Nonfarm Payroll Change", "unit": "persons", "frequency": "monthly", "category": "labor", "description_zh": "非农就业总人数相对上月的变化。", "is_derived": True},
    {"series_key": "us_nonfarm_payroll_3m_avg_change", "display_name_zh": "非农就业三个月平均新增", "display_name_en": "Nonfarm Payroll 3M Average Change", "unit": "persons", "frequency": "monthly", "category": "labor", "description_zh": "最近三个月非农就业新增人数的平均值。", "is_derived": True},
    {"series_key": "us_unemployment_3m_avg", "display_name_zh": "失业率三个月均值", "display_name_en": "Unemployment 3M Average", "unit": "percent", "frequency": "monthly", "category": "labor", "description_zh": "最近三个月失业率的简单平均。", "is_derived": True},
    {"series_key": "us_sahm_rule_gap", "display_name_zh": "简化 Sahm Rule 差值", "display_name_en": "Simplified Sahm Rule Gap", "unit": "percentage_points", "frequency": "monthly", "category": "labor", "description_zh": "最近三个月失业率均值与过去十二个月内三个月均值最低值的差。", "is_derived": True},
    {"series_key": "us_yield_spread_10y_2y", "display_name_zh": "10Y-2Y 收益率利差", "display_name_en": "10Y-2Y Yield Spread", "unit": "percentage_points", "frequency": "daily", "category": "rates", "description_zh": "10 年期国债收益率减去 2 年期收益率。", "is_derived": True},
    {"series_key": "us_yield_spread_10y_3m", "display_name_zh": "10Y-3M 收益率利差", "display_name_en": "10Y-3M Yield Spread", "unit": "percentage_points", "frequency": "daily", "category": "rates", "description_zh": "10 年期国债收益率减去 3 个月收益率。", "is_derived": True},
    {"series_key": "us_yield_spread_30y_5y", "display_name_zh": "30Y-5Y 收益率利差", "display_name_en": "30Y-5Y Yield Spread", "unit": "percentage_points", "frequency": "daily", "category": "rates", "description_zh": "30 年期国债收益率减去 5 年期收益率。", "is_derived": True},
]

DEFINITION_BY_KEY = {row["series_key"]: row for row in RAW_SERIES + DERIVED_SERIES}


def get_series_definition(series_key: str) -> dict[str, Any] | None:
    value = DEFINITION_BY_KEY.get(series_key)
    return deepcopy(value) if value else None
