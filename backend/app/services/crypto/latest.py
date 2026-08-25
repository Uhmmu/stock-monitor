"""Latest crypto ticker cache (crypto/quant program WP 2.5, REST-first).

Redis holds only the newest bounded ticker payload per instrument with a
short TTL; PostgreSQL remains the history authority and the fallback when
the cache is empty or stale. REST polling satisfies the MVP by design; a
stream service may be added later without changing these semantics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CryptoAsset, CryptoInstrument
from app.services.crypto import candles as candle_service
from app.services.crypto.identity import instrument_display_label
from app.services.crypto.providers.binance import BinancePublicClient, BinancePublicError

logger = logging.getLogger(__name__)

PROVIDER_BY_MARKET = {"spot": "binance_spot", "usdm": "binance_usdm"}
DEFAULT_TTL_SECONDS = 60
DEFAULT_STALE_SECONDS = 180


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _redis():
    import redis

    return redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=2)


def _redis_get(key: str) -> str | None:
    try:
        client = _redis()
        value = client.get(key)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:
        return None


def _redis_setex(key: str, ttl_seconds: int, value: str) -> bool:
    try:
        return bool(_redis().setex(key, ttl_seconds, value))
    except Exception:
        return False


def _cache_key(instrument_id: int) -> str:
    return f"crypto:latest:{instrument_id}"


def _health_key(provider: str) -> str:
    return f"crypto:latest:health:{provider}"


def _now_ms() -> int:
    return int(_utcnow().timestamp() * 1000)


@dataclass
class RefreshSummary:
    refreshed: int = 0
    failed: list = field(default_factory=list)


def refresh_latest_tickers(
    db: Session,
    *,
    client: BinancePublicClient,
    instruments: list[CryptoInstrument],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> RefreshSummary:
    """Poll 24h tickers for the bounded universe into the short-TTL cache."""
    summary = RefreshSummary()
    now_iso = _utcnow().isoformat()
    for instrument in instruments:
        provider = PROVIDER_BY_MARKET.get(instrument.market, f"binance_{instrument.market}")
        try:
            ticker = client.ticker_24h(instrument.market, instrument.provider_symbol)
        except BinancePublicError as exc:
            summary.failed.append(
                {"instrument_id": instrument.id, "symbol": instrument.provider_symbol, "error": f"{exc.kind}: {exc.message}"}
            )
            continue
        payload = {
            "instrument_id": instrument.id,
            "provider": provider,
            "symbol": ticker.symbol,
            "last_price": str(ticker.last_price),
            "bid_price": str(ticker.bid_price),
            "ask_price": str(ticker.ask_price),
            "high_price_24h": str(ticker.high_price),
            "low_price_24h": str(ticker.low_price),
            "base_volume_24h": str(ticker.base_volume),
            "quote_volume_24h": str(ticker.quote_volume),
            # 24h rolling close time is the freshest provider event stamp
            "event_time_ms": ticker.close_time_ms,
            "received_at": ticker.received_at,
        }
        _redis_setex(_cache_key(instrument.id), ttl_seconds, json.dumps(payload))
        _redis_setex(
            _health_key(provider), max(ttl_seconds * 3, 300),
            json.dumps({"provider": provider, "last_success": now_iso, "instrument_count": len(instruments)}),
        )
        summary.refreshed += 1
    return summary


def latest_market_payload(
    db: Session,
    *,
    instrument: CryptoInstrument,
    interval: str = "1h",
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> dict:
    """Truthful latest view: cache first, closed-candle fallback with warning.

    Missing cache or an old event stamp never fabricates freshness; the
    payload always names its source and age.
    """
    base = db.get(CryptoAsset, instrument.base_asset_id)
    quote = db.get(CryptoAsset, instrument.quote_asset_id)
    label = instrument_display_label(instrument, base, quote) if base and quote else instrument.provider_symbol
    provider = PROVIDER_BY_MARKET.get(instrument.market, f"binance_{instrument.market}")
    now_ms = _now_ms()

    cached = _redis_get(_cache_key(instrument.id))
    if cached:
        try:
            payload = json.loads(cached)
        except ValueError:
            payload = None
        if payload and payload.get("provider") == provider:
            age_seconds = max(0, (now_ms - payload["event_time_ms"]) / 1000) if payload.get("event_time_ms") else None
            return {
                "instrument_id": instrument.id,
                "display_label": label,
                "source": "ticker_cache",
                "stale": bool(age_seconds is not None and age_seconds > stale_seconds),
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "warning": None,
                **{k: payload[k] for k in (
                    "provider", "symbol", "last_price", "bid_price", "ask_price",
                    "high_price_24h", "low_price_24h", "base_volume_24h", "quote_volume_24h",
                    "event_time_ms", "received_at",
                )},
            }

    candle = candle_service.latest_closed_candle(
        db, instrument_id=instrument.id, interval=interval, provider=provider
    )
    if candle is None:
        return {
            "instrument_id": instrument.id,
            "display_label": label,
            "source": "unavailable",
            "stale": True,
            "age_seconds": None,
            "warning": "数据不足：既无最新 ticker 缓存，也无已收盘 K 线",
            "provider": provider,
            "symbol": instrument.provider_symbol,
        }
    age_seconds = max(0, (now_ms - candle.close_time_ms) / 1000)
    return {
        "instrument_id": instrument.id,
        "display_label": label,
        "source": "closed_candle_fallback",
        "stale": age_seconds > stale_seconds,
        "age_seconds": round(age_seconds, 3),
        "warning": "ticker 缓存不可用，展示最近已收盘 K 线收盘价；非实时报价",
        "provider": candle.provider,
        "symbol": instrument.provider_symbol,
        "last_price": str(candle.close),
        "bid_price": None,
        "ask_price": None,
        "high_price_24h": None,
        "low_price_24h": None,
        "base_volume_24h": None,
        "quote_volume_24h": None,
        "event_time_ms": candle.close_time_ms,
        "received_at": candle.fetched_at.isoformat() if candle.fetched_at else None,
    }
