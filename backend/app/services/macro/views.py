from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.models import MacroObservation, MacroSeries, MacroSyncRun

from .context import _curve_analysis, _float, load_macro_observations
from .definitions import DERIVED_SERIES, RAW_SERIES, SOURCE_NAME, get_series_definition
from .derived import MacroDerivedMetricsService
from .sync import PROVIDER, redact_provider_error, usage_status


DISCLAIMER = "仅为规则化市场环境摘要与研究信息，不构成投资建议。市场反应取决于历史趋势与实际数据相对预期的差异；当前模块未接入一致预期数据。"
ASSET_LABELS = {
    "broad_market": "大盘", "growth_stocks": "成长股", "value_stocks": "价值股", "banks": "银行",
    "real_estate": "房地产", "utilities": "公用事业", "consumer_discretionary": "可选消费",
    "consumer_staples": "必需消费", "healthcare": "医疗保健", "small_caps": "小盘股",
    "bonds": "债券", "usd": "美元", "gold": "黄金",
}
FRESHNESS_DAYS = {"daily": 7, "monthly": 70, "quarterly": 200, "annual": 500}
CARD_KEYS = [
    "us_cpi", "us_unemployment_rate", "us_nonfarm_payroll_total", "us_real_gdp",
    "us_federal_funds_rate", "us_treasury_10y", "us_treasury_2y", "us_retail_sales",
    "us_durable_goods_orders",
]
_RAW_KEYS = {row["series_key"] for row in RAW_SERIES}
_DETAIL_SOURCE_KEYS = {
    "us_real_gdp_qoq": ("us_real_gdp",),
    "us_real_gdp_yoy": ("us_real_gdp",),
    "us_real_gdp_per_capita_yoy": ("us_real_gdp_per_capita",),
    "us_real_gdp_per_capita_5y_cagr": ("us_real_gdp_per_capita",),
    "us_cpi_mom": ("us_cpi",),
    "us_cpi_yoy": ("us_cpi",),
    "us_cpi_3m_annualized": ("us_cpi",),
    "us_retail_sales_mom": ("us_retail_sales",),
    "us_retail_sales_yoy": ("us_retail_sales",),
    "us_durable_goods_orders_mom": ("us_durable_goods_orders",),
    "us_durable_goods_orders_yoy": ("us_durable_goods_orders",),
    "us_nonfarm_payroll_change": ("us_nonfarm_payroll_total",),
    "us_nonfarm_payroll_3m_avg_change": ("us_nonfarm_payroll_total",),
    "us_unemployment_3m_avg": ("us_unemployment_rate",),
    "us_sahm_rule_gap": ("us_unemployment_rate",),
    "us_yield_spread_10y_2y": ("us_treasury_10y", "us_treasury_2y"),
    "us_yield_spread_10y_3m": ("us_treasury_10y", "us_treasury_3m"),
    "us_yield_spread_30y_5y": ("us_treasury_30y", "us_treasury_5y"),
}
_DETAIL_COMPANIONS = {
    "us_cpi": ("us_cpi_mom", "us_cpi_yoy", "us_cpi_3m_annualized"),
    "us_real_gdp": ("us_real_gdp_qoq", "us_real_gdp_yoy"),
    "us_retail_sales": ("us_retail_sales_mom", "us_retail_sales_yoy"),
    "us_durable_goods_orders": ("us_durable_goods_orders_mom", "us_durable_goods_orders_yoy"),
    "us_nonfarm_payroll_total": ("us_nonfarm_payroll_change", "us_nonfarm_payroll_3m_avg_change"),
    "us_unemployment_rate": ("us_unemployment_3m_avg", "us_sahm_rule_gap"),
}


def _safe(value: Any) -> Any:
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, (date, datetime)): return value.isoformat()
    if isinstance(value, dict): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, list): return [_safe(v) for v in value]
    return value


def _latest_raw(values: dict[str, list[tuple[date, Decimal]]], key: str) -> tuple[date, Decimal] | None:
    rows = values.get(key) or []
    return rows[-1] if rows else None


def _derived_rows(service: MacroDerivedMetricsService, key: str) -> list[dict[str, Any]]:
    return service.all_derived().get(key, [])


