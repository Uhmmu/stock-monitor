"""Portfolio overview + per-position valuation (Sections 9-10).

Consumes derived `PortfolioPosition` rows and the latest known price to compute
market value, unrealized PnL, and market-value weights. Never fabricates a price:
a position with no known price is returned with `price_available=False` and
excluded from the weighted denominator, so weights stay honest.
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
        "price_available": price is not None,
        "current_price": price.price if price else None,
        "price_source": price.source if price else None,
        "price_as_of": price.as_of.isoformat() if price and price.as_of else None,
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
    if price is not None:
        market_value = qty * price.price
        unrealized = market_value - cost_basis
        view["market_value"] = round(market_value, 4)
        view["unrealized_pnl"] = round(unrealized, 4)
        view["unrealized_pnl_percent"] = (
            round(unrealized / cost_basis * 100, 4) if cost_basis > 0 else None
        )
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
    return view
