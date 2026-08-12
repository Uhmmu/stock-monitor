"""Broker-authoritative portfolio versus passive-market benchmark comparison."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.ibkr.db_models import IbkrAccountDailyPerformance
from app.models import HistoricalPrice, Portfolio
from app.services.portfolio.investment_ledger import latest_authoritative_run


BENCHMARKS = (
    ("SPY", "标普 500（SPY）"),
    ("QQQ", "纳斯达克 100（QQQ）"),
    ("DIA", "道琼斯工业指数（DIA）"),
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


def _stored_close_points(db: Session, symbol: str, start_date: date) -> tuple[tuple[date, float] | None, tuple[date, float] | None]:
    rows = db.execute(select(HistoricalPrice.date, HistoricalPrice.close).where(
        HistoricalPrice.symbol == symbol, HistoricalPrice.source == "yahoo", HistoricalPrice.date >= start_date,
    ).order_by(HistoricalPrice.date)).all()
    points = [(row.date, float(row.close)) for row in rows if row.close and float(row.close) > 0]
    return (points[0], points[-1]) if points else (None, None)


def _ibkr_performance_inputs(db: Session, portfolio: Portfolio) -> tuple[date, float] | None:
    run = latest_authoritative_run(db, portfolio.user_id)
    if run is None:
        return None
    rows = list(db.scalars(select(IbkrAccountDailyPerformance).where(
        IbkrAccountDailyPerformance.source_sync_run_id == run.id,
        IbkrAccountDailyPerformance.cumulative_return.is_not(None),
    ).order_by(IbkrAccountDailyPerformance.performance_date)).all())
    if not rows:
        return None
    return rows[0].performance_date, float(rows[-1].cumulative_return) * 100


def build_benchmark_comparison(portfolio: Portfolio, db: Session | None = None) -> dict:
    authoritative = _ibkr_performance_inputs(db, portfolio) if db is not None else None
    start_date = authoritative[0] if authoritative else portfolio.benchmark_start_date
    portfolio_return = authoritative[1] if authoritative else portfolio.benchmark_portfolio_return_percent
    return_source = "ibkr_flex" if authoritative else "manual" if start_date is not None and portfolio_return is not None else "unavailable"
    now = datetime.now(UTC)
    if start_date is None or portfolio_return is None:
        return {
            "start_date": start_date,
            "portfolio_return_percent": portfolio_return,
            "configured": False,
            "portfolio_return_source": return_source,
            "benchmarks": [],
            "source": "Yahoo Finance 收盘价",
            "as_of": now,
        }
    if start_date > now.date():
        # Should be prevented on write, but stay explicit if legacy data is bad.
        return {"start_date": start_date, "portfolio_return_percent": portfolio_return, "configured": False, "portfolio_return_source": return_source,
                "benchmarks": [], "source": "Yahoo Finance 收盘价", "as_of": now}

    rows = []
    for symbol, name in BENCHMARKS:
        try:
            start, latest = _stored_close_points(db, symbol, start_date) if isinstance(db, Session) else (None, None)
            if start is None or latest is None:
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
    source = "IBKR Flex 现金流调整时间加权收益 + Yahoo Finance 收盘价（不含股息再投资）" if authoritative else "用户输入组合收益 + Yahoo Finance 收盘价（不含股息再投资）"
    return {"start_date": start_date, "portfolio_return_percent": portfolio_return, "configured": True,
            "portfolio_return_source": return_source, "benchmarks": rows, "source": source, "as_of": now}
