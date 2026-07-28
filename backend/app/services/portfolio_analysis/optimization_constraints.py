from __future__ import annotations

from collections import defaultdict

import numpy as np

from .schemas import OptimizationConstraints


def feasibility_conflicts(symbols: list[str], current: np.ndarray, sectors: list[str], constraints: OptimizationConstraints) -> list[str]:
    conflicts: list[str] = []
    known = set(symbols)
    for symbol in set(constraints.locked_symbols + constraints.do_not_sell_symbols + constraints.excluded_symbols) - known:
        conflicts.append(f"约束中的 {symbol} 不在当前持仓中")
    if set(constraints.locked_symbols) & set(constraints.excluded_symbols):
        conflicts.append("同一股票不能同时锁定和排除")
    if set(constraints.do_not_sell_symbols) & set(constraints.excluded_symbols):
        conflicts.append("同一股票不能同时禁止卖出和排除")
    if constraints.minimum_positions and constraints.minimum_positions > len(symbols) and not constraints.allow_new_symbols:
        conflicts.append("最低持仓数量超过当前可优化证券数量")
    locked = {s for s in constraints.locked_symbols}
    for index, symbol in enumerate(symbols):
        if symbol in locked and current[index] > constraints.max_position_weight + 1e-9:
            conflicts.append(f"{symbol} 已锁定但当前权重超过单股上限")
    sector_locked: dict[str, float] = defaultdict(float)
    for symbol, weight, sector in zip(symbols, current, sectors):
        if symbol in locked or symbol in constraints.do_not_sell_symbols:
            sector_locked[sector] += float(weight)
    for sector, weight in sector_locked.items():
        if weight > constraints.max_sector_weight + 1e-9:
            conflicts.append(f"{sector} 的锁定/禁止卖出权重已超过行业上限")
    required_cash_turnover = constraints.min_cash_weight
    if required_cash_turnover > constraints.max_turnover + 1e-9:
        conflicts.append("最低现金比例高于最大换手率可实现范围")
    available = sum(1 for symbol in symbols if symbol not in constraints.excluded_symbols)
    if available * constraints.max_position_weight + constraints.max_cash_weight < 1 - 1e-9:
        conflicts.append("单股上限与现金上限导致权重无法合计为 100%")
    return conflicts


def project_weights(candidate: np.ndarray, symbols: list[str], current: np.ndarray, sectors: list[str], constraints: OptimizationConstraints) -> tuple[np.ndarray | None, float, list[str]]:
    conflicts = feasibility_conflicts(symbols, current, sectors, constraints)
    if conflicts:
        return None, constraints.min_cash_weight, conflicts
    cash = constraints.min_cash_weight
    target_sum = 1 - cash
    lower = np.zeros(len(symbols)); upper = np.full(len(symbols), constraints.max_position_weight)
    for i, symbol in enumerate(symbols):
        if symbol in constraints.excluded_symbols: upper[i] = 0
        else: lower[i] = constraints.min_position_weight
        if symbol in constraints.locked_symbols: lower[i] = upper[i] = current[i]
        elif symbol in constraints.do_not_sell_symbols: lower[i] = current[i]
    if lower.sum() > target_sum + 1e-9 or upper.sum() < target_sum - 1e-9:
        return None, cash, ["锁定/禁止卖出/单股上限与现金比例导致权重无解"]
    values = np.clip(candidate, lower, upper)
    sector_indices = {sector: np.array([i for i, value in enumerate(sectors) if value == sector]) for sector in set(sectors)}
    for _ in range(100):
        for sector, indices in sector_indices.items():
            total = values[indices].sum()
            if total > constraints.max_sector_weight + 1e-10:
                removable = values[indices] - lower[indices]
                if removable.sum() <= 1e-12:
                    return None, cash, [f"{sector} 行业上限与锁定仓位冲突"]
                values[indices] -= removable * min(1, (total - constraints.max_sector_weight) / removable.sum())
        gap = target_sum - values.sum()
        if abs(gap) < 1e-9: break
        if gap > 0:
            capacity = upper - values
            for sector, indices in sector_indices.items():
                sector_room = max(0.0, constraints.max_sector_weight - values[indices].sum())
                if capacity[indices].sum() > sector_room:
                    capacity[indices] *= sector_room / max(capacity[indices].sum(), 1e-12)
            if capacity.sum() < gap - 1e-9:
                return None, cash, ["行业或单股上限导致剩余权重无法分配"]
            values += capacity * gap / capacity.sum()
        else:
            removable = values - lower
            if removable.sum() < -gap - 1e-9:
                return None, cash, ["锁定或禁止卖出约束导致权重无法降低"]
            values -= removable * (-gap) / removable.sum()
    # Enforce turnover by blending toward current, then re-project. If current
    # itself violates hard caps, the final audit below correctly returns infeasible.
    current_cash = 0.0
    turnover = .5 * (np.abs(values - current).sum() + abs(cash - current_cash))
    if turnover > constraints.max_turnover + 1e-9:
        factor = constraints.max_turnover / turnover if turnover else 1
        values = current + factor * (values - current)
        cash *= factor
        target_sum = 1 - cash
        gap = target_sum - values.sum()
        flexible = np.array([s not in constraints.locked_symbols and s not in constraints.excluded_symbols for s in symbols])
        if flexible.any(): values[flexible] += gap / flexible.sum()
        turnover = .5 * (np.abs(values - current).sum() + cash)
    audit = audit_constraints(values, cash, symbols, current, sectors, constraints)
    return (values, cash, []) if not audit else (None, cash, audit)


def audit_constraints(weights: np.ndarray, cash: float, symbols: list[str], current: np.ndarray, sectors: list[str], constraints: OptimizationConstraints) -> list[str]:
    issues=[]
    if abs(weights.sum()+cash-1)>1e-6: issues.append("权重之和不等于 100%")
    for i,symbol in enumerate(symbols):
        if weights[i] > constraints.max_position_weight+1e-6: issues.append(f"{symbol} 超过单股上限")
        if symbol in constraints.locked_symbols and abs(weights[i]-current[i])>1e-6: issues.append(f"{symbol} 锁定仓位发生变化")
        if symbol in constraints.do_not_sell_symbols and weights[i]<current[i]-1e-6: issues.append(f"{symbol} 禁止卖出约束未满足")
        if symbol in constraints.excluded_symbols and weights[i]>1e-6: issues.append(f"{symbol} 排除约束未满足")
    for sector in set(sectors):
        total=sum(weights[i] for i,value in enumerate(sectors) if value==sector)
        if total>constraints.max_sector_weight+1e-6: issues.append(f"{sector} 超过行业上限")
    turnover=.5*(np.abs(weights-current).sum()+cash)
    if turnover>constraints.max_turnover+1e-6: issues.append("超过最大换手率")
    if not constraints.min_cash_weight-1e-6<=cash<=constraints.max_cash_weight+1e-6: issues.append("现金比例越界")
    active=sum(weight>1e-8 for weight in weights)
    if constraints.minimum_positions and active<constraints.minimum_positions: issues.append("未满足最低持仓数量")
    if constraints.min_position_weight and any(1e-8<weight<constraints.min_position_weight-1e-6 for weight in weights): issues.append("存在低于最低仓位的非零持仓")
    return issues