def _latest_derived(service: MacroDerivedMetricsService, key: str) -> dict[str, Any] | None:
    rows = _derived_rows(service, key)
    return rows[-1] if rows else None


def _previous_derived(service: MacroDerivedMetricsService, key: str) -> dict[str, Any] | None:
    rows = _derived_rows(service, key)
    return rows[-2] if len(rows) > 1 else None


def _latest_comparison_for_key(
    key: str,
    values: dict[str, list[tuple[date, Decimal]]],
    derived: dict[str, list[dict[str, Any]]],
) -> Decimal | None:
    comparison_key = {
        "us_cpi": "us_cpi_yoy",
        "us_unemployment_rate": "us_unemployment_3m_avg",
        "us_nonfarm_payroll_total": "us_nonfarm_payroll_change",
        "us_real_gdp": "us_real_gdp_yoy",
        "us_retail_sales": "us_retail_sales_yoy",
        "us_durable_goods_orders": "us_durable_goods_orders_mom",
        "us_treasury_10y": "us_treasury_10y",
        "us_treasury_2y": "us_treasury_2y",
        "us_federal_funds_rate": "us_federal_funds_rate",
    }.get(key)
    if comparison_key in {"us_treasury_10y", "us_treasury_2y", "us_federal_funds_rate"}:
        rows = values.get(key) or []
        return rows[-1][1] - rows[-22][1] if len(rows) >= 22 else None
    rows = derived.get(comparison_key or "") or []
    if not rows:
        return None
    if comparison_key == "us_nonfarm_payroll_change":
        return Decimal(str(rows[-1]["value"]))
    return Decimal(str(rows[-1]["value"])) - Decimal(str(rows[-2]["value"])) if len(rows) > 1 else None


def _raw_status(definition: dict[str, Any], latest_date: date | None, fetched_at: datetime | None) -> dict[str, Any]:
    if latest_date is None:
        return {"status": "missing", "label_zh": "数据不足", "reason": "暂无可用观察值"}
    threshold = FRESHNESS_DAYS.get(definition["frequency"], 90)
    age_days = max(0, (datetime.now(UTC).date() - latest_date).days)
    # A weekend/holiday does not make a daily yield stale immediately; use a
    # slightly wider window and describe it as a freshness hint.
    if age_days <= threshold:
        status, label = "normal", "正常"
    elif age_days <= threshold * 2:
        status, label = "stale", "可能过期"
    else:
        status, label = "expired", "已过期"
    return {"status": status, "label_zh": label, "age_days": age_days, "last_fetched_at": fetched_at}


def _trend_from_rows(rows: list[dict[str, Any]], lookback: int = 3) -> dict[str, Any]:
    if len(rows) < 2:
        return {"direction": "insufficient_data", "strength": "unknown", "lookback": f"{lookback}", "confidence": 0.0, "reason_codes": ["not_enough_observations"]}
    values = [Decimal(str(row["value"])) for row in rows[-max(2, lookback):]]
    delta = values[-1] - values[0]
    if abs(delta) < Decimal("0.0001"):
        direction, strength = "stable", "weak"
    else:
        direction, strength = ("rising" if delta > 0 else "falling"), ("strong" if abs(delta) >= 1 else "moderate")
    return {"direction": direction, "strength": strength, "lookback": f"{lookback}", "confidence": min(1.0, .45 + len(rows) / 100), "reason_codes": ["latest_vs_lookback"]}


def _impact_label(key: str, latest: Decimal | None, comparison: Decimal | None) -> tuple[str, str]:
    if latest is None:
        return "insufficient_data", "数据不足"
    if key == "us_cpi":
        if comparison is None: return "context_dependent", "依赖情境"
        return ("bullish", "通常偏积极，但取决于增长与就业") if comparison < 0 else ("bearish", "通常偏谨慎，可能推高利率预期")
    if key in {"us_unemployment_rate", "us_durable_goods_orders"}:
        if comparison is None: return "context_dependent", "依赖情境"
        return ("bearish", "通常偏谨慎，需观察是否持续") if comparison > 0 else ("bullish", "通常偏积极，但不能孤立判断")
    if key == "us_nonfarm_payroll_total":
        if comparison is None: return "context_dependent", "依赖情境"
        return ("bullish", "通常支持消费，但过强可能延后降息") if comparison > 0 else ("bearish", "通常偏谨慎，需观察失业率")
    if key in {"us_treasury_10y", "us_treasury_2y", "us_federal_funds_rate"}:
        if comparison is None: return "context_dependent", "依赖情境"
        return ("bearish", "对长久期成长资产通常偏谨慎") if comparison > 0 else ("bullish", "对长久期成长资产通常偏积极")
    if key in {"us_real_gdp", "us_retail_sales"}:
        return "bullish", "经济活动改善通常支持风险资产，但可能伴随利率压力"
    return "context_dependent", "依赖情境"


