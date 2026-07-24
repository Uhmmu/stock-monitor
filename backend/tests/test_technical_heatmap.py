from datetime import date, timedelta

import numpy as np

from app.services.technical_heatmap import (
    ConfirmedPivot,
    WEEKLY_HEATMAP_CONFIG,
    _confirmed_pivot_at,
    aggregate_heat_for_render,
    build_historical_causal_heatmap,
    build_render_bars,
    draw_historical_heat_bars,
    quantize_intensity,
)


def weekly_candles(count: int = 156) -> list[dict]:
    rows = []
    current = 42.0
    start = date(2023, 1, 6)
    for index in range(count):
        drift = 0.72 + ((index % 17) - 8) * 0.18
        opening = current
        close = max(8.0, opening + drift)
        rows.append(
            {
                "week": start + timedelta(weeks=index),
                "data_through": start + timedelta(weeks=index, days=4),
                "open": opening,
                "high": max(opening, close) + 3.0 + index % 4,
                "low": min(opening, close) - 2.5 - index % 3,
                "close": close,
                "volume": 1_000_000 + index * 25_000,
                "vwap": (opening + close) / 2,
            }
        )
        current = close
    return rows


def test_future_changes_do_not_change_earlier_columns():
    original = weekly_candles()
    baseline = build_historical_causal_heatmap(original)
    cutoff = 105
    changed = [dict(row) for row in original]
    for index in range(cutoff + 1, len(changed)):
        factor = 1 + ((index - cutoff) % 5 - 2) * 0.08
        changed[index]["open"] *= factor
        changed[index]["high"] *= factor * 1.03
        changed[index]["low"] *= factor * 0.97
        changed[index]["close"] *= factor
    rebuilt = build_historical_causal_heatmap(
        changed, price_grid=baseline.price_grid
    )
    np.testing.assert_array_equal(
        baseline.support_heat[:, : cutoff + 1],
        rebuilt.support_heat[:, : cutoff + 1],
    )
    np.testing.assert_array_equal(
        baseline.resistance_heat[:, : cutoff + 1],
        rebuilt.resistance_heat[:, : cutoff + 1],
    )


def test_confirmed_pivot_is_not_available_before_right_side_confirmation():
    rows = weekly_candles(12)
    rows[5]["high"] = max(row["high"] for row in rows) + 20
    assert _confirmed_pivot_at(rows, 7, WEEKLY_HEATMAP_CONFIG) is None
    pivot = _confirmed_pivot_at(rows, 8, WEEKLY_HEATMAP_CONFIG)
    assert isinstance(pivot, ConfirmedPivot)
    assert pivot.observed_at_index == 5
    assert pivot.available_from_index == 8


def test_render_aggregation_uses_max_and_quantizes_visibility():
    matrix = np.zeros((8, 8), dtype=np.float32)
    matrix[2, 3] = 0.81
    aggregated = aggregate_heat_for_render(matrix)
    assert aggregated.shape == (4, 4)
    assert aggregated[1, 1] == np.float32(0.81)
    quantized = quantize_intensity(aggregated)
    assert quantized[1, 1] == 4
    assert np.count_nonzero(quantized) == 1


def test_nearby_dense_cells_merge_into_thin_horizontal_box():
    matrix = np.zeros((40, 20), dtype=np.float32)
    matrix[12:15, 2:14] = 0.62
    matrix[16:18, 4:16] = 0.58
    bars = build_render_bars(matrix, 0.0, 40.0, "support")
    assert bars
    longest = max(bars, key=lambda bar: bar.end - bar.start)
    assert longest.role == "support"
    assert longest.end - longest.start >= 10
    assert longest.upper - longest.lower <= 4.1


def test_support_and_resistance_render_bars_never_cross_merge():
    matrix = np.zeros((20, 12), dtype=np.float32)
    matrix[8:11, 2:10] = 0.72
    support = build_render_bars(matrix, 0.0, 20.0, "support")
    resistance = build_render_bars(matrix, 0.0, 20.0, "resistance")
    assert support and resistance
    assert {bar.role for bar in support} == {"support"}
    assert {bar.role for bar in resistance} == {"resistance"}


def test_empty_history_returns_valid_empty_heatmap():
    result = build_historical_causal_heatmap([])
    assert result.support_heat.shape == (400, 0)
    assert result.resistance_heat.shape == (400, 0)
    assert result.current_zones == []
    assert result.current_levels == []


def test_metadata_exposes_current_price_levels_and_projection_contract():
    result = build_historical_causal_heatmap(weekly_candles())
    metadata = result.metadata(weekly_candles()[-1]["close"], 156)
    assert metadata["currentLevels"]
    assert {
        "source",
        "methodFamily",
        "price",
        "role",
        "confidence",
        "distancePercent",
    } <= metadata["currentLevels"][0].keys()
    assert metadata["projectionSpaceBars"] == 10
    assert metadata["projectionExtensionBars"] == 8


def test_active_final_heat_bars_extend_into_projection_space():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = build_historical_causal_heatmap(weekly_candles())
    fig, ax = plt.subplots()
    try:
        draw_historical_heat_bars(ax, result)
        final_edge = result.support_heat.shape[1] - 0.5
        projected = [
            patch
            for patch in ax.patches
            if patch.get_x() >= final_edge
        ]
        assert projected
        assert max(patch.get_width() for patch in projected) == 8
    finally:
        plt.close(fig)
