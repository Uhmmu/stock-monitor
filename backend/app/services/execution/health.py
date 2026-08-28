from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    ExecutionAgent,
    ExecutionEvent,
    ExecutionKillSwitch,
    ExecutionOrder,
    ExecutionTestAccount,
    RiskPolicyVersion,
    SignalLease,
)
from app.services.execution.common import TEST_ENVIRONMENT, as_utc, now_utc


def health_payload(db: Session) -> dict:
    moment = now_utc()
    settings = get_settings()
    enabled = bool(getattr(settings, "execution_control_enabled", False))
    heartbeat_stale = max(1, int(getattr(settings, "execution_agent_heartbeat_stale_seconds", 180)))
    stale_cutoff = moment - timedelta(seconds=heartbeat_stale)
    account_rows = db.scalars(
        select(ExecutionTestAccount).where(
            ExecutionTestAccount.environment == TEST_ENVIRONMENT,
            ExecutionTestAccount.status == "active",
        )
    ).all()
    accounts = len(account_rows)
    agents = db.scalars(
        select(ExecutionAgent).where(
            ExecutionAgent.environment == TEST_ENVIRONMENT,
            ExecutionAgent.status == "active",
        )
    ).all()
    stale_agents = sum(
        1 for agent in agents
        if agent.last_seen_at is None or (as_utc(agent.last_seen_at) or moment) < stale_cutoff
    )
    leases = db.scalar(
        select(func.count(SignalLease.id)).where(
            SignalLease.environment == TEST_ENVIRONMENT,
            SignalLease.status == "leased",
            SignalLease.expires_at > moment,
        )
    ) or 0
    unknown_orders = db.scalar(
        select(func.count(ExecutionOrder.id)).where(
            ExecutionOrder.environment == TEST_ENVIRONMENT,
            ExecutionOrder.status == "unknown",
        )
    ) or 0
    critical_alerts = db.scalar(
        select(func.count(ExecutionEvent.id)).where(
            ExecutionEvent.environment == TEST_ENVIRONMENT,
            ExecutionEvent.event_type.in_(["alert", "risk_reject"]),
        )
    ) or 0
    blockers: list[str] = []
    if not enabled:
        blockers.append("execution_control_disabled")
    if not accounts:
        blockers.append("no_active_test_account")
    policy_accounts = set(db.scalars(select(RiskPolicyVersion.account_id).where(
        RiskPolicyVersion.environment == TEST_ENVIRONMENT,
        RiskPolicyVersion.status == "active",
    )).all())
    if any(account.id not in policy_accounts for account in account_rows):
        blockers.append("missing_active_risk_policy")
    if not agents:
        blockers.append("no_active_agent")
    if stale_agents:
        blockers.append("stale_agent_heartbeat")
    if unknown_orders:
        blockers.append("unknown_order_requires_reconciliation")
    if any(account.last_reconciled_at is None for account in account_rows):
        blockers.append("reconciliation_not_proven")
    if db.scalar(select(ExecutionKillSwitch.id).where(
        ExecutionKillSwitch.environment == TEST_ENVIRONMENT,
        ExecutionKillSwitch.enabled.is_(True),
    ).limit(1)) is not None:
        blockers.append("kill_switch_active")
    state = "TEST_READY" if not blockers else ("BLOCKED" if not enabled else "DEGRADED")
    return {
        "environment": TEST_ENVIRONMENT,
        "health": state,
        "status": state,
        "live_ready": False,
        "test_ready": state == "TEST_READY",
        "execution_enabled": enabled,
        "accounts": accounts,
        "agents": len(agents),
        "stale_agents": stale_agents,
        "active_leases": leases,
        "unknown_orders": unknown_orders,
        "critical_alerts": critical_alerts,
        "blockers": blockers,
        "last_heartbeat_at": max(
            (as_utc(agent.last_seen_at) for agent in agents if agent.last_seen_at is not None),
            default=None,
        ).isoformat() if any(agent.last_seen_at is not None for agent in agents) else None,
    }
