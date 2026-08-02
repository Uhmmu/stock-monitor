from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import MacroObservation, MacroSeries

from .derived import MacroDerivedMetricsService
from .sync import PROVIDER


def load_macro_observations(db) -> tuple[dict[str, list[tuple[date, Decimal]]], dict[str, MacroSeries], list[MacroObservation]]:
    rows = db.execute(
        select(MacroObservation, MacroSeries)
        .join(MacroSeries, MacroSeries.id == MacroObservation.series_id)
        .where(MacroSeries.provider == PROVIDER, MacroSeries.enabled.is_(True))
        .order_by(MacroSeries.series_key, MacroObservation.observation_date)
    ).all()
    values: dict[str, list[tuple[date, Decimal]]] = {}
    series: dict[str, MacroSeries] = {}
    observations: list[MacroObservation] = []
    for observation, definition in rows:
        values.setdefault(definition.series_key, []).append((observation.observation_date, Decimal(str(observation.value))))
        series[definition.series_key] = definition
        observations.append(observation)
    return values, series, observations


def _latest(values: list[tuple[date, Decimal]] | None) -> tuple[date, Decimal] | None:
    return values[-1] if values else None


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _latest_derived(derived: dict[str, list[dict[str, Any]]], key: str) -> dict[str, Any] | None:
    rows = derived.get(key) or []
    return rows[-1] if rows else None


def _trend(values: list[tuple[date, Decimal]], lookback: int = 3) -> str:
    if len(values) < 2:
        return "insufficient_data"
    window = values[-max(2, lookback):]
    delta = window[-1][1] - window[0][1]
    if abs(delta) < Decimal("0.0001"):
        return "stable"
    return "rising" if delta > 0 else "falling"


def _derived_trend(rows: list[dict[str, Any]], lookback: int = 3) -> str:
    if len(rows) < 2:
        return "insufficient_data"
    values = [Decimal(str(row["value"])) for row in rows[-max(2, lookback):]]
    delta = values[-1] - values[0]
    if abs(delta) < Decimal("0.0001"):
        return "stable"
    return "rising" if delta > 0 else "falling"


def _curve_analysis(service: MacroDerivedMetricsService) -> dict[str, Any]:
    spread = service.yield_spread("us_treasury_10y", "us_treasury_2y")
    spread_3m = service.yield_spread("us_treasury_10y", "us_treasury_3m")
    spread_30_5 = service.yield_spread("us_treasury_30y", "us_treasury_5y")
    if not spread:
        return {"state": "insufficient_data", "label_zh": "数据不足", "confidence": 0.0, "derived": True, "reason_codes": ["missing_yield_spread"]}
    current = spread[-1]["value"]
    previous_20 = spread[-21]["value"] if len(spread) >= 21 else None
    previous_60 = spread[-61]["value"] if len(spread) >= 61 else None
    long_rows = service.values("us_treasury_10y")
    short_rows = service.values("us_treasury_2y")
    long_change = long_rows[-1][1] - long_rows[-21][1] if len(long_rows) >= 21 else None
    short_change = short_rows[-1][1] - short_rows[-21][1] if len(short_rows) >= 21 else None
    reasons: list[str] = []
    if current < 0:
        if previous_20 is not None and current > previous_20:
            state, label = "inversion_repair", "倒挂修复中"
            reasons.append("10Y-2Y 仍为负但较 20 个有效交易日前收窄")
        elif previous_20 is not None and current < previous_20:
            state, label = "inversion_deepening", "倒挂加深"
            reasons.append("10Y-2Y 为负且较 20 个有效交易日前扩大")
        else:
            state, label = "inverted", "收益率曲线倒挂"
            reasons.append("10Y-2Y 当前为负")
    elif current < Decimal("0.15"):
        state, label = "flattening", "曲线趋平"
        reasons.append("10Y-2Y 为正但利差较窄")
    elif previous_20 is not None and current < previous_20:
        state, label = "flattening", "曲线趋平"
        reasons.append("10Y-2Y 较 20 个有效交易日前收窄")
    elif long_change is not None and short_change is not None and long_change < short_change:
        state, label = "bull_steepening", "牛市陡峭化"
        reasons.append("长端收益率较短端下降更多")
    elif long_change is not None and short_change is not None and long_change > short_change:
        state, label = "bear_steepening", "熊市陡峭化"
        reasons.append("长端收益率较短端上升更多")
    else:
        state, label = "normal", "正常曲线"
        reasons.append("10Y-2Y 为正且没有足够的方向性变化")
    return {
        "state": state, "label_zh": label, "confidence": 0.72 if previous_20 is not None else 0.42,
        "derived": True, "reason_codes": reasons, "spread_10y_2y": _float(current),
        "spread_10y_2y_20d": _float(current - previous_20) if previous_20 is not None else None,
        "spread_10y_2y_60d": _float(current - previous_60) if previous_60 is not None else None,
        "spread_10y_3m": _float(spread_3m[-1]["value"]) if spread_3m else None,
        "spread_30y_5y": _float(spread_30_5[-1]["value"]) if spread_30_5 else None,
        "short_change_20d": _float(short_change), "long_change_20d": _float(long_change),
    }


