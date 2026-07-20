"""Graham 估值：纯计算、可追溯输入选择和轻量 FRED 缓存。"""
from __future__ import annotations

import csv
import io
import json
import logging
from copy import deepcopy
from datetime import UTC, datetime
from math import isfinite, sqrt
from typing import Any, Callable

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

MIN_GROWTH_PCT = -4.0
MAX_GROWTH_PCT = 15.0
FRED_DAAA_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DAAA"
FRED_CACHE_KEY = "market:fred:daaa:fresh"
FRED_LAST_GOOD_KEY = "market:fred:daaa:last_good"
FRED_FAILURE_KEY = "market:fred:daaa:failure"
FRED_CACHE_TTL = 18 * 60 * 60
FRED_FAILURE_TTL = 5 * 60


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _clamp_growth(value: float) -> float:
    return min(max(value, MIN_GROWTH_PCT), MAX_GROWTH_PCT)


def calculate_graham_number(eps_ttm: float | None, book_value_per_share: float | None) -> float | None:
    """返回 Graham Number；负数、零、NaN 和无穷值均不强行计算。"""
    eps, bvps = _finite_number(eps_ttm), _finite_number(book_value_per_share)
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return sqrt(22.5 * eps * bvps)


def calculate_graham_growth_value(
    eps_ttm: float | None,
    growth_rate_pct: float | None,
    aaa_yield_pct: float | None,
) -> float | None:
    """修正版 Graham Growth Formula；增长率按百分数传入并限制为 -4%..15%。"""
    eps = _finite_number(eps_ttm)
    growth = _finite_number(growth_rate_pct)
    aaa_yield = _finite_number(aaa_yield_pct)
    if eps is None or eps <= 0 or growth is None or aaa_yield is None or aaa_yield <= 0:
        return None
    growth = _clamp_growth(growth)
    multiplier = 8.5 + 2 * growth
    if multiplier <= 0:
        return None
    return eps * multiplier * 4.4 / aaa_yield


def calculate_margin_of_safety(intrinsic_value: float | None, current_price: float | None) -> float | None:
    """返回小数形式的安全边际，例如 0.2 表示 20%。"""
    value, price = _finite_number(intrinsic_value), _finite_number(current_price)
    if value is None or value <= 0 or price is None:
        return None
    return (value - price) / value


