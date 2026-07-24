"""Causal weekly technical-confluence heatmap and compact bar rendering.

The calculation walks forward one weekly candle at a time.  Every historical
column uses only levels available at that candle.  Rendering is intentionally a
separate step: dense nearby cells are collapsed into thin price-level bars and
then merged across adjacent time blocks for a calmer long-term chart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from time import perf_counter
from typing import Literal

import numpy as np

HEATMAP_VERSION = "historical-technical-heatmap-v0.7"
PALETTE_VERSION = "apple-semantic-v1"
SUPPORT_COLOR = "#34c759"
RESISTANCE_COLOR = "#ff3b30"


@dataclass(frozen=True)
class WeeklyHeatmapConfig:
    minimum_warmup_bars: int = 52
    pivot_left_bars: int = 3
    pivot_right_bars: int = 3
    max_structural_age_bars: int = 52
    age_decay_start_bars: int = 13
    invalidation_atr_multiple: float = 0.5
    price_bin_count: int = 400
    minimum_family_count: int = 2
    tolerance_price_ratio: float = 0.008
    tolerance_atr_multiple: float = 0.15
    tolerance_min_ratio: float = 0.003
    tolerance_max_ratio: float = 0.025
    neutral_price_ratio: float = 0.0025
    neutral_atr_multiple: float = 0.05
    render_time_block_bars: int = 2
    render_price_block_bins: int = 2
    render_visible_threshold: float = 0.18
    render_price_gap_blocks: int = 2
    render_center_merge_blocks: int = 4
    render_intensity_merge_tolerance: int = 1
    render_min_time_blocks: int = 1
    projection_space_bars: int = 10
    projection_extension_bars: int = 8


WEEKLY_HEATMAP_CONFIG = WeeklyHeatmapConfig()


@dataclass(frozen=True)
class TechnicalLevel:
    source: str
    method_family: str
    price: float
    confidence: float = 1.0
    role: Literal["support", "resistance", "neutral", "auto"] = "auto"
    observed_at_index: int = 0
    available_from_index: int = 0


@dataclass
class ConfirmedPivot:
    kind: Literal["high", "low"]
    price: float
    observed_at_index: int
    available_from_index: int
    confidence: float
    invalidated: bool = False


@dataclass
class HeatZone:
    lower: float
    upper: float
    center: float
    role: Literal["support", "resistance"]
    raw_count: int
    source_count: int
    family_count: int
    weighted_score: float
    normalized_intensity: float
    sources: list[str] = field(default_factory=list)
    method_families: list[str] = field(default_factory=list)

    def to_dict(self, latest_close: float) -> dict:
        nearest = self.upper if self.role == "support" else self.lower
        return {
            "lower": float(self.lower),
            "upper": float(self.upper),
            "center": float(self.center),
            "role": self.role,
            "rawCount": int(self.raw_count),
            "sourceCount": int(self.source_count),
            "familyCount": int(self.family_count),
            "weightedScore": float(self.weighted_score),
            "normalizedIntensity": float(self.normalized_intensity),
            "distancePercent": float((nearest / latest_close - 1) * 100),
            "sources": list(self.sources),
            "methodFamilies": list(self.method_families),
        }


@dataclass
class RenderBar:
    role: Literal["support", "resistance"]
    start: float
    end: float
    lower: float
    upper: float
    intensity_step: int


@dataclass
class HistoricalHeatmapResult:
    price_grid: np.ndarray
    support_heat: np.ndarray
    resistance_heat: np.ndarray
    current_zones: list[HeatZone]
    current_levels: list[dict]
    calculation_ms: float
    methods_included: list[str]
    config: WeeklyHeatmapConfig

    def metadata(self, latest_close: float, time_count: int) -> dict:
        return {
            "version": HEATMAP_VERSION,
            "mode": "historical_causal",
            "timeframe": "weekly",
            "priceBinCount": int(len(self.price_grid)),
            "timeColumnCount": int(time_count),
            "priceMin": float(self.price_grid[0]),
            "priceMax": float(self.price_grid[-1]),
            "minimumFamilyCount": self.config.minimum_family_count,
            "renderTimeBlockBars": self.config.render_time_block_bars,
            "renderPriceBlockBins": self.config.render_price_block_bins,
            "projectionSpaceBars": self.config.projection_space_bars,
            "projectionExtensionBars": self.config.projection_extension_bars,
            "paletteVersion": PALETTE_VERSION,
            "methodsIncluded": list(self.methods_included),
            "methodsExcluded": [
                "RSI/MACD/ATR（非价格坐标）",
                "未确认的未来摆动点",
                "依赖未来突破确认的结构",
            ],
            "calculationMs": round(self.calculation_ms, 3),
            "currentLevels": list(self.current_levels),
            "currentZones": [
                zone.to_dict(latest_close)
                for zone in sorted(
                    self.current_zones,
                    key=lambda item: (
                        item.role != "support",
                        abs(item.center - latest_close),
                    ),
                )
            ],
        }


def _sma(values: list[float], period: int) -> list[float | None]:
    return [
        None if index + 1 < period else mean(values[index + 1 - period : index + 1])
        for index in range(len(values))
    ]


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    current = values[0]
    output = []
    for value in values:
        current = alpha * value + (1 - alpha) * current
        output.append(current)
    return output


def _atr(rows: list[dict], period: int = 14) -> list[float | None]:
    ranges = []
    for index, row in enumerate(rows):
        previous = rows[index - 1]["close"] if index else row["close"]
        ranges.append(
            max(
                row["high"] - row["low"],
                abs(row["high"] - previous),
                abs(row["low"] - previous),
            )
        )
    return _sma(ranges, period)


def _bollinger(values: list[float], period: int = 20) -> tuple[list, list, list]:
    middle = _sma(values, period)
    lower, upper = [], []
    for index, center in enumerate(middle):
        if center is None:
            lower.append(None)
            upper.append(None)
            continue
        window = values[index + 1 - period : index + 1]
        sigma = (sum((value - center) ** 2 for value in window) / period) ** 0.5
        lower.append(center - 2 * sigma)
        upper.append(center + 2 * sigma)
    return lower, middle, upper


def _prepare_series(weekly: list[dict]) -> dict:
    closes = [row["close"] for row in weekly]
    highs = [row["high"] for row in weekly]
    lows = [row["low"] for row in weekly]
    output = {
        "atr": _atr(weekly),
        "ma20": _sma(closes, 20),
        "ma50": _sma(closes, 50),
        "ma100": _sma(closes, 100),
        "ema20": _ema(closes, 20),
        "ema50": _ema(closes, 50),
        "ema100": _ema(closes, 100),
    }
    lower, middle, upper = _bollinger(closes)
    output.update(
        {
            "bollinger_low": lower,
            "bollinger_middle": middle,
            "bollinger_high": upper,
        }
    )
    for window in (13, 26, 52, 104):
        output[f"rolling_high_{window}"] = [
            None if index + 1 < window else max(highs[index + 1 - window : index + 1])
            for index in range(len(weekly))
        ]
        output[f"rolling_low_{window}"] = [
            None if index + 1 < window else min(lows[index + 1 - window : index + 1])
            for index in range(len(weekly))
        ]
    return output


def _confirmed_pivot_at(
    weekly: list[dict], index: int, config: WeeklyHeatmapConfig
) -> ConfirmedPivot | None:
    pivot_index = index - config.pivot_right_bars
    if pivot_index < config.pivot_left_bars:
        return None
    row = weekly[pivot_index]
    left = weekly[pivot_index - config.pivot_left_bars : pivot_index]
    right = weekly[pivot_index + 1 : index + 1]
    if row["high"] > max(item["high"] for item in left + right):
        prominence = row["high"] - min(item["low"] for item in left + right)
        return ConfirmedPivot(
            "high",
            float(row["high"]),
            pivot_index,
            index,
            min(1.0, prominence / max(row["high"] * 0.09, 0.01)),
        )
    if row["low"] < min(item["low"] for item in left + right):
        prominence = max(item["high"] for item in left + right) - row["low"]
        return ConfirmedPivot(
            "low",
            float(row["low"]),
            pivot_index,
            index,
            min(1.0, prominence / max(row["low"] * 0.09, 0.01)),
        )
    return None


def _active_pivots(
    pivots: list[ConfirmedPivot],
    index: int,
    close: float,
    atr_value: float,
    config: WeeklyHeatmapConfig,
) -> list[ConfirmedPivot]:
    output = []
    for pivot in pivots:
        age = index - pivot.available_from_index
        if pivot.invalidated or age > config.max_structural_age_bars:
            continue
        margin = atr_value * config.invalidation_atr_multiple
        if pivot.kind == "low" and close < pivot.price - margin:
            pivot.invalidated = True
            continue
        if pivot.kind == "high" and close > pivot.price + margin:
            pivot.invalidated = True
            continue
        output.append(pivot)
    return output


def _pivot_confidence(
    pivot: ConfirmedPivot, index: int, config: WeeklyHeatmapConfig
) -> float:
    age = index - pivot.available_from_index
    if age <= config.age_decay_start_bars:
        return pivot.confidence
    span = config.max_structural_age_bars - config.age_decay_start_bars
    return pivot.confidence * max(
        0.25, 1 - (age - config.age_decay_start_bars) / max(span, 1)
    )


def _levels_at(
    weekly: list[dict],
    series: dict,
    index: int,
    pivots: list[ConfirmedPivot],
    config: WeeklyHeatmapConfig,
) -> list[TechnicalLevel]:
    close = weekly[index]["close"]
    atr_value = series["atr"][index] or close * 0.035
    levels: list[TechnicalLevel] = []
    for source in ("ma20", "ma50", "ma100", "ema20", "ema50", "ema100"):
        value = series[source][index]
        if value is not None:
            levels.append(
                TechnicalLevel(source, "moving_average", float(value), observed_at_index=index, available_from_index=index)
            )
    for source in ("bollinger_low", "bollinger_middle", "bollinger_high"):
        value = series[source][index]
        if value is not None:
            levels.append(
                TechnicalLevel(source, "volatility_band", float(value), observed_at_index=index, available_from_index=index)
            )
    for window in (13, 26, 52, 104):
        for side in ("high", "low"):
            value = series[f"rolling_{side}_{window}"][index]
            if value is not None:
                levels.append(
                    TechnicalLevel(
                        f"rolling_{side}_{window}",
                        "rolling_extreme",
                        float(value),
                        0.8 if window < 52 else 1.0,
                        observed_at_index=index,
                        available_from_index=index,
                    )
                )
    if index:
        previous = weekly[index - 1]
        pivot_point = (previous["high"] + previous["low"] + previous["close"]) / 3
        for source, value in {
            "pivot_p": pivot_point,
            "pivot_r1": 2 * pivot_point - previous["low"],
            "pivot_s1": 2 * pivot_point - previous["high"],
            "pivot_r2": pivot_point + previous["high"] - previous["low"],
            "pivot_s2": pivot_point - previous["high"] + previous["low"],
        }.items():
            levels.append(
                TechnicalLevel(
                    source,
                    "previous_period_pivot",
                    float(value),
                    0.75,
                    observed_at_index=index - 1,
                    available_from_index=index,
                )
            )
    for pivot in pivots:
        levels.append(
            TechnicalLevel(
                f"confirmed_swing_{pivot.kind}_{pivot.observed_at_index}",
                "swing_structure",
                pivot.price,
                _pivot_confidence(pivot, index, config),
                "support" if pivot.kind == "low" else "resistance",
                pivot.observed_at_index,
                pivot.available_from_index,
            )
        )
    alternating = next(
        (
            (first, second)
            for first, second in reversed(list(zip(pivots, pivots[1:])))
            if first.kind != second.kind
            and abs(second.price - first.price) >= atr_value * 2
        ),
        None,
    )
    if alternating:
        start, end = alternating
        confidence = min(
            _pivot_confidence(start, index, config),
            _pivot_confidence(end, index, config),
        )
        for ratio in (0.236, 0.382, 0.5, 0.618, 0.786):
            levels.append(
                TechnicalLevel(
                    f"causal_fibonacci_{ratio:g}_{start.observed_at_index}_{end.observed_at_index}",
                    "fibonacci",
                    float(end.price - (end.price - start.price) * ratio),
                    confidence,
                    observed_at_index=end.observed_at_index,
                    available_from_index=end.available_from_index,
                )
            )
    for kind, role in (("low", "support"), ("high", "resistance")):
        anchors = [pivot for pivot in pivots if pivot.kind == kind][-4:]
        if len(anchors) < 2:
            continue
        first, second = anchors[-2:]
        span = second.observed_at_index - first.observed_at_index
        if span < 6:
            continue
        slope = (second.price - first.price) / span
        if (kind == "low" and slope <= 0) or (kind == "high" and slope >= 0):
            continue
        levels.append(
            TechnicalLevel(
                f"causal_{kind}_trendline_{first.observed_at_index}_{second.observed_at_index}",
                "trendline",
                float(second.price + slope * (index - second.observed_at_index)),
                min(
                    _pivot_confidence(first, index, config),
                    _pivot_confidence(second, index, config),
                ),
                role,
                second.observed_at_index,
                second.available_from_index,
            )
        )
    return levels


def _classify_role(
    level: TechnicalLevel,
    close: float,
    atr_value: float,
    config: WeeklyHeatmapConfig,
) -> Literal["support", "resistance", "neutral"]:
    neutral = max(
        close * config.neutral_price_ratio,
        atr_value * config.neutral_atr_multiple,
    )
    if abs(level.price - close) <= neutral:
        return "neutral"
    positional = "support" if level.price < close else "resistance"
    if level.role in ("support", "resistance") and level.role == positional:
        return level.role
    return positional


def _cluster_levels(
    levels: list[TechnicalLevel],
    close: float,
    atr_value: float,
    config: WeeklyHeatmapConfig,
) -> tuple[list[HeatZone], float]:
    tolerance = min(
        close * config.tolerance_max_ratio,
        max(
            close * config.tolerance_min_ratio,
            max(
                close * config.tolerance_price_ratio,
                atr_value * config.tolerance_atr_multiple,
            ),
        ),
    )
    zones: list[HeatZone] = []
    for role in ("support", "resistance"):
        candidates = [
            level
            for level in levels
            if _classify_role(level, close, atr_value, config) == role
        ]
        clusters: list[list[TechnicalLevel]] = []
        for level in sorted(candidates, key=lambda item: item.price):
            if not clusters:
                clusters.append([level])
                continue
            current = clusters[-1]
            weight = max(sum(item.confidence for item in current), 0.001)
            center = sum(item.price * item.confidence for item in current) / weight
            if abs(level.price - center) <= tolerance:
                current.append(level)
            else:
                clusters.append([level])
        for members in clusters:
            families = sorted({member.method_family for member in members})
            sources = sorted({member.source for member in members})
            if len(families) < config.minimum_family_count:
                continue
            family_best: dict[str, float] = {}
            for member in members:
                family_best[member.method_family] = max(
                    family_best.get(member.method_family, 0.0),
                    member.confidence,
                )
            score = sum(min(value, 1.0) for value in family_best.values())
            score += min(max(0, len(sources) - len(families)), 4) * 0.18
            if len(families) == 2 and score < 1.65:
                continue
            total_confidence = max(sum(member.confidence for member in members), 0.001)
            center = sum(
                member.price * member.confidence for member in members
            ) / total_confidence
            span = max(member.price for member in members) - min(
                member.price for member in members
            )
            width = min(
                tolerance * 2.8,
                max(tolerance * 0.85, span + tolerance * 0.55),
            )
            compactness = min(
                1.25, max(0.55, tolerance / max(width, tolerance * 0.5))
            )
            intensity = min(
                1.0, max(0.18, (score - 1.15) / 3.5 * compactness)
            )
            zones.append(
                HeatZone(
                    center - width / 2,
                    center + width / 2,
                    center,
                    role,
                    len(members),
                    len(sources),
                    len(families),
                    score,
                    intensity,
                    sources,
                    families,
                )
            )
    return zones, tolerance


def build_historical_causal_heatmap(
    weekly: list[dict],
    config: WeeklyHeatmapConfig = WEEKLY_HEATMAP_CONFIG,
    *,
    price_grid: np.ndarray | None = None,
) -> HistoricalHeatmapResult:
    started = perf_counter()
    if not weekly:
        grid = np.linspace(0.0, 1.0, config.price_bin_count)
        empty = np.zeros((config.price_bin_count, 0), dtype=np.float32)
        return HistoricalHeatmapResult(
            grid, empty, empty.copy(), [], [], 0.0, [], config
        )
    series = _prepare_series(weekly)
    if price_grid is None:
        atr_values = [value for value in series["atr"] if value is not None]
        padding = max(
            max(atr_values[-26:] or [1.0]) * 1.5,
            weekly[-1]["close"] * 0.02,
        )
        price_grid = np.linspace(
            max(0.0, min(row["low"] for row in weekly) - padding),
            max(row["high"] for row in weekly) + padding,
            config.price_bin_count,
        )
    else:
        price_grid = np.asarray(price_grid, dtype=float).copy()
    support = np.zeros((len(price_grid), len(weekly)), dtype=np.float32)
    resistance = np.zeros_like(support)
    pivots: list[ConfirmedPivot] = []
    latest_zones: list[HeatZone] = []
    latest_levels: list[dict] = []
    for index, row in enumerate(weekly):
        pivot = _confirmed_pivot_at(weekly, index, config)
        if pivot:
            pivots.append(pivot)
        atr_value = series["atr"][index] or row["close"] * 0.035
        active = _active_pivots(
            pivots, index, row["close"], atr_value, config
        )
        if index < config.minimum_warmup_bars:
            continue
        levels = _levels_at(weekly, series, index, active, config)
        if index == len(weekly) - 1:
            latest_levels = [
                {
                    "source": level.source,
                    "methodFamily": level.method_family,
                    "price": float(level.price),
                    "role": _classify_role(
                        level, row["close"], atr_value, config
                    ),
                    "confidence": float(level.confidence),
                    "distancePercent": float(
                        (level.price / row["close"] - 1) * 100
                    ),
                }
                for level in sorted(
                    levels,
                    key=lambda item: (
                        abs(item.price - row["close"]),
                        item.method_family,
                        item.source,
                    ),
                )
            ]
        zones, _ = _cluster_levels(
            levels, row["close"], atr_value, config
        )
        latest_zones = zones
        for zone in zones:
            mask = (price_grid >= zone.lower) & (price_grid <= zone.upper)
            target = support if zone.role == "support" else resistance
            target[mask, index] = np.maximum(
                target[mask, index], zone.normalized_intensity
            )
    methods = [
        "weekly_ma",
        "weekly_ema",
        "bollinger",
        "rolling_extremes",
        "previous_week_pivots",
        "confirmed_swings",
        "causal_fibonacci",
        "causal_trendlines",
    ]
    return HistoricalHeatmapResult(
        price_grid,
        support,
        resistance,
        latest_zones,
        latest_levels,
        (perf_counter() - started) * 1000,
        methods,
        config,
    )


def aggregate_heat_for_render(
    matrix: np.ndarray, config: WeeklyHeatmapConfig = WEEKLY_HEATMAP_CONFIG
) -> np.ndarray:
    price_blocks = (
        matrix.shape[0] + config.render_price_block_bins - 1
    ) // config.render_price_block_bins
    time_blocks = (
        matrix.shape[1] + config.render_time_block_bars - 1
    ) // config.render_time_block_bars
    output = np.zeros((price_blocks, time_blocks), dtype=np.float32)
    for price_index in range(price_blocks):
        for time_index in range(time_blocks):
            block = matrix[
                price_index
                * config.render_price_block_bins : (price_index + 1)
                * config.render_price_block_bins,
                time_index
                * config.render_time_block_bars : (time_index + 1)
                * config.render_time_block_bars,
            ]
            if block.size:
                output[price_index, time_index] = float(np.max(block))
    return output


def quantize_intensity(
    matrix: np.ndarray, threshold: float = WEEKLY_HEATMAP_CONFIG.render_visible_threshold
) -> np.ndarray:
    output = np.zeros_like(matrix, dtype=np.uint8)
    output[(matrix >= threshold) & (matrix < 0.38)] = 1
    output[(matrix >= 0.38) & (matrix < 0.58)] = 2
    output[(matrix >= 0.58) & (matrix < 0.78)] = 3
    output[matrix >= 0.78] = 4
    return output


def _runs_with_small_gaps(
    values: np.ndarray, maximum_gap: int
) -> list[tuple[int, int, int]]:
    active = np.flatnonzero(values)
    if not len(active):
        return []
    runs = []
    start = previous = int(active[0])
    intensity = int(values[previous])
    for raw_index in active[1:]:
        index = int(raw_index)
        if index - previous - 1 <= maximum_gap:
            previous = index
            intensity = max(intensity, int(values[index]))
            continue
        runs.append((start, previous, intensity))
        start = previous = index
        intensity = int(values[index])
    runs.append((start, previous, intensity))
    return runs


def build_render_bars(
    matrix: np.ndarray,
    price_min: float,
    price_max: float,
    role: Literal["support", "resistance"],
    config: WeeklyHeatmapConfig = WEEKLY_HEATMAP_CONFIG,
) -> list[RenderBar]:
    """Collapse dense cells into thin horizontal bars and merge them over time."""
    blocks = quantize_intensity(aggregate_heat_for_render(matrix, config))
    if not blocks.size:
        return []
    price_step = (price_max - price_min) / max(blocks.shape[0], 1)
    candidates: list[RenderBar] = []
    active: list[RenderBar] = []
    for time_index in range(blocks.shape[1]):
        runs = _runs_with_small_gaps(
            blocks[:, time_index], config.render_price_gap_blocks
        )
        current: list[RenderBar] = []
        for start_bin, end_bin, intensity in runs:
            weighted = blocks[start_bin : end_bin + 1, time_index].astype(float)
            indices = np.arange(start_bin, end_bin + 1, dtype=float)
            center_bin = (
                float(np.average(indices, weights=np.maximum(weighted, 1)))
                if weighted.size
                else (start_bin + end_bin) / 2
            )
            center = price_min + (center_bin + 0.5) * price_step
            # A level should read as a price line.  Crowded adjacent levels expand
            # only slightly into a box instead of retaining every tiny cell.
            source_span = end_bin - start_bin + 1
            thickness_blocks = min(
                4.0, max(1.15, 1.0 + (source_span - 1) * 0.35)
            )
            half_height = price_step * thickness_blocks / 2
            bar = RenderBar(
                role,
                time_index * config.render_time_block_bars - 0.5,
                min(
                    matrix.shape[1] - 0.5,
                    (time_index + 1) * config.render_time_block_bars - 0.5,
                ),
                center - half_height,
                center + half_height,
                intensity,
            )
            match = next(
                (
                    previous
                    for previous in active
                    if abs(
                        (previous.lower + previous.upper) / 2 - center
                    )
                    <= price_step * config.render_center_merge_blocks
                    and abs(previous.intensity_step - intensity)
                    <= config.render_intensity_merge_tolerance
                ),
                None,
            )
            if match:
                total_width = max(match.end - match.start, 0.001)
                center_previous = (match.lower + match.upper) / 2
                merged_center = (
                    center_previous * total_width
                    + center * config.render_time_block_bars
                ) / (total_width + config.render_time_block_bars)
                height = min(
                    price_step * 4,
                    max(match.upper - match.lower, bar.upper - bar.lower),
                )
                match.end = bar.end
                match.lower = merged_center - height / 2
                match.upper = merged_center + height / 2
                match.intensity_step = max(match.intensity_step, intensity)
                current.append(match)
            else:
                candidates.append(bar)
                current.append(bar)
        active = current
    return [
        bar
        for bar in candidates
        if bar.end - bar.start
        >= config.render_min_time_blocks * config.render_time_block_bars
    ]


def draw_historical_heat_bars(ax, result: HistoricalHeatmapResult) -> list[RenderBar]:
    from matplotlib.patches import Rectangle

    all_bars: list[RenderBar] = []
    alpha_steps = {1: 0.11, 2: 0.19, 3: 0.29, 4: 0.39}
    for role, matrix, color in (
        ("support", result.support_heat, SUPPORT_COLOR),
        ("resistance", result.resistance_heat, RESISTANCE_COLOR),
    ):
        bars = build_render_bars(
            matrix,
            float(result.price_grid[0]),
            float(result.price_grid[-1]),
            role,
            result.config,
        )
        all_bars.extend(bars)
        for bar in bars:
            alpha = alpha_steps[bar.intensity_step]
            final_edge = matrix.shape[1] - 0.5
            historical_end = min(bar.end, final_edge)
            ax.add_patch(
                Rectangle(
                    (bar.start, bar.lower),
                    historical_end - bar.start,
                    bar.upper - bar.lower,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.35,
                    alpha=alpha,
                    zorder=0.8,
                )
            )
            if (
                matrix.shape[1]
                and bar.end >= final_edge
                and result.config.projection_extension_bars > 0
            ):
                ax.add_patch(
                    Rectangle(
                        (final_edge, bar.lower),
                        result.config.projection_extension_bars,
                        bar.upper - bar.lower,
                        facecolor=color,
                        edgecolor=color,
                        linewidth=0.55,
                        linestyle=(0, (2.5, 2.5)),
                        alpha=alpha * 0.68,
                        zorder=0.75,
                    )
                )
    return all_bars
