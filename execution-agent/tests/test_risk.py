from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from execution_agent.risk import AccountSnapshot, MarketSnapshot, SymbolFilters, evaluate_order
from execution_agent.wire import Lease, RiskPolicy


def _lease(*, target="1", now=None, limits=None) -> Lease:
    current = now or datetime.now(UTC)
    limits = limits or {
        "capital_allocation_usdt": "1000",
        "allowed_symbols": ["BTCUSDT"],
        "allowed_deployment_ids": [1],
        "allowed_instrument_ids": [1],
        "max_order_notional_usdt": "1000",
        "max_gross_notional_usdt": "2000",
        "max_net_notional_usdt": "2000",
        "max_leverage": "2",
        "max_daily_loss_usdt": "100",
        "max_drawdown_usdt": "200",
        "max_open_orders": 3,
        "cooldown_seconds": 0,
        "stale_signal_seconds": 300,
        "stale_account_seconds": 60,
    }
    raw = {"version": "p1", "limits": limits}
    policy = RiskPolicy.from_payload(raw)
    payload = {
        "wire_version": "execution-agent.v1",
        "lease_id": "lease-1",
        "signal_id": "signal-1",
        "account_id": "acct-1",
        "environment": "test",
        "venue": "binance_usdm",
        "symbol": "BTCUSDT",
        "deployment_id": 1,
        "instrument_id": 1,
        "target_exposure": target,
        "issued_at": current.isoformat(),
        "signal_time": current.isoformat(),
        "expires_at": (current + timedelta(minutes=5)).isoformat(),
        "policy_hash": policy.computed_hash,
        "policy": raw,
    }
    return Lease.from_payload(payload)


def _account(**overrides) -> AccountSnapshot:
    values = dict(
        available_balance_usdt=Decimal("5000"), equity_usdt=Decimal("5000"),
        gross_notional_usdt=Decimal("0"), net_notional_usdt=Decimal("0"),
        positions={}, open_orders=0, as_of=datetime.now(UTC), daily_loss_usdt=Decimal("0"),
        drawdown_usdt=Decimal("0"),
    )
    values.update(overrides)
    return AccountSnapshot(**values)


def test_risk_approves_target_and_rounds_step() -> None:
    lease = _lease()
    result = evaluate_order(
        lease,
        account=_account(),
        market=MarketSnapshot("BTCUSDT", Decimal("100"), datetime.now(UTC)),
        filters=SymbolFilters(Decimal("0.1"), Decimal("0.1"), min_notional=Decimal("5")),
    )
    assert result.approved
    assert result.plan and result.plan.quantity == Decimal("10")


def test_reduction_at_gross_limit_is_allowed() -> None:
    lease = _lease(target="0")
    result = evaluate_order(
        lease,
        account=_account(
            gross_notional_usdt=Decimal("1000"), net_notional_usdt=Decimal("1000"),
            positions={"BTCUSDT": Decimal("10")},
        ),
        market=MarketSnapshot("BTCUSDT", Decimal("100"), datetime.now(UTC)),
        filters=SymbolFilters(Decimal("0.1"), Decimal("0.1"), min_notional=Decimal("5")),
    )
    assert result.approved and result.plan and result.plan.side == "SELL"


def test_missing_data_and_limits_fail_closed() -> None:
    lease = _lease()
    market = MarketSnapshot("BTCUSDT", Decimal("100"), datetime.now(UTC))
    filters = SymbolFilters(Decimal("0.1"), Decimal("0.1"))
    assert evaluate_order(lease, account=None, market=market, filters=filters).reason == "missing_account"
    assert evaluate_order(lease, account=_account(daily_loss_usdt=Decimal("101")), market=market, filters=filters).reason == "daily_loss_limit"
    assert evaluate_order(lease, account=_account(), market=market, filters=filters).approved