def build_latest_us_macro_context(db=None) -> dict[str, Any]:
    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    try:
        values, series, observations = load_macro_observations(db)
        derived_service = MacroDerivedMetricsService(values)
        derived = derived_service.all_derived()
        fetched_at = max((row.last_fetched_at for row in observations if row.last_fetched_at), default=None)
        raw = {key: _latest(rows) for key, rows in values.items()}
        real_gdp_yoy = _latest_derived(derived, "us_real_gdp_yoy")
        cpi_yoy = _latest_derived(derived, "us_cpi_yoy")
        cpi_mom = _latest_derived(derived, "us_cpi_mom")
        payroll = _latest_derived(derived, "us_nonfarm_payroll_change")
        retail_yoy = _latest_derived(derived, "us_retail_sales_yoy")
        fed = raw.get("us_federal_funds_rate")
        fed_rows = values.get("us_federal_funds_rate", [])
        fed_1m = fed_rows[-22][1] if len(fed_rows) >= 22 else (fed_rows[0][1] if fed_rows else None)
        fed_3m = fed_rows[-66][1] if len(fed_rows) >= 66 else (fed_rows[0][1] if fed_rows else None)
        unemployment = raw.get("us_unemployment_rate")
        unemployment_avg = _latest_derived(derived, "us_unemployment_3m_avg")
        curve = _curve_analysis(derived_service)
        context = {
            "as_of": fetched_at,
            "source": "alpha_vantage",
            "source_name": "Alpha Vantage（数据标注的美国官方/FRED序列）",
            "growth": {"real_gdp_yoy": _float(real_gdp_yoy["value"] if real_gdp_yoy else None), "trend": _derived_trend(derived.get("us_real_gdp_yoy", [])), "observation_date": real_gdp_yoy["observation_date"] if real_gdp_yoy else None},
            "inflation": {"cpi_yoy": _float(cpi_yoy["value"] if cpi_yoy else None), "cpi_mom": _float(cpi_mom["value"] if cpi_mom else None), "trend": _derived_trend(derived.get("us_cpi_yoy", [])), "observation_date": cpi_yoy["observation_date"] if cpi_yoy else None},
            "labor": {"unemployment_rate": _float(unemployment[1] if unemployment else None), "unemployment_3m_average": _float(unemployment_avg["value"] if unemployment_avg else None), "nonfarm_change": _float(payroll["value"] if payroll else None), "trend": _derived_trend(derived.get("us_unemployment_3m_avg", [])), "observation_date": (payroll or unemployment_avg or {}).get("observation_date") if isinstance(payroll or unemployment_avg, dict) else (unemployment[0] if unemployment else None)},
            "rates": {"fed_funds_rate": _float(fed[1] if fed else None), "fed_funds_change_1m": _float((fed[1] - fed_1m) if fed and fed_1m is not None else None), "fed_funds_change_3m": _float((fed[1] - fed_3m) if fed and fed_3m is not None else None), "treasury_2y": _float(raw.get("us_treasury_2y", (None, None))[1]), "treasury_10y": _float(raw.get("us_treasury_10y", (None, None))[1]), "spread_10y_2y": curve.get("spread_10y_2y"), "curve_state": curve.get("state", "insufficient_data")},
            "consumer": {"retail_sales_yoy": _float(retail_yoy["value"] if retail_yoy else None), "trend": _derived_trend(derived.get("us_retail_sales_yoy", [])), "observation_date": retail_yoy["observation_date"] if retail_yoy else None},
            "warnings": ["指标观察日期并不一致", "未接入市场一致预期数据", "宏观摘要为规则化信息，不构成投资建议"],
        }
        return _json_safe(context)
    finally:
        if owns_db:
            db.close()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
