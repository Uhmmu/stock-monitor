"""The service boundary the holdings module talks to.

`get_latest(symbol, timeframe)` reads the persisted `TechnicalAnalysis` row (the
existing engine's cached weekly output), runs the registered normalizing analyzers,
merges nearby levels into zones, and returns a `TechnicalResult`. If analysis is
missing/failed, it returns a structured unavailable result — never raises — so a
missing technical picture can't break holdings retrieval.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ANALYSIS_ENGINE_VERSION, ANALYZER_VERSION, PARAMETER_SET_VERSION
from app.models import HistoricalPrice, TechnicalAnalysis
from app.services.technical_analysis.analyzers import register_default_analyzers
from app.services.technical_analysis.registry import run_analyzers
from app.services.technical_analysis.schemas import TechnicalResult
from app.services.technical_analysis.zones import merge_zones

logger = logging.getLogger(__name__)

# register the built-in analyzers once at import time
register_default_analyzers()


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


def _unavailable(symbol: str, timeframe: str, status: str, reason: str) -> TechnicalResult:
    return TechnicalResult(
        symbol=symbol.upper(),
        timeframe=timeframe,
        available=False,
        status=status,
        unavailable_reason=reason,
        analyzer_version=ANALYZER_VERSION,
        parameter_set_version=PARAMETER_SET_VERSION,
        analysis_engine_version=ANALYSIS_ENGINE_VERSION,
    )


def get_latest(db: Session, symbol: str, timeframe: str = "1d") -> TechnicalResult:
    value = symbol.upper()
    try:
        row = db.get(TechnicalAnalysis, value)
    except Exception:
        return _unavailable(value, timeframe, "unavailable", "技术分析读取失败。")
    if row is None:
        return _unavailable(value, timeframe, "pending", "技术分析尚未生成。")
    if row.status != "ready" or not row.analysis:
        return _unavailable(value, timeframe, row.status or "pending", "技术分析尚未就绪。")

    analysis = row.analysis or {}
    indicators = analysis.get("indicators") or {}
    current_price = analysis.get("latestClose")
    atr = indicators.get("atr14")

    signals, errors = run_analyzers(value, timeframe, analysis, {"atr": atr, "current_price": current_price})
    support, resistance = merge_zones(signals, current_price, atr)

    trend_signal = next((s for s in signals if s.signal_type == "trend"), None)
    trend_state = "unknown"
    trend_strength = None
    if trend_signal:
        trend_strength = trend_signal.strength
        weekly = trend_signal.metadata.get("weekly_trend")
        trend_state = {"bullish": "uptrend", "bearish": "downtrend", "neutral": "range"}.get(weekly, "unknown")

    vol_signal = next((s for s in signals if s.signal_type == "volatility" and s.source == "atr14"), None)
    volatility_state = vol_signal.metadata.get("state", "unknown") if vol_signal else "unknown"

    return TechnicalResult(
        symbol=value,
        timeframe=timeframe,
        available=True,
        status="ready",
        current_price=current_price,
        trend_state=trend_state,
        trend_strength=trend_strength,
        volatility_state=volatility_state,
        atr=atr,
        signals=signals,
        support_zones=support,
        resistance_zones=resistance,
        indicators=indicators,
        analyzer_errors=errors,
        market_data_source=analysis.get("source"),
        data_through=analysis.get("dataThrough"),
        calculated_at=analysis.get("generatedAt") or (row.generated_at.isoformat() if row.generated_at else datetime.now(UTC).isoformat()),
        price_data_updated_at=row.data_through.isoformat() if row.data_through else None,
    )
