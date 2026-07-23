"""Bridge between a holding and the technical-analysis service boundary (Sections 11-19).

Holdings never touch individual indicators — they consume the normalized
`TechnicalResult` (zones, trend, volatility) from `technical_analysis.get_latest`.
This module layers position context on top: which zones sit above/below the
holding, and probabilistic arrival estimates toward the nearest support/resistance.
Every estimate is probabilistic and may be unavailable; nothing here guarantees a date.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    ANALYSIS_ENGINE_VERSION,
    ANALYZER_VERSION,
    PARAMETER_SET_VERSION,
)
from app.models import HistoricalPrice, PortfolioPosition
from app.services.technical_analysis import get_latest
from app.services.technical_analysis.estimators import estimate_arrival


def _daily_closes(db: Session, symbol: str, limit: int = 260) -> list[float]:
    value = symbol.upper()
    for source in ("fmp", "yahoo"):
        rows = list(
            db.scalars(
                select(HistoricalPrice.close)
                .where(HistoricalPrice.symbol == value, HistoricalPrice.source == source)
                .order_by(HistoricalPrice.date.desc())
                .limit(limit)
            ).all()
        )
        if rows:
            return [float(c) for c in reversed(rows)]
    return []


def _nearest(zones: list, current_price: float | None, *, above: bool):
    if not current_price:
        return None
    candidates = [
        z for z in zones
        if (z.center_price >= current_price) == above and z.center_price != current_price
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda z: abs(z.center_price - current_price))


def build_position_technical(db: Session, position: PortfolioPosition) -> dict:
    """Position-aware technical status. Degrades to a structured unavailable dict
    when the underlying analysis is missing — never raises."""
    result = get_latest(db, position.symbol)
    base = result.to_dict()
    base["symbol"] = position.symbol

    if not result.available or result.current_price is None:
        base["arrival_estimates"] = []
        base["cost_basis_reference"] = {
            "average_cost": position.average_cost,
            "vs_current_price": None,
        }
        return base

    closes = _daily_closes(db, position.symbol)
    context_base = {
        "daily_closes": closes,
        "atr": result.atr,
    }

    estimates = []
    nearest_resistance = _nearest(result.resistance_zones, result.current_price, above=True)
    nearest_support = _nearest(result.support_zones, result.current_price, above=False)
    for label, zone in (("resistance", nearest_resistance), ("support", nearest_support)):
        if zone is None:
            continue
        ctx = {**context_base, "zone_id": f"{zone.zone_type}:{round(zone.center_price, 2)}"}
        estimate = estimate_arrival(result.current_price, zone, ctx)
        if estimate is not None:
            payload = estimate.to_dict()
            payload["direction"] = label
            payload["target_zone"] = zone.to_dict()
            estimates.append(payload)

    base["arrival_estimates"] = estimates
    base["cost_basis_reference"] = {
        "average_cost": position.average_cost,
        "vs_current_price": (
            round((result.current_price - position.average_cost) / position.average_cost * 100, 4)
            if position.average_cost > 0 else None
        ),
    }
    base["analyzer_version"] = ANALYZER_VERSION
    base["parameter_set_version"] = PARAMETER_SET_VERSION
    base["analysis_engine_version"] = ANALYSIS_ENGINE_VERSION
    return base
