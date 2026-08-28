from __future__ import annotations

from datetime import UTC, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ExecutionKillSwitch, ExecutionOrder, ExecutionTestAccount, RiskPolicyVersion
from app.services.execution.common import TEST_ENVIRONMENT, canonical_hash, now_utc


class RiskRejected(ValueError):
    """Deterministic fail-closed risk decision."""


_ALIASES = {
    "deployment_allowlist": "allowed_deployment_ids",
    "instrument_allowlist": "allowed_instrument_ids",
    "max_signal_age": "stale_signal_seconds",
    "max_signal_age_seconds": "stale_signal_seconds",
    "max_signal_staleness": "stale_signal_seconds",
    "max_signal_staleness_seconds": "stale_signal_seconds",
    "max_order_notional": "max_order_notional_usdt",
    "max_gross_notional": "max_gross_notional_usdt",
    "max_net_notional": "max_net_notional_usdt",
    "max_daily_loss": "max_daily_loss_usdt",
    "max_drawdown": "max_drawdown_usdt",
    "max_funding_rate": "max_funding_rate_abs",
}

_REQUIRED_LIMITS = (
    "capital_allocation_usdt",
    "max_order_notional_usdt",
    "max_gross_notional_usdt",
    "max_net_notional_usdt",
    "max_leverage",
    "max_daily_loss_usdt",
    "max_drawdown_usdt",
    "max_open_orders",
    "cooldown_seconds",
    "stale_signal_seconds",
    "stale_account_seconds",
    "max_funding_rate_abs",
    "max_volatility",
    "allowed_symbols",
    "allowed_deployment_ids",
    "allowed_instrument_ids",
)


def _limit(limits: dict[str, Any], name: str, default: Any = None) -> Any:
    if name in limits:
        return limits[name]
    for alias, canonical in _ALIASES.items():
        if canonical == name and alias in limits:
            return limits[alias]
    return default


