from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    FinancialStatementSnapshot,
    PortfolioPosition,
    Security,
    StockDiscoverySettings,
    ValuationSnapshot,
    WatchlistItem,
)
from app.services.market_data import fetch_stock_profile


_SUFFIX_BY_EXCHANGE = {
    "TOKYO": ".T", "JPX": ".T", "TSE": ".T",
    "TORONTO": ".TO", "TSX": ".TO", "HONG KONG": ".HK", "HKEX": ".HK",
    "LONDON": ".L", "LSE": ".L", "ASX": ".AX",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_ticker(raw_ticker: str, exchange: str | None = None) -> tuple[str | None, str]:
    raw = (raw_ticker or "").strip().upper().replace("$", "")
    if ":" in raw:
        prefix, symbol = raw.rsplit(":", 1)
        exchange = exchange or prefix
        raw = symbol
    raw = re.sub(r"\s+", "", raw)
    if not raw or len(raw) > 32 or not re.fullmatch(r"[A-Z0-9.\-]+", raw):
        return None, "股票代码格式无法识别"
    exchange_key = (exchange or "").strip().upper()
    if raw.isdigit() and len(raw) == 4 and exchange_key in ("TOKYO", "JPX", "TSE"):
        raw += ".T"
    elif "." not in raw and "-" not in raw and exchange_key in _SUFFIX_BY_EXCHANGE:
        raw += _SUFFIX_BY_EXCHANGE[exchange_key]
    # Yahoo uses a dash for common US share classes (BRK.B -> BRK-B), while
    # exchange suffixes such as 7203.T remain dots.
    if re.fullmatch(r"[A-Z]{1,5}\.[A-Z]", raw) and exchange_key in ("", "NYSE", "NASDAQ", "US"):
        raw = raw.replace(".", "-")
    return raw, "代码已按 Yahoo/本地证券规则规范化"


def resolve_local_symbol(db: Session, raw_ticker: str, exchange: str | None = None) -> tuple[str | None, str, Security | None]:
    normalized, reason = normalize_ticker(raw_ticker, exchange)
    if not normalized:
        return None, reason, None
    row = db.scalar(select(Security).where(or_(
        Security.yahoo_symbol == normalized,
        Security.finnhub_symbol == normalized,
        Security.display_symbol == normalized,
    )).limit(1))
    if row:
        return row.yahoo_symbol or row.finnhub_symbol or normalized, "已匹配本地统一证券实体", row
    return normalized, reason, None


def _latest_statement_fcf(db: Session, ticker: str) -> tuple[float | None, str | None]:
    row = db.scalar(select(FinancialStatementSnapshot).where(
        FinancialStatementSnapshot.ticker == ticker,
        FinancialStatementSnapshot.frequency == "annual",
    ).order_by(FinancialStatementSnapshot.period_end.desc()).limit(1))
    if not row:
        return None, None
    return _number((row.cash_flow or {}).get("free_cash_flow")), row.period_end.isoformat()


def _latest_valuation(db: Session, ticker: str) -> dict:
    row = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == ticker)
                    .order_by(ValuationSnapshot.snapshot_date.desc()).limit(1))
    return dict(row.payload or {}) if row else {}


