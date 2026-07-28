"""Deterministic, locally calculated weekly technical analysis and charting."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import HistoricalPrice, TechnicalAnalysis
from app.services.market_data import fetch_daily_history

ANALYSIS_VERSION = "weekly-v2-heatmap-v0.7"
# 历史数据源优先级：FMP 优先（付费主源），其数据无法覆盖的标的（如 HTTP 402）回退 yfinance 免费源。
HISTORY_SOURCES = ("fmp", "yahoo")
FALLBACK_SOURCE = "yahoo"
logger = logging.getLogger(__name__)


def _load_history(db: Session, symbol: str) -> tuple[list[HistoricalPrice], str | None]:
    """按 HISTORY_SOURCES 优先级返回该标的的历史行与命中的 source（都没有则 (空, None)）。"""
    value = symbol.upper()
    for source in HISTORY_SOURCES:
        rows = list(
            db.scalars(
                select(HistoricalPrice)
                .where(
                    HistoricalPrice.symbol == value,
                    HistoricalPrice.source == source,
                )
                .order_by(HistoricalPrice.date)
            ).all()
        )
        if rows:
            return rows, source
    return [], None


def _f(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def aggregate_weekly(daily: Iterable[Any]) -> list[dict]:
    groups: dict[date, list[dict]] = defaultdict(list)
    for item in daily:
        get = item.get if isinstance(item, dict) else lambda key: getattr(item, key)
        try:
            day, o, h, low, close = (
                get("date"),
                _f(get("open")),
                _f(get("high")),
                _f(get("low")),
                _f(get("close")),
            )
        except (AttributeError, KeyError):
            continue
        if not isinstance(day, date) or None in (o, h, low, close):
            continue
        groups[
            day.fromisocalendar(day.isocalendar().year, day.isocalendar().week, 1)
        ].append(
            {
                "date": day,
                "open": o,
                "high": h,
                "low": low,
                "close": close,
                "volume": max(0, int(get("volume") or 0)),
                "vwap": _f(get("vwap")),
            }
        )
    output = []
    for week in sorted(groups):
        rows = sorted(groups[week], key=lambda row: row["date"])
        volume = sum(row["volume"] for row in rows)
        weighted = sum(
            (
                row["vwap"]
                if row["vwap"] is not None
                else (row["high"] + row["low"] + row["close"]) / 3
            )
            * row["volume"]
            for row in rows
        )
        output.append(
            {
                "week": week,
                "data_through": rows[-1]["date"],
                "open": rows[0]["open"],
                "high": max(row["high"] for row in rows),
                "low": min(row["low"] for row in rows),
                "close": rows[-1]["close"],
                "volume": volume,
                "vwap": weighted / volume if volume else None,
            }
        )
    return output


def aggregate_monthly(daily: Iterable[Any]) -> list[dict]:
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for item in daily:
        get = item.get if isinstance(item, dict) else lambda key: getattr(item, key)
        try:
            day, o, h, low, close = (
                get("date"),
                _f(get("open")),
                _f(get("high")),
                _f(get("low")),
                _f(get("close")),
            )
        except (AttributeError, KeyError):
            continue
        if not isinstance(day, date) or None in (o, h, low, close):
            continue
        groups[(day.year, day.month)].append(
            {
                "date": day,
                "open": o,
                "high": h,
                "low": low,
                "close": close,
                "volume": max(0, int(get("volume") or 0)),
            }
        )
    output = []
    for year_month in sorted(groups):
        rows = sorted(groups[year_month], key=lambda row: row["date"])
        output.append(
            {
                "time": date(year_month[0], year_month[1], 1),
                "open": rows[0]["open"],
                "high": max(row["high"] for row in rows),
                "low": min(row["low"] for row in rows),
                "close": rows[-1]["close"],
                "volume": sum(row["volume"] for row in rows),
            }
        )
    return output


def _chart_series_payload(rows: list[dict], time_key: str) -> dict:
    closes = [row["close"] for row in rows]
    moving_averages: dict[str, list[dict]] = {}
    for period in (20, 50):
        moving_averages[f"ma{period}"] = [
            {"time": row[time_key].isoformat(), "value": float(value)}
            for row, value in zip(rows, sma(closes, period))
            if value is not None
        ]
    return {
        "candles": [
            {
                "time": row[time_key].isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            }
            for row in rows
        ],
        "moving_averages": moving_averages,
    }


def build_weekly_chart_data(rows: Iterable[Any], source: str | None = None) -> dict:
    """Build the interactive-chart payload from cached daily history only."""
    cached_rows = list(rows)
    weekly = aggregate_weekly(cached_rows)[-156:]
    if not weekly:
        return {
            "chart_data_status": "insufficient",
            "chart_data_reason": "historical_data_unavailable",
            "chart_data_source": source,
            "weekly": [],
            "moving_averages": {"ma20": [], "ma50": []},
            "chart_series": {
                "day": {"candles": [], "moving_averages": {"ma20": [], "ma50": []}},
                "week": {"candles": [], "moving_averages": {"ma20": [], "ma50": []}},
                "month": {"candles": [], "moving_averages": {"ma20": [], "ma50": []}},
            },
        }

    daily = []
    for item in cached_rows[-780:]:
        try:
            day = item["date"] if isinstance(item, dict) else item.date
            get = item.get if isinstance(item, dict) else lambda key: getattr(item, key)
            values = {
                "time": day,
                "open": _f(get("open")),
                "high": _f(get("high")),
                "low": _f(get("low")),
                "close": _f(get("close")),
                "volume": max(0, int(get("volume") or 0)),
            }
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if isinstance(day, date) and None not in (
            values["open"],
            values["high"],
            values["low"],
            values["close"],
        ):
            daily.append(values)
    monthly = aggregate_monthly(cached_rows)[-120:]
    weekly_payload = _chart_series_payload(weekly, "week")
    chart_series = {
        "day": _chart_series_payload(daily, "time"),
        "week": weekly_payload,
        "month": _chart_series_payload(monthly, "time"),
    }

    return {
        "chart_data_status": "ready",
        "chart_data_reason": None,
        "chart_data_source": source,
        "weekly": weekly_payload["candles"],
        "moving_averages": weekly_payload["moving_averages"],
        "chart_series": chart_series,
    }


def load_cached_weekly_chart_data(db: Session, symbol: str) -> dict:
    """Read chart data from HistoricalPrice without performing an upstream fetch."""
    rows, source = _load_history(db, symbol)
    return build_weekly_chart_data(rows, source)


def sma(values: list[float], period: int) -> list[float | None]:
    return [
        None if index + 1 < period else mean(values[index + 1 - period : index + 1])
        for index in range(len(values))
    ]


def ema(values: list[float], period: int) -> list[float | None]:
    if not values:
        return []
    alpha, result, current = 2 / (period + 1), [], values[0]
    for value in values:
        current = alpha * value + (1 - alpha) * current
        result.append(current)
    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    gains = [max(0, values[i] - values[i - 1]) for i in range(1, len(values))]
    losses = [max(0, values[i - 1] - values[i]) for i in range(1, len(values))]
    avg_gain, avg_loss = mean(gains[:period]), mean(losses[:period])
    result[period] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        result[i] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def atr(rows: list[dict], period: int = 14) -> list[float | None]:
    tr = []
    for i, row in enumerate(rows):
        previous = rows[i - 1]["close"] if i else row["close"]
        tr.append(
            max(
                row["high"] - row["low"],
                abs(row["high"] - previous),
                abs(row["low"] - previous),
            )
        )
    return sma(tr, period)


def macd(values: list[float]) -> tuple[list[float], list[float], list[float]]:
    fast, slow = ema(values, 12), ema(values, 26)
    line = [a - b for a, b in zip(fast, slow)]
    signal = [x or 0 for x in ema(line, 9)]
    return line, signal, [a - b for a, b in zip(line, signal)]


def bollinger(
    values: list[float], period: int = 20, deviations: float = 2
) -> tuple[list, list, list]:
    mid = sma(values, period)
    upper, lower = [], []
    for i, center in enumerate(mid):
        if center is None:
            upper.append(None)
            lower.append(None)
            continue
        window = values[i + 1 - period : i + 1]
        sigma = math.sqrt(sum((x - center) ** 2 for x in window) / period)
        upper.append(center + deviations * sigma)
        lower.append(center - deviations * sigma)
    return lower, mid, upper


def detect_swings(weekly: list[dict], window: int = 2) -> list[dict]:
    atrs = atr(weekly)
    swings = []
    for i in range(window, len(weekly) - window):
        row, neighbors = (
            weekly[i],
            weekly[i - window : i] + weekly[i + 1 : i + window + 1],
        )
        kind = (
            "high"
            if row["high"] > max(x["high"] for x in neighbors)
            else "low"
            if row["low"] < min(x["low"] for x in neighbors)
            else None
        )
        if not kind:
            continue
        price = row["high"] if kind == "high" else row["low"]
        opposite = (
            min(x["low"] for x in neighbors)
            if kind == "high"
            else max(x["high"] for x in neighbors)
        )
        prominence = abs(price - opposite)
        threshold = max((atrs[i] or 0) * 0.5, price * 0.015)
        if prominence < threshold:
            continue
        swings.append(
            {
                "type": kind,
                "date": row["data_through"].isoformat(),
                "price": price,
                "confirmed": True,
                "prominence": prominence,
                "strength": min(1, prominence / max(threshold * 3, 0.0001)),
                "volume": row["volume"],
                "index": i,
            }
        )
    return swings


def support_resistance(
    swings: list[dict], latest: float, latest_atr: float | None
) -> tuple[list[dict], list[dict]]:
    tolerance = max((latest_atr or 0) * 0.5, latest * 0.012)
    clusters: list[list[dict]] = []
    for swing in sorted(swings, key=lambda x: x["price"]):
        cluster = next(
            (
                c
                for c in clusters
                if abs(mean(x["price"] for x in c) - swing["price"]) <= tolerance
            ),
            None,
        )
        if cluster is None:
            clusters.append([swing])
        else:
            cluster.append(swing)
    zones = []
    latest_pivot_index = max((swing["index"] for swing in swings), default=0)
    average_pivot_volume = mean(swing["volume"] for swing in swings) if swings else 0
    for cluster in clusters:
        center = sum(x["price"] * (0.5 + x["strength"]) for x in cluster) / sum(
            0.5 + x["strength"] for x in cluster
        )
        kind = "support" if center < latest else "resistance"
        touches = len(cluster)
        periods_since_touch = latest_pivot_index - max(x["index"] for x in cluster)
        recency = max(0.2, 1 - periods_since_touch / 156)
        volume_confirmation = bool(
            average_pivot_volume
            and mean(x["volume"] for x in cluster) >= average_pivot_volume
        )
        zones.append(
            {
                "low": center - tolerance / 2,
                "high": center + tolerance / 2,
                "center": center,
                "type": kind,
                "touchCount": touches,
                "strength": min(
                    1,
                    0.12
                    + touches * 0.16
                    + mean(x["strength"] for x in cluster) * 0.32
                    + recency * 0.16
                    + (0.08 if volume_confirmation else 0),
                ),
                "mostRecentTouchDate": max(x["date"] for x in cluster),
                "distancePercent": (center / latest - 1) * 100,
                "signals": ["confirmed_weekly_pivot"]
                + (["repeated_touches"] if touches >= 2 else [])
                + (["recent_touch"] if periods_since_touch <= 26 else [])
                + (["above_average_pivot_volume"] if volume_confirmation else []),
            }
        )
    support = sorted(
        (z for z in zones if z["high"] < latest), key=lambda z: -z["center"]
    )[:3]
    resistance = sorted(
        (z for z in zones if z["low"] > latest), key=lambda z: z["center"]
    )[:3]
    return support, resistance


def fibonacci(swings: list[dict], latest_atr: float | None) -> dict:
    pairs = [(a, b) for a, b in zip(swings, swings[1:]) if a["type"] != b["type"]]
    minimum = (latest_atr or 0) * 2
    selected = next(
        ((a, b) for a, b in reversed(pairs) if abs(b["price"] - a["price"]) >= minimum),
        None,
    )
    if not selected:
        return {
            "available": False,
            "omissionReason": "No sufficiently confirmed weekly swing was found within the analysis window.",
        }
    start, end = selected
    direction = "up" if end["price"] > start["price"] else "down"
    ratios = (0, 0.236, 0.382, 0.5, 0.618, 0.786, 1)
    levels = {
        f"{ratio * 100:g}%": end["price"] - (end["price"] - start["price"]) * ratio
        for ratio in ratios
    }
    return {
        "available": True,
        "direction": direction,
        "startDate": start["date"],
        "startPrice": start["price"],
        "endDate": end["date"],
        "endPrice": end["price"],
        "selectionMethod": "most_recent_confirmed_alternating_pivots_at_least_2_atr",
        "confidence": min(start["strength"], end["strength"]),
        "levels": levels,
    }


def trend_lines(
    swings: list[dict], weekly: list[dict], latest_index: int, latest: float, latest_atr: float | None
) -> list[dict]:
    output = []
    for pivot_type, line_type in (
        ("low", "rising_support"),
        ("high", "falling_resistance"),
    ):
        points = [p for p in swings if p["type"] == pivot_type]
        candidates = []
        for i, a in enumerate(points):
            for b in points[i + 1 :]:
                slope = (b["price"] - a["price"]) / (b["index"] - a["index"])
                if (line_type == "rising_support" and slope <= 0) or (
                    line_type == "falling_resistance" and slope >= 0
                ):
                    continue
                tol = max((latest_atr or 0) * 0.6, latest * 0.012)
                touches = [
                    p
                    for p in points
                    if abs(
                        p["price"] - (a["price"] + slope * (p["index"] - a["index"]))
                    )
                    <= tol
                ]
                observed = range(a["index"], latest_index + 1)
                breaks = sum(
                    (
                        weekly[index]["low"]
                        < a["price"] + slope * (index - a["index"]) - tol
                    )
                    if line_type == "rising_support"
                    else (
                        weekly[index]["high"]
                        > a["price"] + slope * (index - a["index"]) + tol
                    )
                    for index in observed
                )
                if breaks > max(1, (latest_index - a["index"] + 1) // 12):
                    continue
                projection = a["price"] + slope * (latest_index - a["index"])
                score = min(1, len(touches) / 4) * max(
                    0, 1 - abs(projection - latest) / max(latest * 0.35, 1)
                )
                if len(touches) >= 2 and score >= 0.35:
                    candidates.append((score, a, b, touches, projection))
        if candidates:
            score, a, b, touches, projection = max(candidates, key=lambda x: x[0])
            relation = (
                "near"
                if abs(latest / projection - 1) <= 0.02
                else "above"
                if latest > projection
                else "below"
            )
            output.append(
                {
                    "type": line_type,
                    "anchors": [
                        {"date": a["date"], "price": a["price"], "index": a["index"]},
                        {"date": b["date"], "price": b["price"], "index": b["index"]},
                    ],
                    "confirmingTouches": len(touches),
                    "confidence": score,
                    "projectedPrice": projection,
                    "priceRelation": relation,
                }
            )
    return output


def build_analysis(symbol: str, daily: list[Any], source: str = "fmp") -> tuple[dict, list[dict]]:
    weekly_all = aggregate_weekly(daily)
    weekly = weekly_all[-156:]
    if not weekly:
        raise ValueError("No valid historical prices")
    closes = [x["close"] for x in weekly]
    daily_close = [
        _f(x.close if not isinstance(x, dict) else x["close"]) for x in daily
    ]
    daily_close = [x for x in daily_close if x is not None]
    weekly_atr = atr(weekly)
    swings = detect_swings(weekly)
    support, resistance = support_resistance(swings, closes[-1], weekly_atr[-1])
    fib = fibonacci(swings, weekly_atr[-1])
    lines = trend_lines(swings, weekly, len(weekly) - 1, closes[-1], weekly_atr[-1])
    confluences = []
    if fib.get("available"):
        for label, level in fib["levels"].items():
            for zone in support + resistance:
                if zone["low"] <= level <= zone["high"]:
                    confluences.append(
                        {
                            "fibonacciLevel": label,
                            "price": level,
                            "zoneType": zone["type"],
                            "zoneCenter": zone["center"],
                            "description": "fibonacci_zone_overlap",
                        }
                    )
    d_rsi = rsi(daily_close)
    macd_line, macd_signal, macd_hist = macd(daily_close)
    d_ma20, d_ma60, d_ema20 = (
        sma(daily_close, 20),
        sma(daily_close, 60),
        ema(daily_close, 20),
    )
    d_rows = [
        {"high": _f(x.high), "low": _f(x.low), "close": _f(x.close)}
        if not isinstance(x, dict)
        else x
        for x in daily
    ]
    d_atr = atr(d_rows)
    bb_low, _, bb_high = bollinger(daily_close)
    wma20, wma50 = sma(closes, 20), sma(closes, 50)
    weekly_trend = (
        "bullish"
        if wma20[-1] is not None
        and wma50[-1] is not None
        and closes[-1] > wma20[-1] > wma50[-1]
        else "bearish"
        if wma20[-1] is not None
        and wma50[-1] is not None
        and closes[-1] < wma20[-1] < wma50[-1]
        else "neutral"
    )
    omitted = []
    if wma50[-1] is None:
        omitted.append("Insufficient data for weekly MA50")
    if not fib["available"]:
        omitted.append(fib["omissionReason"])
    if not resistance:
        omitted.append("No valid resistance above current price")
    result = {
        "symbol": symbol,
        "generatedAt": datetime.now(UTC).isoformat(),
        "dataThrough": weekly[-1]["data_through"].isoformat(),
        "visibleStartDate": weekly[0]["week"].isoformat(),
        "visibleEndDate": weekly[-1]["data_through"].isoformat(),
        "latestClose": closes[-1],
        "weeklyTrend": weekly_trend,
        "nearestSupport": support[0] if support else None,
        "nearestResistance": resistance[0] if resistance else None,
        "supportZones": support,
        "resistanceZones": resistance,
        "fibonacci": fib,
        "trendLines": lines,
        "swings": swings,
        "indicators": {
            "rsi14": d_rsi[-1] if d_rsi else None,
            "macd": macd_line[-1] if macd_line else None,
            "macdSignal": macd_signal[-1] if macd_signal else None,
            "macdHistogram": macd_hist[-1] if macd_hist else None,
            "ma5": sma(daily_close, 5)[-1] if daily_close else None,
            "ma20": d_ma20[-1] if d_ma20 else None,
            "ma60": d_ma60[-1] if d_ma60 else None,
            "ema20": d_ema20[-1] if d_ema20 else None,
            "atr14": d_atr[-1] if d_atr else None,
            "weeklyMa20": wma20[-1],
            "weeklyMa50": wma50[-1],
            "bollingerLow": bb_low[-1] if bb_low else None,
            "bollingerHigh": bb_high[-1] if bb_high else None,
            "weeklyVwap": weekly[-1]["vwap"],
        },
        "confluences": confluences,
        "omittedReasons": omitted,
        "source": source,
        "analysisVersion": ANALYSIS_VERSION,
    }
    return result, weekly


def input_hash(rows: list[HistoricalPrice]) -> str:
    basis = "|".join(
        f"{r.date}:{r.open}:{r.high}:{r.low}:{r.close}:{r.volume}" for r in rows
    )
    return hashlib.sha256(f"{ANALYSIS_VERSION}|{basis}".encode()).hexdigest()


def render_chart(
    symbol: str,
    weekly: list[dict],
    analysis: dict,
    path: str,
    *,
    historical_heatmap: Any | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    from app.services.technical_heatmap import (
        RESISTANCE_COLOR,
        SUPPORT_COLOR,
        build_historical_causal_heatmap,
        draw_historical_heat_bars,
    )

    heatmap = historical_heatmap or build_historical_causal_heatmap(weekly)

    fig, (ax, volume_ax) = plt.subplots(
        2,
        1,
        figsize=(12, 7),
        dpi=120,
        sharex=True,
        gridspec_kw={"height_ratios": [4, 1]},
    )
    temp = f"{path}.tmp.webp"
    try:
        fig.patch.set_facecolor("#10131d")
        ax.set_facecolor("#10131d")
        volume_ax.set_facecolor("#10131d")
        draw_historical_heat_bars(ax, heatmap)
        for i, row in enumerate(weekly):
            color = "#53c7a2" if row["close"] >= row["open"] else "#ef7186"
            ax.vlines(
                i, row["low"], row["high"], color=color, linewidth=0.8, zorder=3
            )
            bottom, height = (
                min(row["open"], row["close"]),
                abs(row["close"] - row["open"]),
            )
            ax.add_patch(
                Rectangle(
                    (i - 0.3, bottom),
                    0.6,
                    max(height, row["close"] * 0.0005),
                    color=color,
                    alpha=0.9,
                    zorder=3,
                )
            )
            volume_ax.bar(i, row["volume"], color=color, width=0.65, alpha=0.5)
        closes = [x["close"] for x in weekly]
        for period, color in ((20, "#d9a7ff"), (50, "#75a7ff")):
            values = sma(closes, period)
            ax.plot(
                [x if x is not None else math.nan for x in values],
                color=color,
                linewidth=1.2,
                label=f"MA{period}",
                zorder=4,
            )
        if analysis["fibonacci"].get("available"):
            for label, value in analysis["fibonacci"]["levels"].items():
                ax.axhline(
                    value,
                    color="#d7b96f",
                    alpha=0.18,
                    linewidth=0.7,
                    zorder=2,
                )
        for line in analysis["trendLines"]:
            a, b = line["anchors"]
            slope = (b["price"] - a["price"]) / (b["index"] - a["index"])
            ax.plot(
                [a["index"], len(weekly) - 1],
                [a["price"], a["price"] + slope * (len(weekly) - 1 - a["index"])],
                color="#e8e9f2",
                alpha=0.55,
                zorder=4,
            )
        ax.axhline(
            analysis["latestClose"],
            color="#f3f4fa",
            alpha=0.42,
            linewidth=0.75,
            linestyle="--",
            zorder=4,
        )
        current_edge = len(weekly) - 0.5
        ax.axvline(
            current_edge,
            color="#8990a7",
            alpha=0.22,
            linewidth=0.7,
            linestyle=(0, (2, 4)),
            zorder=1,
        )
        ax.text(
            current_edge + 0.7,
            0.985,
            "CURRENT LEVELS",
            transform=ax.get_xaxis_transform(),
            color="#8990a7",
            alpha=0.72,
            fontsize=6.5,
            fontweight="semibold",
            ha="left",
            va="top",
        )
        ax.set_xlim(
            -0.5,
            current_edge + heatmap.config.projection_space_bars,
        )
        ax.set_title(
            f"{symbol} · Historical Causal Confluence · Weekly · through {analysis['dataThrough']}",
            color="#f3f4fa",
            loc="left",
        )
        handles, _ = ax.get_legend_handles_labels()
        handles.extend(
            [
                Patch(
                    facecolor=SUPPORT_COLOR,
                    alpha=0.28,
                    label="Support confluence",
                ),
                Patch(
                    facecolor=RESISTANCE_COLOR,
                    alpha=0.28,
                    label="Resistance confluence",
                ),
            ]
        )
        ax.legend(
            handles=handles,
            frameon=False,
            labelcolor="#ccd0df",
            ncol=4,
            fontsize=8,
            loc="lower right",
        )
        ax.grid(alpha=0.08)
        volume_ax.grid(alpha=0.06)
        for axis in (ax, volume_ax):
            axis.tick_params(colors="#8990a7")
        ticks = list(range(0, len(weekly), max(1, len(weekly) // 6)))
        volume_ax.set_xticks(
            ticks,
            [weekly[i]["week"].isoformat() for i in ticks],
            rotation=20,
            ha="right",
        )
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(
            temp, format="webp", bbox_inches="tight", facecolor=fig.get_facecolor()
        )
        if os.path.getsize(temp) < 1000:
            raise RuntimeError("generated chart is unexpectedly empty")
        os.replace(temp, path)
    finally:
        plt.close(fig)
        Path(temp).unlink(missing_ok=True)


def _upsert_history(db: Session, rows: list[dict]) -> tuple[int, int]:
    """按 (symbol, date, source) 幂等 upsert；返回 (处理行数, 变更行数)。与 fmp_market.upsert_history 同构。"""
    if not rows:
        return 0, 0
    changed = 0
    for values in rows:
        existing = db.scalar(
            select(HistoricalPrice).where(
                HistoricalPrice.symbol == values["symbol"],
                HistoricalPrice.date == values["date"],
                HistoricalPrice.source == values["source"],
            )
        )
        if existing is None:
            db.add(HistoricalPrice(**values))
            changed += 1
            continue
        if any(
            getattr(existing, key) != value
            for key, value in values.items()
            if key not in {"symbol", "date", "source"}
        ):
            for key, value in values.items():
                if key not in {"symbol", "date", "source"}:
                    setattr(existing, key, value)
            changed += 1
    db.flush()
    return len(rows), changed


def sync_fallback_history(db: Session, symbol: str, *, today: date | None = None) -> dict:
    """yfinance 回退：仅当 FMP 无法提供该标的历史时使用。拉取日线 EOD 并 upsert 到 source=yahoo。"""
    value = symbol.upper()
    rows = fetch_daily_history(value, today=today)
    total, changed = _upsert_history(db, rows)
    db.commit()
    logger.info(
        "[technical-analysis] yahoo fallback sync symbol=%s received=%d changed=%d",
        value,
        total,
        changed,
    )
    # generate_for_symbol 幂等：input_hash 未变且已有 ready 图表时自动跳过重算。
    analysis = generate_for_symbol(db, value)
    return {"received": total, "changed": changed, "analysis": analysis}


def generate_for_symbol(db: Session, symbol: str, *, force: bool = False) -> dict:
    rows, source = _load_history(db, symbol)
    if not rows:
        return {"status": "pending", "reason": "historical_data_unavailable"}
    digest = input_hash(rows)
    existing = db.get(TechnicalAnalysis, symbol.upper())
    if (
        existing
        and existing.input_hash == digest
        and existing.status == "ready"
        and existing.image_path
        and os.path.exists(existing.image_path)
        and not force
    ):
        return {"status": "unchanged", "symbol": symbol.upper()}
    settings = get_settings()
    path = str(
        Path(settings.technical_chart_dir) / f"{symbol.upper()}-{digest[:12]}.webp"
    )
    try:
        analysis, weekly = build_analysis(symbol.upper(), rows, source or "fmp")
        from app.services.technical_heatmap import build_historical_causal_heatmap

        historical_heatmap = build_historical_causal_heatmap(weekly)
        analysis["historicalCausalHeatmap"] = historical_heatmap.metadata(
            analysis["latestClose"], len(weekly)
        )
        render_chart(
            symbol.upper(),
            weekly,
            analysis,
            path,
            historical_heatmap=historical_heatmap,
        )
    except Exception as exc:
        row = existing or TechnicalAnalysis(
            symbol=symbol.upper(),
            analysis={},
            analysis_version=ANALYSIS_VERSION,
            input_hash=digest,
        )
        if existing is None:
            row.status = "failed"
            db.add(row)
        # A previous ready analysis/chart remains the served cache.
        row.last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
        db.commit()
        logger.exception("[technical-analysis] generation failed symbol=%s", symbol.upper())
        return {
            "status": "failed",
            "symbol": symbol.upper(),
            "reason": type(exc).__name__,
        }
    structured_hash = hashlib.sha256(
        json.dumps(analysis, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    row = existing or TechnicalAnalysis(
        symbol=symbol.upper(), analysis_version=ANALYSIS_VERSION, input_hash=digest
    )
    if existing is None:
        db.add(row)
    old_path = row.image_path
    row.status, row.analysis, row.analysis_version, row.input_hash = (
        "ready",
        analysis,
        ANALYSIS_VERSION,
        digest,
    )
    row.structured_hash, row.image_path, row.image_format = (
        structured_hash,
        path,
        "webp",
    )
    row.data_through, row.generated_at, row.last_error = (
        rows[-1].date,
        datetime.now(UTC),
        None,
    )
    db.commit()
    logger.info(
        "[technical-analysis] chart cached symbol=%s data_through=%s path=%s",
        symbol.upper(),
        rows[-1].date,
        path,
    )
    if old_path and old_path != path:
        try:
            Path(old_path).unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "status": "ready",
        "symbol": symbol.upper(),
        "data_through": rows[-1].date.isoformat(),
    }
