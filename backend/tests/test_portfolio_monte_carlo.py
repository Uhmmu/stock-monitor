import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Portfolio, PortfolioAnalysisRun, User
from app.services.portfolio_analysis.bootstrap import joint_block_bootstrap
from app.services.portfolio_analysis.monte_carlo import calculate_monte_carlo
from app.services.portfolio_analysis.expected_return import calculate_expected_return
from app.services.portfolio_analysis.schemas import ExpectedReturnRequest, MonteCarloInput


@pytest.fixture
def db_portfolio():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, Portfolio.__table__, PortfolioAnalysisRun.__table__])
    with Session(engine) as db:
        user = User(username="monte", password_hash="x", status="active"); db.add(user); db.flush()
        portfolio = Portfolio(user_id=user.id, slug="default", name="test"); db.add(portfolio); db.commit()
        yield db, portfolio


def _returns(columns=("AAA", "BBB"), rows=260, seed=7, correlation=.7):
    rng = np.random.default_rng(seed); market = rng.normal(.0002, .01, rows)
    values = {}
    for index, symbol in enumerate(columns):
        noise = rng.normal(0, .01, rows)
        values[symbol] = correlation * market + (1-correlation) * noise + index * .00001
    return pd.DataFrame(values, index=pd.bdate_range("2022-01-03", periods=rows))


def _positions(symbols=("AAA", "BBB")):
    return [{"symbol": symbol, "market_value": 1000, "currency": "USD", "sector": "Technology", "asset_type": "stock"} for symbol in symbols]


def test_joint_bootstrap_preserves_row_relationships():
    history = np.column_stack([np.arange(100), np.arange(100) * 10])
    sample = joint_block_bootstrap(history, 40, 20, 5, np.random.default_rng(1))
    assert np.all(sample[:, :, 1] == sample[:, :, 0] * 10)
    assert np.all(np.diff(sample[:, :5, 0], axis=1) == 1)


def test_fixed_seed_is_reproducible(db_portfolio):
    db, portfolio = db_portfolio; returns = _returns()
    request = MonteCarloInput(simulations=1000, horizon_years=1, random_seed=42, method="block_bootstrap")
    first = calculate_monte_carlo(db, portfolio, request, positions_override=_positions(), returns_override=returns, expected_override={"AAA": .07, "BBB": .06})
    second = calculate_monte_carlo(db, portfolio, request, positions_override=_positions(), returns_override=returns, expected_override={"AAA": .07, "BBB": .06})
    assert first["terminal_value_percentiles"] == second["terminal_value_percentiles"]
    assert first["max_drawdown"] == second["max_drawdown"]


def test_monthly_contribution_and_rebalancing(db_portfolio):
    db, portfolio = db_portfolio
    returns = pd.DataFrame({"AAA": np.zeros(100), "BBB": np.zeros(100)}, index=pd.bdate_range("2022-01-03", periods=100))
    request = MonteCarloInput(simulations=1000, horizon_years=1, random_seed=1, monthly_contribution=100, rebalance_frequency="monthly")
    result = calculate_monte_carlo(db, portfolio, request, positions_override=_positions(), returns_override=returns, expected_override={"AAA": 0, "BBB": 0})
    assert result["terminal_value_percentiles"]["p50"] == pytest.approx(3200, abs=.1)
    assert len(result["sample_paths"]) == 75


def test_single_asset_and_highly_correlated_portfolios(db_portfolio):
    db, portfolio = db_portfolio
    single_returns = _returns(("AAA",), correlation=1)
    single = calculate_monte_carlo(db, portfolio, MonteCarloInput(simulations=1000, random_seed=3), positions_override=_positions(("AAA",)), returns_override=single_returns, expected_override={"AAA": .06})
    assert single["status"] == "completed"
    correlated = _returns(correlation=.999)
    result = calculate_monte_carlo(db, portfolio, MonteCarloInput(simulations=1000, random_seed=3, method="student_t"), positions_override=_positions(), returns_override=correlated, expected_override={"AAA": .06, "BBB": .06})
    assert result["max_drawdown"]["probability_over_20_percent"] >= 0
    assert result["confidence"] in {"low", "medium", "high"}


def test_insufficient_history_is_explicit(db_portfolio):
    db, portfolio = db_portfolio
    returns = _returns(rows=20)
    result = calculate_monte_carlo(db, portfolio, MonteCarloInput(simulations=1000), positions_override=_positions(), returns_override=returns, expected_override={"AAA": .06, "BBB": .06})
    assert result["status"] == "insufficient_data"
    assert result["confidence"] == "low"


def test_expected_return_blend_renormalizes_missing_models(db_portfolio, monkeypatch):
    db, portfolio = db_portfolio
    returns = _returns(("AAA",), rows=300)
    monkeypatch.setattr("app.services.portfolio_analysis.expected_return.load_joint_returns", lambda *args, **kwargs: SimpleNamespace(returns=returns, warnings=[]))
    monkeypatch.setattr("app.services.portfolio_analysis.expected_return.estimate_sensitivities", lambda *args, **kwargs: {"market_beta": 1.1})
    monkeypatch.setattr("app.services.portfolio_analysis.expected_return._fundamental_model", lambda *args, **kwargs: (.08, ["盈利增长"]))
    monkeypatch.setattr("app.services.portfolio_analysis.expected_return._forward_model", lambda *args, **kwargs: (None, []))
    result = calculate_expected_return(db, portfolio, ExpectedReturnRequest(), positions_override=_positions(("AAA",)))
    weights = result["assets"][0]["model_weights"]
    assert "forward" not in weights
    assert sum(weights.values()) == pytest.approx(1.0)
    assert set(weights) == {"historical", "capm", "fundamental"}