def enrich_candidate(db: Session, ticker: str, raw: dict) -> tuple[dict, str]:
    """Use persisted local facts first, then one existing Yahoo profile request."""
    local: dict[str, Any] = {"ticker": ticker, "sources": [], "as_of": datetime.now(UTC).isoformat()}
    valuation = _latest_valuation(db, ticker)
    if valuation:
        local["valuation_classification"] = valuation.get("model_signals") or valuation.get("classification")
        local["sources"].append("local_calculation")
    fcf, period = _latest_statement_fcf(db, ticker)
    if fcf is not None:
        local["free_cash_flow"] = fcf
        local["free_cash_flow_period"] = period
        local["sources"].append("yfinance")
    try:
        info = fetch_stock_profile(ticker)
    except Exception:
        info = {}
    if info:
        fields = {
            "company_name": info.get("longName") or info.get("shortName"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"), "average_volume": info.get("averageVolume"),
            "pe_trailing": info.get("trailingPE"), "pe_forward": info.get("forwardPE"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "revenue_growth": info.get("revenueGrowth"), "earnings_growth": info.get("earningsGrowth"),
            "gross_margin": info.get("grossMargins"), "operating_margin": info.get("operatingMargins"),
            "free_cash_flow": info.get("freeCashflow") if info.get("freeCashflow") is not None else local.get("free_cash_flow"),
            "sector": info.get("sector"), "industry": info.get("industry"), "currency": info.get("currency"),
            "fifty_two_week_change": info.get("52WeekChange"),
        }
        local.update({key: _number(value) if key not in ("company_name", "sector", "industry", "currency") else value for key, value in fields.items()})
        local["sources"].append("yfinance")
        return local, "verified"
    # Perplexity facts remain visible, but failure to reach Yahoo is not proof
    # that a valid international symbol is unsupported.
    raw_financial = raw.get("financial_snapshot") or {}
    if raw_financial:
        local["fallback_to_perplexity"] = True
    return local, "partial" if raw_financial else "pending"


@dataclass(frozen=True)
class FilterDecision:
    status: str
    reasons: list[str]
    details: dict


def apply_filters(
    *, raw: dict, local: dict, ticker: str | None, settings: StockDiscoverySettings,
    held_symbols: set[str], watched_symbols: set[str], symbol_valid: bool,
) -> FilterDecision:
    if not symbol_valid or not ticker:
        return FilterDecision("unsupported_symbol", ["股票代码无法识别"], {})
    if ticker in held_symbols:
        reason = "与当前持仓重复"
        return FilterDecision("already_held" if settings.exclude_current_holdings else "accepted_with_warning", [reason], {"excluded_by_setting": settings.exclude_current_holdings})
    if ticker in watched_symbols:
        reason = "已在自选股"
        return FilterDecision("already_watched" if settings.exclude_watchlist else "accepted_with_warning", [reason], {"excluded_by_setting": settings.exclude_watchlist})

    financial = raw.get("financial_snapshot") or {}
    def metric(name: str) -> float | None:
        return _number(local.get(name)) if local.get(name) is not None else _number(financial.get(name))

    reasons: list[str] = []
    hard: list[str] = []
    warnings: list[str] = []
    market_cap = metric("market_cap") or _number(raw.get("market_cap"))
    fcf = metric("free_cash_flow")
    trailing = metric("pe_trailing")
    forward = metric("pe_forward")
    sales = metric("price_to_sales")
    growth = metric("revenue_growth")
    sector = str(local.get("sector") or raw.get("sector") or "").lower()
    financial_company = "financial" in sector or "bank" in str(local.get("industry") or raw.get("industry") or "").lower()

    if market_cap is not None and market_cap < settings.min_market_cap:
        hard.append("市值低于当前最低门槛")
    if settings.require_positive_fcf and fcf is not None and fcf <= 0 and not financial_company:
        hard.append("自由现金流为负")
    quality = raw.get("quality_level")
    high_quality_growth = quality == "high" and (growth or 0) >= .20
    if trailing is not None and trailing > settings.max_trailing_pe:
        (warnings if high_quality_growth and trailing <= settings.max_trailing_pe * 1.5 else hard).append("预期增长不足以支持当前极高市盈率" if not high_quality_growth else "市盈率偏高")
    if forward is not None and forward > settings.max_forward_pe:
        (warnings if high_quality_growth and forward <= settings.max_forward_pe * 1.5 else hard).append("预期市盈率过高" if not high_quality_growth else "预期市盈率偏高")
    if sales is not None and sales > settings.max_price_to_sales and not financial_company:
        (warnings if high_quality_growth and sales <= settings.max_price_to_sales * 1.5 else hard).append("市销率过高" if not high_quality_growth else "市销率偏高")
    if raw.get("valuation_level") == "extreme":
        warnings.append("Perplexity 判断估值极高")
    if settings.filter_extreme_momentum and raw.get("momentum_state") == "euphoric":
        warnings.append("近期动量过热")

    key_values = [market_cap, trailing, forward, sales, fcf]
    if not any(value is not None for value in key_values):
        reasons.append("缺少关键数据")
        if settings.missing_data_policy == "reject":
            return FilterDecision("rejected", reasons, {"missing_data": True})
        return FilterDecision("watch_only" if settings.missing_data_policy == "watch_only" else "insufficient_data", reasons, {"missing_data": True})
    if hard:
        return FilterDecision("rejected", list(dict.fromkeys(hard + warnings)), {"hard_failures": hard})
    if warnings:
        status = "watch_only" if any("过热" in item or "极高" in item for item in warnings) else "accepted_with_warning"
        return FilterDecision(status, list(dict.fromkeys(warnings)), {})
    return FilterDecision("accepted", [], {})
