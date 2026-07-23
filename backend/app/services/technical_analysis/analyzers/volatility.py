"""ATR / Bollinger volatility normalization."""
from __future__ import annotations

from app.services.technical_analysis.schemas import TechnicalSignal


class VolatilityAnalyzer:
    name = "volatility"
    version = "v0.4"
    supported_timeframes = {"1d", "1w"}

    def analyze(self, symbol: str, timeframe: str, analysis: dict, context: dict) -> list[TechnicalSignal]:
        indicators = analysis.get("indicators") or {}
        close = analysis.get("latestClose")
        signals: list[TechnicalSignal] = []
        atr = indicators.get("atr14")
        if atr is not None and close:
            atr_pct = atr / close
            if atr_pct >= 0.04:
                state = "expanding"
            elif atr_pct <= 0.015:
                state = "contracting"
            else:
                state = "normal"
            signals.append(
                TechnicalSignal(
                    signal_type="volatility",
                    direction="neutral",
                    timeframe="1d",
                    strength=min(1.0, atr_pct / 0.06),
                    confidence=0.55,
                    value=atr,
                    source="atr14",
                    metadata={"state": state, "atr_percent": atr_pct},
                )
            )
        bb_low, bb_high = indicators.get("bollingerLow"), indicators.get("bollingerHigh")
        if bb_low is not None and bb_high is not None and close:
            if close >= bb_high:
                direction, band = "bearish", "upper"
            elif close <= bb_low:
                direction, band = "bullish", "lower"
            else:
                direction, band = "neutral", "inside"
            signals.append(
                TechnicalSignal(
                    signal_type="volatility",
                    direction=direction,
                    timeframe="1d",
                    strength=0.5,
                    confidence=0.5,
                    price_zone_low=bb_low,
                    price_zone_high=bb_high,
                    source="bollinger",
                    metadata={"band": band},
                )
            )
        return signals