def _definition_with_latest(db, key: str, values, series_rows, service) -> dict[str, Any] | None:
    definition = get_series_definition(key)
    if definition is None:
        return None
    raw = _latest_raw(values, key)
    row = series_rows.get(key)
    latest_fetched = None
    if row:
        latest_observation = db.scalar(select(MacroObservation).where(MacroObservation.series_id == row.id).order_by(MacroObservation.observation_date.desc()).limit(1))
        latest_fetched = latest_observation.last_fetched_at if latest_observation else None
    comparison_key = {
        "us_cpi": "us_cpi_yoy", "us_unemployment_rate": "us_unemployment_3m_avg", "us_nonfarm_payroll_total": "us_nonfarm_payroll_change",
        "us_real_gdp": "us_real_gdp_yoy", "us_retail_sales": "us_retail_sales_yoy", "us_durable_goods_orders": "us_durable_goods_orders_mom",
        "us_treasury_10y": "us_treasury_10y", "us_treasury_2y": "us_treasury_2y", "us_federal_funds_rate": "us_federal_funds_rate",
    }.get(key)
    if comparison_key in {"us_treasury_10y", "us_treasury_2y", "us_federal_funds_rate"}:
        raw_rows = values.get(key) or []
        comparison = raw_rows[-1][1] - raw_rows[-22][1] if len(raw_rows) >= 22 else None
    else:
        comparison_item = _latest_derived(service, comparison_key) if comparison_key else None
        comparison_previous = _previous_derived(service, comparison_key) if comparison_key else None
        if comparison_key in {"us_nonfarm_payroll_change"}:
            comparison = Decimal(str(comparison_item["value"])) if comparison_item else None
        elif comparison_item and comparison_previous:
            comparison = Decimal(str(comparison_item["value"])) - Decimal(str(comparison_previous["value"]))
        else:
            comparison = None
    impact, impact_label = _impact_label(key, raw[1] if raw else None, comparison)
    trend_rows = [{"value": value, "observation_date": observed} for observed, value in (values.get(key) or [])]
    if comparison_key and comparison_key in service.all_derived():
        trend_rows = service.all_derived().get(comparison_key) or trend_rows
    return _safe({
        **definition,
        "latest": {"observation_date": raw[0], "value": raw[1]} if raw else None,
        "previous": {"observation_date": (values.get(key) or [])[-2][0], "value": (values.get(key) or [])[-2][1]} if len(values.get(key) or []) > 1 else None,
        "sparkline": [{"observation_date": observed, "value": value} for observed, value in (values.get(key) or [])[-36:]],
        "current_impact": {"label": impact, "label_zh": impact_label},
        "trend": _trend_from_rows(trend_rows),
        "freshness": _raw_status(definition, raw[0] if raw else None, latest_fetched),
        "data_status": "available" if raw else "insufficient",
    })


def build_series_list(db, *, category: str | None = None, frequency: str | None = None, enabled: bool | None = None) -> list[dict[str, Any]]:
    values, series_rows, _ = load_macro_observations(db)
    service = MacroDerivedMetricsService(values)
    result = []
    for definition in RAW_SERIES + DERIVED_SERIES:
        if category and definition["category"] != category: continue
        if frequency and definition["frequency"] != frequency: continue
        if enabled is False: continue
        if enabled is True and not definition.get("is_derived") and series_rows.get(definition["series_key"]) and not series_rows[definition["series_key"]].enabled: continue
        item = _definition_with_latest(db, definition["series_key"], values, series_rows, service) if not definition.get("is_derived") else {
            **definition,
            "latest": _latest_derived(service, definition["series_key"]),
            "previous": _previous_derived(service, definition["series_key"]),
            "data_status": "available" if _latest_derived(service, definition["series_key"]) else "insufficient",
            "freshness": {"status": "derived", "label_zh": "系统推导"},
            "current_impact": {"label": "context_dependent", "label_zh": "依赖情境"},
            "trend": _trend_from_rows(_derived_rows(service, definition["series_key"])),
        }
        if item and (enabled is not False or item.get("data_status") != "insufficient"):
            result.append(item)
    return result


