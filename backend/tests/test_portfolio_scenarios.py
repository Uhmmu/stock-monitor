from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import HistoricalPrice, Portfolio, User
from app.services.portfolio_analysis.factor_model import factor_return
from app.services.portfolio_analysis.schemas import StressTestRequest
from app.services.portfolio_analysis.stress_test import calculate_stress_test


TABLES = [User.__table__, Portfolio.__table__, HistoricalPrice.__table__]


@pytest.fixture
def db_portfolio():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as db:
        user = User(username="scenario", password_hash="x", status="active")
        db.add(user); db.flush()
        portfolio = Portfolio(user_id=user.id, slug="default", name="test")
        db.add(portfolio); db.commit()
        yield db, portfolio


def _history(db, symbol, start, count=90, daily=.001):
    price = 100.0
    for index in range(count):
        price *= 1 + daily
        day = start + timedelta(days=index)
        db.add(HistoricalPrice(symbol=symbol, date=day, open=price, high=price, low=price, close=price, volume=100, source="fmp"))
    db.commit()


def test_factor_shock_is_deterministic_and_bounded():
    sensitivity = {"market_beta": 1.2, "sector_beta": .5, "rate_sensitivity": -.00025, "fx_sensitivity": 1, "growth_sensitivity": .5, "volatility_sensitivity": -.03}
    first = factor_return(sensitivity, market_shock=-.3, sector_shock=-.2, rate_change_bp=100, fx_shock=0, style_shock=-.1, volatility_change=.5)
    assert first == factor_return(sensitivity, market_shock=-.3, sector_shock=-.2, rate_change_bp=100, fx_shock=0, style_shock=-.1, volatility_change=.5)
    assert -.95 <= first <= 2


def test_historical_replay_marks_actual_assets(db_portfolio):
    db, portfolio = db_portfolio
    _history(db, "AAA", date(2022, 1, 1), daily=-.002)
    _history(db, "SPY", date(2022, 1, 1), daily=-.001)
    positions = [{"symbol": "AAA", "market_value": 1000, "currency": "USD", "sector": "Technology", "industry": None, "asset_type": "stock"}]
    request = StressTestRequest(mode="historical_replay", start_date=date(2022, 1, 5), end_date=date(2022, 2, 5))
    result = calculate_stress_test(db, portfolio, request, positions_override=positions)
    assert result["data_quality"] == "actual"
    assert result["asset_results"][0]["method"] == "actual"
    assert result["actual_asset_count"] == 1


def test_new_listing_uses_sector_proxy_and_marks_mixed_quality(db_portfolio):
    db, portfolio = db_portfolio
    _history(db, "OLD", date(2022, 1, 1), daily=-.001)
    _history(db, "XLK", date(2022, 1, 1), daily=-.002)
    _history(db, "SPY", date(2022, 1, 1), daily=-.001)
    positions = [
        {"symbol": "OLD", "market_value": 500, "currency": "USD", "sector": "Technology", "industry": None, "asset_type": "stock"},
        {"symbol": "NEW", "market_value": 500, "currency": "USD", "sector": "Technology", "industry": None, "asset_type": "stock"},
    ]
    request = StressTestRequest(mode="historical_replay", start_date=date(2022, 1, 5), end_date=date(2022, 2, 5))
    result = calculate_stress_test(db, portfolio, request, positions_override=positions)
    assert result["data_quality"] == "mixed"
    assert {row["method"] for row in result["asset_results"]} == {"actual", "proxy"}


def test_no_sector_data_uses_factor_model_with_confidence(db_portfolio):
    db, portfolio = db_portfolio
    _history(db, "ODD", date(2022, 1, 1), daily=.0015)
    _history(db, "SPY", date(2022, 1, 1), daily=.001)
    positions = [{"symbol": "ODD", "market_value": 1000, "currency": "USD", "sector": None, "industry": None, "asset_type": "stock"}]
    request = StressTestRequest(mode="custom_scenario", market_shock=-.2, sector_shocks={})
    result = calculate_stress_test(db, portfolio, request, positions_override=positions)
    assert result["asset_results"][0]["method"] == "factor_model"
    assert result["asset_results"][0]["confidence"] in {"low", "medium", "high"}


def test_pre_2021_cannot_be_real_replay(db_portfolio):
    db, portfolio = db_portfolio
    positions = [{"symbol": "AAA", "market_value": 1000, "currency": "USD", "sector": None, "industry": None, "asset_type": "stock"}]
    request = StressTestRequest(mode="historical_replay", start_date=date(2008, 1, 1), end_date=date(2009, 1, 1))
    result = calculate_stress_test(db, portfolio, request, positions_override=positions)
    assert result["status"] == "invalid_input"
    assert "不能标记为真实历史回放" in result["message"]


def test_extreme_custom_inputs_are_rejected():
    with pytest.raises(ValidationError):
        StressTestRequest(mode="custom_scenario", market_shock=-.95)
    with pytest.raises(ValidationError):
        StressTestRequest(mode="custom_scenario", sector_shocks={"Technology": -1.0})
    with pytest.raises(ValidationError):
        StressTestRequest(mode="custom_scenario", interest_rate_change_bp=2000)
