"""Moving-average trend normalization (MA20 / MA60 / MA200 + weekly trend)."""
from __future__ import annotations

from app.services.technical_analysis.schemas import TechnicalSignal


class MovingAverageAnalyzer:
    name = "moving_average"
    version = "v0.4"
    supported_timeframes = {"1d", "1w"}

    def analyze(self, symbol: str, timeframe: str, analysis: dict, context: dict) -> list[TechnicalSignal]:
        indicators = analysis.get("indicators") or {}
        close = analysis.get("latestClose")
        signals: list[TechnicalSignal] = []
        for key, label, source in (("ma20", "MA20", "ma20"), ("ma60", "MA60", "ma60"), ("weeklyMa50", "MA200-proxy", "weekly_ma50")):
            value = indicators.get(key)
            if value is None or close is None:
                continue
            direction = "bullish" if close >= value else "bearish"
            signals.append(
                TechnicalSignal(
                    signal_type="moving_average",
                    direction=direction,
                    timeframe=timeframe,
                    strength=min(1.0, abs(close - value) / max(value, 1e-9)),
                    confidence=0.6,
                    value=value,
                    source=source,
                    metadata={"label": label, "price_above": close >= value},
                )
            )
        trend = analysis.get("weeklyTrend")
        if trend:
            signals.append(
                TechnicalSignal(
                    signal_type="trend",
                    direction="bullish" if trend == "bullish" else "bearish" if trend == "bearish" else "neutral",
                    timeframe="1w",
                    strength=0.7 if trend in ("bullish", "bearish") else 0.3,
                    confidence=0.6,
                    source="weekly_ma_stack",
                    metadata={"weekly_trend": trend},
                )
            )
        return signals
