"""Target-arrival estimators.

Priority order (first that returns an available result wins):
    historical barrier estimator -> ATR-based estimator -> trend-projection estimator

The trend-projection estimator is gated: it only activates when the trend is
sufficiently stable and aligned with the target direction; otherwise it returns a
structured unavailable result. Every estimate is probabilistic (probability +
trading-day range), never a guaranteed date.
"""
from app.services.technical_analysis.estimators.atr_range import AtrRangeEstimator
from app.services.technical_analysis.estimators.historical_barrier import HistoricalBarrierEstimator
from app.services.technical_analysis.estimators.trend_projection import TrendProjectionEstimator

# Order matters: recommended priority.
DEFAULT_ESTIMATORS = [
    HistoricalBarrierEstimator(),
    AtrRangeEstimator(),
    TrendProjectionEstimator(),
]

__all__ = [
    "AtrRangeEstimator",
    "HistoricalBarrierEstimator",
    "TrendProjectionEstimator",
    "DEFAULT_ESTIMATORS",
    "estimate_arrival",
]


def estimate_arrival(current_price, target_zone, context):
    """Run estimators in priority order; return the first available estimate,
    else the last (unavailable) result so the caller always gets structured output."""
    last = None
    for estimator in DEFAULT_ESTIMATORS:
        try:
            result = estimator.estimate(current_price, target_zone, context)
        except Exception:
            continue
        last = result
        if result is not None and result.available:
            return result
    return last
