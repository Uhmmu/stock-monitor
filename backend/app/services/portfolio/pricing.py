"""Current-price lookup for holdings valuation.

Reads what the pipeline already persisted rather than making live calls per
request: latest `PriceSnapshot` (the dashboard's poll source) first, then the
most recent daily close (FMP primary, Yahoo fallback — matching the rest of the
app). Returns None when no price is known — callers surface an explicit gap
("数据不足") rather than valuing the position at zero.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice, PriceSnapshot
from app.config import get_settings
from app.services.price_snapshots import get_latest_persisted_price_snapshot


@dataclass(frozen=True)
class PriceInfo:
    price: float
    source: str  # snapshot / fmp / yahoo
    previous_close: float | None = None
    as_of: date | datetime | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    vwap: float | None = None
    volume: float | None = None
    market_session: str | None = None
    is_delayed: bool | None = None
    feed: str | None = None


def _realtime_prices(symbols: set[str]) -> dict[str, PriceInfo]:
    if not symbols:
        return {}
    try:
        import redis
        settings = get_settings()
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=.3, socket_timeout=.3)
        raw_values = client.mget([f"market:realtime:{symbol}" for symbol in sorted(symbols)])
    except Exception:
        return {}
    result: dict[str, PriceInfo] = {}
    for symbol, raw in zip(sorted(symbols), raw_values):
        try:
            envelope = json.loads(raw) if raw else None
            quote = envelope.get("authoritative_quote") if isinstance(envelope, dict) and isinstance(envelope.get("authoritative_quote"), dict) else envelope
            if not isinstance(quote, dict):
                continue
            price = float(quote.get("price"))
            timestamp = datetime.fromisoformat(str(quote.get("timestamp")).replace("Z", "+00:00"))
            timestamp = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
            if price <= 0 or (datetime.now(UTC) - timestamp).total_seconds() > max(1, settings.realtime_stale_seconds):
                continue
            def number(key):
                try: return float(quote[key]) if quote.get(key) is not None else None
                except (TypeError, ValueError): return None
            result[symbol] = PriceInfo(
                price=price, source=f"realtime:{quote.get('provider') or 'unknown'}",
                previous_close=number("previous_close"), as_of=timestamp,
                open=number("open"), day_high=number("high"), day_low=number("low"),
                vwap=number("vwap"), volume=number("volume"),
                market_session=quote.get("market_session"), is_delayed=quote.get("is_delayed"),
                feed=quote.get("feed"),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return result


def latest_price(db: Session, symbol: str) -> PriceInfo | None:
    value = symbol.upper()
    realtime = _realtime_prices({value}).get(value)
    if realtime is not None:
        return realtime
    snap = get_latest_persisted_price_snapshot(db, value)
    if snap is not None and snap.last_price:
        return PriceInfo(
            price=float(snap.last_price),
            source="snapshot",
            previous_close=snap.previous_close,
            as_of=snap.market_timestamp or snap.fetched_at,
            open=snap.open_price, day_high=snap.day_high, day_low=snap.day_low,
            volume=snap.day_volume, market_session=snap.market_session,
            is_delayed=snap.is_delayed,
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
    result: dict[str, PriceInfo] = _realtime_prices(wanted)
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
    seen_snapshot_symbols: set[str] = set()
    for row in snapshots:
        if row.symbol in seen_snapshot_symbols:
            continue
        seen_snapshot_symbols.add(row.symbol)
        if row.symbol in result:
            current = result[row.symbol]
            # Realtime feeds are authoritative for the latest price but some
            # omit session reference fields. Preserve the fresh price while
            # filling those gaps from the latest persisted market snapshot.
            result[row.symbol] = replace(
                current,
                previous_close=current.previous_close if current.previous_close is not None else row.previous_close,
                open=current.open if current.open is not None else row.open_price,
                day_high=current.day_high if current.day_high is not None else row.day_high,
                day_low=current.day_low if current.day_low is not None else row.day_low,
                volume=current.volume if current.volume is not None else row.day_volume,
                market_session=current.market_session or row.market_session,
                is_delayed=current.is_delayed if current.is_delayed is not None else row.is_delayed,
                feed=current.feed or row.feed,
            )
        elif row.last_price:
            result[row.symbol] = PriceInfo(
                price=float(row.last_price),
                source="snapshot",
                previous_close=row.previous_close,
                as_of=row.market_timestamp or row.fetched_at,
                open=row.open_price, day_high=row.day_high, day_low=row.day_low,
                volume=row.day_volume, market_session=row.market_session,
                is_delayed=row.is_delayed,
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
