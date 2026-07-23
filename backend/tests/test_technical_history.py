from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import HistoricalPrice, TechnicalAnalysis
from app.services import market_data
from app.services import technical_analysis_engine as technical_analysis


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def _frame(rows: list[dict]) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(r["date"]) for r in rows])
    return pd.DataFrame(
        {
            "Open": [r["open"] for r in rows],
            "High": [r["high"] for r in rows],
            "Low": [r["low"] for r in rows],
            "Close": [r["close"] for r in rows],
            "Volume": [r["volume"] for r in rows],
        },
        index=index,
    )


def test_fetch_daily_history_validates_and_derives_change(monkeypatch):
    rows = [
        {"date": "2026-07-20", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        # invalid row: high < low -> dropped, and resets change basis
        {"date": "2026-07-21", "open": 10, "high": 8, "low": 9, "close": 10, "volume": 100},
        {"date": "2026-07-22", "open": 10, "high": 13, "low": 9, "close": 12, "volume": 110},
    ]
    monkeypatch.setattr(
        market_data.yf, "Ticker", lambda symbol: SimpleNamespace(history=lambda **kw: _frame(rows))
    )
    out = market_data.fetch_daily_history("aapl", today=date(2026, 7, 22))
    assert [r["date"] for r in out] == [date(2026, 7, 20), date(2026, 7, 22)]
    assert all(r["source"] == "yahoo" and r["vwap"] is None for r in out)
    # 2026-07-22 follows a dropped invalid row, so change basis was reset -> None
    assert out[-1]["change"] is None
    assert out[-1]["close"] == Decimal("12")


def test_fetch_daily_history_empty_frame(monkeypatch):
    monkeypatch.setattr(
        market_data.yf, "Ticker", lambda symbol: SimpleNamespace(history=lambda **kw: pd.DataFrame())
    )
    assert market_data.fetch_daily_history("aapl") == []


def test_sync_history_is_idempotent_and_generates(db, monkeypatch):
    rows = [
        {"date": f"2024-{month:02d}-01", "open": 100 + month, "high": 105 + month,
         "low": 95 + month, "close": 100 + month, "volume": 1_000_000}
        for month in range(1, 13)
    ] + [
        {"date": f"2025-{month:02d}-01", "open": 110 + month, "high": 115 + month,
         "low": 105 + month, "close": 110 + month, "volume": 1_000_000}
        for month in range(1, 13)
    ]
    monkeypatch.setattr(
        market_data.yf, "Ticker", lambda symbol: SimpleNamespace(history=lambda **kw: _frame(rows))
    )
    monkeypatch.setattr(technical_analysis, "render_chart", lambda *a, **k: None)

    first = technical_analysis.sync_fallback_history(db, "aapl", today=date(2025, 12, 31))
    assert first["received"] == len(rows)
    assert first["changed"] == len(rows)
    stored = db.scalars(select(HistoricalPrice)).all()
    assert stored and all(r.source == "yahoo" for r in stored)

    second = technical_analysis.sync_fallback_history(db, "aapl", today=date(2025, 12, 31))
    assert second["changed"] == 0
    row = db.get(TechnicalAnalysis, "AAPL")
    assert row is not None and row.status == "ready"
    assert row.analysis["source"] == "yahoo"


def test_fmp_source_takes_priority_over_yahoo(db, monkeypatch):
    """同一标的同时存在 fmp 与 yahoo 历史时，generate 应优先使用 fmp。"""
    from datetime import timedelta
    monkeypatch.setattr(technical_analysis, "render_chart", lambda *a, **k: None)
    start = date(2024, 1, 1)
    for i in range(60):
        day = start + timedelta(days=i)
        for source, base in (("fmp", 100), ("yahoo", 200)):
            db.add(HistoricalPrice(symbol="AAPL", date=day, source=source,
                                   open=base + i, high=base + i + 2,
                                   low=base + i - 2, close=base + i + 1, volume=1_000_000))
    db.commit()
    rows, source = technical_analysis._load_history(db, "AAPL")
    assert source == "fmp"
    result = technical_analysis.generate_for_symbol(db, "AAPL", force=True)
    assert db.get(TechnicalAnalysis, "AAPL").analysis["source"] == "fmp"
