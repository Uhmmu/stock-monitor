"""Swing-point support/resistance normalization.

Reads the persisted weekly analysis' supportZones / resistanceZones (computed by
the existing engine) and re-expresses each as a standardized support/resistance
TechnicalSignal. Downstream, `zones.merge_zones` merges nearby signals into
`PriceLevelZone`s.
"""
from __future__ import annotations

from app.services.technical_analysis.schemas import TechnicalSignal


class SwingPointAnalyzer:
    name = "swing_point"
    version = "v0.4"
    supported_timeframes = {"1d", "1w"}

    def analyze(self, symbol: str, timeframe: str, analysis: dict, context: dict) -> list[TechnicalSignal]:
        signals: list[TechnicalSignal] = []
        for kind, zones in (("support", analysis.get("supportZones") or []), ("resistance", analysis.get("resistanceZones") or [])):
            for zone in zones:
                low, high, center = zone.get("low"), zone.get("high"), zone.get("center")
                if low is None or high is None:
                    continue
                signals.append(
                    TechnicalSignal(
                        signal_type=f"{kind}_zone",
                        direction="bullish" if kind == "support" else "bearish",
                        timeframe="1w",
                        strength=float(zone.get("strength") or 0.0),
                        confidence=float(zone.get("strength") or 0.0),
                        value=center,
                        price_zone_low=low,
                        price_zone_high=high,
                        source="swing_low_cluster" if kind == "support" else "swing_high_cluster",
                        metadata={
                            "touch_count": zone.get("touchCount"),
                            "most_recent_touch": zone.get("mostRecentTouchDate"),
                            "signals": zone.get("signals", []),
                            "volume_confirmation": "above_average_pivot_volume" in (zone.get("signals") or []),
                        },
                    )
                )
        return signals
