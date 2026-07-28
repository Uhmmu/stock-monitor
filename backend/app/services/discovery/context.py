from __future__ import annotations

import hashlib
import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Portfolio,
    PortfolioStrategyProfile,
    FinancialStatementSnapshot,
    NewsItem,
    QuarterlyFinancial,
    SecEvent,
    SecFinancialPeriod,
    Security,
    StockDiscoveryCandidate,
    StockDiscoveryRun,
    StockProfile,
    ValuationSnapshot,
    WatchlistItem,
)
from app.services.portfolio.performance import build_summary
from app.services.portfolio.portfolio_health import build_health
from app.services.portfolio.strategy_profile import get_or_create_strategy_profile


def _strategy(profile: PortfolioStrategyProfile) -> dict:
    return {
        "strategy_type": profile.strategy_type,
        "investment_horizon": profile.investment_horizon,
        "risk_tolerance": profile.risk_tolerance,
        "valuation_preference": profile.valuation_preference,
        "minimum_quality_score": profile.minimum_quality_score,
        "max_single_position_percent": profile.max_single_position,
        "max_theme_exposure_percent": profile.max_theme_exposure,
        "preferred_regions": profile.preferred_regions,
        "preferred_market_caps": profile.preferred_market_caps,
    }


def _latest_by_ticker(rows) -> dict:
    latest = {}
    for row in rows:
        latest.setdefault(row.ticker, row)
    return latest


