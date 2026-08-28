"""Goal 6 TEST-only control-plane safety checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import hmac

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.database import get_db
from app.api.execution_admin_routes import router as admin_router
from app.auth import create_token, hash_password
from app.models import (
    CryptoAsset,
    CryptoInstrument,
    ExecutionIntent,
    ExecutionOrder,
    ExecutionTestAccount,
    QuantFeatureSet,
    QuantFeatureValue,
    QuantSignal,
    QuantStrategyDeployment,
    User,
)
from app.services.execution.auth import AgentAuthError, authenticate_request, create_agent, sign_request
from app.services.execution.intents import claim_next_lease, create_test_account, lease_payload, project_eligible_intents
from app.services.execution.ledger import record_event
from app.services.execution.risk import create_policy, normalize_limits, set_kill_switch


TABLES = [
    "users", "crypto_assets", "crypto_instruments", "quant_feature_sets", "quant_feature_values",
    "quant_strategy_deployments", "quant_signals", "execution_test_accounts", "execution_intents",
    "execution_agents", "execution_request_nonces", "signal_leases", "execution_orders", "execution_fills",
    "execution_events", "risk_policy_versions", "execution_kill_switches",
]


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("EXECUTION_CONTROL_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in TABLES])
    with Session(engine) as session:
        yield session
    engine.dispose()
    get_settings.cache_clear()


def _seed(db: Session):
    now = datetime.now(UTC).replace(microsecond=0)
    user = User(username="goal6", password_hash="x", role="admin", status="active")
    base = CryptoAsset(slug="bitcoin", symbol="BTC", display_name="Bitcoin", asset_kind="coin", status="active")
    quote = CryptoAsset(slug="tether", symbol="USDT", display_name="Tether", asset_kind="token", status="active")
    db.add_all([user, base, quote]); db.flush()
    instrument = CryptoInstrument(
        venue="binance", market="usdm_futures", provider_symbol="BTCUSDT", kind="perpetual",
        base_asset_id=base.id, quote_asset_id=quote.id, settlement_asset_id=quote.id,
        tick_size=Decimal("0.1"), step_size=Decimal("0.001"), min_notional=Decimal("5"),
        status="trading", calendar="utc",
    )
    feature_set = QuantFeatureSet(
        feature_set_key="execution-test", name="Execution test", version="v1", supported_intervals=["1h"],
        feature_schema={}, parameters={}, input_declarations={}, availability_policy="source_causal_v1",
        config_hash="1" * 64, status="released",
    )
    db.add_all([instrument, feature_set]); db.flush()
    feature = QuantFeatureValue(
        feature_set_id=feature_set.id, instrument_id=instrument.id, interval="1h",
        bar_open_time_ms=int(now.timestamp() * 1000), as_of=now, available_at=now,
        input_hash="2" * 64, input_snapshot={},
        payload={
            "bar": {"close": "100"}, "funding": {"funding_rate": "0.0001"},
            "realized_volatility_24": "0.02",
        }, coverage=1, quality="ok",
    )
    deployment = QuantStrategyDeployment(
        user_id=user.id, strategy_key="dual-ma-trend-v1", strategy_version="v1",
        instrument_id=instrument.id, interval="1h", target_exposure=Decimal("1"), status="active",
    )
    db.add_all([feature, deployment]); db.flush()
    signal = QuantSignal(
        user_id=user.id, deployment_id=deployment.id, environment="paper", status="consumed",
        strategy_key=deployment.strategy_key, strategy_version="v1", instrument_id=instrument.id,
        interval="1h", decision_time=now, target_exposure=Decimal("1"), reason="test",
        evidence={}, feature_value_id=feature.id, input_hash=feature.input_hash,
        data_hash="3" * 64, feature_hash="4" * 64, code_hash="5" * 64,
        idempotency_key="goal6-consumed-signal", generated_at=now,
        valid_from=now - timedelta(seconds=1), expires_at=now + timedelta(minutes=30),
    )
    db.add(signal); db.flush()
    account = create_test_account(db, user_id=user.id, initial_capital=Decimal("1000"))
    limits = {
        "allowed_deployment_ids": [deployment.id], "allowed_instrument_ids": [instrument.id],
        "allowed_symbols": ["BTCUSDT"], "capital_allocation_usdt": "1000",
        "max_order_notional_usdt": "1000", "max_gross_notional_usdt": "2000",
        "max_net_notional_usdt": "2000", "max_leverage": "2",
        "max_daily_loss_usdt": "100", "max_drawdown_usdt": "200", "max_open_orders": 2,
        "cooldown_seconds": 0, "stale_signal_seconds": 3600, "stale_account_seconds": 60,
        "max_funding_rate_abs": "0.001", "max_volatility": "0.1",
    }
    policy = create_policy(db, account_id=account.id, created_by=user.id, limits=limits)
    agent, _token = create_agent(db, owner_id=user.id, name="local", account_ids=[account.id])
    db.flush()
    return user, instrument, deployment, signal, account, policy, agent


def test_policy_is_complete_and_test_sized():
    with pytest.raises(ValueError, match="缺少必要限制"):
        normalize_limits({"allowed_symbols": ["BTCUSDT"]}, require_complete=True)
    with pytest.raises(ValueError, match="不能超过 3"):
        normalize_limits({
            "allowed_deployment_ids": [1], "allowed_instrument_ids": [1], "allowed_symbols": ["BTCUSDT"],
            "capital_allocation_usdt": 100, "max_order_notional_usdt": 100,
            "max_gross_notional_usdt": 100, "max_net_notional_usdt": 100, "max_leverage": 4,
            "max_daily_loss_usdt": 10, "max_drawdown_usdt": 10, "max_open_orders": 1,
            "cooldown_seconds": 0, "stale_signal_seconds": 60, "stale_account_seconds": 30,
            "max_funding_rate_abs": "0.001", "max_volatility": "0.1",
        }, require_complete=True)


def test_consumed_paper_signal_projects_once_and_lease_is_flat(db):
    _user, instrument, deployment, signal, _account, policy, agent = _seed(db)
    intents = project_eligible_intents(db)
    assert len(intents) == 1 and intents[0].signal_id == signal.id
    lease = claim_next_lease(db, agent)
    assert lease is not None and claim_next_lease(db, agent) is None
    payload = lease_payload(db, lease)
    assert payload and payload["lease_id"] == lease.lease_token
    assert payload["deployment_id"] == deployment.id and payload["instrument_id"] == instrument.id
    assert payload["policy_hash"] == policy.policy_hash
    assert payload["risk_evidence"]["funding_rate"] == "0.0001"
    assert payload["environment"] == "test" and "intent" not in payload


def test_event_lineage_is_idempotent_and_reconciled(db):
    _user, instrument, _deployment, _signal, account, _policy, agent = _seed(db)
    intent = project_eligible_intents(db)[0]
    lease = claim_next_lease(db, agent)
    assert lease is not None
    submitted = {
        "client_order_id": "EA-goal6", "instrument_id": instrument.id, "symbol": "BTCUSDT",
        "side": "buy", "quantity": "1", "price": "100", "order_type": "market",
    }
    first = record_event(
        db, agent_id=agent.id, event_id="submitted-1", event_type="order_submitted",
        payload=submitted, lease_id=lease.lease_token,
    )
    assert record_event(
        db, agent_id=agent.id, event_id="submitted-1", event_type="order_submitted",
        payload=submitted, lease_id=lease.lease_token,
    ).id == first.id
    record_event(
        db, agent_id=agent.id, event_id="fill-1", event_type="fill", lease_id=lease.lease_token,
        payload={
            "client_order_id": "EA-goal6", "provider_trade_id": "trade-1", "side": "buy",
            "quantity": "1", "price": "100", "fee": "0.04", "fee_asset": "USDT",
        },
    )
    record_event(
        db, agent_id=agent.id, event_id="reconcile-1", event_type="reconciliation",
        lease_id=lease.lease_token, payload={"client_order_id": "EA-goal6", "status": "ok"},
    )
    record_event(
        db, agent_id=agent.id, event_id="ack-1", event_type="lease_ack",
        lease_id=lease.lease_token, payload={"status": "filled"},
    )
    order = db.scalar(select(ExecutionOrder).where(ExecutionOrder.client_order_id == "EA-goal6"))
    db.refresh(intent); db.refresh(account)
    assert order and order.status == "filled"
    assert intent.status == "consumed"
    assert account.last_reconciled_at is not None


def test_kill_switch_blocks_new_lease(db):
    user, _instrument, _deployment, _signal, account, _policy, agent = _seed(db)
    project_eligible_intents(db)
    set_kill_switch(
        db, scope_type="account", scope_id=account.id, enabled=True,
        reason="drill", changed_by=user.id,
    )
    assert claim_next_lease(db, agent) is None


def test_machine_auth_uses_raw_token_and_rejects_nonce_replay(db):
    _user, _instrument, _deployment, _signal, _account, _policy, agent = _seed(db)
    token = "goal6-machine-token-" * 3
    # Replace the generated credential with a deterministic test token.
    from app.services.execution.auth import hash_agent_token

    agent.token_hash = hash_agent_token(token)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    nonce = "nonce-once"
    path = "/api/execution-agent/v1/status"
    signature = sign_request(token, "GET", path, "", b"", timestamp, nonce)
    canonical = "\n".join(("GET", path, "", hashlib.sha256(b"").hexdigest(), timestamp, nonce)).encode()
    assert signature == hmac.new(token.encode(), canonical, hashlib.sha256).hexdigest()
    headers = [
        (b"x-execution-agent-token", token.encode()),
        (b"x-execution-agent-timestamp", timestamp.encode()),
        (b"x-execution-agent-nonce", nonce.encode()),
        (b"x-execution-agent-signature", signature.encode()),
    ]
    request = Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": headers})
    assert authenticate_request(db, request, b"").id == agent.id
    with pytest.raises(AgentAuthError) as replay:
        authenticate_request(db, request, b"")
    assert replay.value.status_code == 409


def test_admin_ui_contract_uses_body_step_up_and_one_time_token(db):
    user, _instrument, _deployment, _signal, _account, policy, _agent = _seed(db)
    user.password_hash = hash_password("goal6-password")
    db.commit()
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, headers={"Authorization": f"Bearer {create_token(user.id)}"})

    account_response = client.post(
        "/api/execution/admin/accounts",
        json={"password": "goal6-password", "name": "UI TEST"},
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]
    agent_response = client.post(
        "/api/execution/admin/agents",
        json={"password": "goal6-password", "account_id": account_id, "name": "ui-local"},
    )
    assert agent_response.status_code == 201 and len(agent_response.json()["token"]) >= 32
    status_payload = client.get("/api/execution/admin/status").json()
    assert all("token" not in item for item in status_payload["agents"])
    limits = dict(policy.limits)
    policy_response = client.post(
        "/api/execution/admin/policies",
        json={"password": "goal6-password", "account_id": account_id, "limits": limits},
    )
    assert policy_response.status_code == 201
    kill_response = client.post(
        "/api/execution/admin/kill-switches",
        json={
            "password": "goal6-password", "scope_type": "account", "scope_id": account_id,
            "enabled": True, "reason": "UI drill",
        },
    )
    assert kill_response.status_code == 200 and kill_response.json()["enabled"] is True


def test_events_route_accepts_agent_wire_version_envelope(db):
    """The agent always tags events with wire_version; the route must accept it.

    Regression: EventRequest used extra="forbid" without declaring
    wire_version, so every real agent event POST failed with 422 and tripped
    the local kill switch ("control event delivery unavailable").
    """
    import json as _json

    from fastapi.testclient import TestClient as _TC

    from app.api.execution_agent_routes import router as agent_router

    _user, _instrument, _deployment, _signal, account, _policy, agent = _seed(db)
    wire_agent, token = create_agent(db, owner_id=_user.id, name="wire-local", account_ids=[account.id])
    db.commit()
    intent = project_eligible_intents(db)[0]
    lease = claim_next_lease(db, wire_agent)
    assert lease is not None

    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_db] = lambda: db
    client = _TC(app)

    def _post(body: dict):
        payload = _json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        nonce = f"nonce-{timestamp}-{len(body)}"
        path = "/api/execution-agent/v1/events"
        signature = sign_request(token, "POST", path, "", payload, timestamp, nonce)
        return client.post(
            path,
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Execution-Agent-Id": "wire-local",
                "X-Execution-Agent-Token": token,
                "X-Execution-Agent-Timestamp": timestamp,
                "X-Execution-Agent-Nonce": nonce,
                "X-Execution-Agent-Signature": signature,
            },
        )

    ok = _post({
        "wire_version": "execution-agent.v1",
        "event_id": "evt-wire-1",
        "event_type": "lease_ack",
        "lease_id": lease.lease_token,
        "account_id": account.id,
        "payload": {"status": "acked"},
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "accepted"

    conflict = _post({
        "wire_version": "execution-agent.v9",
        "event_id": "evt-wire-2",
        "event_type": "lease_ack",
        "lease_id": lease.lease_token,
        "payload": {},
    })
    assert conflict.status_code == 409
