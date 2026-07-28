from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import HistoricalPrice, Portfolio, PortfolioAnalysisRun, PortfolioPosition, PriceSnapshot, User
from app.services.portfolio_analysis.data_loader import load_joint_returns
from app.services.portfolio_analysis.risk_metrics import calculate_metrics, covariance_matrix
from app.services.portfolio_analysis.schemas import PortfolioAnalysisRequest
from app.services.portfolio_analysis.service import latest_metrics, run_metrics_analysis


TABLES = [User.__table__, Portfolio.__table__, PortfolioPosition.__table__, PriceSnapshot.__table__, HistoricalPrice.__table__, PortfolioAnalysisRun.__table__]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def _history(db, symbol, prices, start=date(2021, 1, 4)):
    for index, close in enumerate(prices):
        day = start + timedelta(days=index)
        db.add(HistoricalPrice(symbol=symbol, date=day, open=close, high=close, low=close, close=close, volume=100, source="fmp"))
    db.commit()


def test_equal_weight_portfolio_is_deterministic_and_risk_contributions_sum_to_one(db):
    _history(db, "AAA", [100, 101, 100, 103, 104, 105])
    _history(db, "BBB", [50, 49, 50, 51, 52, 53])
    loaded = load_joint_returns(db, ["AAA", "BBB"], {"AAA": .5, "BBB": .5}, allow_fetch=False)
    expected = loaded.returns.mul(pd.Series({"AAA": .5, "BBB": .5}), axis=1).sum(axis=1)
    assert np.allclose(loaded.portfolio_returns, expected)
    result = calculate_metrics(loaded.portfolio_returns, loaded.returns, pd.Series({"AAA": .5, "BBB": .5}), {"AAA": "Tech", "BBB": "Health"}, None, "ledoit_wolf")
    assert sum(row["risk_contribution"] for row in result["asset_risk_contributions"]) == pytest.approx(1.0)
    assert result["metrics"]["hhi"] == pytest.approx(.5)


def test_single_asset_metrics_and_covariance(db):
    _history(db, "ONE", [100, 98, 101, 97, 103, 105])
    loaded = load_joint_returns(db, ["ONE"], {"ONE": 1}, allow_fetch=False)
    covariance = covariance_matrix(loaded.returns, "ledoit_wolf")
    assert covariance.shape == (1, 1)
    result = calculate_metrics(loaded.portfolio_returns, loaded.returns, pd.Series({"ONE": 1.0}), {"ONE": "Tech"}, None, "ledoit_wolf")
    assert result["asset_risk_contributions"][0]["risk_contribution"] == pytest.approx(1.0)
    assert result["metrics"]["max_drawdown"] < 0


def test_missing_asset_is_warned_and_remaining_weight_is_normalized(db):
    _history(db, "KNOWN", [100, 101, 102, 103])
    loaded = load_joint_returns(db, ["KNOWN", "MISSING"], {"KNOWN": .6, "MISSING": .4}, allow_fetch=False)
    assert not loaded.portfolio_returns.empty
    assert loaded.portfolio_returns.equals(loaded.returns["KNOWN"])
    assert any("MISSING 缺少历史行情" in warning for warning in loaded.warnings)


def test_new_listing_common_and_dynamic_modes_do_not_zero_fill(db):
    _history(db, "OLD", [100 + i for i in range(12)])
    _history(db, "NEW", [50 + i for i in range(6)], start=date(2021, 1, 10))
    common = load_joint_returns(db, ["OLD", "NEW"], {"OLD": .5, "NEW": .5}, mode="common_start", allow_fetch=False)
    dynamic = load_joint_returns(db, ["OLD", "NEW"], {"OLD": .5, "NEW": .5}, mode="dynamic_available", allow_fetch=False)
    assert common.returns.notna().all().all()
    assert len(dynamic.portfolio_returns) > len(common.portfolio_returns)
    assert dynamic.returns["NEW"].isna().any()
    assert dynamic.effective_weights.loc[dynamic.returns["NEW"].isna(), "NEW"].eq(0).all()


def test_empty_portfolio_returns_structured_insufficient_result(db):
    user = User(username="risk", password_hash="x", status="active")
    db.add(user)
    db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="empty")
    db.add(portfolio)
    db.commit()
    result = run_metrics_analysis(db, portfolio, PortfolioAnalysisRequest(portfolio_id=portfolio.id))
    assert result["status"] == "insufficient_data"
    assert result["confidence"] == "low"
    assert result["coverage_warning"]
    assert db.query(PortfolioAnalysisRun).one().status == "completed"


def test_latest_metrics_only_reuses_completed_results_from_last_seven_days(db):
    user = User(username="cache", password_hash="x", status="active")
    db.add(user)
    db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="cache")
    db.add(portfolio)
    db.flush()
    db.add(PortfolioAnalysisRun(
        portfolio_id=portfolio.id,
        analysis_type="metrics",
        status="completed",
        input_snapshot_json={},
        assumptions_json={},
        result_json={"marker": "expired"},
        model_version="test",
        completed_at=datetime.now(UTC) - timedelta(days=8),
    ))
    db.commit()
    assert latest_metrics(db, portfolio.id) is None

    db.add(PortfolioAnalysisRun(
        portfolio_id=portfolio.id,
        analysis_type="metrics",
        status="completed",
        input_snapshot_json={},
        assumptions_json={},
        result_json={"marker": "fresh"},
        model_version="test",
        completed_at=datetime.now(UTC) - timedelta(days=6),
    ))
    db.commit()
    assert latest_metrics(db, portfolio.id) == {"marker": "fresh"}
