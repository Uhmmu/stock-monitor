import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Portfolio, PortfolioAnalysisRun, User
from app.services.portfolio_analysis.optimizer import calculate_optimization
from app.services.portfolio_analysis.schemas import OptimizationConstraints, OptimizationRequest


@pytest.fixture
def db_portfolio():
    engine=create_engine("sqlite+pysqlite:///:memory:");Base.metadata.create_all(engine,tables=[User.__table__,Portfolio.__table__,PortfolioAnalysisRun.__table__])
    with Session(engine) as db:
        user=User(username="optimizer",password_hash="x",status="active");db.add(user);db.flush();portfolio=Portfolio(user_id=user.id,slug="default",name="test");db.add(portfolio);db.commit();yield db,portfolio


def _returns(symbols,rows=300,seed=8):
    rng=np.random.default_rng(seed);market=rng.normal(.0003,.012,rows)
    return pd.DataFrame({symbol:market*(.5+i*.05)+rng.normal(.0001,.006,rows) for i,symbol in enumerate(symbols)},index=pd.bdate_range("2022-01-03",periods=rows))


def _positions(values,sectors=None):
    sectors=sectors or ["Technology","Technology","Healthcare","Healthcare","Industrials","Energy"][:len(values)]
    return [{"symbol":f"S{i}","market_value":value,"current_price":37+i,"currency":"USD","sector":sectors[i],"asset_type":"stock"} for i,value in enumerate(values)]


def test_optimization_satisfies_weight_position_sector_and_turnover_constraints(db_portfolio):
    db,portfolio=db_portfolio;positions=_positions([180,170,165,165,160,160]);symbols=[p["symbol"] for p in positions]
    constraints=OptimizationConstraints(max_position_weight=.22,max_sector_weight=.38,max_turnover=.25,min_cash_weight=.03,max_cash_weight=.2)
    result=calculate_optimization(db,portfolio,OptimizationRequest(objective="balanced",constraints=constraints),positions_override=positions,returns_override=_returns(symbols),expected_override={s:.06+i*.01 for i,s in enumerate(symbols)})
    assert result["status"]=="completed"
    assert sum(result["target_weights"].values())+result["cash_weight"]==pytest.approx(1)
    assert max(result["target_weights"].values())<=.22+1e-6
    assert result["turnover"]<=.25+1e-6
    sector_totals={sector:sum(row["target_weight"] for row in result["weight_changes"] if row["sector"]==sector) for sector in set(p["sector"] for p in positions)}
    assert max(sector_totals.values())<=.38+1e-6


def test_locked_and_do_not_sell_positions_are_respected(db_portfolio):
    db,portfolio=db_portfolio;positions=_positions([200]*5,["A","B","C","D","E"]);symbols=[p["symbol"] for p in positions]
    constraints=OptimizationConstraints(max_position_weight=.4,max_sector_weight=.5,max_turnover=.6,locked_symbols=["S0"],do_not_sell_symbols=["S1"])
    result=calculate_optimization(db,portfolio,OptimizationRequest(objective="maximum_sharpe",constraints=constraints),positions_override=positions,returns_override=_returns(symbols),expected_override={"S0":.03,"S1":.04,"S2":.08,"S3":.1,"S4":.12})
    assert result["status"]=="completed"
    assert result["target_weights"]["S0"]==pytest.approx(.2)
    assert result["target_weights"]["S1"]>=.2-1e-6


def test_constraint_conflict_returns_infeasible(db_portfolio):
    db,portfolio=db_portfolio;positions=_positions([600,100,100,100,100],["Tech","Health","Industry","Energy","Utility"]);symbols=[p["symbol"] for p in positions]
    constraints=OptimizationConstraints(max_position_weight=.3,max_sector_weight=.5,max_turnover=.5,locked_symbols=["S0"])
    result=calculate_optimization(db,portfolio,OptimizationRequest(constraints=constraints),positions_override=positions,returns_override=_returns(symbols),expected_override={s:.07 for s in symbols})
    assert result["status"]=="infeasible"
    assert any("锁定" in issue for issue in result["constraint_conflicts"])


def test_integer_share_rounding_returns_cash_error(db_portfolio):
    db,portfolio=db_portfolio;positions=_positions([200]*5,["A","B","C","D","E"]);symbols=[p["symbol"] for p in positions]
    constraints=OptimizationConstraints(max_position_weight=.35,max_sector_weight=.5,max_turnover=.7,fractional_shares=False,minimum_trade_amount=0)
    result=calculate_optimization(db,portfolio,OptimizationRequest(objective="maximum_sharpe",constraints=constraints),positions_override=positions,returns_override=_returns(symbols),expected_override={s:.04+i*.02 for i,s in enumerate(symbols)})
    assert result["status"]=="completed"
    assert all(row["fractional_share_change"] is None or float(row["fractional_share_change"]).is_integer() for row in result["suggested_trades"])
    assert "rounding_cash" in result


def test_highly_concentrated_technology_portfolio_can_de_risk_with_cash(db_portfolio):
    db,portfolio=db_portfolio;positions=_positions([600,100,100,100,100],["Technology"]*5);symbols=[p["symbol"] for p in positions]
    constraints=OptimizationConstraints(max_position_weight=.2,max_sector_weight=.6,min_cash_weight=.4,max_cash_weight=.5,max_turnover=.5)
    result=calculate_optimization(db,portfolio,OptimizationRequest(objective="stable",constraints=constraints),positions_override=positions,returns_override=_returns(symbols),expected_override={s:.07 for s in symbols})
    assert result["status"]=="completed"
    assert result["cash_weight"]==pytest.approx(.4)
    assert sum(result["target_weights"].values())==pytest.approx(.6)
