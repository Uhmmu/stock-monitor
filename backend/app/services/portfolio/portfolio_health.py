"""Structural portfolio health (Sections 20-24).

Deliberately separate from technical condition: this measures how the portfolio
is *built* (concentration, sector exposure), not where any holding sits in its
chart. Weights come from market value; positions with no known price are excluded
from the weighted base and reported as a coverage gap rather than silently zeroed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Portfolio, StockProfile

from .performance import build_summary


def _concentration(weights: list[float]) -> dict:
    """weights are fractions in [0,1] over the priced base."""
    if not weights:
        return {
            "available": False,
            "reason": "暂无可估值持仓，无法计算集中度。",
            "hhi": None,
            "top_five_weight": None,
            "effective_holdings": None,
        }
    hhi = sum(w * w for w in weights)
    ordered = sorted(weights, reverse=True)
    top_five = sum(ordered[:5])
    return {
        "available": True,
        "hhi": round(hhi, 6),
        # HHI on fractions ranges (0,1]; scale to the familiar 0-10000 too
        "hhi_scaled": round(hhi * 10000, 2),
        "top_five_weight": round(top_five * 100, 4),
        "effective_holdings": round(1 / hhi, 2) if hhi > 0 else None,
        "holdings_count": len(weights),
    }


def _sector_exposure(db: Session, priced_positions: list[dict], total_market_value: float) -> dict:
    if total_market_value <= 0:
        return {"available": False, "reason": "暂无可估值持仓，无法计算行业暴露。", "buckets": []}
    symbols = [p["symbol"] for p in priced_positions]
    profiles = {
        row.ticker: row.official_sector
        for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(symbols))).all()
    }
    buckets: dict[str, float] = {}
    unknown_value = 0.0
    for pos in priced_positions:
        sector = profiles.get(pos["symbol"]) or None
        if sector is None:
            unknown_value += pos["market_value"]
            continue
        buckets[sector] = buckets.get(sector, 0.0) + pos["market_value"]
    out = [
        {"sector": sector, "market_value": round(value, 4),
         "weight": round(value / total_market_value * 100, 4)}
        for sector, value in sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return {
        "available": True,
        "buckets": out,
        # honest gap: value we couldn't classify (Section: never fabricate)
        "unclassified_weight": round(unknown_value / total_market_value * 100, 4) if unknown_value else 0.0,
    }


def build_health(db: Session, portfolio: Portfolio) -> dict:
    summary = build_summary(db, portfolio)
    priced = [p for p in summary["positions"] if p["price_available"]]
    total_mv = summary["total_market_value"]
    weights = [p["market_value"] / total_mv for p in priced] if total_mv > 0 else []

    return {
        "portfolio_id": portfolio.id,
        "total_market_value": total_mv,
        "priced_count": len(priced),
        "position_count": summary["position_count"],
        "has_unpriced_positions": summary["has_unpriced_positions"],
        "concentration": _concentration(weights),
        "sector_exposure": _sector_exposure(db, priced, total_mv),
    }
