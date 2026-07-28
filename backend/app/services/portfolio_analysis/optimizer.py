from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioAnalysisRun

from .data_loader import load_joint_returns
from .expected_return import calculate_expected_return
from .optimization_constraints import audit_constraints, project_weights
from .optimization_models import OBJECTIVE_MAP, raw_target, scipy_target
from .risk_metrics import covariance_matrix, drawdown_details, historical_var_cvar, risk_contributions
from .schemas import ExpectedReturnRequest, OptimizationRequest
from .service import _finite_json, _position_snapshot
from .stress_test import calculate_stress_test
from .schemas import StressTestRequest
from .trade_plan import build_trade_plan


MODEL_VERSION="portfolio-optimizer-v1.0"


OPTIMIZATION_PRESETS={
    "stable":{"label":"更稳健","objective":"minimum_cvar","description":"优先降低尾部风险与波动。","constraints":{"max_position_weight":.15,"max_sector_weight":.30,"max_turnover":.25,"min_cash_weight":.05}},
    "balanced":{"label":"均衡优化","objective":"risk_parity","description":"以风险平价作为 Black-Litterman 预留边界的当前实现。","constraints":{"max_position_weight":.20,"max_sector_weight":.35,"max_turnover":.25,"min_cash_weight":.03}},
    "aggressive":{"label":"进取优化","objective":"maximum_sharpe","description":"使用融合预期收益最大化风险调整回报，并保留严格仓位约束。","constraints":{"max_position_weight":.25,"max_sector_weight":.40,"max_turnover":.30,"min_cash_weight":0}},
}


def optimization_presets()->dict:return {"presets":OPTIMIZATION_PRESETS,"objectives":["minimum_variance","maximum_sharpe","target_return","risk_parity","maximum_diversification","minimum_cvar"],"black_litterman_status":"reserved"}


def _metrics(returns: pd.DataFrame, weights: np.ndarray, expected: np.ndarray, covariance: np.ndarray, sectors: list[str], cash: float)->dict:
    series=returns.to_numpy()@weights
    annual_return=float(expected@weights+.04*cash);vol=float(np.sqrt(max(weights@covariance@weights,0))*np.sqrt(252));var,cvar=historical_var_cvar(pd.Series(series),.95);drawdown=drawdown_details(pd.Series(series,index=returns.index))
    sector_weights=defaultdict(float)
    for sector,weight in zip(sectors,weights):sector_weights[sector]+=float(weight)
    return {"expected_annual_return":annual_return,"annual_volatility":vol,"sharpe_ratio":(annual_return-.04)/vol if vol else None,"max_drawdown_estimate":drawdown["value"],"var_95":var,"cvar_95":cvar,"largest_position_weight":float(max(weights,default=0)),"largest_sector_weight":max(sector_weights.values(),default=0),"hhi":float(np.square(weights).sum()+cash**2),"cash_weight":cash}