def build_series_detail(
    db,
    key: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    include_history: bool = True,
) -> dict[str, Any] | None:
    definition = get_series_definition(key)
    if definition is None: return None
    source_keys = (key,) if key in _RAW_KEYS else _DETAIL_SOURCE_KEYS.get(key, ())
    values, series_rows, observations = load_macro_observations(db, series_keys=source_keys)
    service = MacroDerivedMetricsService(values)
    derived = service.all_derived()
    if definition.get("is_derived"):
        rows = derived.get(key, [])
        observations_for_detail = [{"observation_date": row["observation_date"], "value": row["value"], "is_derived": True} for row in rows]
    else:
        series = series_rows.get(key)
        raw_rows = [row for row in observations if series and row.series_id == series.id]
        observations_for_detail = [{"observation_date": row.observation_date, "value": row.value, "raw_value": row.raw_value, "unit": row.unit, "provider": row.provider, "source_name": row.source_name, "is_preliminary": row.is_preliminary, "revision_number": row.revision_number, "last_fetched_at": row.last_fetched_at, "is_derived": False} for row in raw_rows]
    if start_date: observations_for_detail = [row for row in observations_for_detail if row["observation_date"] >= start_date]
    if end_date: observations_for_detail = [row for row in observations_for_detail if row["observation_date"] <= end_date]
    observations_for_detail = observations_for_detail[-max(1, min(limit, 2500)):]
    latest = observations_for_detail[-1] if observations_for_detail else None
    previous = observations_for_detail[-2] if len(observations_for_detail) > 1 else None
    companion_keys = _DETAIL_COMPANIONS.get(key, ())
    trend_rows = observations_for_detail
    if key in _RAW_KEYS:
        trend_rows = [{"observation_date": observed, "value": value} for observed, value in values.get(key, [])]
    elif definition.get("is_derived"):
        trend_rows = derived.get(key, [])
    latest_raw = _latest_raw(values, key)
    latest_fetched = latest.get("last_fetched_at") if latest and not definition.get("is_derived") else None
    comparison = None
    if key in _RAW_KEYS:
        comparison = _latest_comparison_for_key(key, values, derived)
    impact, impact_label = _impact_label(key, latest_raw[1] if latest_raw else (Decimal(str(latest["value"])) if latest and latest.get("value") is not None else None), comparison)
    freshness = _raw_status(definition, latest_raw[0] if latest_raw else None, latest_fetched) if key in _RAW_KEYS else {"status": "derived", "label_zh": "系统推导"}
    return _safe({
        **definition,
        "observations": observations_for_detail if include_history else [],
        "latest": latest,
        "previous": previous,
        "sparkline": observations_for_detail[-36:] if include_history else [],
        "trend": _trend_from_rows(trend_rows),
        "current_impact": {"label": impact, "label_zh": impact_label},
        "freshness": freshness,
        "data_status": "available" if latest is not None else "insufficient",
        "derived_comparisons": {
            "mom": derived.get(f"{key}_mom", [])[-1] if derived.get(f"{key}_mom") else None,
            "yoy": derived.get(f"{key}_yoy", [])[-1] if derived.get(f"{key}_yoy") else None,
        },
        "derived_series": {derived_key: derived.get(derived_key, [])[-max(1, min(limit, 2500)):] for derived_key in companion_keys} if include_history else {},
        "interpretation": {"why_it_matters": definition.get("why_it_matters"), "rising_interpretation": definition.get("rising_interpretation"), "falling_interpretation": definition.get("falling_interpretation"), "bullish_scenarios": definition.get("bullish_scenarios", []), "bearish_scenarios": definition.get("bearish_scenarios", []), "context_notes": definition.get("context_notes", []), "affected_assets": definition.get("affected_assets", {})},
        "source_attribution": SOURCE_NAME, "disclaimer": DISCLAIMER,
    })


