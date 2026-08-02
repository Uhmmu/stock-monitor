"""Deterministic, current-position portfolio health aggregation.

The service reads persisted prices, financial statements, valuation snapshots,
profiles, security metadata, and structured SEC filing items. It never refreshes
analysis data and never calls an LLM. Missing data stays missing and is surfaced
through market-value coverage rather than being converted to a zero score.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import pstdev
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FinancialStatementSnapshot,
    Portfolio,
    SecFiling,
    Security,
    StockProfile,
    ValuationSnapshot,
)

from .performance import build_summary

NEUTRAL_SCORE = 50.0
PARTIAL_COVERAGE = 60.0
SUFFICIENT_COVERAGE = 80.0
VALUATION_STALE_DAYS = 45
FUNDAMENTAL_STALE_DAYS = 550
SEC_STALE_DAYS = 550
SEC_FLAG_LOOKBACK_DAYS = 730

CONCENTRATION_THRESHOLDS = {
    "largest_elevated": 25.0,
    "largest_high": 35.0,
    "top_three_high": 70.0,
    "sector_elevated": 45.0,
    "sector_high": 60.0,
}

HEALTH_COMPONENT_WEIGHTS = {
    "fundamental_quality": 0.35,
    "valuation_safety": 0.25,
    "financial_resilience": 0.15,
    "concentration_safety": 0.15,
    "sec_safety": 0.10,
}

SEC_ITEM_FLAGS = {
    "1.05": ("cybersecurity_incident", "重大网络安全事故", "high", 70.0),
    "2.03": ("debt_covenant_risk", "新增重大债务", "warning", 35.0),
    "2.04": ("debt_covenant_risk", "债务加速到期", "high", 80.0),
    "3.01": ("regulatory_compliance", "上市规则不合规", "high", 75.0),
    "3.02": ("share_dilution", "股权稀释", "warning", 45.0),
    "4.01": ("auditor_change", "更换会计师事务所", "warning", 40.0),
    "4.02": ("restatement", "过往财报不可信", "high", 85.0),
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _ratio(numerator: Any, denominator: Any) -> float | None:
    left, right = _number(numerator), _number(denominator)
    return left / right if left is not None and right not in (None, 0) else None


def _linear_score(value: float | None, weak: float, strong: float) -> float | None:
    if value is None:
        return None
    if weak == strong:
        return NEUTRAL_SCORE
    return _clamp((value - weak) / (strong - weak) * 100)


def _average(values: Iterable[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return sum(valid) / len(valid) if valid else None


def _grade(score: float | None) -> str:
    if score is None:
        return "数据不足"
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "良好"
    if score >= 70:
        return "尚可"
    if score >= 60:
        return "偏弱"
    return "风险较高"


def _risk_grade(score: float | None) -> str:
    if score is None:
        return "数据不足"
    if score <= 20:
        return "很低"
    if score <= 40:
        return "较低"
    if score <= 60:
        return "中等"
    if score <= 80:
        return "较高"
    return "很高"


def _coverage_status(weight: float) -> str:
    if weight >= SUFFICIENT_COVERAGE:
        return "sufficient"
    if weight >= PARTIAL_COVERAGE:
        return "partial"
    return "insufficient"


def _days_old(value: date | datetime | str | None, today: date) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
        except ValueError:
            return None
    current = value.date() if isinstance(value, datetime) else value
    return max(0, (today - current).days)


def _freshness(ages: list[int], stale_after: int) -> str:
    if not ages:
        return "unavailable"
    stale = sum(age > stale_after for age in ages)
    if stale == len(ages):
        return "stale"
    if stale:
        return "mixed"
    return "fresh"


def _coverage_dimension(
    positions: list[dict],
    covered: set[str],
    *,
    freshness: str,
    excluded: set[str] | None = None,
    confidence: float | None = None,
    basis: str = "market_value",
) -> dict:
    excluded = excluded or set()
    total_value = sum(_number(row.get("base_currency_market_value")) or 0 for row in positions)
    covered_value = sum(
        _number(row.get("base_currency_market_value")) or 0
        for row in positions
        if row["symbol"] in covered
    )
    if basis == "position_count":
        total = len(positions)
        weight = len(covered) / total * 100 if total else 0.0
    else:
        weight = covered_value / total_value * 100 if total_value > 0 else 0.0
    symbols = {row["symbol"] for row in positions}
    uncovered = symbols - covered - excluded
    resolved_confidence = confidence if confidence is not None else weight / 100
    return {
        "covered_weight": round(weight, 2),
        "uncovered_weight": round(max(0.0, 100 - weight), 2),
        "covered_market_value": round(covered_value, 4),
        "uncovered_market_value": round(max(0.0, total_value - covered_value), 4),
        "covered_symbols": sorted(covered),
        "uncovered_symbols": sorted(uncovered),
        "excluded_symbols": sorted(excluded),
        "freshness": freshness,
        "confidence": round(_clamp(resolved_confidence, 0, 1), 3),
        "status": _coverage_status(weight),
        "basis": basis,
    }


def _latest_by_ticker(rows: Iterable[Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for row in rows:
        latest.setdefault(row.ticker, row)
    return latest


def _group_statement_rows(rows: Iterable[FinancialStatementSnapshot]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if len(grouped[row.ticker]) >= 2:
            continue
        try:
            balance = dict(row.balance_sheet or {})
            balance["stockholders_equity"] = balance.get("shareholders_equity", balance.get("stockholders_equity"))
            grouped[row.ticker].append({
                "date": row.period_end,
                "synced_at": row.synced_at,
                **dict(row.income_statement or {}),
                **balance,
                **dict(row.cash_flow or {}),
            })
        except (TypeError, ValueError):
            # One malformed snapshot must not suppress valid analysis for other symbols.
            continue
    return grouped


def _metric(payload: dict, group: str, key: str) -> dict | None:
    items = payload.get(group)
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("key") == key:
            status = item.get("status")
            if status in {"insufficient", "not_applicable"}:
                return None
            return item
    return None


def _metric_value(payload: dict, group: str, key: str) -> float | None:
    item = _metric(payload, group, key)
    return _number(item.get("value")) if item else None


def _current_ratio_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 1:
        return _linear_score(value, 0.4, 1.2)
    if value <= 3:
        return _linear_score(value, 0.5, 2.0)
    return _clamp(90 - (value - 3) * 5)


def _fundamental_snapshot(payload: dict, periods: list[dict]) -> dict | None:
    try:
        current = periods[0] if periods else {}
        revenue = _number(current.get("revenue"))
        gross_margin = _ratio(current.get("gross_profit"), revenue)
        operating_margin = _ratio(current.get("operating_income"), revenue)
        net_margin = _ratio(current.get("net_income"), revenue)
        fcf = _number(current.get("free_cash_flow"))
        if fcf is None:
            fcf = _number(current.get("operating_cash_flow"))
        fcf_margin = _ratio(fcf, revenue)
        cash_conversion = _ratio(current.get("operating_cash_flow"), current.get("net_income"))

        profitability = _average([
            _linear_score(gross_margin, 0.10, 0.60),
            _linear_score(operating_margin, -0.05, 0.30),
            _linear_score(net_margin, -0.05, 0.25),
        ])
        growth = _average([
            _linear_score(_metric_value(payload, "growth", "revenue_growth"), -10, 25),
            _linear_score(_metric_value(payload, "growth", "eps_growth"), -20, 30),
        ])
        cashflow = _average([
            _linear_score(fcf_margin, -0.05, 0.25),
            _linear_score(cash_conversion, 0.5, 1.5),
        ])

        piotroski = _metric(payload, "health", "piotroski")
        piotroski_score = None
        if piotroski:
            components = _number(piotroski.get("available_components")) or 9
            value = _number(piotroski.get("value"))
            if value is not None and components > 0:
                piotroski_score = _clamp(value / components * 100)
        balance_sheet = _average([
            _current_ratio_score(_metric_value(payload, "health", "current_ratio")),
            _linear_score(_metric_value(payload, "health", "altman_z"), 1.0, 4.0),
            piotroski_score,
        ])
        capital_efficiency = _average([
            _linear_score(_metric_value(payload, "health", "roe"), 0, 25),
            _linear_score(_metric_value(payload, "health", "roic"), 0, 20),
        ])
        subscores = {
            "profitability": profitability,
            "growth": growth,
            "cashflow_quality": cashflow,
            "balance_sheet_health": balance_sheet,
            "capital_efficiency": capital_efficiency,
        }
        score = _average(subscores.values())
        if score is None:
            return None
        available = sum(value is not None for value in subscores.values())
        return {
            "score": round(score, 2),
            "subscores": {key: _round(value) for key, value in subscores.items()},
            "data_completeness": round(available / len(subscores), 3),
        }
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _valuation_snapshot(payload: dict, *, stale: bool) -> dict | None:
    try:
        signals = payload.get("model_signals")
        if not isinstance(signals, list):
            return None
        configured_weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else {}
        risks: list[tuple[float, float]] = []
        available_weight = 0.0
        configured_total = sum(max(0.0, _number(value) or 0.0) for value in configured_weights.values())
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            stars = _number(signal.get("stars"))
            if stars is None or not 1 <= stars <= 5:
                continue
            weight = max(0.0, _number(configured_weights.get(signal.get("key"))) or 0.0)
            if configured_total <= 0:
                weight = 1.0
            if weight <= 0:
                continue
            risks.append(((5 - stars) * 25, weight))
            available_weight += weight
        if not risks or available_weight <= 0:
            return None
        score = sum(risk * weight for risk, weight in risks) / available_weight
        model_coverage = min(1.0, available_weight / configured_total) if configured_total > 0 else min(1.0, len(risks) / 3)
        spread = pstdev([risk for risk, _ in risks]) if len(risks) > 1 else 25.0
        agreement = _clamp(1 - spread / 60, 0, 1)
        confidence = model_coverage * (0.55 + 0.45 * agreement)
        if stale:
            confidence *= 0.6
        return {"score": round(score, 2), "confidence": round(confidence, 3), "model_count": len(risks)}
    except (AttributeError, TypeError, ValueError):
        return None


def _is_company(position: dict, security: Security | None, valuation: ValuationSnapshot | None) -> bool:
    instrument_type = str(security.instrument_type or "").upper() if security else ""
    if any(value in instrument_type for value in ("ETF", "FUND", "MUTUAL", "INDEX", "CRYPTO")):
        return False
    if instrument_type:
        return instrument_type in {"EQUITY", "STOCK", "ADR"}
    payload = valuation.payload if valuation and isinstance(valuation.payload, dict) else {}
    return bool(payload.get("company") or payload.get("classification"))


def _weighted_score(stock_rows: list[dict], field: str, total_market_value: float) -> tuple[float | None, float]:
    valid = [row for row in stock_rows if _number(row.get(field)) is not None]
    covered_value = sum(row["market_value"] for row in valid)
    if covered_value <= 0:
        return None, 0.0
    score = sum(row["market_value"] * row[field] for row in valid) / covered_value
    coverage = covered_value / total_market_value * 100 if total_market_value > 0 else 0.0
    return round(score, 2), round(coverage, 2)


def _contributors(stock_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    rows = [{
        "symbol": row["symbol"],
        "score": round(row["fundamental_score"], 2),
        "weight": round(row["weight"], 2),
        "contribution": round(row["weight"] / 100 * (row["fundamental_score"] - NEUTRAL_SCORE), 2),
    } for row in stock_rows if row.get("fundamental_score") is not None]
    positive = sorted((row for row in rows if row["contribution"] > 0), key=lambda row: row["contribution"], reverse=True)[:3]
    negative = sorted((row for row in rows if row["contribution"] < 0), key=lambda row: row["contribution"])[:3]
    return positive, negative


def _bucket(values: dict[str, float], total: float, label_key: str) -> list[dict]:
    return [
        {label_key: label, "market_value": round(value, 4), "weight": round(value / total * 100, 2)}
        for label, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
    ] if total > 0 else []


def _concentration(
    positions: list[dict],
    total: float,
    profiles: dict[str, StockProfile],
    securities: dict[int, Security],
    valuations: dict[str, ValuationSnapshot],
) -> dict:
    if total <= 0 or not positions:
        return {
            "available": False,
            "reason": "暂无可估值持仓，无法计算集中度。",
            "risk_score": None,
            "largest_position_weight": None,
            "top_two_weight": None,
            "top_three_weight": None,
            "top_five_weight": None,
            "hhi": None,
            "hhi_scaled": None,
            "effective_holdings": None,
            "effective_position_count": None,
            "holdings_count": 0,
            "sector_weights": [], "industry_weights": [], "country_weights": [], "currency_weights": [],
        }
    weighted = sorted(
        ((row["base_currency_market_value"] / total * 100, row) for row in positions),
        key=lambda item: item[0],
    )
    ordered = [value for value, _ in reversed(weighted)]
    fractions = [value / 100 for value in ordered]
    hhi = sum(value * value for value in fractions)

    sector_values: dict[str, float] = defaultdict(float)
    industry_values: dict[str, float] = defaultdict(float)
    country_values: dict[str, float] = defaultdict(float)
    currency_values: dict[str, float] = defaultdict(float)
    for row in positions:
        profile = profiles.get(row["symbol"])
        valuation = valuations.get(row["symbol"])
        payload = valuation.payload if valuation and isinstance(valuation.payload, dict) else {}
        classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
        security = securities.get(row.get("security_id"))
        sector = (profile.official_sector if profile else None) or classification.get("sector") or "未分类"
        industry = (profile.official_industry if profile else None) or classification.get("industry") or "未分类"
        country = (security.country_code if security else None) or "未分类"
        value = row["base_currency_market_value"]
        sector_values[str(sector)] += value
        industry_values[str(industry)] += value
        country_values[str(country)] += value
        currency_values[row.get("currency") or "未分类"] += value

    largest = ordered[0]
    top_three = sum(ordered[:3])
    max_sector = max((value / total * 100 for key, value in sector_values.items() if key != "未分类"), default=0.0)
    largest_risk = _clamp(largest / CONCENTRATION_THRESHOLDS["largest_high"] * 100)
    top_three_risk = _clamp(top_three / CONCENTRATION_THRESHOLDS["top_three_high"] * 100)
    sector_risk = _clamp(max_sector / CONCENTRATION_THRESHOLDS["sector_high"] * 100)
    hhi_risk = _clamp((hhi - 0.10) / 0.40 * 100)
    risk = _average([largest_risk, top_three_risk, sector_risk, hhi_risk])
    return {
        "available": True,
        "risk_score": _round(risk),
        "grade": _risk_grade(risk),
        "largest_position_weight": round(largest, 2),
        "top_two_weight": round(sum(ordered[:2]), 2),
        "top_three_weight": round(top_three, 2),
        "top_five_weight": round(sum(ordered[:5]), 2),
        "hhi": round(hhi, 6),
        "hhi_scaled": round(hhi * 10000, 2),
        "effective_holdings": round(1 / hhi, 2) if hhi > 0 else None,
        "effective_position_count": round(1 / hhi, 2) if hhi > 0 else None,
        "holdings_count": len(positions),
        "sector_weights": _bucket(sector_values, total, "sector"),
        "industry_weights": _bucket(industry_values, total, "industry"),
        "country_weights": _bucket(country_values, total, "country"),
        "currency_weights": _bucket(currency_values, total, "currency"),
    }


def _sec_analysis(
    positions: list[dict],
    filings: list[SecFiling],
    applicable: set[str],
    excluded: set[str],
    total: float,
    today: date,
) -> tuple[dict, dict]:
    grouped: dict[str, list[SecFiling]] = defaultdict(list)
    for filing in filings:
        grouped[filing.ticker].append(filing)
    covered = {symbol for symbol in applicable if grouped.get(symbol)}
    ages = [_days_old(max(grouped[symbol], key=lambda row: row.filing_date).filing_date, today) for symbol in covered]
    clean_ages = [age for age in ages if age is not None]

    position_map = {row["symbol"]: row for row in positions}
    flag_symbols: dict[str, set[str]] = defaultdict(set)
    flag_details: dict[str, tuple[str, str, float]] = {}
    symbol_flags: dict[str, dict[str, float]] = defaultdict(dict)
    cutoff = today - timedelta(days=SEC_FLAG_LOOKBACK_DAYS)
    for symbol in covered:
        for filing in grouped[symbol]:
            if filing.filing_date < cutoff:
                continue
            codes = [code.strip() for code in str(filing.items or "").split(",") if code.strip()]
            for code in codes:
                mapped = SEC_ITEM_FLAGS.get(code)
                if not mapped:
                    continue
                flag, label, severity, risk = mapped
                flag_symbols[flag].add(symbol)
                flag_details[flag] = (label, severity, risk)
                symbol_flags[symbol][flag] = max(symbol_flags[symbol].get(flag, 0), risk)

    exposures = []
    for flag, symbols in flag_symbols.items():
        value = sum(position_map[symbol]["base_currency_market_value"] for symbol in symbols if symbol in position_map)
        label, severity, _ = flag_details[flag]
        exposures.append({
            "flag": flag, "label": label, "severity": severity,
            "weight": round(value / total * 100, 2) if total > 0 else 0.0,
            "affected_symbols": sorted(symbols),
        })
    exposures.sort(key=lambda row: ({"high": 2, "warning": 1}.get(row["severity"], 0), row["weight"]), reverse=True)

    affected_positions = []
    sec_score_rows = []
    for symbol in covered:
        risks = symbol_flags.get(symbol, {})
        risk_score = min(100.0, sum(risks.values())) if risks else 0.0
        row = position_map[symbol]
        sec_score_rows.append({"market_value": row["base_currency_market_value"], "score": risk_score})
        if risks:
            affected_positions.append({
                "symbol": symbol, "weight": row["weight"], "risk_score": risk_score,
                "flags": sorted(risks),
            })
    covered_value = sum(position_map[symbol]["base_currency_market_value"] for symbol in covered if symbol in position_map)
    score = (
        sum(row["market_value"] * row["score"] for row in sec_score_rows) / covered_value
        if covered_value > 0 else None
    )
    coverage = _coverage_dimension(
        positions, covered, excluded=excluded, freshness=_freshness(clean_ages, SEC_STALE_DAYS),
        confidence=(covered_value / total if total > 0 else 0.0),
    )
    return {
        "score": _round(score), "grade": _risk_grade(score),
        "coverage_weight": coverage["covered_weight"],
        "flag_exposures": exposures,
        "affected_positions": sorted(affected_positions, key=lambda row: row["weight"], reverse=True),
        "highest_severity_flags": [row for row in exposures if row["severity"] == "high"],
    }, coverage


def _finding(
    id_: str, category: str, severity: str, title: str, message: str,
    *, evidence: dict | None = None, symbols: list[str] | None = None,
    weight: float = 0.0, priority: int = 50,
) -> dict:
    return {
        "id": id_, "category": category, "severity": severity, "title": title, "message": message,
        "evidence": evidence or {}, "affected_symbols": symbols or [],
        "affected_weight": round(weight, 2), "priority": priority,
    }


def _findings(
    fundamental: dict, valuation: dict, sec: dict, concentration: dict,
    coverage: dict, stale_symbols: set[str], positions: list[dict],
) -> list[dict]:
    rows: list[dict] = []
    for key, label in (("fundamental", "基本面"), ("valuation", "估值"), ("sec", "SEC")):
        item = coverage[key]
        if item["covered_weight"] < PARTIAL_COVERAGE:
            rows.append(_finding(
                f"{key}_coverage_low", "coverage", "warning", f"{label}数据覆盖不足",
                f"当前{label}数据仅覆盖 {item['covered_weight']:.0f}% 的已估值持仓市值，暂不形成明确结论。",
                evidence={"coverage_weight": item["covered_weight"]}, symbols=item["uncovered_symbols"],
                weight=item["uncovered_weight"], priority=95,
            ))
    price = coverage["price"]
    if price["covered_weight"] < 100:
        rows.append(_finding(
            "price_coverage_gap", "data_quality", "warning", "部分当前持仓缺少可用价格",
            "缺少价格或汇率的持仓未进入市值加权分析。",
            evidence={"coverage": price["covered_weight"]}, symbols=price["uncovered_symbols"],
            weight=price["uncovered_weight"], priority=100,
        ))
    if stale_symbols:
        rows.append(_finding(
            "stale_analysis", "data_quality", "warning", "部分分析快照已过期",
            "以下持仓仍使用已有快照，但可信度已下调。",
            symbols=sorted(stale_symbols), priority=90,
        ))

    f_score, v_score = fundamental.get("score"), valuation.get("score")
    if fundamental["coverage_weight"] >= PARTIAL_COVERAGE and valuation["coverage_weight"] >= PARTIAL_COVERAGE:
        if f_score is not None and v_score is not None and f_score >= 85 and v_score <= 40:
            rows.append(_finding(
                "quality_value_aligned", "quality", "positive", "质量与估值相互支持",
                "当前覆盖范围内的持仓质量较高，组合估值风险仍处于可控区间。",
                evidence={"fundamental_score": f_score, "valuation_risk": v_score}, priority=80,
            ))
        elif f_score is not None and v_score is not None and f_score >= 85 and v_score >= 65:
            rows.append(_finding(
                "quality_expensive", "valuation", "warning", "企业质量较高，但估值风险偏高",
                "组合的基本面质量较强，当前定价对长期回报的容错空间相对有限。",
                evidence={"fundamental_score": f_score, "valuation_risk": v_score}, priority=85,
            ))
        elif f_score is not None and v_score is not None and f_score < 70 and v_score >= 60:
            rows.append(_finding(
                "quality_value_weak", "quality", "high", "质量与估值同时承压",
                "当前覆盖范围内同时出现基本面偏弱和估值风险偏高的组合特征。",
                evidence={"fundamental_score": f_score, "valuation_risk": v_score}, priority=100,
            ))

    largest = concentration.get("largest_position_weight") or 0
    top_three = concentration.get("top_three_weight") or 0
    if largest > CONCENTRATION_THRESHOLDS["largest_high"]:
        symbol = max(positions, key=lambda row: row["weight"])["symbol"] if positions else ""
        rows.append(_finding(
            "largest_position_high", "concentration", "high", "单一持仓集中度较高",
            f"最大持仓占已估值组合 {largest:.1f}%，其变化会显著影响组合整体。",
            evidence={"largest_position_weight": largest}, symbols=[symbol] if symbol else [],
            weight=largest, priority=100,
        ))
    elif largest > CONCENTRATION_THRESHOLDS["largest_elevated"]:
        rows.append(_finding(
            "largest_position_elevated", "concentration", "warning", "单一持仓集中度偏高",
            f"最大持仓占已估值组合 {largest:.1f}%。",
            evidence={"largest_position_weight": largest}, weight=largest, priority=85,
        ))
    if top_three > CONCENTRATION_THRESHOLDS["top_three_high"]:
        top_symbols = [row["symbol"] for row in sorted(positions, key=lambda row: row["weight"], reverse=True)[:3]]
        rows.append(_finding(
            "top_three_high", "concentration", "high", "前三大持仓集中度较高",
            f"前三大持仓合计占 {top_three:.1f}%，组合结果较依赖少数标的。",
            evidence={"top_three_weight": top_three}, symbols=top_symbols, weight=top_three, priority=95,
        ))
    sectors = [row for row in concentration.get("sector_weights", []) if row["sector"] != "未分类"]
    if sectors:
        top_sector = sectors[0]
        if top_sector["weight"] > CONCENTRATION_THRESHOLDS["sector_high"]:
            rows.append(_finding(
                "sector_high", "allocation", "high", "行业集中风险较高",
                f"{top_sector['sector']}占已估值组合 {top_sector['weight']:.1f}%。",
                evidence=top_sector, weight=top_sector["weight"], priority=90,
            ))
        elif top_sector["weight"] > CONCENTRATION_THRESHOLDS["sector_elevated"]:
            rows.append(_finding(
                "sector_elevated", "allocation", "warning", "行业集中度偏高",
                f"{top_sector['sector']}占已估值组合 {top_sector['weight']:.1f}%。",
                evidence=top_sector, weight=top_sector["weight"], priority=80,
            ))

    for exposure in sec.get("flag_exposures", []):
        if exposure["flag"] == "share_dilution" and exposure["weight"] <= 20:
            continue
        severity = "high" if exposure["severity"] == "high" else "warning"
        rows.append(_finding(
            f"sec_{exposure['flag']}", "sec", severity, f"{exposure['label']}风险暴露",
            f"相关持仓占已估值组合 {exposure['weight']:.1f}%，来源为近两年结构化 SEC 事件。",
            evidence={"flag": exposure["flag"], "exposure_weight": exposure["weight"]},
            symbols=exposure["affected_symbols"], weight=exposure["weight"], priority=90,
        ))
    severity_rank = {"high": 4, "warning": 3, "positive": 2, "info": 1}
    return sorted(rows, key=lambda row: (
        severity_rank.get(row["severity"], 0), row["affected_weight"], row["priority"]
    ), reverse=True)


def _overall_health(fundamental: dict, valuation: dict, sec: dict, concentration: dict) -> dict:
    components: dict[str, tuple[float | None, float, float]] = {
        "fundamental_quality": (
            fundamental.get("score"), HEALTH_COMPONENT_WEIGHTS["fundamental_quality"],
            fundamental.get("coverage_weight", 0) / 100,
        ),
        "valuation_safety": (
            100 - valuation["score"] if valuation.get("score") is not None else None,
            HEALTH_COMPONENT_WEIGHTS["valuation_safety"], valuation.get("coverage_weight", 0) / 100,
        ),
        "financial_resilience": (
            _average([
                (fundamental.get("subscores") or {}).get("cashflow_quality", {}).get("score"),
                (fundamental.get("subscores") or {}).get("balance_sheet_health", {}).get("score"),
            ]),
            HEALTH_COMPONENT_WEIGHTS["financial_resilience"], fundamental.get("coverage_weight", 0) / 100,
        ),
        "concentration_safety": (
            100 - concentration["risk_score"] if concentration.get("risk_score") is not None else None,
            HEALTH_COMPONENT_WEIGHTS["concentration_safety"], 1.0 if concentration.get("available") else 0.0,
        ),
        "sec_safety": (
            100 - sec["score"] if sec.get("score") is not None else None,
            HEALTH_COMPONENT_WEIGHTS["sec_safety"], sec.get("coverage_weight", 0) / 100,
        ),
    }
    included = [key for key, (score, _, coverage) in components.items() if score is not None and coverage * 100 >= PARTIAL_COVERAGE]
    excluded = [key for key in components if key not in included]
    weight_sum = sum(components[key][1] for key in included)
    confidence = (
        sum(components[key][1] * components[key][2] for key in included) / weight_sum
        if weight_sum else 0.0
    )
    has_core = any(key in included for key in ("fundamental_quality", "valuation_safety"))
    score = (
        sum(components[key][0] * components[key][1] for key in included) / weight_sum
        if weight_sum and has_core and confidence >= 0.5 else None
    )
    return {
        "score": _round(score), "grade": _grade(score), "confidence": round(confidence, 3),
        "included_components": included, "excluded_components": excluded,
    }


def build_health(db: Session, portfolio: Portfolio) -> dict:
    """Aggregate latest persisted analysis for this portfolio's open positions."""
    now = datetime.now(UTC)
    today = now.date()
    # Health is a database/cached-data aggregation and must never initiate FX IO.
    summary = build_summary(db, portfolio, cached_fx_only=True)
    priced = [row for row in summary["positions"] if row["valuation_available"] and row["base_currency_market_value"] > 0]
    total = summary["total_market_value"]
    for row in priced:
        row["weight"] = row["base_currency_market_value"] / total * 100 if total > 0 else 0.0
    symbols = [row["symbol"] for row in priced]

    security_ids = {row["security_id"] for row in priced if row.get("security_id")}
    securities = {
        row.id: row for row in db.scalars(select(Security).where(Security.id.in_(security_ids))).all()
    } if security_ids else {}
    profiles = {
        row.ticker: row for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all()
    } if symbols else {}
    valuation_rows = list(db.scalars(
        select(ValuationSnapshot).where(ValuationSnapshot.ticker.in_(symbols))
        .order_by(ValuationSnapshot.ticker, ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc())
    ).all()) if symbols else []
    valuations = _latest_by_ticker(valuation_rows)
    statement_rows = list(db.scalars(
        select(FinancialStatementSnapshot).where(
            FinancialStatementSnapshot.ticker.in_(symbols), FinancialStatementSnapshot.frequency == "annual",
        ).order_by(FinancialStatementSnapshot.ticker, FinancialStatementSnapshot.period_end.desc())
    ).all()) if symbols else []
    statements = _group_statement_rows(statement_rows)
    filings = list(db.scalars(
        select(SecFiling).where(SecFiling.ticker.in_(symbols))
        .order_by(SecFiling.ticker, SecFiling.filing_date.desc())
    ).all()) if symbols else []

    company_symbols: set[str] = set()
    excluded_company_symbols: set[str] = set()
    fundamental_rows: list[dict] = []
    valuation_rows_out: list[dict] = []
    fundamental_ages: list[int] = []
    valuation_ages: list[int] = []
    stale_symbols: set[str] = set()
    for position in priced:
        symbol = position["symbol"]
        valuation = valuations.get(symbol)
        security = securities.get(position.get("security_id"))
        is_company = _is_company(position, security, valuation) or (
            security is None and (symbol in profiles or symbol in statements)
        )
        if not is_company:
            excluded_company_symbols.add(symbol)
            continue
        company_symbols.add(symbol)
        payload = valuation.payload if valuation and isinstance(valuation.payload, dict) else {}
        fundamental = _fundamental_snapshot(payload, statements.get(symbol, []))
        latest_statement = statements.get(symbol, [{}])[0]
        source_dates = [latest_statement.get("synced_at"), latest_statement.get("date")]
        if valuation:
            source_dates.append(valuation.updated_at)
        source_ages = [_days_old(value, today) for value in source_dates if value is not None]
        fundamental_age = max((age for age in source_ages if age is not None), default=None)
        if fundamental and fundamental_age is not None:
            fundamental_ages.append(fundamental_age)
            if fundamental_age > FUNDAMENTAL_STALE_DAYS:
                stale_symbols.add(symbol)
            fundamental_rows.append({
                "symbol": symbol, "market_value": position["base_currency_market_value"], "weight": position["weight"],
                "fundamental_score": fundamental["score"], "subscores": fundamental["subscores"],
                "data_completeness": fundamental["data_completeness"],
            })

        valuation_age = _days_old(valuation.snapshot_date if valuation else None, today)
        is_stale = valuation_age is not None and valuation_age > VALUATION_STALE_DAYS
        result = _valuation_snapshot(payload, stale=is_stale) if valuation else None
        if result and valuation_age is not None:
            valuation_ages.append(valuation_age)
            if is_stale:
                stale_symbols.add(symbol)
            valuation_rows_out.append({
                "symbol": symbol, "market_value": position["base_currency_market_value"], "weight": position["weight"],
                "valuation_risk": result["score"], "confidence": result["confidence"],
            })

    fundamental_score, fundamental_coverage = _weighted_score(fundamental_rows, "fundamental_score", total)
    subscore_keys = ("profitability", "growth", "cashflow_quality", "balance_sheet_health", "capital_efficiency")
    subscore_output = {}
    for key in subscore_keys:
        rows = [{**row, "value": row["subscores"].get(key)} for row in fundamental_rows]
        score, coverage_weight = _weighted_score(rows, "value", total)
        subscore_output[key] = {"score": score, "coverage_weight": coverage_weight}
    positives, negatives = _contributors(fundamental_rows)
    fundamental_covered = {row["symbol"] for row in fundamental_rows}
    fundamental_covered_value = sum(row["market_value"] for row in fundamental_rows)
    fundamental_confidence = (
        sum(row["market_value"] * row["data_completeness"] for row in fundamental_rows) / fundamental_covered_value
        if fundamental_covered_value > 0 else 0.0
    )
    fundamental_coverage_detail = _coverage_dimension(
        priced, fundamental_covered, excluded=excluded_company_symbols,
        freshness=_freshness(fundamental_ages, FUNDAMENTAL_STALE_DAYS),
        confidence=fundamental_confidence,
    )
    fundamental = {
        "score": fundamental_score, "grade": _grade(fundamental_score),
        "coverage_weight": fundamental_coverage,
        "covered_market_value": fundamental_coverage_detail["covered_market_value"],
        "uncovered_market_value": fundamental_coverage_detail["uncovered_market_value"],
        "subscores": subscore_output,
        "top_positive_contributors": positives, "top_negative_contributors": negatives,
    }

    valuation_score, valuation_coverage = _weighted_score(valuation_rows_out, "valuation_risk", total)
    valuation_covered_value = sum(row["market_value"] for row in valuation_rows_out)
    average_confidence = (
        sum(row["market_value"] * row["confidence"] for row in valuation_rows_out) / valuation_covered_value
        if valuation_covered_value > 0 else 0.0
    )
    adjusted_score = (
        sum(row["market_value"] * (row["valuation_risk"] * row["confidence"] + NEUTRAL_SCORE * (1 - row["confidence"])) for row in valuation_rows_out)
        / valuation_covered_value if valuation_covered_value > 0 else None
    )
    def exposure(predicate) -> float:
        value = sum(row["market_value"] for row in valuation_rows_out if predicate(row))
        return round(value / total * 100, 2) if total > 0 else 0.0
    valuation = {
        "score": valuation_score, "raw_weighted_valuation_risk": valuation_score,
        "confidence_adjusted_valuation_risk": _round(adjusted_score), "grade": _risk_grade(valuation_score),
        "coverage_weight": valuation_coverage, "average_confidence": round(average_confidence, 3),
        "undervalued_weight": exposure(lambda row: row["valuation_risk"] <= 40),
        "fairly_valued_weight": exposure(lambda row: 40 < row["valuation_risk"] <= 60),
        "overvalued_weight": exposure(lambda row: row["valuation_risk"] > 60),
        "high_risk_weight": exposure(lambda row: row["valuation_risk"] >= 70),
        "low_confidence_valuation_weight": exposure(lambda row: row["confidence"] < 0.5),
    }
    valuation_coverage_detail = _coverage_dimension(
        priced, {row["symbol"] for row in valuation_rows_out}, excluded=excluded_company_symbols,
        freshness=_freshness(valuation_ages, VALUATION_STALE_DAYS), confidence=average_confidence,
    )

    concentration = _concentration(priced, total, profiles, securities, valuations)
    filing_symbols = {filing.ticker for filing in filings}
    sec_applicable = {
        row["symbol"] for row in priced
        if row["symbol"] in company_symbols and (
            securities.get(row.get("security_id")) is None
            or securities[row["security_id"]].country_code in (None, "US")
            or row["symbol"] in filing_symbols
        )
    }
    sec_excluded = {row["symbol"] for row in priced} - sec_applicable
    sec, sec_coverage_detail = _sec_analysis(priced, filings, sec_applicable, sec_excluded, total, today)

    price_covered = {row["symbol"] for row in priced}
    price_ages: list[int] = []
    for row in priced:
        age = _days_old(row.get("price_as_of"), today)
        if age is not None:
            price_ages.append(age)
    price_coverage = _coverage_dimension(
        summary["positions"], price_covered, freshness=_freshness(price_ages, 7), basis="position_count",
    )
    coverage = {
        "price": price_coverage,
        "fundamental": fundamental_coverage_detail,
        "valuation": valuation_coverage_detail,
        "sec": sec_coverage_detail,
    }
    health = _overall_health(fundamental, valuation, sec, concentration)
    findings = _findings(fundamental, valuation, sec, concentration, coverage, stale_symbols, priced)

    cash_value = max(0.0, _number(portfolio.cash_balance) or 0.0)
    gross_value = total + cash_value
    sector_buckets = [row for row in concentration.get("sector_weights", []) if row["sector"] != "未分类"]
    unclassified_sector = next((row["weight"] for row in concentration.get("sector_weights", []) if row["sector"] == "未分类"), 0.0)
    # Account-history evidence is displayed beside the immutable objective
    # score. Historical performance is context, never silently promoted into a
    # forecast or into the existing health score.
    from .investment_ledger import overview as ledger_overview, return_attribution
    ledger = ledger_overview(db, portfolio, cached_fx_only=True)
    attribution = return_attribution(db, portfolio)
    negative = [row for row in attribution.get("items", []) if row.get("total_pnl", 0) < 0]
    account_analytics = {
        "fact_type": "account_fact_and_project_derived",
        "historical_performance_is_not_forecast": True,
        "time_weighted_return": ledger.get("time_weighted_return"),
        "max_drawdown": ledger.get("max_drawdown"),
        "realized_pnl": ledger.get("realized_pnl"),
        "unrealized_pnl": ledger.get("unrealized_pnl"),
        "dividend_income": ledger.get("dividend_income"),
        "fees_and_taxes": (ledger.get("fees") or 0) + (ledger.get("taxes") or 0),
        "cash_weight": round((ledger.get("cash") or 0) / max(ledger.get("net_asset_value") or 0, 1) * 100, 2),
        "largest_positive_contributor": attribution.get("items", [None])[0] if attribution.get("items") else None,
        "largest_negative_contributor": min(negative, key=lambda row: row["total_pnl"], default=None),
        "data_completeness": ledger.get("data_completeness"),
        "source": ledger.get("account_data_source"),
    }
    return {
        "portfolio_id": portfolio.id, "as_of": now,
        "base_currency": portfolio.base_currency,
        "total_market_value": total, "invested_market_value": total,
        "cash_value": round(cash_value, 4),
        "cash_weight": round(cash_value / gross_value * 100, 2) if gross_value > 0 else 0.0,
        "cash_tracked": ledger.get("account_data_source") == "ibkr_flex",
        "priced_count": len(priced), "position_count": summary["position_count"],
        "has_unpriced_positions": summary["has_unpriced_positions"] or summary["has_unconverted_positions"],
        "health": health,
        "fundamental_quality": fundamental,
        "valuation_risk": valuation,
        "sec_risk": sec,
        "concentration": concentration,
        "coverage": coverage,
        "findings": findings,
        # Backward-compatible alias for the original health-tab response.
        "sector_exposure": {
            "available": concentration.get("available", False),
            "reason": concentration.get("reason"),
            "buckets": sector_buckets,
            "unclassified_weight": unclassified_sector,
        },
        "account_analytics": account_analytics,
    }
