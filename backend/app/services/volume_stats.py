"""成交量对比语境：历史均量 + 盘中预估全天量 + 量比标签。

用途：给报告 AI 和前端市场快照提供"放量/缩量"判断。孤立的成交量数字没有意义，
必须和历史均量对照才知道是多是少。盘中用线性外推预估全天量（不追求精确，避免耗算力）。

- 历史均量走 yfinance 日 K（带进程内当日缓存，均量一天内变化极小）。
- 盘中已过交易时段占比走 exchange_calendars 的当日 open/close。
- 纯计算部分（外推、量比、标签）与 IO 分离，便于单测。
"""
from datetime import UTC, date, datetime

import exchange_calendars as xcals
import pandas as pd
import yfinance as yf

# 量比阈值：预估全天量 / 历史均量
HEAVY_RATIO = 1.5  # ≥ 放量
LIGHT_RATIO = 0.7  # ≤ 缩量

_AVG_WINDOW_DAYS = 30
_calendar = xcals.get_calendar("XNYS", start="2000-01-01", end="2100-12-31")

# {(ticker, date): avg_volume}，均量一天变化极小，进程内当日缓存避免重复拉取
_avg_cache: dict[tuple[str, date], float | None] = {}


def average_daily_volume(ticker: str, moment: datetime | None = None) -> float | None:
    """过去 ~30 个交易日的日均成交量。当日进程内缓存。"""
    today = (moment or datetime.now(UTC)).date()
    cache_key = (ticker.upper(), today)
    if cache_key in _avg_cache:
        return _avg_cache[cache_key]
    result: float | None = None
    try:
        hist = yf.Ticker(ticker).history(period=f"{_AVG_WINDOW_DAYS}d")
        if hist is not None and not hist.empty and "Volume" in hist.columns:
            volumes = hist["Volume"].dropna()
            volumes = volumes[volumes > 0]
            if not volumes.empty:
                result = float(volumes.mean())
    except Exception:
        result = None
    _avg_cache[cache_key] = result
    return result


def session_elapsed_fraction(moment: datetime | None = None) -> float | None:
    """当日交易时段已过占比 (0,1]。非交易日/盘前返回 None，盘后返回 1.0。"""
    now = (moment or datetime.now(UTC)).astimezone(UTC)
    session_date = pd.Timestamp(now.date())
    if session_date not in _calendar.schedule.index:
        return None
    schedule = _calendar.schedule.loc[session_date]
    open_ts = pd.Timestamp(schedule["open"])
    close_ts = pd.Timestamp(schedule["close"])
    now_ts = pd.Timestamp(now)
    if now_ts < open_ts:
        return None
    if now_ts >= close_ts:
        return 1.0
    total = (close_ts - open_ts).total_seconds()
    if total <= 0:
        return None
    elapsed = (now_ts - open_ts).total_seconds()
    return max(min(elapsed / total, 1.0), 0.0)


def estimate_full_day_volume(current_volume: float | None, elapsed_fraction: float | None) -> float | None:
    """线性外推预估全天量：当前累计量 / 已过时段占比。

    盘后 elapsed_fraction=1.0 直接返回实际量；盘前/无数据返回 None。
    """
    if current_volume is None or current_volume <= 0:
        return None
    if elapsed_fraction is None or elapsed_fraction <= 0:
        return None
    return current_volume / elapsed_fraction


def volume_ratio(estimated_full_day: float | None, avg_volume: float | None) -> float | None:
    """预估全天量 / 历史均量。"""
    if not estimated_full_day or not avg_volume or avg_volume <= 0:
        return None
    return estimated_full_day / avg_volume


def volume_label(ratio: float | None) -> str | None:
    """量比 → 放量/缩量/正常。数据不足返回 None。"""
    if ratio is None:
        return None
    if ratio >= HEAVY_RATIO:
        return "放量"
    if ratio <= LIGHT_RATIO:
        return "缩量"
    return "正常"


def volume_context(ticker: str, current_volume: float | None, moment: datetime | None = None) -> dict:
    """汇总一只股票的成交量对比语境，供报告注入与 dashboard 端点复用。

    返回：{avg_volume, estimated_full_day, ratio, label}，任意字段可能为 None（数据不足）。
    """
    avg = average_daily_volume(ticker, moment)
    fraction = session_elapsed_fraction(moment)
    estimated = estimate_full_day_volume(current_volume, fraction)
    ratio = volume_ratio(estimated, avg)
    return {
        "avg_volume": avg,
        "estimated_full_day": estimated,
        "ratio": ratio,
        "label": volume_label(ratio),
    }
