"""Crypto technical analysis over persisted candles (crypto/quant program WP 3.3).

Reuses the equity engine's pure indicator math (SMA/EMA/RSI/ATR/MACD/
Bollinger) on normalized crypto candles. No 252-day/XNYS assumptions:
parameter sets are versioned per interval, minimum history is explicit, and
insufficient data returns a gap — never fabricated indicator values. The
equity ``TechnicalAnalysis`` store is never written.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.services.crypto import candles as candle_service
from app.services.technical_analysis_engine import atr, bollinger, ema, macd, rsi, sma

CRYPTO_TECHNICAL_VERSION = "crypto-v1"
PARAMETER_SET_VERSION = "crypto-indicators-v1"

# per-interval parameter set; all use causal windows only
PARAMETER_SETS = {
    "1h": {"rsi": 14, "atr": 14, "sma": [20, 50, 200], "ema": [21], "bollinger": {"period": 20, "stddev": 2.0}},
    "4h": {"rsi": 14, "atr": 14, "sma": [20, 50, 200], "ema": [21], "bollinger": {"period": 20, "stddev": 2.0}},
    "1d": {"rsi": 14, "atr": 14, "sma": [20, 50, 200], "ema": [21], "bollinger": {"period": 20, "stddev": 2.0}},
}

MIN_CANDLES = 30
CHART_WINDOW = 500


def _rows_for_engine(candles):
    return [{"high": float(c.high), "low": float(c.low), "close": float(c.close)} for c in candles]


def _series(points: list[tuple[int, float | None]]) -> list[dict]:
    return [{"time_ms": t, "value": v} for t, v in points if v is not None]


def _last(values) -> float | None:
    for value in reversed(values):
        if value is not None:
            return float(value)
    return None


def crypto_technical_payload(
    db: Session,
    *,
    instrument_id: int,
    interval: str,
    limit: int = 1000,
) -> dict:
    """Deterministic indicator read over closed candles; explicit omissions."""
    params = PARAMETER_SETS.get(interval)
    if params is None:
        return {"status": "invalid", "reason": f"unsupported interval {interval!r}", "version": CRYPTO_TECHNICAL_VERSION}

    candles = candle_service.read_candles(
        db, instrument_id=instrument_id, interval=interval, limit=max(limit, CHART_WINDOW)
    )
    if len(candles) < MIN_CANDLES:
        return {
            "status": "insufficient",
            "version": CRYPTO_TECHNICAL_VERSION,
            "parameter_set_version": PARAMETER_SET_VERSION,
            "interval": interval,
            "candle_count": len(candles),
            "minimum_required": MIN_CANDLES,
            "reason": f"数据不足：{interval} 已收盘 K 线仅 {len(candles)} 根，至少需要 {MIN_CANDLES} 根",
            "omissions": ["rsi", "atr", "sma", "ema", "bollinger", "macd"],
        }

    closes = [float(c.close) for c in candles]
    times = [c.open_time_ms for c in candles]
    rows = _rows_for_engine(candles)
    window = candles[-CHART_WINDOW:]

    sma_series = {period: _series(list(zip(times, sma(closes, period))))[-CHART_WINDOW:] for period in params["sma"]}
    ema_series = {period: _series(list(zip(times, ema(closes, period))))[-CHART_WINDOW:] for period in params["ema"]}
    rsi_values = rsi(closes, params["rsi"])
    atr_values = atr(rows, params["atr"])
    macd_line, macd_signal, macd_hist = macd(closes)
    lower, middle, upper = bollinger(closes, params["bollinger"]["period"], params["bollinger"]["stddev"])

    digest = hashlib.sha256(
        json.dumps(
            {
                "instrument_id": instrument_id,
                "interval": interval,
                "candles": [[c.open_time_ms, str(c.open), str(c.high), str(c.low), str(c.close), str(c.base_volume)] for c in candles],
            },
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    return {
        "status": "ready",
        "version": CRYPTO_TECHNICAL_VERSION,
        "parameter_set_version": PARAMETER_SET_VERSION,
        "interval": interval,
        "candle_count": len(candles),
        "minimum_required": MIN_CANDLES,
        "data_through_ms": candles[-1].close_time_ms,
        "input_hash": digest,
        "last": {
            "close": str(candles[-1].close),
            "rsi": _last(rsi_values),
            "atr": _last(atr_values),
            "macd": _last(macd_line),
            "macd_signal": _last(macd_signal),
            "macd_histogram": _last(macd_hist),
            "bollinger_upper": _last(upper),
            "bollinger_middle": _last(middle),
            "bollinger_lower": _last(lower),
        },
        "series": {
            "time_ms": [c.open_time_ms for c in window],
            "close": [str(c.close) for c in window],
            **{f"sma{period}": sma_series[period] for period in params["sma"]},
            **{f"ema{period}": ema_series[period] for period in params["ema"]},
        },
        "omissions": [],
        "note": "指标由已收盘 K 线确定性计算，参数集按周期版本化；不含股票日历或 252 日假设",
    }
