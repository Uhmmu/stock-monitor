"""Trend-projection estimator (gated).

Only activates when the trend is sufficiently stable AND aligned with the target
direction, using a linear regression over recent closes. Otherwise returns a
structured unavailable result ("当前走势缺乏稳定方向…").
"""
from __future__ import annotations

from app.services.technical_analysis.schemas import ArrivalEstimate

MIN_SAMPLE = 30
MIN_FIT = 0.35  # minimum R^2 for the trend to count as "stable"


def _linreg(y: list[float]) -> tuple[float, float, float]:
    """Return (slope, intercept, r_squared) for y vs index."""
    n = len(y)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(y) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (v - my) for x, v in zip(xs, y))
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((v - my) ** 2 for v in y)
    ss_res = sum((v - (slope * x + intercept)) ** 2 for x, v in zip(xs, y))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return slope, intercept, r2


class TrendProjectionEstimator:
    name = "trend_projection"
    version = "v0.4"

    def estimate(self, current_price, target_zone, context) -> ArrivalEstimate:
        zone_id = context.get("zone_id", target_zone.zone_type)
        closes: list[float] = context.get("daily_closes") or []
        unavailable = ArrivalEstimate(
            estimator=self.name,
            target_zone_id=zone_id,
            unavailable_reason="当前走势缺乏稳定方向，暂不提供趋势到达时间。",
        )
        if not current_price or len(closes) < MIN_SAMPLE:
            return unavailable
        window = closes[-min(len(closes), 90):]
        slope, _, r2 = _linreg(window)
        if r2 < MIN_FIT or slope == 0:
            return unavailable
        target = target_zone.center_price
        needed = target - current_price
        # trend must be aligned with the direction toward the target
        if (needed > 0) != (slope > 0):
            return unavailable
        days = needed / slope
        if days <= 0:
            return unavailable
        median_days = max(1, round(days))
        return ArrivalEstimate(
            estimator=self.name,
            target_zone_id=zone_id,
            probability_5d=0.6 if median_days <= 5 else None,
            probability_10d=0.6 if median_days <= 10 else None,
            probability_20d=0.6 if median_days <= 20 else None,
            median_days=median_days,
            lower_days=max(1, round(median_days * 0.6)),
            upper_days=round(median_days * 1.6),
            confidence=min(0.6, r2),
            assumptions=[
                f"线性趋势拟合 R²={r2:.2f}",
                "假设当前趋势斜率延续，仅在趋势稳定时提供",
            ],
        )
