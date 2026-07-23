"""Current-price lookup for holdings valuation.

Reads what the pipeline already persisted rather than making live calls per
request: latest `PriceSnapshot` (the dashboard's poll source) first, then the
most recent daily close (FMP primary, Yahoo fallback — matching the rest of the
app). Returns None when no price is known — callers surface an explicit gap
("数据不足") rather than valuing the position at zero.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice, PriceSnapshot


@dataclass(frozen=True)
class PriceInfo:
    price: float
    source: str  # snapshot / fmp / yahoo
    previous_close: float | None = None


def latest_price(db: Session, symbol: str) -> PriceInfo | None:
    value = symbol.upper()
    snap = db.scalar(
        select(PriceSnapshot)
        .where(PriceSnapshot.ticker == value)
        .order_by(PriceSnapshot.quote_time.desc())
        .limit(1)
    )
    if snap is not None and snap.price:
        return PriceInfo(price=float(snap.price), source="snapshot", previous_close=snap.previous_close)

    for source in ("fmp", "yahoo"):
        row = db.scalar(
            select(HistoricalPrice)
            .where(HistoricalPrice.symbol == value, HistoricalPrice.source == source)
            .order_by(HistoricalPrice.date.desc())
            .limit(1)
        )
        if row is not None and row.close:
            prev = float(row.close) - float(row.change) if row.change is not None else None
            return PriceInfo(price=float(row.close), source=source, previous_close=prev)
    return None


def price_map(db: Session, symbols: list[str]) -> dict[str, PriceInfo]:
    return {s: info for s in {sym.upper() for sym in symbols} if (info := latest_price(db, s))}
