"""ATR-based arrival estimator.

Uses ATR as a proxy for daily travel distance to estimate how many trading days
price might need to cover the gap to a zone, plus a rough probability that a
random-walk-with-drift touches the barrier within N days. Always probabilistic.
"""
from __future__ import annotations

import math

from app.services.technical_analysis.schemas import ArrivalEstimate


def _touch_probability(distance_atr: float, days: int) -> float:
    """Rough probability that a zero-drift random walk of `days` steps (each ~1 ATR
    std) reaches a barrier `distance_atr` ATRs away. Reflection-principle style
    approximation, clamped to [0, 0.98]."""
    if distance_atr <= 0:
        return 0.95
    sigma = math.sqrt(days)
    z = distance_atr / max(sigma, 1e-9)
    # 2*(1 - Phi(z)) approximates first-passage probability for a single barrier.
    prob = 2 * (1 - _phi(z))
    return max(0.0, min(0.98, prob))


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


class AtrRangeEstimator:
    name = "atr_range"
    version = "v0.4"

    def estimate(self, current_price, target_zone, context) -> ArrivalEstimate:
        zone_id = context.get("zone_id", target_zone.zone_type)
        atr = context.get("atr")
        if not atr or not current_price:
            return ArrivalEstimate(
                estimator=self.name,
                target_zone_id=zone_id,
                unavailable_reason="缺少 ATR 或当前价格，无法估算到达时间。",
            )
        distance = abs(target_zone.center_price - current_price)
        distance_atr = distance / atr
        median_days = max(1, round(distance_atr ** 2))  # expected steps to cover distance
        return ArrivalEstimate(
            estimator=self.name,
            target_zone_id=zone_id,
            probability_5d=_touch_probability(distance_atr, 5),
            probability_10d=_touch_probability(distance_atr, 10),
            probability_20d=_touch_probability(distance_atr, 20),
            median_days=median_days,
            lower_days=max(1, round(median_days * 0.5)),
            upper_days=round(median_days * 2.0),
            confidence=0.4,
            assumptions=[
                "以 ATR14 作为每日波动尺度",
                "假设近似无漂移随机游走，仅供参考",
            ],
        )