def _state(state: str, label: str, tone: str, confidence: float, drivers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"state": state, "label_zh": label, "tone": tone, "confidence": round(max(0, min(1, confidence)), 2), "drivers": drivers, "disclaimer": DISCLAIMER}


_SUMMARY_LABELS = {
    "growth": "增长",
    "inflation": "通胀",
    "labor": "就业",
    "policy": "政策",
    "yield_curve": "收益率曲线",
    "consumer": "消费",
}


def _enrich_summary_drivers(
    summaries: dict[str, dict[str, Any]],
    values: dict[str, list[tuple[date, Decimal]]],
    service: MacroDerivedMetricsService,
) -> None:
    derived = service.all_derived()
    for summary in summaries.values():
        for driver in summary.get("drivers", []):
            key = driver.get("series_key")
            definition = get_series_definition(key) if key else None
            driver["display_name_zh"] = (definition or {}).get("display_name_zh") or _SUMMARY_LABELS.get(key, key)
            driver["unit"] = (definition or {}).get("unit")
            if not definition:
                continue

            if key in derived:
                rows = derived[key]
            else:
                rows = [
                    {"observation_date": observed, "value": value}
                    for observed, value in values.get(key, [])
                ]
            if not rows:
                continue

            target_date = driver.get("observation_date")
            current_index = len(rows) - 1
            if target_date is not None:
                target_iso = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
                matching = [
                    index for index, row in enumerate(rows)
                    if str(row.get("observation_date")) == target_iso
                ]
                if matching:
                    current_index = matching[-1]
            current = rows[current_index]
            comparison_offset = 1
            comparison_label = "上一可比观察期"
            if key == "us_yield_spread_10y_2y":
                comparison_offset = 20
                comparison_label = "20 个有效交易日前"
            elif key == "us_federal_funds_rate":
                one_month = rows[current_index - 21] if current_index >= 21 else None
                one_month_change = current["value"] - one_month["value"] if one_month else None
                if summary.get("state") in {"tightening", "easing"} and one_month_change is not None and abs(one_month_change) <= Decimal("0.05") and current_index >= 65:
                    comparison_offset = 65
                    comparison_label = "约 3 个月前"
                else:
                    comparison_offset = 21
                    comparison_label = "约 1 个月前"
            previous = rows[current_index - comparison_offset] if current_index >= comparison_offset else None
            driver["current_value"] = current.get("value")
            driver["current_observation_date"] = current.get("observation_date")
            driver["previous_value"] = previous.get("value") if previous else None
            driver["previous_observation_date"] = previous.get("observation_date") if previous else None
            driver["comparison_label_zh"] = comparison_label


