"""User-configured portfolio versus passive-market benchmark comparison."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import yfinance as yf

from app.models import Portfolio


BENCHMARKS = (
    ("SPY", "标普 500（SPY）"),
    ("QQQ", "纳斯达克 100（QQQ）"),
    ("VT", "全球股票（VT）"),
)


def _close_points(symbol: str, start_date: date) -> tuple[tuple[date, float] | None, tuple[date, float] | None]:
    """Return first close on/after start and most recent close, without guessing holidays."""
    # Yahoo's end argument is exclusive.  Asking through tomorrow makes the
    # latest completed trading day available while still returning only closes.
    frame = yf.Ticker(symbol).history(
        start=start_date.isoformat(), end=(datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
        interval="1d", auto_adjust=False,
    )
    if frame is None or frame.empty or "Close" not in frame:
        return None, None
    points: list[tuple[date, float]] = []
    for index, raw in frame["Close"].items():
        try:
            day, close = index.date(), float(raw)
        except (AttributeError, TypeError, ValueError):
            continue
        if close > 0 and close == close:
            points.append((day, close))
    return (points[0], points[-1]) if points else (None, None)


def build_benchmark_comparison(portfolio: Portfolio) -> dict:
    start_date = portfolio.benchmark_start_date
    portfolio_return = portfolio.benchmark_portfolio_return_percent
    now = datetime.now(UTC)
    if start_date is None or portfolio_return is None:
        return {
            "start_date": start_date,
            "portfolio_return_percent": portfolio_return,
            "configured": False,
            "benchmarks": [],
            "source": "Yahoo Finance 收盘价",
            "as_of": now,
        }
    if start_date > now.date():
        # Should be prevented on write, but stay explicit if legacy data is bad.
        return {"start_date": start_date, "portfolio_return_percent": portfolio_return, "configured": False,
                "benchmarks": [], "source": "Yahoo Finance 收盘价", "as_of": now}

    rows = []
    for symbol, name in BENCHMARKS:
        try:
            start, latest = _close_points(symbol, start_date)
        except Exception:
            start = latest = None
        if start is None or latest is None:
            rows.append({"symbol": symbol, "name": name, "start_price": None, "start_price_date": None,
                         "latest_price": None, "latest_price_date": None, "return_percent": None,
                         "relative_return_percent": None, "status": "unavailable", "message": "未能取得足够的历史收盘价"})
            continue
        benchmark_return = (latest[1] / start[1] - 1) * 100
        rows.append({"symbol": symbol, "name": name, "start_price": round(start[1], 4), "start_price_date": start[0],
                     "latest_price": round(latest[1], 4), "latest_price_date": latest[0],
                     "return_percent": round(benchmark_return, 4),
                     "relative_return_percent": round(portfolio_return - benchmark_return, 4),
                     "status": "available", "message": None})
    return {"start_date": start_date, "portfolio_return_percent": portfolio_return, "configured": True,
            "benchmarks": rows, "source": "Yahoo Finance 收盘价（不含股息再投资）", "as_of": now}
