from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice


SOURCE_PRIORITY = ("fmp", "yahoo")
MIN_OBSERVATIONS = 60
LONG_GAP_DAYS = 20


@dataclass
class LoadedReturns:
    prices: pd.DataFrame
    returns: pd.DataFrame
    portfolio_returns: pd.Series
    effective_weights: pd.DataFrame
    sources: dict[str, str]
    actual_start_dates: dict[str, str | None]
    warnings: list[str]


def _local_prices(db: Session, symbol: str) -> tuple[pd.Series, str | None]:
    value = symbol.upper()
    for source in SOURCE_PRIORITY:
        rows = db.execute(
            select(HistoricalPrice.date, HistoricalPrice.close)
            .where(HistoricalPrice.symbol == value, HistoricalPrice.source == source)
            .order_by(HistoricalPrice.date)
        ).all()
        points = {row.date: float(row.close) for row in rows if row.close and float(row.close) > 0}
        if points:
            result = pd.Series(points, name=value, dtype=float).sort_index()
            result.index = pd.to_datetime(result.index)
            return result, source
    return pd.Series(name=value, dtype=float), None


def _fetch_fallback(db: Session, symbol: str) -> tuple[pd.Series, str | None, str | None]:
    """FMP first, then adjusted Yahoo. Failures are data-quality warnings, never fatal."""
    fmp_error = None
    try:
        from app.services.fmp_market import sync_history

        sync_history(db, symbol)
        series, source = _local_prices(db, symbol)
        if not series.empty:
            return series, source, None
    except Exception as exc:  # upstream boundaries intentionally degrade
        db.rollback()
        fmp_error = type(exc).__name__
    try:
        frame = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=True)
        if frame is None or frame.empty:
            return pd.Series(name=symbol, dtype=float), None, f"{symbol} 无可用历史行情"
        points: dict[date, float] = {}
        for idx, value in frame.get("Close", pd.Series(dtype=float)).items():
            try:
                number = float(value)
                if math.isfinite(number) and number > 0:
                    points[idx.date()] = number
            except (TypeError, ValueError, AttributeError):
                continue
        warning = f"{symbol} FMP 不可用（{fmp_error}），本次使用 Yahoo 复权行情" if fmp_error else None
        result = pd.Series(points, name=symbol, dtype=float).sort_index()
        result.index = pd.to_datetime(result.index)
        return result, "yahoo_live_adjusted", warning
    except Exception as exc:
        return pd.Series(name=symbol, dtype=float), None, f"{symbol} 行情读取失败：{type(exc).__name__}"


def load_joint_returns(
    db: Session,
    symbols: list[str],
    weights: dict[str, float],
    *,
    mode: str = "common_start",
    allow_fetch: bool = True,
) -> LoadedReturns:
    series: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    starts: dict[str, str | None] = {}
    warnings: list[str] = []
    for raw in symbols:
        symbol = raw.upper()
        values, source = _local_prices(db, symbol)
        if values.empty and allow_fetch:
            values, source, warning = _fetch_fallback(db, symbol)
            if warning:
                warnings.append(warning)
        if values.empty:
            starts[symbol] = None
            warnings.append(f"{symbol} 缺少历史行情，已从历史风险序列排除")
            continue
        series[symbol] = values
        sources[symbol] = source or "unknown"
        starts[symbol] = values.index.min().isoformat()
        if len(values) < MIN_OBSERVATIONS:
            warnings.append(f"{symbol} 仅有 {len(values)} 个有效交易日，风险估计可信度较低")

    if not series:
        empty = pd.DataFrame()
        return LoadedReturns(empty, empty, pd.Series(dtype=float), empty, sources, starts, warnings)

    prices = pd.concat(series.values(), axis=1).sort_index()
    raw_returns = prices.pct_change(fill_method=None)
    abnormal = raw_returns.abs() > 0.8
    for symbol in raw_returns.columns:
        count = int(abnormal[symbol].sum())
        if count:
            warnings.append(f"{symbol} 移除 {count} 个超过 ±80% 的异常单日收益")
    returns = raw_returns.mask(abnormal)

    available_symbols = list(series)
    available_weight_total = sum(max(0.0, weights.get(s, 0.0)) for s in available_symbols)
    if available_weight_total <= 0:
        return LoadedReturns(prices, returns, pd.Series(dtype=float), pd.DataFrame(), sources, starts, warnings)
    normalized = pd.Series({s: max(0.0, weights.get(s, 0.0)) / available_weight_total for s in available_symbols})

    if mode == "common_start":
        joint = returns.dropna(how="any")
        effective = pd.DataFrame([normalized] * len(joint), index=joint.index)
        portfolio_returns = joint.mul(normalized, axis=1).sum(axis=1)
        returns = joint
    else:
        valid = returns.notna()
        daily_denominator = valid.mul(normalized, axis=1).sum(axis=1).replace(0, float("nan"))
        effective = valid.mul(normalized, axis=1).div(daily_denominator, axis=0)
        portfolio_returns = returns.mul(effective).sum(axis=1, min_count=1).dropna()
        effective = effective.loc[portfolio_returns.index]
        returns = returns.loc[portfolio_returns.index]

    if not portfolio_returns.empty:
        calendar_span = (portfolio_returns.index.max() - portfolio_returns.index.min()).days
        if calendar_span > 0 and len(portfolio_returns) / calendar_span < 0.45:
            warnings.append("联合有效交易日偏少，部分资产存在较长缺失区间")
    for symbol, values in returns.items():
        longest = _longest_missing_run(values.isna().tolist())
        if longest >= LONG_GAP_DAYS:
            warnings.append(f"{symbol} 存在连续 {longest} 个联合交易日缺失")
    return LoadedReturns(prices, returns, portfolio_returns, effective, sources, starts, warnings)


def _longest_missing_run(values: list[bool]) -> int:
    longest = current = 0
    for missing in values:
        current = current + 1 if missing else 0
        longest = max(longest, current)
    return longest
