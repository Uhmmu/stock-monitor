"""Historical barrier estimator.

Looks at how often, historically, price moved a comparable distance within N
trading days. Requires a sufficient sample of daily closes in the context;
otherwise returns a structured unavailable result.
"""
from __future__ import annotations

from app.services.technical_analysis.schemas import ArrivalEstimate

MIN_SAMPLE = 60


class HistoricalBarrierEstimator:
    name = "historical_barrier"
    version = "v0.4"

    def estimate(self, current_price, target_zone, context) -> ArrivalEstimate:
        zone_id = context.get("zone_id", target_zone.zone_type)
        closes: list[float] = context.get("daily_closes") or []
        if not current_price or len(closes) < MIN_SAMPLE:
            return ArrivalEstimate(
                estimator=self.name,
                target_zone_id=zone_id,
                unavailable_reason="历史价格样本不足，无法用历史相似情形估算到达时间。",
            )
        target = target_zone.center_price
        upward = target >= current_price
        # required relative move to reach the zone edge nearest current price
        edge = target_zone.lower_price if upward else target_zone.upper_price
        required = (edge - current_price) / current_price if current_price else 0.0
        hits = {5: 0, 10: 0, 20: 0}
        totals = {5: 0, 10: 0, 20: 0}
        touch_days: list[int] = []
        for horizon in (5, 10, 20):
            for i in range(len(closes) - horizon):
                base = closes[i]
                if base <= 0:
                    continue
                window = closes[i + 1 : i + 1 + horizon]
                totals[horizon] += 1
                touched_at = None
                for step, price in enumerate(window, 1):
                    move = (price - base) / base
                    if (upward and move >= required) or (not upward and move <= required):
                        touched_at = step
                        break
                if touched_at is not None:
                    hits[horizon] += 1
                    if horizon == 20:
                        touch_days.append(touched_at)
        def prob(h: int) -> float | None:
            return round(hits[h] / totals[h], 3) if totals[h] else None
        median_days = None
        lower_days = None
        upper_days = None
        if touch_days:
            touch_days.sort()
            median_days = touch_days[len(touch_days) // 2]
            lower_days = touch_days[max(0, len(touch_days) // 10)]
            upper_days = touch_days[min(len(touch_days) - 1, len(touch_days) * 9 // 10)]
        return ArrivalEstimate(
            estimator=self.name,
            target_zone_id=zone_id,
            probability_5d=prob(5),
            probability_10d=prob(10),
            probability_20d=prob(20),
            median_days=median_days,
            lower_days=lower_days,
            upper_days=upper_days,
            confidence=min(0.7, len(closes) / 500),
            assumptions=[
                f"基于最近 {len(closes)} 个交易日的历史相似位移情形",
                "历史频率不代表未来概率",
            ],
        )