def _compact_scalars(payload: dict, limit: int = 24) -> dict:
    result = {}
    for key, value in (payload or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
        if len(result) >= limit:
            break
    return result


def build_local_research_context(db: Session, base_context: dict) -> dict:
    """Attach persisted Yahoo/FMP/Finnhub/SEC facts without new provider calls."""
    symbols = list(dict.fromkeys(
        [str(row.get("ticker")) for row in base_context.get("holdings", []) if row.get("ticker")]
        + [str(item) for item in base_context.get("current_watchlist", [])]
    ))[:60]
    if not symbols:
        return base_context
    profiles = {
        row.ticker: row
        for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all()
    }
    valuations = _latest_by_ticker(db.scalars(
        select(ValuationSnapshot).where(ValuationSnapshot.ticker.in_(symbols))
        .order_by(ValuationSnapshot.ticker, ValuationSnapshot.snapshot_date.desc())
    ).all())
    yahoo = _latest_by_ticker(db.scalars(
        select(FinancialStatementSnapshot).where(
            FinancialStatementSnapshot.ticker.in_(symbols),
            FinancialStatementSnapshot.frequency == "quarterly",
        ).order_by(FinancialStatementSnapshot.ticker, FinancialStatementSnapshot.period_end.desc())
    ).all())
    provider_financials = _latest_by_ticker(db.scalars(
        select(QuarterlyFinancial).where(QuarterlyFinancial.ticker.in_(symbols))
        .order_by(QuarterlyFinancial.ticker, QuarterlyFinancial.period_end.desc())
    ).all())
    sec_financials = _latest_by_ticker(db.scalars(
        select(SecFinancialPeriod).where(SecFinancialPeriod.ticker.in_(symbols))
        .order_by(SecFinancialPeriod.ticker, SecFinancialPeriod.period_end.desc())
    ).all())
    sec_events: dict[str, list[dict]] = {}
    for row in db.scalars(
        select(SecEvent).where(SecEvent.ticker.in_(symbols))
        .order_by(SecEvent.ticker, SecEvent.filing_date.desc()).limit(180)
    ).all():
        bucket = sec_events.setdefault(row.ticker, [])
        if len(bucket) < 3:
            bucket.append({
                "filing_date": row.filing_date,
                "form": row.form,
                "item": row.item_label,
                "summary": row.summary_zh,
                "source": "sec_edgar",
            })
    news_rows = db.scalars(
        select(NewsItem).where(or_(
            NewsItem.ticker.in_(symbols),
            NewsItem.scope == "market",
        )).order_by(NewsItem.published_at.desc(), NewsItem.id.desc()).limit(40)
    ).all()
    news_summaries = [{
        "ticker": None if row.scope == "market" else row.ticker,
        "scope": row.scope,
        "title": row.translated_title or row.title,
        "original_title": row.title,
        "summary": (row.ai_summary or row.summary or "概要数据不足")[:1500],
        "published_at": row.published_at,
        "source": row.source or row.provider,
        "topic": row.topic,
        "sentiment_score": row.sentiment_score,
        "url": row.url,
    } for row in news_rows]
    universe = []
    for ticker in symbols:
        profile = profiles.get(ticker)
        valuation = valuations.get(ticker)
        statement = yahoo.get(ticker)
        provider = provider_financials.get(ticker)
        sec = sec_financials.get(ticker)
        universe.append({
            "ticker": ticker,
            "company_name": profile.company_name if profile else None,
            "sector": profile.official_sector if profile else None,
            "industry": profile.official_industry if profile else None,
            "profile_source": profile.source if profile else None,
            "valuation": (valuation.payload if valuation else {}),
            "valuation_as_of": valuation.snapshot_date if valuation else None,
            "yfinance_statement": {
                "period_end": statement.period_end,
                "income_statement": _compact_scalars(statement.income_statement),
                "balance_sheet": _compact_scalars(statement.balance_sheet),
                "cash_flow": _compact_scalars(statement.cash_flow),
            } if statement else None,
            "finnhub_or_fmp_financial": {
                "period_end": provider.period_end,
                "source": provider.source,
                "revenue": provider.revenue,
                "eps": provider.eps,
                "net_income": provider.net_income,
                "free_cash_flow": provider.free_cash_flow,
            } if provider else None,
            "sec_financial": {
                "period_end": sec.period_end,
                "revenue": sec.revenue,
                "net_income": sec.net_income,
                "operating_cash_flow": sec.operating_cash_flow,
                "source": sec.source,
            } if sec else None,
            "sec_events": sec_events.get(ticker, []),
        })
    enriched = {
        **base_context,
        "local_research_universe": universe,
        "local_news_summaries": news_summaries,
    }
    return json.loads(json.dumps(enriched, ensure_ascii=False, default=str))


def build_portfolio_context(db: Session, portfolio: Portfolio, user_id: int) -> tuple[dict, str]:
    """Build a compact, privacy-safe prompt payload using persisted local data only."""
    summary = build_summary(db, portfolio, cached_fx_only=True)
    health = build_health(db, portfolio)
    profile = get_or_create_strategy_profile(db, user_id)
    positions = summary["positions"]
    symbols = [row["symbol"] for row in positions]
    profiles = {row.ticker: row for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all()} if symbols else {}
    security_ids = [row["security_id"] for row in positions if row.get("security_id")]
    securities = {row.id: row for row in db.scalars(select(Security).where(Security.id.in_(security_ids))).all()} if security_ids else {}

    holdings = []
    valuation_rows = list(db.scalars(select(ValuationSnapshot).where(ValuationSnapshot.ticker.in_(symbols))
        .order_by(ValuationSnapshot.ticker, ValuationSnapshot.snapshot_date.desc())).all()) if symbols else []
    valuations: dict[str, ValuationSnapshot] = {}
    for valuation in valuation_rows:
        valuations.setdefault(valuation.ticker, valuation)
    sec_flags: dict[str, list[str]] = {}
    for flag in health.get("sec_risk", {}).get("flag_exposures", []):
        for symbol in flag.get("affected_symbols", []):
            sec_flags.setdefault(symbol, []).append(flag.get("label") or flag.get("flag"))
    for row in positions:
        security = securities.get(row.get("security_id"))
        stock_profile = profiles.get(row["symbol"])
        valuation = valuations.get(row["symbol"])
        valuation_payload = dict(valuation.payload or {}) if valuation else {}
        signals = valuation_payload.get("model_signals") or []
        holdings.append({
            "ticker": row["symbol"],
            "company_name": (security.display_name if security else None) or (stock_profile.company_name if stock_profile else None),
            "portfolio_weight_percent": row.get("portfolio_weight"),
            "market_value_base_currency": row.get("base_currency_market_value"),
            "unrealized_gain_loss_percent": row.get("unrealized_pnl_percent"),
            "sector": stock_profile.official_sector if stock_profile else None,
            "industry": stock_profile.official_industry if stock_profile else None,
            "country": security.country_code if security else None,
            "listing_market": security.market if security else None,
            "currency": row.get("currency"),
            "valuation_signals": [{"label": item.get("label"), "verdict": item.get("verdict"), "stars": item.get("stars")} for item in signals[:6]],
            "valuation_as_of": valuation.snapshot_date.isoformat() if valuation else None,
            "sec_risk_flags": sec_flags.get(row["symbol"], []),
            "data_available": bool(row.get("valuation_available")),
        })

    watched = list(db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True)).order_by(WatchlistItem.display_order)).all())
    rejected = list(db.scalars(
        select(StockDiscoveryCandidate)
        .join(StockDiscoveryRun, StockDiscoveryRun.id == StockDiscoveryCandidate.run_id)
        .where(StockDiscoveryRun.user_id == user_id, StockDiscoveryCandidate.dismissed.is_(True))
        .order_by(StockDiscoveryCandidate.created_at.desc()).limit(20)
    ).all())
    concentration = health.get("concentration", {})
    context = {
        "as_of": health.get("as_of"),
        "base_currency": portfolio.base_currency,
        "portfolio_summary": {
            "position_count": summary["position_count"],
            "priced_count": summary["priced_count"],
            "total_market_value": summary["total_market_value"],
            "top_holdings": sorted(holdings, key=lambda row: row.get("portfolio_weight_percent") or 0, reverse=True)[:8],
            "largest_position_weight": concentration.get("largest_position_weight"),
            "top_three_weight": concentration.get("top_three_weight"),
            "sector_weights": concentration.get("sector_weights", [])[:10],
            "currency_weights": concentration.get("currency_weights", [])[:10],
            "coverage": health.get("coverage", {}),
            "fundamental_quality": {key: health.get("fundamental_quality", {}).get(key) for key in ("score", "grade", "coverage_weight")},
            "valuation_risk": {key: health.get("valuation_risk", {}).get(key) for key in ("score", "grade", "coverage_weight", "average_confidence")},
            "sec_risk": {key: health.get("sec_risk", {}).get(key) for key in ("score", "grade", "coverage_weight")},
            "known_findings": health.get("findings", [])[:10],
        },
        "holdings": holdings,
        "investment_preferences": _strategy(profile),
        "current_watchlist": [row.ticker for row in watched],
        "recently_rejected_candidates": [row.normalized_ticker or row.raw_ticker for row in rejected],
        "known_data_gaps": [
            "未持久化的主题/因子/商业模式暴露需要在本次分析中谨慎推断。",
            "缺少价格或汇率的持仓不参与本地市值权重。",
        ],
    }
    # Portfolio health payloads can contain timezone-aware datetimes. Convert
    # the final compact context through JSON once so it is both prompt-safe and
    # directly persistable in PostgreSQL JSON without driver-specific encoders.
    json_safe_context = json.loads(json.dumps(context, ensure_ascii=False, default=str))
    canonical = json.dumps(json_safe_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json_safe_context, hashlib.sha256(canonical.encode("utf-8")).hexdigest()
