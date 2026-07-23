"""Normalized technical-analysis contracts.

These are the ONLY shapes the holdings module is allowed to consume. Individual
analyzers (swing points, moving averages, Bollinger, Fibonacci, trend lines,
volume profile, …) all normalize their output into these dataclasses, so the
holdings domain never depends on any single analyzer's implementation details.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.config import ANALYSIS_ENGINE_VERSION, ANALYZER_VERSION, PARAMETER_SET_VERSION


@dataclass
class TechnicalSignal:
    """A single normalized technical observation emitted by one analyzer."""

    signal_type: str  # e.g. support_zone / resistance_zone / trend / momentum / volatility
    direction: str  # bullish / bearish / neutral
    timeframe: str  # 1d / 1w …
    strength: float  # 0..1
    confidence: float  # 0..1
    source: str  # analyzer-specific origin, e.g. swing_low_cluster / ma60
    value: float | None = None
    price_zone_low: float | None = None
    price_zone_high: float | None = None
    detected_at: datetime | None = None
    valid_until: datetime | None = None
    analyzer_version: str = ANALYZER_VERSION
    parameter_set_version: str = PARAMETER_SET_VERSION
    analysis_engine_version: str = ANALYSIS_ENGINE_VERSION
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "strength": self.strength,
            "confidence": self.confidence,
            "value": self.value,
            "price_zone_low": self.price_zone_low,
            "price_zone_high": self.price_zone_high,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "source": self.source,
            "analyzer_version": self.analyzer_version,
            "parameter_set_version": self.parameter_set_version,
            "analysis_engine_version": self.analysis_engine_version,
            "metadata": self.metadata,
        }


@dataclass
class PriceLevelZone:
    """A support/resistance level expressed as a zone, merged from nearby signals."""

    zone_type: str  # support / resistance
    lower_price: float
    upper_price: float
    center_price: float
    strength: float
    confidence: float
    timeframe: str
    sources: list[str] = field(default_factory=list)
    source_signal_ids: list[str] = field(default_factory=list)
    touch_count: int = 0
    last_touched_at: str | None = None
    status: str = "active"  # active / approaching / testing / broken / reclaimed / expired
    analyzer_version: str = ANALYZER_VERSION
    parameter_set_version: str = PARAMETER_SET_VERSION
    analysis_engine_version: str = ANALYSIS_ENGINE_VERSION

    def to_dict(self) -> dict:
        return {
            "zone_type": self.zone_type,
            "lower_price": self.lower_price,
            "upper_price": self.upper_price,
            "center_price": self.center_price,
            "strength": self.strength,
            "confidence": self.confidence,
            "timeframe": self.timeframe,
            "sources": self.sources,
            "source_signal_ids": self.source_signal_ids,
            "touch_count": self.touch_count,
            "last_touched_at": self.last_touched_at,
            "status": self.status,
            "analyzer_version": self.analyzer_version,
            "parameter_set_version": self.parameter_set_version,
            "analysis_engine_version": self.analysis_engine_version,
        }


@dataclass
class ArrivalEstimate:
    """Probabilistic estimate of how long price may take to reach a zone.

    Never a guaranteed forecast; always probability + trading-day ranges, or a
    structured unavailable result.
    """

    estimator: str
    target_zone_id: str
    probability_5d: float | None = None
    probability_10d: float | None = None
    probability_20d: float | None = None
    median_days: int | None = None
    lower_days: int | None = None
    upper_days: int | None = None
    confidence: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None
    analyzer_version: str = ANALYZER_VERSION
    parameter_set_version: str = PARAMETER_SET_VERSION
    analysis_engine_version: str = ANALYSIS_ENGINE_VERSION

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    def to_dict(self) -> dict:
        return {
            "estimator": self.estimator,
            "target_zone_id": self.target_zone_id,
            "available": self.available,
            "probability_5d": self.probability_5d,
            "probability_10d": self.probability_10d,
            "probability_20d": self.probability_20d,
            "median_days": self.median_days,
            "lower_days": self.lower_days,
            "upper_days": self.upper_days,
            "confidence": self.confidence,
            "assumptions": self.assumptions,
            "unavailable_reason": self.unavailable_reason,
            "analyzer_version": self.analyzer_version,
            "parameter_set_version": self.parameter_set_version,
            "analysis_engine_version": self.analysis_engine_version,
        }


@dataclass
class TechnicalResult:
    """Everything the holdings module needs about one symbol's technical picture."""

    symbol: str
    timeframe: str
    available: bool
    status: str  # ready / pending / failed / unavailable
    current_price: float | None = None
    trend_state: str = "unknown"  # uptrend / downtrend / range / unknown
    trend_strength: float | None = None
    volatility_state: str = "unknown"  # expanding / contracting / normal / unknown
    atr: float | None = None
    signals: list[TechnicalSignal] = field(default_factory=list)
    support_zones: list[PriceLevelZone] = field(default_factory=list)
    resistance_zones: list[PriceLevelZone] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)
    analyzer_errors: list[dict] = field(default_factory=list)
    market_data_source: str | None = None
    data_through: str | None = None
    calculated_at: str | None = None
    price_data_updated_at: str | None = None
    analyzer_version: str = ANALYZER_VERSION
    parameter_set_version: str = PARAMETER_SET_VERSION
    analysis_engine_version: str = ANALYSIS_ENGINE_VERSION
    unavailable_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "available": self.available,
            "status": self.status,
            "current_price": self.current_price,
            "trend_state": self.trend_state,
            "trend_strength": self.trend_strength,
            "volatility_state": self.volatility_state,
            "atr": self.atr,
            "signals": [s.to_dict() for s in self.signals],
            "support_zones": [z.to_dict() for z in self.support_zones],
            "resistance_zones": [z.to_dict() for z in self.resistance_zones],
            "indicators": self.indicators,
            "analyzer_errors": self.analyzer_errors,
            "market_data_source": self.market_data_source,
            "data_through": self.data_through,
            "calculated_at": self.calculated_at,
            "price_data_updated_at": self.price_data_updated_at,
            "analyzer_version": self.analyzer_version,
            "parameter_set_version": self.parameter_set_version,
            "analysis_engine_version": self.analysis_engine_version,
            "unavailable_reason": self.unavailable_reason,
        }