def build_macro_summaries(db, values, service) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    gdp = _latest_derived(service, "us_real_gdp_yoy"); qoq = _latest_derived(service, "us_real_gdp_qoq"); qoq_prev = _previous_derived(service, "us_real_gdp_qoq")
    if not gdp or not qoq: summaries["growth"] = _state("unknown", "数据不足", "neutral", .0, [])
    elif qoq["value"] < 0 and qoq_prev and qoq_prev["value"] < 0: summaries["growth"] = _state("contracting", "增长收缩", "negative", .76, [{"series_key": "us_real_gdp_qoq", "observation_date": qoq["observation_date"], "effect": "negative", "reason": "实际 GDP 季度环比连续两期为负"}])
    elif qoq_prev and qoq["value"] < qoq_prev["value"]: summaries["growth"] = _state("slowing", "增长放缓", "mixed", .68, [{"series_key": "us_real_gdp_qoq", "observation_date": qoq["observation_date"], "effect": "negative", "reason": "实际 GDP 季度环比低于上一期"}])
    else: summaries["growth"] = _state("expanding", "增长扩张", "positive", .6, [{"series_key": "us_real_gdp_yoy", "observation_date": gdp["observation_date"], "effect": "positive", "reason": "实际 GDP 同比仍为可用正值"}])
    cpi = _latest_derived(service, "us_cpi_yoy"); cpi_prev = _previous_derived(service, "us_cpi_yoy")
    if not cpi: summaries["inflation"] = _state("unknown", "数据不足", "neutral", 0, [])
    elif cpi_prev and cpi["value"] < cpi_prev["value"]: summaries["inflation"] = _state("slowing", "通胀回落", "positive", .7, [{"series_key": "us_cpi_yoy", "observation_date": cpi["observation_date"], "effect": "positive", "reason": "CPI 同比低于上一可比观察期"}])
    elif cpi_prev and cpi["value"] > cpi_prev["value"]: summaries["inflation"] = _state("sticky", "通胀偏热", "negative", .7, [{"series_key": "us_cpi_yoy", "observation_date": cpi["observation_date"], "effect": "negative", "reason": "CPI 同比高于上一可比观察期"}])
    else: summaries["inflation"] = _state("mixed", "通胀信号混合", "mixed", .45, [])
    unemployment = _latest_derived(service, "us_unemployment_3m_avg"); payroll = _latest_derived(service, "us_nonfarm_payroll_3m_avg_change"); sahm = _latest_derived(service, "us_sahm_rule_gap")
    if not unemployment: summaries["labor"] = _state("unknown", "数据不足", "neutral", 0, [])
    elif sahm and sahm["value"] >= Decimal("0.5"): summaries["labor"] = _state("cooling", "就业降温，衰退风险提示", "negative", .78, [{"series_key": "us_sahm_rule_gap", "observation_date": sahm["observation_date"], "effect": "negative", "reason": "简化 Sahm Rule 差值达到 0.50 个百分点"}])
    elif payroll and payroll["value"] < 0: summaries["labor"] = _state("cooling", "就业降温", "mixed", .65, [{"series_key": "us_nonfarm_payroll_3m_avg_change", "observation_date": payroll["observation_date"], "effect": "negative", "reason": "非农就业三个月平均新增转为负值"}])
    else: summaries["labor"] = _state("steady", "就业稳健", "positive", .58, [{"series_key": "us_unemployment_3m_avg", "observation_date": unemployment["observation_date"], "effect": "positive", "reason": "失业率三个月均值仍有可用数据且未触发规则信号"}])
    fed_rows = values.get("us_federal_funds_rate") or []
    fed_change_1m = fed_rows[-1][1] - fed_rows[-22][1] if len(fed_rows) >= 22 else None
    fed_change_3m = fed_rows[-1][1] - fed_rows[-66][1] if len(fed_rows) >= 66 else None
    if fed_change_1m is None: summaries["policy"] = _state("unknown", "数据不足", "neutral", 0, [])
    elif fed_change_1m > Decimal("0.05") or (fed_change_3m is not None and fed_change_3m > Decimal("0.1")): summaries["policy"] = _state("tightening", "政策偏紧", "negative", .7, [{"series_key": "us_federal_funds_rate", "observation_date": fed_rows[-1][0], "effect": "negative", "reason": "联邦基金利率较近期观察期上升"}])
    elif fed_change_1m < Decimal("-0.05") or (fed_change_3m is not None and fed_change_3m < Decimal("-0.1")): summaries["policy"] = _state("easing", "政策转松", "positive", .7, [{"series_key": "us_federal_funds_rate", "observation_date": fed_rows[-1][0], "effect": "positive", "reason": "联邦基金利率较近期观察期下降"}])
    else: summaries["policy"] = _state("neutral", "维持高利率或方向不明", "neutral", .45, [])
    curve = _curve_analysis(service)
    summaries["yield_curve"] = _state(curve["state"], curve["label_zh"], "mixed" if "inversion" in curve["state"] or curve["state"] == "flattening" else "neutral", curve["confidence"], [{"series_key": "us_yield_spread_10y_2y", "observation_date": (service.values("us_treasury_10y") or [(None, None)])[-1][0], "effect": "mixed", "reason": reason} for reason in curve.get("reason_codes", [])])
    retail = _latest_derived(service, "us_retail_sales_yoy"); retail_prev = _previous_derived(service, "us_retail_sales_yoy")
    summaries["consumer"] = _state("unknown", "数据不足", "neutral", 0, []) if not retail else _state("moderate", "消费温和" if not retail_prev or retail["value"] >= retail_prev["value"] else "消费降温", "positive" if not retail_prev or retail["value"] >= retail_prev["value"] else "mixed", .55, [{"series_key": "us_retail_sales_yoy", "observation_date": retail["observation_date"], "effect": "mixed", "reason": "零售销售同比作为名义消费活动参考"}])
    known = [row for key, row in summaries.items() if key != "composite" and row["state"] != "unknown"]
    negative = sum(row["tone"] == "negative" for row in known); positive = sum(row["tone"] == "positive" for row in known)
    composite_label = "信号混合" if abs(negative - positive) <= 1 else "增长与消费偏强" if positive > negative else "增长/金融条件偏谨慎"
    summaries["composite"] = _state("mixed", composite_label, "mixed", .5, [{"series_key": key, "observation_date": None, "effect": row["tone"], "reason": row["label_zh"]} for key, row in summaries.items() if key != "composite" and row["state"] != "unknown"])
    _enrich_summary_drivers(summaries, values, service)
    return summaries


