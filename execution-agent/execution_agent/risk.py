from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Mapping

from .wire import Lease, RiskPolicy


def _d(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


@dataclass(frozen=True)
class SymbolFilters:
    step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None = None
    min_notional: Decimal | None = None

    def validate(self) -> bool:
        return self.step_size > 0 and self.min_quantity > 0 and (self.max_quantity is None or self.max_quantity > 0)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: Decimal | None
    as_of: datetime
    funding_rate: Decimal | None = None
    volatility: Decimal | None = None
    evidence_as_of: datetime | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    available_balance_usdt: Decimal | None
    equity_usdt: Decimal | None
    gross_notional_usdt: Decimal | None
    net_notional_usdt: Decimal | None
    positions: Mapping[str, Decimal]
    open_orders: int | None
    as_of: datetime
    daily_loss_usdt: Decimal | None = None
    drawdown_usdt: Decimal | None = None
    last_order_at: datetime | None = None


@dataclass(frozen=True)
class OrderPlan:
    symbol: str
    side: str
    quantity: Decimal
    notional_usdt: Decimal
    desired_quantity: Decimal
    current_quantity: Decimal


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    plan: OrderPlan | None = None
    details: Mapping[str, object] = field(default_factory=dict)


def _missing_policy(policy: RiskPolicy) -> list[str]:
    required = {
        "capital_allocation_usdt": policy.capital_allocation_usdt,
        "max_order_notional_usdt": policy.max_order_notional_usdt,
        "max_gross_notional_usdt": policy.max_gross_notional_usdt,
        "max_net_notional_usdt": policy.max_net_notional_usdt,
        "max_leverage": policy.max_leverage,
        "max_daily_loss_usdt": policy.max_daily_loss_usdt,
        "max_drawdown_usdt": policy.max_drawdown_usdt,
        "max_open_orders": policy.max_open_orders,
        "cooldown_seconds": policy.cooldown_seconds,
        "stale_signal_seconds": policy.stale_signal_seconds,
        "stale_account_seconds": policy.stale_account_seconds,
    }
    missing = [name for name, value in required.items() if value is None]
    if not policy.allowed_symbols:
        missing.append("allowed_symbols")
    if not policy.allowed_deployment_ids:
        missing.append("allowed_deployment_ids")
    if not policy.allowed_instrument_ids:
        missing.append("allowed_instrument_ids")
    return missing


def round_quantity(quantity: Decimal, step_size: Decimal) -> Decimal:
    if quantity <= 0 or step_size <= 0:
        return Decimal("0")
    units = (quantity / step_size).to_integral_value(rounding=ROUND_DOWN)
    return units * step_size


def _reject(reason: str, **details: object) -> RiskDecision:
    return RiskDecision(False, reason, details=details)


def evaluate_order(
    lease: Lease,
    *,
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    filters: SymbolFilters | None,
    now: datetime | None = None,
) -> RiskDecision:
    """Apply the local same-or-stricter TEST policy before an order call."""

    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    policy = lease.policy
    missing = _missing_policy(policy)
    if missing:
        return _reject("missing_policy", fields=missing)
    if lease.environment != "test" or lease.venue != "binance_usdm":
        return _reject("wrong_environment")
    if lease.expires_at <= current_time:
        return _reject("stale_signal", detail="lease_expired")
    signal_time = lease.signal_time or lease.issued_at
    stale_signal = (current_time - signal_time).total_seconds()
    if stale_signal > int(policy.stale_signal_seconds or 0):
        return _reject("stale_signal", age_seconds=stale_signal)
    if account is None:
        return _reject("missing_account")
    if market is None or market.price is None or market.price <= 0:
        return _reject("missing_market")
    if market.symbol.upper() != lease.symbol.upper():
        return _reject("instrument_mismatch")
    market_age = (current_time - market.as_of.astimezone(UTC)).total_seconds()
    if market_age > int(policy.stale_account_seconds or 0) or market_age < -60:
        return _reject("stale_market", age_seconds=market_age)
    if filters is None or not filters.validate():
        return _reject("missing_exchange_filters")
    account_age = (current_time - account.as_of.astimezone(UTC)).total_seconds()
    if account_age > int(policy.stale_account_seconds or 0) or account_age < -60:
        return _reject("stale_account", age_seconds=account_age)
    if policy.allowed_symbols and lease.symbol.upper() not in policy.allowed_symbols:
        return _reject("symbol_not_allowed")
    if account.available_balance_usdt is None or account.equity_usdt is None:
        return _reject("missing_account_balance")
    if account.open_orders is None:
        return _reject("missing_open_orders")
    if account.open_orders >= int(policy.max_open_orders or 0):
        return _reject("max_open_orders")
    if account.daily_loss_usdt is None:
        return _reject("missing_daily_loss")
    if account.drawdown_usdt is None:
        return _reject("missing_drawdown")
    if account.gross_notional_usdt is None or account.net_notional_usdt is None:
        return _reject("missing_exposure")
    if policy.max_funding_rate_abs is not None:
        if market.funding_rate is None:
            return _reject("missing_funding")
        if market.evidence_as_of is None or (current_time - market.evidence_as_of.astimezone(UTC)).total_seconds() > int(policy.stale_signal_seconds or 0):
            return _reject("stale_market_evidence")
        if abs(market.funding_rate) > policy.max_funding_rate_abs:
            return _reject("funding_limit")
    if policy.max_volatility is not None:
        if market.volatility is None:
            return _reject("missing_volatility")
        if market.evidence_as_of is None or (current_time - market.evidence_as_of.astimezone(UTC)).total_seconds() > int(policy.stale_signal_seconds or 0):
            return _reject("stale_market_evidence")
        if abs(market.volatility) > policy.max_volatility:
            return _reject("volatility_limit")
    if account.daily_loss_usdt > policy.max_daily_loss_usdt:
        return _reject("daily_loss_limit")
    if account.drawdown_usdt > policy.max_drawdown_usdt:
        return _reject("drawdown_limit")
    if account.last_order_at is not None:
        cooldown_age = (current_time - account.last_order_at.astimezone(UTC)).total_seconds()
        if cooldown_age < int(policy.cooldown_seconds or 0):
            return _reject("cooldown", remaining_seconds=int(policy.cooldown_seconds or 0) - cooldown_age)

    price = market.price
    current_quantity = _d(account.positions.get(lease.symbol.upper(), Decimal("0"))) or Decimal("0")
    desired_quantity = policy.capital_allocation_usdt * lease.target_exposure / price
    delta = desired_quantity - current_quantity
    if delta == 0:
        return RiskDecision(True, "no_order_needed", plan=None)
    quantity = round_quantity(abs(delta), filters.step_size)
    if quantity <= 0:
        return _reject("quantity_below_step")
    if filters.max_quantity is not None and quantity > filters.max_quantity:
        return _reject("quantity_above_exchange_max")
    notional = quantity * price
    if quantity < filters.min_quantity:
        return _reject("quantity_below_exchange_min")
    if filters.min_notional is not None and notional < filters.min_notional:
        return _reject("notional_below_exchange_min")
    if notional > policy.max_order_notional_usdt:
        return _reject("max_order_notional", notional=str(notional))
    current_notional = abs(current_quantity * price)
    desired_notional = abs(desired_quantity * price)
    # Replacing the current position, rather than adding every order to gross,
    # lets a flattening/reducing order pass when already at a gross limit.
    gross_after = max(Decimal("0"), account.gross_notional_usdt - current_notional + desired_notional)
    net_after = account.net_notional_usdt - current_quantity * price + desired_quantity * price
    if gross_after > policy.max_gross_notional_usdt:
        return _reject("max_gross_notional", gross_after=str(gross_after))
    if abs(net_after) > policy.max_net_notional_usdt:
        return _reject("max_net_notional", net_after=str(net_after))
    if account.equity_usdt <= 0:
        return _reject("invalid_equity")
    if gross_after / account.equity_usdt > policy.max_leverage:
        return _reject("max_leverage", leverage=str(gross_after / account.equity_usdt))
    if notional > account.available_balance_usdt * policy.max_leverage:
        return _reject("insufficient_available_balance")
    return RiskDecision(
        True,
        "approved",
        plan=OrderPlan(
            symbol=lease.symbol,
            side="BUY" if delta > 0 else "SELL",
            quantity=quantity,
            notional_usdt=notional,
            desired_quantity=desired_quantity,
            current_quantity=current_quantity,
        ),
    )