def calculate_cagr(start_value: float, end_value: float, years: int) -> float | None:
    """使用正的起止值计算 CAGR，返回百分数。"""
    start, end = _finite_number(start_value), _finite_number(end_value)
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def data_point(
    value: Any,
    source: str,
    *,
    field: str | None = None,
    as_of: str | None = None,
    quality: str,
    **extra: Any,
) -> dict[str, Any]:
    if isinstance(as_of, (int, float)):
        try:
            as_of = datetime.fromtimestamp(as_of, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            as_of = None
    elif as_of is not None:
        as_of = str(as_of)
    return {
        "value": _finite_number(value), "source": source, "field": field,
        "as_of": as_of, "quality": quality, **extra,
    }


def parse_fred_daaa_csv(content: str) -> dict[str, Any] | None:
    """解析 FRED CSV，倒序寻找最近一个非空且为正的 DAAA 百分数。"""
    rows = list(csv.DictReader(io.StringIO(content)))
    for row in reversed(rows):
        value = _finite_number(row.get("DAAA"))
        if value is not None and value > 0:
            return data_point(value, "FRED_DAAA", field="DAAA", as_of=row.get("DATE") or row.get("observation_date"), quality="market_data")
    return None


def _decode_cached(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        result = json.loads(raw)
        return result if _finite_number(result.get("value")) is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def get_latest_aaa_corporate_bond_yield(
    cache_client: Any = None,
    http_get: Callable[..., Any] = httpx.get,
) -> dict[str, Any] | None:
    """读取 FRED DAAA；18 小时新鲜缓存优先，请求失败时回退最后成功值。"""
    if cache_client is None:
        try:
            import redis
            cache_client = redis.Redis.from_url(get_settings().redis_url)
        except Exception as exc:
            logger.warning("FRED DAAA Redis 初始化失败: %s", exc)
    if cache_client is not None:
        try:
            cached = _decode_cached(cache_client.get(FRED_CACHE_KEY))
            if cached:
                return cached
            if cache_client.get(FRED_FAILURE_KEY):
                stale = _decode_cached(cache_client.get(FRED_LAST_GOOD_KEY))
                return ({**stale, "cache_status": "stale_fallback"} if stale else None)
        except Exception as exc:
            logger.warning("FRED DAAA 缓存读取失败: %s", exc)
    try:
        response = http_get(FRED_DAAA_URL, timeout=30.0, follow_redirects=True, headers={"User-Agent": "stock-monitor/2.0"})
        response.raise_for_status()
        point = parse_fred_daaa_csv(response.text)
        if point is None:
            raise ValueError("FRED DAAA CSV 没有有效观测值")
        if cache_client is not None:
            encoded = json.dumps(point)
            try:
                cache_client.setex(FRED_CACHE_KEY, FRED_CACHE_TTL, encoded)
                cache_client.set(FRED_LAST_GOOD_KEY, encoded)
                cache_client.delete(FRED_FAILURE_KEY)
            except Exception as exc:
                logger.warning("FRED DAAA 缓存写入失败: %s", exc)
        return point
    except (httpx.HTTPError, ValueError, csv.Error) as exc:
        logger.warning("FRED DAAA 获取失败: %s", exc)
        if cache_client is not None:
            try:
                cache_client.setex(FRED_FAILURE_KEY, FRED_FAILURE_TTL, "1")
            except Exception as cache_exc:
                logger.warning("FRED DAAA 失败缓存写入失败: %s", cache_exc)
    if cache_client is not None:
        try:
            stale = _decode_cached(cache_client.get(FRED_LAST_GOOD_KEY))
            if stale:
                return {**stale, "cache_status": "stale_fallback"}
        except Exception as exc:
            logger.warning("FRED DAAA 最后成功缓存读取失败: %s", exc)
    return None


def _periods(financials: dict[str, Any]) -> list[dict[str, Any]]:
    return financials.get("periods") or []


def resolve_current_price(info: dict[str, Any], quote: dict[str, Any] | None = None) -> dict[str, Any]:
    quote = quote or {}
    if _finite_number(quote.get("price")) is not None:
        return data_point(quote["price"], quote.get("source") or "project_quote", field="price", as_of=quote.get("as_of"), quality="market_data")
    for field in ("fastInfoLastPrice", "currentPrice", "regularMarketPrice", "previousClose"):
        if _finite_number(info.get(field)) is not None:
            return data_point(info[field], "yfinance", field=field, as_of=info.get("regularMarketTime"), quality="market_data")
    return data_point(None, "unavailable", quality="missing")


def resolve_eps_ttm(
    info: dict[str, Any], finnhub: dict[str, Any], quarters: list[dict[str, Any]], financials: dict[str, Any],
) -> dict[str, Any]:
    if _finite_number(info.get("trailingEps")) is not None:
        return data_point(info["trailingEps"], "yfinance", field="trailingEps", as_of=(_periods(financials) or [{}])[0].get("date"), quality="reported")
    for field in ("epsTTM", "epsNormalizedAnnual", "epsAnnual"):
        if _finite_number(finnhub.get(field)) is not None:
            return data_point(finnhub[field], "finnhub", field=field, quality="reported")
    recent = quarters[:4]
    quarterly_eps = [_finite_number(row.get("eps")) for row in recent]
    if len(recent) == 4 and all(value is not None for value in quarterly_eps):
        as_of = str(recent[0].get("period_end") or "")[:10] or None
        return data_point(sum(value for value in quarterly_eps if value is not None), "calculated_financials", field="sum_four_quarter_diluted_eps", as_of=as_of, quality="calculated")
    income_values = [_finite_number(row.get("net_income")) for row in recent]
    shares = _finite_number(info.get("sharesOutstanding"))
    if len(recent) == 4 and all(value is not None for value in income_values) and shares and shares > 0:
        as_of = str(recent[0].get("period_end") or "")[:10] or None
        return data_point(sum(value for value in income_values if value is not None) / shares, "calculated_financials", field="ttm_net_income/shares_outstanding", as_of=as_of, quality="calculated")
    return data_point(None, "unavailable", quality="missing")


def resolve_bvps(info: dict[str, Any], finnhub: dict[str, Any], financials: dict[str, Any]) -> dict[str, Any]:
    if _finite_number(info.get("bookValue")) is not None:
        return data_point(info["bookValue"], "yfinance", field="bookValue", as_of=(_periods(financials) or [{}])[0].get("date"), quality="reported")
    for field in ("bookValuePerShareQuarterly", "bookValuePerShareAnnual"):
        if _finite_number(finnhub.get(field)) is not None:
            return data_point(finnhub[field], "finnhub", field=field, quality="reported")
    latest = (_periods(financials) or [{}])[0]
    equity = _finite_number(latest.get("stockholders_equity"))
    shares = _finite_number(latest.get("shares_issued")) or _finite_number(info.get("sharesOutstanding"))
    if equity is not None and shares is not None and shares > 0:
        return data_point(equity / shares, "calculated_financials", field="common_stockholders_equity/shares_outstanding", as_of=latest.get("date"), quality="calculated")
    return data_point(None, "unavailable", quality="missing")


def resolve_growth_rate(info: dict[str, Any], financials: dict[str, Any], eps_ttm: float | None) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    analyst = _finite_number(info.get("longTermPotentialGrowthRate"))
    if analyst is not None:
        analyst = analyst * 100 if abs(analyst) <= 1 else analyst
        candidates.append({"value": analyst, "source": "analyst_forward_growth", "weight": .5, "quality": "analyst_estimate"})
    forward_eps = _finite_number(info.get("forwardEps"))
    if analyst is None and forward_eps is not None and eps_ttm is not None:
        forward_growth = calculate_cagr(eps_ttm, forward_eps, 1)
        if forward_growth is not None:
            candidates.append({"value": forward_growth, "source": "forward_eps_cagr", "weight": .5, "quality": "estimated"})
    periods = _periods(financials)
    eps_rows = [(row.get("date"), _finite_number(row.get("diluted_eps"))) for row in periods]
    eps_rows = [(date, value) for date, value in eps_rows if value is not None and value > 0]
    if len(eps_rows) >= 2:
        years = min(len(eps_rows) - 1, 5)
        historical = calculate_cagr(eps_rows[years][1], eps_rows[0][1], years)
        if historical is not None:
            candidates.append({"value": historical, "source": f"historical_eps_cagr_{years}y", "weight": .3, "quality": "historical"})
    revenue_rows = [(row.get("date"), _finite_number(row.get("revenue"))) for row in periods]
    revenue_rows = [(date, value) for date, value in revenue_rows if value is not None and value > 0]
    if len(revenue_rows) >= 2:
        years = min(len(revenue_rows) - 1, 5)
        historical = calculate_cagr(revenue_rows[years][1], revenue_rows[0][1], years)
        if historical is not None:
            candidates.append({"value": historical, "source": f"historical_revenue_cagr_{years}y", "weight": .2, "quality": "historical"})
    if not candidates:
        return data_point(None, "unavailable", quality="missing", candidates=[])
    total_weight = sum(item["weight"] for item in candidates)
    raw = sum(item["value"] * item["weight"] for item in candidates) / total_weight
    value = _clamp_growth(raw)
    source = candidates[0]["source"] if len(candidates) == 1 else "weighted_growth_sources"
    as_of = periods[0].get("date") if periods else None
    return data_point(
        value, source, as_of=as_of,
        quality=candidates[0]["quality"] if len(candidates) == 1 else "estimated",
        raw_value=raw, clamped=value != raw, candidates=candidates,
        growth_rate_used=value, growth_rate_source=source,
        growth_rate_raw=raw, growth_rate_clamped=value != raw,
    )


def evaluate_graham_applicability(
    sector: str | None, industry: str | None, eps_ttm: float | None, bvps: float | None,
    earnings_stability: float | None = None,
) -> dict[str, Any]:
    """给出模型整体适用性；有限适用行业仍保留可计算结果。"""
    del earnings_stability  # 预留给后续稳定性序列，不用缺失值伪造结论。
    eps, book = _finite_number(eps_ttm), _finite_number(bvps)
    reasons: list[str] = []
    missing: list[str] = []
    if eps is None:
        missing.append("eps_ttm")
    elif eps <= 0:
        reasons.append("EPS TTM 小于或等于 0，Graham Number 与 Growth Formula 均不适用。")
        return {"status": "not_applicable", "confidence": "not_recommended", "reasons": reasons, "missing_fields": missing}
    if book is None:
        missing.append("book_value_per_share")
    elif book <= 0:
        reasons.append("BVPS 小于或等于 0，Graham Number 不适用；成长公式仍可单独参考。")
    text = f"{sector or ''} {industry or ''}".lower()
    if any(word in text for word in ("bank", "financial", "insurance")):
        reasons.append("金融行业应同时结合 P/B、ROE、资本充足率和资产质量。")
    if "reit" in text or "real estate investment trust" in text:
        reasons.append("REIT 应同时结合 P/FFO、AFFO 和 NAV。")
    if any(word in text for word in ("software", "saas")):
        reasons.append("高增长 SaaS 的账面价值与盈利假设可能严重偏离市场定价。")
    if any(word in text for word in ("oil", "gas", "mining", "steel", "commodity", "cyclical")):
        reasons.append("周期股的 TTM EPS 可能位于周期高低点，应结合正常化 EPS。")
    if missing:
        reasons.append(f"缺少数据：{', '.join(missing)}。")
    limited = bool(reasons or missing)
    return {"status": "limited" if limited else "applicable", "confidence": "low_confidence" if limited else "normal", "reasons": reasons, "missing_fields": missing}


def _valuation_status(margin: float | None) -> str:
    if margin is None:
        return "not_applicable"
    if margin >= .2:
        return "undervalued"
    if margin >= -.1:
        return "fairly_valued"
    return "overvalued"


def _scenario(name: str, growth: float, eps: float | None, aaa: float | None, price: float | None) -> dict[str, Any]:
    value = calculate_graham_growth_value(eps, growth, aaa)
    margin = calculate_margin_of_safety(value, price)
    return {
        "name": name, "growth_rate": growth, "intrinsic_value": value,
        "current_price": price, "margin_of_safety": margin,
        "premium_or_discount": -margin if margin is not None else None,
        "status": _valuation_status(margin), "available": value is not None,
    }


def build_graham_analysis(
    symbol: str,
    currency: str | None,
    current_price: dict[str, Any],
    eps_ttm: dict[str, Any],
    book_value_per_share: dict[str, Any],
    growth_rate: dict[str, Any],
    aaa_yield: dict[str, Any] | None,
    sector: str | None,
    industry: str | None,
) -> dict[str, Any]:
    price, eps, bvps = current_price.get("value"), eps_ttm.get("value"), book_value_per_share.get("value")
    aaa_yield = aaa_yield or data_point(None, "unavailable", quality="missing")
    growth = _finite_number(growth_rate.get("value"))
    graham_value = calculate_graham_number(eps, bvps)
    graham_margin = calculate_margin_of_safety(graham_value, price)
    scenarios: dict[str, Any] = {}
    if growth is not None:
        base = _clamp_growth(growth)
        scenarios = {
            "conservative": _scenario("Conservative", max(MIN_GROWTH_PCT, base - 3), eps, aaa_yield.get("value"), price),
            "base": _scenario("Base", base, eps, aaa_yield.get("value"), price),
            "optimistic": _scenario("Optimistic", min(MAX_GROWTH_PCT, base + 3), eps, aaa_yield.get("value"), price),
        }
    else:
        scenarios = {key: _scenario(name, 0, None, None, price) for key, name in (("conservative", "Conservative"), ("base", "Base"), ("optimistic", "Optimistic"))}
        for item in scenarios.values():
            item["growth_rate"] = None
    applicability = evaluate_graham_applicability(sector, industry, eps, bvps)
    extra_missing = []
    if price is None:
        extra_missing.append("current_price")
    if growth is None:
        extra_missing.append("growth_rate")
    if aaa_yield.get("value") is None:
        extra_missing.append("aaa_corporate_bond_yield")
    if extra_missing:
        applicability["missing_fields"] = list(dict.fromkeys(applicability["missing_fields"] + extra_missing))
        applicability["reasons"].append(f"缺少数据：{', '.join(extra_missing)}；相关结果不可用。")
        if applicability["status"] == "applicable":
            applicability["status"] = "limited"
            applicability["confidence"] = "low_confidence"
    base_margin = scenarios["base"]["margin_of_safety"]
    summary_margin = base_margin if base_margin is not None else graham_margin
    updated = datetime.now(UTC).isoformat()
    financial_dates = [point.get("as_of") for point in (eps_ttm, book_value_per_share) if point.get("as_of")]
    return {
        "symbol": symbol, "currency": currency or "USD", "current_price": price,
        "sector": sector, "industry": industry,
        "graham_number": {"value": graham_value, "margin_of_safety": graham_margin, "status": _valuation_status(graham_margin), "available": graham_value is not None},
        "growth_formula": scenarios,
        "inputs": {"current_price": current_price, "eps_ttm": eps_ttm, "book_value_per_share": book_value_per_share, "growth_rate": growth_rate, "aaa_yield": aaa_yield},
        "applicability": applicability, "overall_status": _valuation_status(summary_margin),
        "financial_period": max(financial_dates) if financial_dates else None, "updated_at": updated,
    }


def build_graham_from_sources(
    symbol: str, info: dict[str, Any], finnhub: dict[str, Any], quarters: list[dict[str, Any]],
    financials: dict[str, Any], quote: dict[str, Any] | None, aaa_yield: dict[str, Any] | None,
) -> dict[str, Any]:
    price = resolve_current_price(info, quote)
    eps = resolve_eps_ttm(info, finnhub, quarters, financials)
    bvps = resolve_bvps(info, finnhub, financials)
    growth = resolve_growth_rate(info, financials, eps.get("value"))
    return build_graham_analysis(symbol, info.get("currency"), price, eps, bvps, growth, aaa_yield, info.get("sector"), info.get("industry"))


def apply_graham_overrides(
    original: dict[str, Any], *, growth_rate: float | None = None,
    aaa_yield: float | None = None, normalized_eps: float | None = None,
) -> dict[str, Any]:
    """仅从快照输入重算；每个覆盖点都保留 original，绝不修改快照原始数据。"""
    inputs = deepcopy(original["inputs"])
    for key, override, field in (
        ("growth_rate", growth_rate, "growth_rate"),
        ("aaa_yield", aaa_yield, "aaa_yield"),
        ("eps_ttm", normalized_eps, "normalized_eps"),
    ):
        if override is None:
            continue
        raw = _finite_number(override)
        if raw is None:
            continue
        if key == "growth_rate":
            raw = _clamp_growth(raw)
        extra = ({"growth_rate_used": raw, "growth_rate_source": "user_override", "growth_rate_raw": override,
                  "growth_rate_clamped": raw != override} if key == "growth_rate" else {})
        inputs[key] = data_point(raw, "user_override", field=field, quality="user_input", original=inputs[key], **extra)
    return build_graham_analysis(
        original["symbol"], original.get("currency"), inputs["current_price"], inputs["eps_ttm"],
        inputs["book_value_per_share"], inputs["growth_rate"], inputs["aaa_yield"],
        original.get("sector"), original.get("industry"),
    )
