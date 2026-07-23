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
        "realized_pnl": pos.realized_pnl,
        "currency": pos.currency,
        "last_transaction_at": pos.last_transaction_at.isoformat() if pos.last_transaction_at else None,
        "price_available": price is not None,
        "current_price": price.price if price else None,
        "price_source": price.source if price else None,
        "market_value": None,
        "unrealized_pnl": None,
        "unrealized_pnl_percent": None,
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


def build_summary(db: Session, portfolio: Portfolio) -> dict:
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

    priced = [v for v in views if v["price_available"]]
    total_market_value = round(sum(v["market_value"] for v in priced), 4)
    total_cost = round(sum(v["total_cost"] for v in views), 4)
    total_unrealized = round(sum(v["unrealized_pnl"] for v in priced), 4)
    total_realized = round(sum((v["realized_pnl"] or 0.0) for v in views), 4)

    for view in views:
        if view["price_available"] and total_market_value > 0:
            view["portfolio_weight"] = round(view["market_value"] / total_market_value * 100, 4)

    return {
        "portfolio_id": portfolio.id,
        "base_currency": portfolio.base_currency,
        "position_count": len(views),
        "priced_count": len(priced),
        "total_market_value": total_market_value,
        "total_cost": total_cost,
        "total_unrealized_pnl": total_unrealized,
        "total_unrealized_pnl_percent": (
            round(total_unrealized / total_cost * 100, 4) if total_cost > 0 else None
        ),
        "total_realized_pnl": total_realized,
        "has_unpriced_positions": len(priced) < len(views),
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

    return _position_view(pos, latest_price(db, pos.symbol))
