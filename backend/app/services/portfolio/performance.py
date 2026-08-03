"""Portfolio overview + per-position valuation (Sections 9-10).

Consumes derived `PortfolioPosition` rows and the latest known price to compute
market value, unrealized PnL, and market-value weights. Never fabricates a price:
project market snapshots are authoritative; only when they are absent may the
IBKR report mark be shown as an explicitly stale fallback. A position with no
known price remains excluded from the weighted denominator.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioPosition

from .fx import FxQuote, cached_fx_rate_map, fx_rate_map
from .pricing import PriceInfo, price_map


def _position_view(pos: PortfolioPosition, price: PriceInfo | None) -> dict:
    qty = pos.total_quantity or 0.0
    cost_basis = pos.total_cost or 0.0
    view = {
        "symbol": pos.symbol,
        "security_id": pos.security_id,
        "total_quantity": qty,
        "average_cost": pos.average_cost,
        "total_cost": cost_basis,
        "currency": pos.currency,
        "last_transaction_at": pos.last_transaction_at.isoformat() if pos.last_transaction_at else None,
        "authority_source": pos.authority_source,
        "ibkr_conid": pos.ibkr_conid,
        "ibkr_market_price": pos.ibkr_market_price,
        "ibkr_market_value": pos.ibkr_market_value,
        "ibkr_unrealized_pnl": pos.ibkr_unrealized_pnl,
        "ibkr_fx_rate_to_base": pos.ibkr_fx_rate_to_base,
        "ibkr_report_date": pos.ibkr_report_date.isoformat() if pos.ibkr_report_date else None,
        "ibkr_details": pos.ibkr_details,
        "authority_conflicts": pos.authority_conflicts,
        "price_available": price is not None or pos.ibkr_market_price is not None,
        "project_price_available": price is not None,
        "current_price": price.price if price else pos.ibkr_market_price,
        "previous_close": price.previous_close if price else None,
        "daily_change_amount": None,
        "daily_change_percent": None,
        "price_source": price.source if price else ("ibkr_flex_fallback" if pos.ibkr_market_price is not None else None),
        "price_as_of": price.as_of.isoformat() if price and price.as_of else (pos.ibkr_report_date.isoformat() if pos.ibkr_report_date else None),
        "price_is_report_fallback": price is None and pos.ibkr_market_price is not None,
        "quantity_source": "IBKR" if pos.authority_source == "ibkr_flex" else "portfolio_transactions",
        "average_cost_source": "IBKR" if pos.authority_source == "ibkr_flex" else "portfolio_transactions",
        "market_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_percent": None,
        "fx_rate": None,
        "fx_rate_source": None,
        "base_currency_market_value": None,
        "base_currency_total_cost": None,
        "base_currency_unrealized_pnl": None,
        "valuation_available": False,
        "portfolio_weight": None,
    }
    effective_price = price.price if price is not None else pos.ibkr_market_price
    if effective_price is not None:
        market_value = qty * effective_price
        unrealized = market_value - cost_basis
        view["market_value"] = round(market_value, 4)
        view["unrealized_pnl"] = round(unrealized, 4)
        view["unrealized_pnl_percent"] = (
            round(unrealized / cost_basis * 100, 4) if cost_basis > 0 else None
        )
        previous_close = price.previous_close if price is not None else None
        if previous_close is not None and previous_close > 0:
            view["daily_change_amount"] = round(effective_price - previous_close, 4)
            view["daily_change_percent"] = round((effective_price - previous_close) / previous_close * 100, 4)
    return view


def _apply_fx(view: dict, quote: FxQuote | None) -> None:
    if quote is None:
        return
    view["fx_rate"] = round(quote.rate, 10)
    view["fx_rate_source"] = quote.source
    view["base_currency_total_cost"] = round(view["total_cost"] * quote.rate, 4)
    if not view["price_available"]:
        return
    view["base_currency_market_value"] = round(view["market_value"] * quote.rate, 4)
    view["base_currency_unrealized_pnl"] = round(view["unrealized_pnl"] * quote.rate, 4)
    view["valuation_available"] = True


def build_summary(db: Session, portfolio: Portfolio, *, cached_fx_only: bool = False) -> dict:
    positions = list(
        db.scalars(
            select(PortfolioPosition)
            .where(
                PortfolioPosition.portfolio_id == portfolio.id,
                PortfolioPosition.total_quantity > 0,
            )
            .order_by(PortfolioPosition.symbol)
        ).all()
    )
    prices = price_map(db, [p.symbol for p in positions])
    views = [_position_view(p, prices.get(p.symbol)) for p in positions]
    rate_resolver = cached_fx_rate_map if cached_fx_only else fx_rate_map
    rates = rate_resolver(portfolio.base_currency, {v["currency"] for v in views})
    for view in views:
        _apply_fx(view, rates.get(view["currency"]))

    valued = [v for v in views if v["valuation_available"]]
    converted_costs = [v for v in views if v["base_currency_total_cost"] is not None]
    total_market_value = round(sum(v["base_currency_market_value"] for v in valued), 4)
    total_cost = round(sum(v["base_currency_total_cost"] for v in converted_costs), 4)
    total_unrealized = round(sum(v["base_currency_unrealized_pnl"] for v in valued), 4)
    valued_cost = round(sum(v["base_currency_total_cost"] for v in valued), 4)
    for view in views:
        if view["valuation_available"] and total_market_value > 0:
            view["portfolio_weight"] = round(
                view["base_currency_market_value"] / total_market_value * 100, 4
            )

    return {
        "portfolio_id": portfolio.id,
        "base_currency": portfolio.base_currency,
        "position_count": len(views),
        "priced_count": len(valued),
        "total_market_value": total_market_value,
        "cash_balance": portfolio.cash_balance,
        "total_net_liquidation": round(total_market_value + (portfolio.cash_balance or 0.0), 4),
        "total_cost": total_cost,
        "total_unrealized_pnl": total_unrealized,
        "total_unrealized_pnl_percent": (
            round(total_unrealized / valued_cost * 100, 4) if valued_cost > 0 else None
        ),
        "has_unpriced_positions": any(not v["price_available"] for v in views),
        "has_unconverted_positions": any(v["fx_rate"] is None for v in views),
        "fx_conversion_used": any(
            v["currency"] != portfolio.base_currency and v["fx_rate"] is not None for v in views
        ),
        "positions": views,
    }


def build_position_detail(db: Session, portfolio: Portfolio, symbol: str) -> dict | None:
    pos = db.scalar(
        select(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio.id,
            PortfolioPosition.symbol == symbol.upper(),
        )
    )
    if pos is None:
        return None
    from .pricing import latest_price

    view = _position_view(pos, latest_price(db, pos.symbol))
    quote = fx_rate_map(portfolio.base_currency, {view["currency"]}).get(view["currency"])
    _apply_fx(view, quote)
    if pos.authority_source == "ibkr_flex" and pos.ibkr_sync_run_id:
        from app.integrations.ibkr.db_models import IbkrFlexRecord
        rows = db.scalars(select(IbkrFlexRecord).where(
            IbkrFlexRecord.sync_run_id == pos.ibkr_sync_run_id,
            IbkrFlexRecord.symbol == pos.symbol,
            IbkrFlexRecord.section.in_(("trades", "dividends", "fifo_performance", "tax_lots")),
        ).order_by(IbkrFlexRecord.occurred_at.desc().nullslast(), IbkrFlexRecord.report_date.desc().nullslast()).limit(100)).all()
        view["ibkr_account_activity"] = [{
            "id": row.id, "section": row.section, "occurred_at": row.occurred_at,
            "report_date": row.report_date, "quantity": row.quantity, "price": row.price,
            "amount": row.amount, "currency": row.currency,
            "fields": {key: value for key, value in (row.raw_payload or {}).items() if key not in {"accountId", "acctAlias"}},
            "source": "IBKR Flex",
        } for row in rows]
    return view
