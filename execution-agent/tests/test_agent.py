from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from execution_agent.agent import ExecutionAgent
from execution_agent.config import AgentConfig
from execution_agent.errors import ExecutionBlocked
from execution_agent.journal import Journal
from execution_agent.risk import SymbolFilters
from execution_agent.security import KillSwitch
from execution_agent.wire import Lease, RiskPolicy


def make_lease(now: datetime | None = None) -> Lease:
    now = now or datetime.now(UTC)
    limits = {
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
    policy = RiskPolicy.from_payload({"version": "p1", "limits": limits})
    return Lease.from_payload(
        {
            "wire_version": "execution-agent.v1",
            "lease_id": "lease-1",
            "signal_id": "signal-1",
            "account_id": "acct-1",
            "environment": "test",
            "venue": "binance_usdm",
            "symbol": "BTCUSDT",
            "deployment_id": 1,
            "instrument_id": 1,
            "target_exposure": "1",
            "issued_at": now.isoformat(),
            "signal_time": now.isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "policy_hash": policy.computed_hash,
            "policy": {"version": "p1", "limits": limits},
        }
    )


class FakeControl:
    def __init__(self, lease=None):
        self.lease = lease
        self.events = []

    def get_lease(self):
        lease, self.lease = self.lease, None
        return lease

    def post_event(self, event):
        self.events.append(event.as_dict())

    def post_event_payload(self, payload, *, idempotency_key=None):
        self.events.append(dict(payload))


class FakeExchange:
    def __init__(self, *, accepted=True):
        self.accepted = accepted
        self.placed = []
        self.queried = []
        self._position = Decimal("0")

    def exchange_filters(self, symbol):
        return SymbolFilters(Decimal("0.1"), Decimal("0.1"), min_notional=Decimal("5"))

    def account_snapshot(self):
        from execution_agent.risk import AccountSnapshot
        return AccountSnapshot(
            available_balance_usdt=Decimal("5000"), equity_usdt=Decimal("5000"),
            gross_notional_usdt=abs(self._position * Decimal("100")), net_notional_usdt=self._position * Decimal("100"),
            positions={"BTCUSDT": self._position}, open_orders=0, as_of=datetime.now(UTC),
            daily_loss_usdt=Decimal("0"), drawdown_usdt=Decimal("0"),
        )

    def mark_price(self, symbol):
        return Decimal("100"), datetime.now(UTC).timestamp()

    def place_with_recovery(self, **kwargs):
        self.placed.append(kwargs)
        if not self.accepted:
            from execution_agent.errors import UnresolvedOrderError
            raise UnresolvedOrderError(kwargs["client_order_id"], "unknown")
        self._position = Decimal("10")
        return {"orderId": 1, "clientOrderId": kwargs["client_order_id"], "status": "FILLED", "executedQty": "10", "avgPrice": "100"}

    def user_trades(self, *, symbol, **kwargs):
        if not self.placed:
            return []
        return [{"id": 1, "clientOrderId": self.placed[-1]["client_order_id"], "symbol": symbol, "side": "BUY", "qty": "10", "price": "100"}]

    def query_order(self, **kwargs):
        self.queried.append(kwargs)
        return None

    def cancel_order(self, **kwargs):
        return {"clientOrderId": kwargs["client_order_id"], "status": "CANCELED", "executedQty": "0"}


def _agent(tmp_path, lease=None, exchange=None):
    root = tmp_path / "agent"
    root.mkdir(mode=0o700, exist_ok=True)
    config = AgentConfig(root, "http://testserver", "agent-1", "t" * 40, "k", "s")
    journal = Journal(root / "journal.sqlite3")
    return ExecutionAgent(config, FakeControl(lease), exchange or FakeExchange(), journal, kill_switch=KillSwitch(root / "KILL_SWITCH")), journal


def test_run_once_executes_and_posts_idempotent_events(tmp_path):
    agent, journal = _agent(tmp_path, make_lease())
    result = agent.run_once()
    assert result["status"] == "filled"
    assert journal.rebuild_positions() == {"BTCUSDT": Decimal("10")}
    assert any(item["event_type"] == "lease_ack" for item in agent.control.events)
    submitted = next(item for item in agent.control.events if item["event_type"] == "order_submitted")
    assert submitted["payload"]["quantity"] == "10" and "order" not in submitted["payload"]
    fill = next(item for item in agent.control.events if item["event_type"] == "fill")
    assert fill["payload"]["provider_trade_id"] == 1 and "fills" not in fill["payload"]
    journal.close()


def test_ambiguous_order_trips_kill_switch(tmp_path):
    agent, journal = _agent(tmp_path, make_lease(), FakeExchange(accepted=False))
    result = agent.run_once()
    assert result["status"] == "unknown"
    assert agent.kill_switch.is_active()
    with pytest.raises(ExecutionBlocked):
        agent.run_once()
    journal.close()


def test_kill_switch_does_not_claim_new_lease(tmp_path):
    agent, journal = _agent(tmp_path, make_lease())
    agent.kill_switch.trip("operator stop")
    with pytest.raises(ExecutionBlocked):
        agent.run_once()
    assert agent.control.events == []
    assert agent.control.lease is not None
    journal.close()


def test_remote_manual_position_mismatch_blocks_before_submit(tmp_path):
    exchange = FakeExchange()
    exchange._position = Decimal("1")
    agent, journal = _agent(tmp_path, make_lease(), exchange)
    result = agent.run_once()
    assert result["reason"] == "local_reconciliation_mismatch"
    assert exchange.placed == []
    assert agent.kill_switch.is_active()
    journal.close()


def test_restart_queries_incomplete_before_polling(tmp_path):
    agent, journal = _agent(tmp_path, make_lease())
    journal.prepare_order(lease_id="old", client_order_id="EA-old", symbol="BTCUSDT", side="BUY", quantity=Decimal("1"), target_exposure=Decimal("1"))
    journal.close()
    exchange = FakeExchange()
    agent, reopened = _agent(tmp_path, make_lease(), exchange)
    with pytest.raises(ExecutionBlocked):
        agent.run_once()
    assert exchange.queried and exchange.queried[0]["client_order_id"] == "EA-old"
    assert agent.kill_switch.is_active()
    reopened.close()