def normalize_limits(limits: dict[str, Any], *, require_complete: bool = False) -> dict[str, Any]:
    """Normalize accepted aliases and validate a bounded TEST policy schema."""

    if not isinstance(limits, dict):
        raise ValueError("risk policy limits 必须为对象")
    normalized = dict(limits)
    for alias, canonical in _ALIASES.items():
        if canonical not in normalized and alias in normalized:
            normalized[canonical] = normalized[alias]
    missing = [key for key in _REQUIRED_LIMITS if key not in normalized]
    if require_complete and missing:
        raise ValueError(f"risk policy 缺少必要限制: {', '.join(missing)}")

    for key in ("allowed_deployment_ids", "allowed_instrument_ids"):
        if key in normalized:
            values = normalized[key]
            if not isinstance(values, list) or not values or any(not isinstance(item, int) or item <= 0 for item in values):
                raise ValueError(f"{key} 必须为非空正整数数组")
            normalized[key] = sorted(set(values))
    if "allowed_symbols" in normalized:
        symbols = normalized["allowed_symbols"]
        if not isinstance(symbols, list) or not symbols or any(not isinstance(item, str) or not item.strip() for item in symbols):
            raise ValueError("allowed_symbols 必须为非空字符串数组")
        normalized["allowed_symbols"] = sorted({item.strip().upper() for item in symbols})

    numeric_keys = {
        "capital_allocation_usdt", "max_order_notional_usdt", "max_gross_notional_usdt",
        "max_net_notional_usdt", "max_leverage", "max_daily_loss_usdt", "max_drawdown_usdt",
        "cooldown_seconds", "stale_signal_seconds", "stale_account_seconds",
        "max_funding_rate_abs", "max_volatility",
    }
    values: dict[str, Decimal] = {}
    for key in numeric_keys:
        if key not in normalized:
            continue
        try:
            value = Decimal(str(normalized[key]))
        except Exception as exc:
            raise ValueError(f"{key} 必须为有限数值") from exc
        if not value.is_finite() or value < 0:
            raise ValueError(f"{key} 必须为非负数")
        values[key] = value
    if "max_open_orders" in normalized:
        try:
            open_orders = int(normalized["max_open_orders"])
        except (TypeError, ValueError) as exc:
            raise ValueError("max_open_orders 必须为正整数") from exc
        if open_orders < 1:
            raise ValueError("max_open_orders 必须为正整数")
        normalized["max_open_orders"] = open_orders
    for key in (
        "capital_allocation_usdt", "max_order_notional_usdt", "max_gross_notional_usdt",
        "max_net_notional_usdt", "max_leverage", "max_daily_loss_usdt", "max_drawdown_usdt",
        "stale_signal_seconds", "stale_account_seconds", "max_funding_rate_abs", "max_volatility",
    ):
        if key in values and values[key] <= 0:
            raise ValueError(f"{key} 必须为正数")
    if "cooldown_seconds" in values:
        normalized["cooldown_seconds"] = int(values["cooldown_seconds"])
    for key, value in values.items():
        if key != "cooldown_seconds":
            normalized[key] = str(value)

    # Hard ceilings prevent an accidentally complete policy from being a
    # disguised live-sized limit.
    if all(key in values for key in ("max_order_notional_usdt", "capital_allocation_usdt")) and values["max_order_notional_usdt"] > values["capital_allocation_usdt"]:
        raise ValueError("单笔限额不能超过 capital_allocation_usdt")
    if all(key in values for key in ("max_gross_notional_usdt", "capital_allocation_usdt")) and values["max_gross_notional_usdt"] > values["capital_allocation_usdt"] * Decimal("10"):
        raise ValueError("总敞口限额超出安全上限")
    if all(key in values for key in ("max_net_notional_usdt", "max_gross_notional_usdt")) and values["max_net_notional_usdt"] > values["max_gross_notional_usdt"]:
        raise ValueError("净敞口限额不能超过总敞口限额")
    if "max_leverage" in values and values["max_leverage"] > Decimal("3"):
        raise ValueError("TEST max_leverage 不能超过 3")
    if "max_daily_loss_usdt" in values and "capital_allocation_usdt" in values and values["max_daily_loss_usdt"] > values["capital_allocation_usdt"]:
        raise ValueError("每日亏损限额不能超过资金分配")
    if "max_drawdown_usdt" in values and "capital_allocation_usdt" in values and values["max_drawdown_usdt"] > values["capital_allocation_usdt"]:
        raise ValueError("回撤限额不能超过资金分配")
    if "stale_signal_seconds" in values and values["stale_signal_seconds"] > Decimal("86400"):
        raise ValueError("stale_signal_seconds 超出上限")
    if "stale_account_seconds" in values and values["stale_account_seconds"] > Decimal("86400"):
        raise ValueError("stale_account_seconds 超出上限")
    if "max_funding_rate_abs" in values and values["max_funding_rate_abs"] > Decimal("1"):
        raise ValueError("max_funding_rate_abs 超出上限")
    if "max_volatility" in values and values["max_volatility"] > Decimal("10"):
        raise ValueError("max_volatility 超出上限")
    return normalized


def active_policy(db: Session, account_id: int, *, now=None) -> RiskPolicyVersion | None:
    moment = now or now_utc()
    return db.scalar(
        select(RiskPolicyVersion)
        .where(
            RiskPolicyVersion.account_id == account_id,
            RiskPolicyVersion.environment == TEST_ENVIRONMENT,
            RiskPolicyVersion.status == "active",
            or_(RiskPolicyVersion.effective_at.is_(None), RiskPolicyVersion.effective_at <= moment),
        )
        .order_by(RiskPolicyVersion.version.desc())
        .limit(1)
    )


