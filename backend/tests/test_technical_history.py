from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from fastapi import HTTPException

from app.api.routes import (
    technical_analysis_detail,
    technical_price_alert_create,
    technical_price_alert_delete,
)
from app.models import (
    HistoricalPrice,
    InvestmentCalendarEvent,
    Portfolio,
    PortfolioPosition,
    TechnicalAnalysis,
    User,
    WatchlistItem,
)
from app.schemas import UserPriceAlertCreate
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


def test_technical_detail_exposes_cached_weekly_series(db):
    from datetime import timedelta

    user = User(
        username="chart-user",
        password_hash="test",
        role="user",
        status="active",
    )
    db.add(user)
    db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="测试组合")
    db.add(portfolio)
    db.flush()
    db.add(
        PortfolioPosition(
            portfolio_id=portfolio.id,
            symbol="AAPL",
            total_quantity=10,
            average_cost=123.45,
            total_cost=1234.5,
            currency="USD",
        )
    )
    db.add(
        InvestmentCalendarEvent(
            id="earnings-aapl-2025q1",
            event_type="earnings",
            symbol="AAPL",
            title="季度财报",
            event_date=date(2025, 4, 28),
            primary_source="test",
            status="active",
        )
    )
    db.add(WatchlistItem(ticker="AAPL", enabled=True))
    db.add(
        TechnicalAnalysis(
            symbol="AAPL",
            status="ready",
            analysis={"latestClose": 169.0, "source": "fmp"},
            analysis_version=technical_analysis.ANALYSIS_VERSION,
            input_hash="cached",
            data_through=date(2025, 4, 28),
        )
    )
    start = date(2024, 1, 1)
    for index in range(70):
        price = 100 + index
        db.add(
            HistoricalPrice(
                symbol="AAPL",
                date=start + timedelta(weeks=index),
                source="fmp",
                open=price,
                high=price + 2,
                low=price - 2,
                close=price + 1,
                volume=1_000_000 + index,
            )
        )
    db.commit()

    result = technical_analysis_detail("aapl", user, db)
    assert result["chart_data_status"] == "ready"
    assert result["chart_data_source"] == "fmp"
    assert len(result["weekly"]) == 70
    assert len(result["moving_averages"]["ma20"]) == 51
    assert len(result["moving_averages"]["ma50"]) == 21
    assert result["portfolio_cost"]["average_cost"] == 123.45
    assert result["events"][0]["type"] == "earnings"


def test_technical_detail_reports_insufficient_chart_data(db):
    user = User(
        username="empty-chart-user",
        password_hash="test",
        role="user",
        status="active",
    )
    db.add(user)
    db.add(WatchlistItem(ticker="AAPL", enabled=True))
    db.commit()

    result = technical_analysis_detail("AAPL", user, db)
    assert result["status"] == "pending"
    assert result["chart_data_status"] == "insufficient"
    assert result["chart_data_reason"] == "historical_data_unavailable"
    assert result["weekly"] == []


def test_price_alert_routes_are_idempotent_and_user_scoped(db):
    owner = User(
        username="price-alert-owner",
        password_hash="test",
        role="user",
        status="active",
    )
    other = User(
        username="price-alert-other",
        password_hash="test",
        role="user",
        status="active",
    )
    db.add_all([owner, other, WatchlistItem(ticker="AAPL", enabled=True)])
    db.commit()
    payload = UserPriceAlertCreate(target_price=200, direction="above")

    created = technical_price_alert_create("AAPL", payload, owner, db)
    duplicate = technical_price_alert_create("aapl", payload, owner, db)
    assert duplicate["id"] == created["id"]

    with pytest.raises(HTTPException) as exc:
        technical_price_alert_delete("AAPL", created["id"], other, db)
    assert exc.value.status_code == 404

    response = technical_price_alert_delete("AAPL", created["id"], owner, db)
    assert response.status_code == 204