def build_overview(db) -> dict[str, Any]:
    settings = get_settings()
    values, series_rows, observations = load_macro_observations(db)
    service = MacroDerivedMetricsService(values)
    latest_run = db.scalar(select(MacroSyncRun).where(MacroSyncRun.provider == PROVIDER).order_by(MacroSyncRun.started_at.desc()).limit(1))
    latest_observation_date = max((row.observation_date for row in observations), default=None)
    fetched_at = max((row.last_fetched_at for row in observations if row.last_fetched_at), default=None)
    cards = []
    for key in CARD_KEYS:
        item = _definition_with_latest(db, key, values, series_rows, service)
        if item: cards.append(item)
    available = sum(1 for definition in RAW_SERIES if values.get(definition["series_key"]))
    errors = redact_provider_error(latest_run.error_summary_json) if latest_run and isinstance(latest_run.error_summary_json, dict) else {}
    usage = usage_status(db, settings).as_dict()
    configured = bool(settings.alpha_vantage_enabled and settings.alpha_vantage_api_key.strip())
    if not configured: source_status = "not_configured"
    elif latest_run and latest_run.status in {"failed", "partial_success"}: source_status = "partial_failure" if available else "failed"
    elif observations and latest_observation_date and (datetime.now(UTC).date() - latest_observation_date).days > 90: source_status = "stale"
    else: source_status = "healthy" if available else "no_data"
    last_full_success_at = db.scalar(
        select(MacroSyncRun.finished_at).where(
            MacroSyncRun.provider == PROVIDER,
            MacroSyncRun.status == "success",
            (
                (MacroSyncRun.requested_series_count >= len(RAW_SERIES))
                | (MacroSyncRun.trigger_type == "scheduled_retry")
            ),
        ).order_by(MacroSyncRun.finished_at.desc()).limit(1)
    )
    return _safe({
        "source": {"provider": PROVIDER, "name": SOURCE_NAME, "enabled": settings.alpha_vantage_enabled, "configured": configured, "status": source_status, "status_label_zh": {"not_configured": "未配置", "healthy": "正常", "partial_failure": "部分失败", "failed": "同步失败", "stale": "数据可能过期", "no_data": "暂无数据"}.get(source_status, source_status)},
        "last_sync_at": latest_run.finished_at if latest_run else None,
        "last_attempt_status": latest_run.status if latest_run else None,
        "last_successful_sync_at": last_full_success_at,
        "last_full_success_at": last_full_success_at,
        "latest_observation_date": latest_observation_date,
        "latest_fetched_at": fetched_at,
        "usage": usage,
        "summaries": build_macro_summaries(db, values, service),
        "cards": cards,
        "curve_analysis": _curve_analysis(service),
        "integrity": {"raw_series_count": len(RAW_SERIES), "available_series_count": available, "missing_series_keys": [definition["series_key"] for definition in RAW_SERIES if not values.get(definition["series_key"])], "latest_run_status": latest_run.status if latest_run else None, "errors": errors},
        "disclaimer": DISCLAIMER,
    })