def create_policy(
    db: Session,
    *,
    account_id: int,
    created_by: int,
    limits: dict[str, Any],
    activate: bool = True,
) -> RiskPolicyVersion:
    account = db.get(ExecutionTestAccount, account_id)
    if account is None or account.environment != TEST_ENVIRONMENT:
        raise ValueError("TEST account 不存在")
    limits = normalize_limits(limits, require_complete=activate)
    latest = db.scalar(
        select(RiskPolicyVersion)
        .where(RiskPolicyVersion.account_id == account_id, RiskPolicyVersion.environment == TEST_ENVIRONMENT)
        .order_by(RiskPolicyVersion.version.desc())
        .limit(1)
    )
    version = (latest.version + 1) if latest else 1
    if activate:
        db.execute(
            update(RiskPolicyVersion)
            .where(
                RiskPolicyVersion.account_id == account_id,
                RiskPolicyVersion.environment == TEST_ENVIRONMENT,
                RiskPolicyVersion.status == "active",
            )
            .values(status="retired")
        )
    policy = RiskPolicyVersion(
        account_id=account_id,
        created_by=created_by,
        approved_by=created_by if activate else None,
        environment=TEST_ENVIRONMENT,
        version=version,
        status="active" if activate else "draft",
        policy_hash=canonical_hash(limits),
        limits=limits,
        effective_at=now_utc() if activate else None,
    )
    db.add(policy)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ValueError("risk policy 版本冲突") from exc
    return policy


def is_killed(
    db: Session,
    *,
    account_id: int | None = None,
    agent_id: int | None = None,
    deployment_id: int | None = None,
    instrument_id: int | None = None,
) -> tuple[bool, str | None]:
    scopes: list[tuple[str, int]] = [("global", 0)]
    if account_id is not None:
        scopes.append(("account", account_id))
    if agent_id is not None:
        scopes.append(("agent", agent_id))
    if deployment_id is not None:
        scopes.append(("deployment", deployment_id))
    if instrument_id is not None:
        scopes.append(("instrument", instrument_id))
    for scope_type, scope_id in scopes:
        row = db.scalar(
            select(ExecutionKillSwitch).where(
                ExecutionKillSwitch.environment == TEST_ENVIRONMENT,
                ExecutionKillSwitch.scope_type == scope_type,
                ExecutionKillSwitch.scope_id == scope_id,
                ExecutionKillSwitch.enabled.is_(True),
            )
        )
        if row is not None:
            return True, row.reason or f"{scope_type}_kill_switch"
    return False, None


def set_kill_switch(
    db: Session,
    *,
    scope_type: str,
    scope_id: int | None,
    enabled: bool,
    reason: str | None,
    changed_by: int,
) -> ExecutionKillSwitch:
    if scope_type not in {"global", "account", "agent", "deployment", "instrument"}:
        raise ValueError("kill switch scope 无效")
    if scope_type == "global":
        scope_id = 0
    elif scope_id is None or scope_id <= 0:
        raise ValueError("非 global scope 必须提供 scope_id")
    row = db.scalar(
        select(ExecutionKillSwitch).where(
            ExecutionKillSwitch.environment == TEST_ENVIRONMENT,
            ExecutionKillSwitch.scope_type == scope_type,
            ExecutionKillSwitch.scope_id == scope_id,
        )
    )
    if row is None:
        row = ExecutionKillSwitch(
            scope_type=scope_type,
            scope_id=scope_id,
            environment=TEST_ENVIRONMENT,
            enabled=bool(enabled),
            reason=reason,
            changed_by=changed_by,
        )
        db.add(row)
    else:
        row.enabled = bool(enabled)
        row.reason = reason
        row.changed_by = changed_by
        row.changed_at = now_utc()
    db.flush()
    return row


def _scope_allowed(limits: dict[str, Any], key: str, value: int) -> bool:
    allowlist = _limit(limits, key)
    return bool(allowlist) and value in allowlist