def calculate_optimization(db:Session,portfolio:Portfolio,request:OptimizationRequest,*,positions_override:list[dict]|None=None,returns_override:pd.DataFrame|None=None,expected_override:dict[str,float]|None=None,include_stress_comparison:bool=False)->dict:
    positions,warnings=(positions_override,[]) if positions_override is not None else _position_snapshot(db,portfolio);total=sum(float(p["market_value"]) for p in positions)
    if not positions or total<=0:return {"status":"insufficient_data","message":"当前组合没有可估值持仓","constraint_conflicts":[],"warnings":warnings}
    symbols=[p["symbol"] for p in positions];sectors=[p.get("sector") or "未分类" for p in positions];current=np.array([float(p["market_value"])/total for p in positions])
    if returns_override is None:
        loaded=load_joint_returns(db,symbols,dict(zip(symbols,current)),mode="common_start");returns=loaded.returns.dropna(how="any");warnings.extend(loaded.warnings)
    else:returns=returns_override[symbols].dropna(how="any")
    if len(returns)<60:return {"status":"insufficient_data","message":"联合历史行情不足，无法构造鲁棒协方差矩阵","constraint_conflicts":[],"warnings":warnings}
    if expected_override is None:
        expected_result=calculate_expected_return(db,portfolio,ExpectedReturnRequest(portfolio_id=portfolio.id),positions_override=positions);expected_map={r["symbol"]:r["base"] for r in expected_result.get("assets",[])}
    else:expected_map=expected_override
    expected=np.array([expected_map.get(s,.06) for s in symbols]);daily_cov=covariance_matrix(returns,request.covariance_method).to_numpy();candidate=scipy_target(request.objective,expected,daily_cov*252,returns.to_numpy(),current,sectors,symbols,request.constraints,request.target_return)
    if candidate is None:candidate=raw_target(request.objective,expected,daily_cov,returns.to_numpy())
    projected,cash,conflicts=project_weights(candidate,symbols,current,sectors,request.constraints)
    if projected is None:return {"status":"infeasible","message":"当前目标与仓位约束无法同时满足","constraint_conflicts":conflicts,"warnings":warnings}
    if request.objective=="target_return" and request.target_return is not None and float(expected@projected+.04*cash)<request.target_return-1e-6:
        return {"status":"infeasible","message":"目标收益在当前仓位和换手限制下不可达","constraint_conflicts":["target_return","max_position_weight/max_turnover"],"warnings":warnings}
    audit=audit_constraints(projected,cash,symbols,current,sectors,request.constraints)
    if audit:return {"status":"infeasible","message":"优化结果未通过约束审计","constraint_conflicts":audit,"warnings":warnings}
    target=dict(zip(symbols,map(float,projected)));trades,rounding_cash=build_trade_plan(positions,target,total,fractional_shares=request.constraints.fractional_shares,minimum_trade_amount=request.constraints.minimum_trade_amount)
    current_metrics=_metrics(returns,current,expected,daily_cov,sectors,0);optimized_metrics=_metrics(returns,projected,expected,daily_cov,sectors,cash)
    turnover=.5*(np.abs(projected-current).sum()+cash)
    stress_comparison=[]
    # Reuse the same deterministic stage-two scenarios for before/after.
    if include_stress_comparison:
        optimized_positions=[{**p,"market_value":total*target[p["symbol"]]} for p in positions]
        for code in ("growth_repricing","semiconductor_drop","recession","inflation_rebound"):
            payload=StressTestRequest(portfolio_id=portfolio.id,scenario_code=code,mode="proxy_scenario",use_fundamental_modifiers=True)
            before=calculate_stress_test(db,portfolio,payload,positions_override=positions);after=calculate_stress_test(db,portfolio,payload,positions_override=optimized_positions)
            stress_comparison.append({"scenario_code":code,"current_return":before.get("estimated_portfolio_return"),"optimized_return":after.get("estimated_portfolio_return")})
    status="completed";optimization_warnings=list(warnings)
    if request.constraints.allow_new_symbols and request.constraints.only_current_positions:
        optimization_warnings.append("已请求允许新增证券，但当前未提供候选池；本次仅优化当前持仓")
    if max(projected,default=0)>.4:optimization_warnings.append("目标仓位超过 40%，请检查约束配置")
    covariance_frame=pd.DataFrame(daily_cov,index=symbols,columns=symbols)
    current_risk=risk_contributions(covariance_frame,pd.Series(current,index=symbols));optimized_risk=risk_contributions(covariance_frame,pd.Series(projected,index=symbols))
    return _finite_json({"status":status,"objective":OBJECTIVE_MAP.get(request.objective,request.objective),"portfolio_value":total,"current_metrics":current_metrics,"optimized_metrics":optimized_metrics,"target_weights":target,"cash_weight":cash,"weight_changes":[{"symbol":s,"current_weight":float(c),"target_weight":float(t),"change":float(t-c),"sector":sector} for s,c,t,sector in zip(symbols,current,projected,sectors)],"risk_contribution_changes":[{"symbol":s,"current":current_risk[i]["risk_contribution"],"optimized":optimized_risk[i]["risk_contribution"]} for i,s in enumerate(symbols)],"suggested_trades":trades,"rounding_cash":rounding_cash,"turnover":float(turnover),"estimated_trade_count":sum(r["action"]!="hold" for r in trades),"estimated_trade_amount":sum(abs(r["trade_amount"]) for r in trades),"constraint_satisfaction":{"satisfied":True,"issues":[]},"stress_comparison":stress_comparison,"assumptions":{"expected_return_model":"expected-return-blend-v1.0","covariance_model":request.covariance_method,"numeric_engine":"python","black_litterman":"reserved_not_active"},"warnings":optimization_warnings,"model_version":MODEL_VERSION})


def persist_optimization(db:Session,portfolio:Portfolio,request:OptimizationRequest,result:dict)->PortfolioAnalysisRun:
    run=PortfolioAnalysisRun(portfolio_id=portfolio.id,analysis_type="optimization",status="completed",input_snapshot_json=request.model_dump(mode="json"),assumptions_json=result.get("assumptions",{}),result_json=result,model_version=MODEL_VERSION,completed_at=datetime.now(UTC));db.add(run);db.commit();db.refresh(run);return run