def build_yield_curve(db) -> dict[str, Any]:
    values, _, _ = load_macro_observations(db)
    maturities = [("3M", "us_treasury_3m"), ("2Y", "us_treasury_2y"), ("5Y", "us_treasury_5y"), ("10Y", "us_treasury_10y"), ("30Y", "us_treasury_30y")]
    date_sets = [set(observed for observed, _ in values.get(key, [])) for _, key in maturities]
    common = sorted(set.intersection(*date_sets)) if all(date_sets) else []
    curves = []
    for label, offset in (("current", 0), ("1m", 20), ("3m", 60)):
        if len(common) <= offset: continue
        observed = common[-1 - offset]
        curves.append({"label": label, "observation_date": observed, "points": [{"maturity": maturity, "value": dict(values[key]).get(observed)} for maturity, key in maturities]})
    service = MacroDerivedMetricsService(values)
    return _safe({"maturities": [item[0] for item in maturities], "curves": curves, "spreads": {"10y_2y": service.yield_spread("us_treasury_10y", "us_treasury_2y"), "10y_3m": service.yield_spread("us_treasury_10y", "us_treasury_3m")}, "analysis": _curve_analysis(service), "disclaimer": DISCLAIMER})


def build_sync_status(db) -> dict[str, Any]:
    overview = build_overview(db)
    runs = db.scalars(select(MacroSyncRun).where(MacroSyncRun.provider == PROVIDER).order_by(MacroSyncRun.started_at.desc()).limit(20)).all()
    hour = max(0, min(23, int(get_settings().alpha_vantage_macro_sync_hour_utc)))
    return {"source": overview["source"], "usage": overview["usage"], "last_successful_sync_at": overview["last_successful_sync_at"], "last_attempt_at": overview["last_sync_at"], "last_attempt_status": overview["last_attempt_status"], "next_scheduled_sync": f"每日 {hour:02d}:00 UTC（Celery Beat due check）", "runs": [_safe({"id": row.id, "status": row.status, "started_at": row.started_at, "finished_at": row.finished_at, "requested_series_count": row.requested_series_count, "successful_series_count": row.successful_series_count, "failed_series_count": row.failed_series_count, "api_requests_used": row.api_requests_used, "inserted_count": row.inserted_count, "updated_count": row.updated_count, "unchanged_count": row.unchanged_count, "errors": redact_provider_error(row.error_summary_json), "trigger_type": row.trigger_type}) for row in runs], "disclaimer": DISCLAIMER}


def build_explanation(db, key: str) -> dict[str, Any] | None:
    detail = build_series_detail(db, key, limit=2, include_history=False)
    if detail is None: return None
    definition = get_series_definition(key) or {}
    latest = detail.get("latest")
    previous = detail.get("previous")
    current = None
    if latest and previous and previous.get("value") not in (None, 0):
        current = (Decimal(str(latest["value"])) / Decimal(str(previous["value"])) - 1) * 100
    impact, impact_label = _impact_label(key, Decimal(str(latest["value"])) if latest else None, current)
    return _safe({
        "series_key": key, "name_zh": definition.get("display_name_zh"), "name_en": definition.get("display_name_en"),
        "definition": definition.get("description_zh"), "current": latest, "previous": previous,
        "change": {"value": current, "label": "较前一观察期变化（仅作数值比较）"} if current is not None else None,
        "observation_date": latest.get("observation_date") if latest else None, "last_fetched_at": latest.get("last_fetched_at") if latest else None,
        "how_to_read": {"rising": definition.get("rising_interpretation"), "falling": definition.get("falling_interpretation")},
        "market_impact": [{"asset": ASSET_LABELS.get(asset, asset), "stance": stance, "reason": "影响取决于增长、通胀、利率与市场预期；模块不输出永久利多/利空。"} for asset, stance in (definition.get("affected_assets") or {}).items()],
        "current_system_judgment": {"label": impact, "label_zh": impact_label, "reason": "当前判断仅依据已存历史序列、相邻观察值和规则化派生指标。", "confidence": "中等" if current is not None else "未知"},
        "limitations": definition.get("context_notes", []) + ["当前没有市场一致预期数据，因此不显示‘超预期’或‘不及预期’。", DISCLAIMER],
        "source_attribution": SOURCE_NAME,
    })