def policy_allowed(
    db: Session,
    account: ExecutionTestAccount,
    *,
    agent_id: int | None = None,
    deployment_id: int | None = None,
    instrument_id: int | None = None,
    symbol: str | None = None,
    signal_generated_at=None,
    signal_expires_at=None,
    now=None,
) -> tuple[bool, str | None]:
    moment = now or now_utc()
    if account.environment != TEST_ENVIRONMENT or account.status != "active":
        return False, "account_not_active"
    killed, reason = is_killed(
        db,
        account_id=account.id,
        agent_id=agent_id,
        deployment_id=deployment_id,
        instrument_id=instrument_id,
    )
    if killed:
        return False, reason
    policy = active_policy(db, account.id, now=moment)
    if policy is None:
        return False, "missing_active_policy"
    limits = policy.limits or {}
    if deployment_id is None or not _scope_allowed(limits, "allowed_deployment_ids", deployment_id):
        return False, "deployment_not_allowlisted"
    if instrument_id is None or not _scope_allowed(limits, "allowed_instrument_ids", instrument_id):
        return False, "instrument_not_allowlisted"
    symbols = _limit(limits, "allowed_symbols", [])
    if symbol is None or not symbols or symbol.upper() not in {str(value).upper() for value in symbols}:
        return False, "symbol_not_allowlisted"
    stale_signal = _limit(limits, "stale_signal_seconds")
    if signal_generated_at is not None and stale_signal is not None:
        generated = signal_generated_at if signal_generated_at.tzinfo else signal_generated_at.replace(tzinfo=moment.tzinfo)
        if (moment - generated).total_seconds() > float(stale_signal):
            return False, "signal_stale"
    if signal_expires_at is not None:
        expires = signal_expires_at if signal_expires_at.tzinfo else signal_expires_at.replace(tzinfo=moment.tzinfo)
        if expires <= moment:
            return False, "signal_expired"
    return True, None


def validate_order_risk(
    db: Session,
    account: ExecutionTestAccount,
    *,
    agent_id: int | None,
    deployment_id: int | None,
    instrument_id: int,
    side: str,
    quantity: Decimal,
    price: Decimal | None,
    symbol: str | None = None,
    now=None,
) -> tuple[bool, str | None]:
    """Apply persisted limits and fail closed when a configured input is absent."""

    allowed, reason = policy_allowed(
        db,
        account,
        agent_id=agent_id,
        deployment_id=deployment_id,
        instrument_id=instrument_id,
        symbol=symbol,
        now=now,
    )
    if not allowed:
        return False, reason
    policy = active_policy(db, account.id, now=now)
    assert policy is not None
    limits = policy.limits or {}
    notional = None if price is None else abs(quantity * price)
    ceiling = _limit(limits, "max_order_notional_usdt")
    if ceiling is not None:
        if notional is None:
            return False, "max_order_notional_usdt_price_required"
        if notional > Decimal(str(ceiling)):
            return False, "max_order_notional_usdt_exceeded"
    max_leverage = _limit(limits, "max_leverage")
    if max_leverage is not None:
        if notional is None:
            return False, "max_leverage_price_required"
        if notional > abs(Decimal(str(account.initial_capital))) * Decimal(str(max_leverage)):
            return False, "max_leverage_exceeded"
    max_open = _limit(limits, "max_open_orders")
    if max_open is not None:
        open_count = db.query(ExecutionOrder).filter(
            ExecutionOrder.account_id == account.id,
            ExecutionOrder.status.in_(["created", "submitted", "partially_filled", "cancel_requested", "unknown"]),
        ).count()
        if open_count >= int(max_open):
            return False, "max_open_orders_exceeded"
    cooldown = _limit(limits, "cooldown_seconds")
    if cooldown:
        latest = db.scalar(
            select(ExecutionOrder.created_at)
            .where(ExecutionOrder.account_id == account.id)
            .order_by(ExecutionOrder.created_at.desc())
            .limit(1)
        )
        if latest is not None:
            latest_utc = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
            if (now_utc() - latest_utc).total_seconds() < float(cooldown):
                return False, "cooldown_active"
    return True, None
