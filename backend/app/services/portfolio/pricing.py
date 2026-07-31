"""Current-price lookup for holdings valuation.

Reads what the pipeline already persisted rather than making live calls per
request: latest `PriceSnapshot` (the dashboard's poll source) first, then the
most recent daily close (FMP primary, Yahoo fallback — matching the rest of the
app). Returns None when no price is known — callers surface an explicit gap
("数据不足") rather than valuing the position at zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice, PriceSnapshot
from app.services.price_snapshots import get_latest_persisted_price_snapshot


@dataclass(frozen=True)
class PriceInfo:
    price: float
    source: str  # snapshot / fmp / yahoo
    previous_close: float | None = None
    as_of: date | datetime | None = None


def latest_price(db: Session, symbol: str) -> PriceInfo | None:
    value = symbol.upper()
    snap = get_latest_persisted_price_snapshot(db, value)
    if snap is not None and snap.last_price:
        return PriceInfo(
            price=float(snap.last_price),
            source="snapshot",
            previous_close=snap.previous_close,
            as_of=snap.market_timestamp or snap.fetched_at,
        )

    for source in ("fmp", "yahoo"):
        row = db.scalar(
            select(HistoricalPrice)
            .where(HistoricalPrice.symbol == value, HistoricalPrice.source == source)
            .order_by(HistoricalPrice.date.desc())
            .limit(1)
        )
        if row is not None and row.close:
            prev = float(row.close) - float(row.change) if row.change is not None else None
            return PriceInfo(price=float(row.close), source=source, previous_close=prev, as_of=row.date)
    return None


def price_map(db: Session, symbols: list[str]) -> dict[str, PriceInfo]:
    """Resolve prices in at most three queries, preserving the existing source order."""
    wanted = {symbol.upper() for symbol in symbols}
    if not wanted:
        return {}
    result: dict[str, PriceInfo] = {}
    snapshots = db.scalars(
        select(PriceSnapshot).where(
            PriceSnapshot.symbol.in_(wanted),
            PriceSnapshot.source_type == "price_snapshot",
            PriceSnapshot.last_price > 0,
        ).order_by(
            PriceSnapshot.symbol,
            PriceSnapshot.market_timestamp.desc().nullslast(),
            PriceSnapshot.fetched_at.desc().nullslast(),
            PriceSnapshot.persisted_at.desc().nullslast(),
        )
    ).all()
    for row in snapshots:
        if row.symbol not in result and row.last_price:
            result[row.symbol] = PriceInfo(
                price=float(row.last_price),
                source="snapshot",
                previous_close=row.previous_close,
                as_of=row.market_timestamp or row.fetched_at,
            )
    unresolved = wanted - result.keys()
    for source in ("fmp", "yahoo"):
        if not unresolved:
            break
        rows = db.scalars(
            select(HistoricalPrice).where(
                HistoricalPrice.symbol.in_(unresolved), HistoricalPrice.source == source,
            ).order_by(HistoricalPrice.symbol, HistoricalPrice.date.desc())
        ).all()
        for row in rows:
            if row.symbol in result or not row.close:
                continue
            previous = float(row.close) - float(row.change) if row.change is not None else None
            result[row.symbol] = PriceInfo(
                price=float(row.close), source=source, previous_close=previous, as_of=row.date,
            )
        unresolved = wanted - result.keys()
    return result
