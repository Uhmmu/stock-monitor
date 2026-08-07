"""Authenticated realtime/intraday market API; browsers never contact providers."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import NewsProviderState
from app.research.security import normalize_symbol
from app.services.intraday_market import bar_out, event_out, intraday_bars, intraday_summary, monitor_events
from app.services.price_snapshots import get_latest_persisted_price_snapshot, price_snapshot_out


router = APIRouter(prefix="/api/market", tags=["realtime-market"], dependencies=[Depends(get_current_user)])
REALTIME_CHANNEL = "market:realtime:updates"


# Register the static stream path before ``/realtime/{symbol}``; Starlette
# resolves routes in declaration order.
@router.get("/realtime/stream")
async def realtime_stream_route(request: Request, symbols: str = Query(..., min_length=1)):
    return await _realtime_stream_response(request, symbols)


def _symbols(value: str | None) -> list[str]:
    result: list[str] = []
    for item in (value or "").split(","):
        if not item.strip():
            continue
        symbol = normalize_symbol(item)
        if symbol not in result:
            result.append(symbol)
    if len(result) > 50:
        raise HTTPException(422, "最多查询 50 个股票代码")
    return result


def _client():
    settings = get_settings()
    return redis.Redis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=1, socket_timeout=1,
    )


def _decoded(raw: str | bytes | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _redis_quote(symbol: str) -> dict[str, Any] | None:
    try:
        value = _decoded(_client().get(f"market:realtime:{symbol}"))
    except redis.RedisError:
        return None
    if not value:
        return None
    # State implementations may store a quote directly or a full envelope.
    quote = value.get("authoritative_quote") if isinstance(value.get("authoritative_quote"), dict) else value
    timestamp = quote.get("timestamp")
    try:
        stamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
        age = max(0, int((datetime.now(UTC) - stamp).total_seconds()))
    except (TypeError, ValueError):
        age = None
    stale_after = max(1, get_settings().realtime_stale_seconds)
    value["stale"] = age is None or age > stale_after
    value["age_seconds"] = age
    value["stale_after_seconds"] = stale_after
    value["source_type"] = "realtime_quote"
    for key, field in quote.items():
        value.setdefault(key, field)
    value["is_stale"] = value["stale"]
    return value


def _snapshot_fallback(db: Session, symbol: str) -> dict[str, Any] | None:
    row = get_latest_persisted_price_snapshot(db, symbol)
    if row is None:
        return None
    snapshot = price_snapshot_out(row)
    result = {
        "symbol": symbol,
        "authoritative_quote": {
            "symbol": symbol, "price": snapshot["last_price"],
            "open": snapshot["open_price"], "high": snapshot["day_high"],
            "low": snapshot["day_low"], "previous_close": snapshot["previous_close"],
            "volume": snapshot["day_volume"], "timestamp": snapshot["market_timestamp"] or snapshot["fetched_at"],
            "received_at": snapshot["fetched_at"], "provider": snapshot["provider"],
            "feed": None, "market_session": snapshot["market_session"],
            "is_delayed": snapshot["is_delayed"], "delayed_seconds": snapshot["delay_seconds"],
        },
        "alternate_quotes": [], "divergence": None,
        "stale": snapshot["is_stale"], "age_seconds": snapshot["age_seconds"],
        "stale_after_seconds": snapshot["stale_after_seconds"],
        "source_type": "price_snapshot_fallback",
    }
    result.update(result["authoritative_quote"])
    result["is_stale"] = result["stale"]
    return result


def realtime_value(db: Session, symbol: str) -> dict[str, Any] | None:
    return _redis_quote(symbol) or _snapshot_fallback(db, symbol)


@router.get("/realtime/{symbol}")
def realtime_quote(symbol: str, db: Session = Depends(get_db)):
    value = normalize_symbol(symbol)
    result = realtime_value(db, value)
    if result is None:
        raise HTTPException(404, f"{value} 暂无可用行情")
    return result


@router.get("/realtime")
def realtime_quotes(symbols: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    values = _symbols(symbols)
    quotes = {symbol: realtime_value(db, symbol) for symbol in values}
    return {
        "quotes": [value for value in quotes.values() if value is not None],
        "missing": [symbol for symbol, value in quotes.items() if value is None],
    }


@router.get("/intraday/{symbol}")
def get_intraday_bars(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|5m|15m)$"),
    range: str = Query("1d", pattern="^(1d|5d)$"),
    limit: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    value = normalize_symbol(symbol)
    end = datetime.now(UTC)
    start = end - timedelta(days=5 if range == "5d" else 1)
    rows = intraday_bars(db, value, interval=interval, start=start, end=end, limit=limit)
    return {"symbol": value, "interval": interval, "range": range, "bars": [bar_out(row) for row in rows]}


@router.get("/intraday/{symbol}/summary")
def get_intraday_summary(symbol: str, db: Session = Depends(get_db)):
    return intraday_summary(db, normalize_symbol(symbol))


@router.get("/events")
def get_market_events(
    symbols: str | None = None, since: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db),
):
    rows = monitor_events(db, symbols=_symbols(symbols), since=since, limit=limit)
    return {"events": [event_out(row) for row in rows], "count": len(rows)}


@router.get("/providers/status")
def provider_status(db: Session = Depends(get_db)):
    names = ("alpaca", "tiingo", "finnhub", "yfinance")
    market: dict[str, Any] = {}
    client = None
    try:
        client = _client()
        for name in names:
            market[name] = _decoded(client.get(f"market:provider:{name}:health"))
    except redis.RedisError:
        market = {name: None for name in names}
    news_rows = db.scalars(select(NewsProviderState)).all()
    news = {
        row.provider: {
            "last_fetch": row.last_execution_at, "last_success": row.last_successful_fetch,
            "requests_today": row.request_count, "updated_at": row.updated_at,
        }
        for row in news_rows
    }
    for name in ("tiingo", "marketaux", "yfinance", "finnhub"):
        cached = None
        if client is not None:
            try:
                cached = _decoded(client.get(f"news:provider:{name}:health"))
            except redis.RedisError:
                pass
        if cached:
            news[name] = {**(news.get(name) or {}), **cached}
        else:
            news.setdefault(name, None)
    providers = dict(market)
    for name, value in news.items():
        key = f"{name}_news" if name in providers else name
        providers[key] = value
    return {"providers": providers, "generated_at": datetime.now(UTC), "redis_available": client is not None}


async def _realtime_stream_response(request: Request, symbols: str):
    wanted = set(_symbols(symbols))
    heartbeat = max(5, get_settings().realtime_sse_heartbeat_seconds)

    async def events():
        import redis.asyncio as aioredis
        client = aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(REALTIME_CHANNEL)
            yield "event: ready\ndata: {\"connected\":true}\n\n"
            while not await request.is_disconnected():
                message = await pubsub.get_message(timeout=heartbeat)
                if not message:
                    yield ": heartbeat\n\n"
                    continue
                data = _decoded(message.get("data"))
                if not data:
                    continue
                symbol = str(data.get("symbol") or (data.get("data") or {}).get("symbol") or "").upper()
                if symbol and symbol not in wanted:
                    continue
                event = str(data.get("event") or "quote_update")
                safe = json.dumps(data.get("data", data), ensure_ascii=False, separators=(",", ":"))
                yield f"event: {event}\ndata: {safe}\n\n"
        except (redis.RedisError, asyncio.CancelledError):
            if not await request.is_disconnected():
                yield "event: provider_status\ndata: {\"connected\":false}\n\n"
        finally:
            await pubsub.aclose()
            await client.aclose()

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })
