"""Shared persistence helpers for validated daily OHLCV bars."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice
from app.services.industry_pulse.provider import ProviderHistory


def upsert_history(
    db: Session,
    ticker: str,
    history: ProviderHistory,
    existing_cache: dict[tuple[str, str, date], HistoricalPrice] | None = None,
) -> int:
    if not history.bars or not history.provider:
        return 0
    symbol = ticker.upper()
    source = "yahoo" if history.provider == "yfinance" else history.provider
    existing = (
        {day: row for (cached_symbol, cached_source, day), row in existing_cache.items() if cached_symbol == symbol and cached_source == source}
        if existing_cache is not None
        else {row.date: row for row in db.scalars(select(HistoricalPrice).where(HistoricalPrice.symbol == symbol, HistoricalPrice.source == source)).all()}
    )
    inserted = 0
    for bar in history.bars:
        row = existing.get(bar.date)
        if row is None:
            row = HistoricalPrice(symbol=symbol, date=bar.date, source=source)
            db.add(row)
            existing[bar.date] = row
            if existing_cache is not None:
                existing_cache[(symbol, source, bar.date)] = row
            inserted += 1
        row.open, row.high, row.low, row.close = bar.open, bar.high, bar.low, bar.close
        row.adjusted_close, row.volume = bar.adjusted_close, bar.volume
    return inserted


def latest_dates(db: Session, symbols: list[str] | set[str] | tuple[str, ...]) -> dict[str, date]:
    values = {str(symbol).upper() for symbol in symbols}
    rows = db.execute(
        select(HistoricalPrice.symbol, HistoricalPrice.date)
        .where(HistoricalPrice.symbol.in_(values))
        .order_by(HistoricalPrice.symbol, HistoricalPrice.date.desc())
    ).all()
    result: dict[str, date] = {}
    for symbol, day in rows:
        result.setdefault(symbol, day)
    return result


def history_counts(db: Session, symbols: list[str] | set[str] | tuple[str, ...], source: str | None = None) -> dict[str, int]:
    values = {str(symbol).upper() for symbol in symbols}
    query = select(HistoricalPrice.symbol, HistoricalPrice.date).where(HistoricalPrice.symbol.in_(values))
    if source:
        query = query.where(HistoricalPrice.source == source)
    rows = db.execute(query).all()
    days: dict[str, set[date]] = {}
    for symbol, day in rows:
        days.setdefault(symbol, set()).add(day)
    return {symbol: len(symbol_days) for symbol, symbol_days in days.items()}
