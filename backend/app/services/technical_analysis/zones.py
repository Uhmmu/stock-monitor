"""Merge nearby support/resistance signals into combined PriceLevelZones.

Rule: merge when the distance between zone centers is <= ATR × threshold.
The threshold is configurable (not hardcoded inside unrelated logic) and defaults
to ZONE_MERGE_ATR_MULTIPLE. Merged zones preserve every contributing source.
"""
from __future__ import annotations

from app.services.technical_analysis.schemas import PriceLevelZone, TechnicalSignal

# Configurable merge threshold (multiples of ATR). Kept here as a single knob so
# future analyzers/tuning change one value rather than scattering constants.
ZONE_MERGE_ATR_MULTIPLE = 0.75


def _zone_signals(signals: list[TechnicalSignal], zone_type: str) -> list[TechnicalSignal]:
    wanted = "support_zone" if zone_type == "support" else "resistance_zone"
    return [
        s
        for s in signals
        if s.signal_type == wanted and s.price_zone_low is not None and s.price_zone_high is not None
    ]


def merge_zones(
    signals: list[TechnicalSignal],
    current_price: float | None,
    atr: float | None,
    *,
    threshold: float = ZONE_MERGE_ATR_MULTIPLE,
) -> tuple[list[PriceLevelZone], list[PriceLevelZone]]:
    """Return (support_zones, resistance_zones) merged from signals."""
    support = _merge_kind(_zone_signals(signals, "support"), "support", current_price, atr, threshold)
    resistance = _merge_kind(_zone_signals(signals, "resistance"), "resistance", current_price, atr, threshold)
    return support, resistance


def _center(sig: TechnicalSignal) -> float:
    if sig.value is not None:
        return sig.value
    return ((sig.price_zone_low or 0) + (sig.price_zone_high or 0)) / 2


def _merge_kind(
    signals: list[TechnicalSignal],
    zone_type: str,
    current_price: float | None,
    atr: float | None,
    threshold: float,
) -> list[PriceLevelZone]:
    if not signals:
        return []
    tolerance = (atr or 0) * threshold
    if tolerance <= 0 and current_price:
        tolerance = current_price * 0.012  # fallback when ATR unavailable
    ordered = sorted(signals, key=_center)
    clusters: list[list[TechnicalSignal]] = []
    for sig in ordered:
        if clusters and abs(_center(sig) - _center(clusters[-1][-1])) <= tolerance:
            clusters[-1].append(sig)
        else:
            clusters.append([sig])
    zones: list[PriceLevelZone] = []
    for idx, cluster in enumerate(clusters):
        low = min(s.price_zone_low for s in cluster)
        high = max(s.price_zone_high for s in cluster)
        center = sum(_center(s) for s in cluster) / len(cluster)
        strength = min(1.0, sum(s.strength for s in cluster) / len(cluster) + 0.08 * (len(cluster) - 1))
        confidence = sum(s.confidence for s in cluster) / len(cluster)
        sources = sorted({s.source for s in cluster})
        touch = sum(int(s.metadata.get("touch_count") or 0) for s in cluster)
        last_touched = max((s.metadata.get("most_recent_touch") for s in cluster if s.metadata.get("most_recent_touch")), default=None)
        zones.append(
            PriceLevelZone(
                zone_type=zone_type,
                lower_price=low,
                upper_price=high,
                center_price=center,
                strength=strength,
                confidence=confidence,
                timeframe=cluster[0].timeframe,
                sources=sources,
                source_signal_ids=[f"{zone_type}:{idx}:{s.source}" for s in cluster],
                touch_count=touch,
                last_touched_at=last_touched,
                status=_zone_status(zone_type, low, high, current_price, atr),
            )
        )
    # nearest-first ordering relative to price
    if current_price is not None:
        zones.sort(key=lambda z: abs(z.center_price - current_price))
    return zones


def _zone_status(zone_type: str, low: float, high: float, price: float | None, atr: float | None) -> str:
    if price is None:
        return "active"
    band = (atr or 0) * 0.3 or (price * 0.005)
    if low - band <= price <= high + band:
        return "testing"
    distance = min(abs(price - low), abs(price - high))
    if distance <= (atr or price * 0.02) * 1.5:
        return "approaching"
    if zone_type == "support" and price < low:
        return "broken"
    if zone_type == "resistance" and price > high:
        return "broken"
    return "active"
