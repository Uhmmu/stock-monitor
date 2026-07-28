from __future__ import annotations

import numpy as np


def summarize_simulations(initial: float, terminal: np.ndarray, drawdowns: np.ndarray, target: float | None) -> dict:
    percentiles = {f"p{level}": float(np.percentile(terminal, level)) for level in (5, 10, 25, 50, 75, 90, 95)}
    return {
        "terminal_value_percentiles": percentiles,
        "probability_of_loss": float(np.mean(terminal < initial)),
        "probability_loss_over_10_percent": float(np.mean(terminal < initial * .9)),
        "probability_loss_over_20_percent": float(np.mean(terminal < initial * .8)),
        "probability_reach_target": float(np.mean(terminal >= target)) if target is not None else None,
        "max_drawdown": {"median": float(np.median(drawdowns)), "p10": float(np.percentile(drawdowns, 10)), "p90": float(np.percentile(drawdowns, 90)), "probability_over_20_percent": float(np.mean(drawdowns < -.2)), "probability_over_30_percent": float(np.mean(drawdowns < -.3))},
    }
