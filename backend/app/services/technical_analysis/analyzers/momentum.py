"""RSI / MACD momentum normalization."""
from __future__ import annotations

from app.services.technical_analysis.schemas import TechnicalSignal


class MomentumAnalyzer:
    name = "momentum"
    version = "v0.4"
    supported_timeframes = {"1d", "1w"}

    def analyze(self, symbol: str, timeframe: str, analysis: dict, context: dict) -> list[TechnicalSignal]:
        indicators = analysis.get("indicators") or {}
        signals: list[TechnicalSignal] = []
        rsi = indicators.get("rsi14")
        if rsi is not None:
            if rsi >= 70:
                direction, state = "bearish", "overbought"
            elif rsi <= 30:
                direction, state = "bullish", "oversold"
            else:
                direction, state = "neutral", "neutral"
            signals.append(
                TechnicalSignal(
                    signal_type="momentum",
                    direction=direction,
                    timeframe="1d",
                    strength=min(1.0, abs(rsi - 50) / 50),
                    confidence=0.5,
                    value=rsi,
                    source="rsi14",
                    metadata={"state": state},
                )
            )
        macd_hist = indicators.get("macdHistogram")
        if macd_hist is not None:
            signals.append(
                TechnicalSignal(
                    signal_type="momentum",
                    direction="bullish" if macd_hist >= 0 else "bearish",
                    timeframe="1d",
                    strength=min(1.0, abs(macd_hist) / max(abs(analysis.get("latestClose") or 1) * 0.02, 1e-9)),
                    confidence=0.45,
                    value=macd_hist,
                    source="macd",
                    metadata={"histogram": macd_hist},
                )
            )
        return signals
