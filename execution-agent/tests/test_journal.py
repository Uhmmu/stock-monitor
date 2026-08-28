from __future__ import annotations

from decimal import Decimal

import pytest

from execution_agent.errors import InstanceAlreadyRunning, SecurityError
from execution_agent.journal import Journal
from execution_agent.security import InstanceLock
from execution_agent.wire import AgentEvent


def test_restart_rebuilds_fills_and_dedupes_events(tmp_path) -> None:
    root = tmp_path / "agent"
    root.mkdir(mode=0o700)
    path = root / "journal.sqlite3"
    journal = Journal(path)
    journal.prepare_order(lease_id="l1", client_order_id="EA1", symbol="BTCUSDT", side="BUY", quantity=Decimal("1"), target_exposure=Decimal("1"))
    journal.record_exchange_order({"clientOrderId": "EA1", "orderId": 4, "status": "PARTIALLY_FILLED", "executedQty": "1", "avgPrice": "100"})
    assert journal.record_fill({"id": 8, "clientOrderId": "EA1", "symbol": "BTCUSDT", "side": "BUY", "qty": "1", "price": "100"})
    event = AgentEvent("l1", "fill", {"client_order_id": "EA1"})
    assert journal.record_event(event)
    assert not journal.record_event(event)
    journal.close()
    with Journal(path) as reopened:
        assert reopened.rebuild_positions() == {"BTCUSDT": Decimal("1")}
        assert reopened.order("EA1").status == "PARTIAL"
        assert len(reopened.pending_events()) == 1


def test_single_instance_lock(tmp_path) -> None:
    root = tmp_path / "agent"
    root.mkdir(mode=0o700)
    first = InstanceLock(root / "agent.lock")
    second = InstanceLock(root / "agent.lock")
    first.acquire()
    try:
        with pytest.raises(InstanceAlreadyRunning):
            second.acquire()
    finally:
        first.release()


def test_journal_rejects_weak_permissions(tmp_path) -> None:
    root = tmp_path / "agent"
    root.mkdir(mode=0o700)
    path = root / "journal.sqlite3"
    path.touch(mode=0o644)
    with pytest.raises(SecurityError):
        Journal(path)
