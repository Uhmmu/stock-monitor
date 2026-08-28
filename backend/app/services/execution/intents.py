from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CryptoInstrument,
    ExecutionAgent,
    ExecutionIntent,
    ExecutionOrder,
    ExecutionTestAccount,
    QuantFeatureValue,
    QuantSignal,
    QuantStrategyDeployment,
    RiskPolicyVersion,
    SignalLease,
)
from app.services.execution.common import DEFAULT_VENUE, TEST_ENVIRONMENT, as_utc, now_utc
from app.services.execution.risk import policy_allowed


def create_test_account(
    db: Session,
    *,
    user_id: int,
    name: str = "TEST account",
    initial_capital: Decimal | str | float = Decimal("10000"),
    venue: str = DEFAULT_VENUE,
    base_currency: str = "USDT",
    account_key: str | None = None,
) -> ExecutionTestAccount:
    capital = Decimal(str(initial_capital))
    if not capital.is_finite() or capital <= 0:
        raise ValueError("初始资金必须为正数")
    if venue != DEFAULT_VENUE:
        raise ValueError("仅允许 Binance TEST venue")
    account = ExecutionTestAccount(
        user_id=user_id,
        name=name.strip() or "TEST account",
        account_key=(account_key or f"test-{user_id}-{secrets.token_hex(8)}").strip(),
        environment=TEST_ENVIRONMENT,
        venue=DEFAULT_VENUE,
        base_currency=base_currency.strip().upper() or "USDT",
        initial_capital=capital,
        cash=capital,
        status="active",
    )
    try:
        with db.begin_nested():
            db.add(account)
            db.flush()
    except IntegrityError as exc:
        raise ValueError("TEST account 已存在") from exc
    return account


def account_killed(db: Session, account_id: int, *, agent_id: int | None = None, deployment_id: int | None = None, instrument_id: int | None = None) -> tuple[bool, str | None]:
    from app.services.execution.risk import is_killed

    return is_killed(db, account_id=account_id, agent_id=agent_id, deployment_id=deployment_id, instrument_id=instrument_id)


def _active_policy(db: Session, account_id: int) -> RiskPolicyVersion | None:
    return db.scalar(
        select(RiskPolicyVersion)
        .where(
            RiskPolicyVersion.account_id == account_id,
            RiskPolicyVersion.environment == TEST_ENVIRONMENT,
            RiskPolicyVersion.status == "active",
            or_(RiskPolicyVersion.effective_at.is_(None), RiskPolicyVersion.effective_at <= now_utc()),
        )
        .order_by(RiskPolicyVersion.version.desc())
        .limit(1)
    )


def _signal_candidates(db: Session, account: ExecutionTestAccount):
    # Signals are deliberately copied, never consumed/rejected/superseded by
    # this path.  The deployment and timestamp predicates are duplicated here
    # as a second authority boundary in case an old paper row is stale.
    return db.scalars(
        select(QuantSignal)
        .join(QuantStrategyDeployment, QuantStrategyDeployment.id == QuantSignal.deployment_id)
        .where(
            QuantSignal.user_id == account.user_id,
            QuantSignal.environment == "paper",
            QuantSignal.expires_at > now_utc(),
            QuantStrategyDeployment.user_id == account.user_id,
            QuantStrategyDeployment.environment == "paper",
            QuantStrategyDeployment.status == "active",
        )
        .order_by(QuantSignal.decision_time.desc(), QuantSignal.generated_at.desc(), QuantSignal.id.desc())
    ).all()


def project_eligible_intents(db: Session, account_id: int | None = None) -> list[ExecutionIntent]:
    """Project the latest valid paper signals into isolated TEST intents."""

    query = select(ExecutionTestAccount).where(
        ExecutionTestAccount.environment == TEST_ENVIRONMENT,
        ExecutionTestAccount.status == "active",
    )
    if account_id is not None:
        query = query.where(ExecutionTestAccount.id == account_id)
    accounts = db.scalars(query).all()
    created: list[ExecutionIntent] = []
    now = now_utc()
    for account in accounts:
        policy = _active_policy(db, account.id)
        if policy is None:
            continue
        seen: set[tuple[int, int]] = set()
        for signal in _signal_candidates(db, account):
            key = (signal.deployment_id, signal.instrument_id)
            if key in seen:
                continue
            seen.add(key)
            if as_utc(signal.expires_at) is None or as_utc(signal.expires_at) <= now:
                continue
            instrument = db.get(CryptoInstrument, signal.instrument_id)
            if (
                instrument is None
                or instrument.market != "usdm_futures"
                or instrument.kind != "perpetual"
                or instrument.status != "trading"
            ):
                continue
            allowed, _ = policy_allowed(
                db,
                account,
                deployment_id=signal.deployment_id,
                instrument_id=signal.instrument_id,
                symbol=instrument.provider_symbol,
                signal_generated_at=signal.generated_at,
                signal_expires_at=signal.expires_at,
            )
            if not allowed:
                continue
            existing = db.scalar(
                select(ExecutionIntent).where(
                    ExecutionIntent.account_id == account.id,
                    ExecutionIntent.signal_id == signal.id,
                )
            )
            if existing is not None:
                if existing.status in {"pending", "leased", "acked"} and as_utc(existing.signal_expires_at) <= now:
                    existing.status = "expired"
                continue
            feature = db.get(QuantFeatureValue, signal.feature_value_id) if signal.feature_value_id else None
            feature_payload = feature.payload if feature is not None and isinstance(feature.payload, dict) else {}
            funding = feature_payload.get("funding") if isinstance(feature_payload.get("funding"), dict) else {}
            bar = feature_payload.get("bar") if isinstance(feature_payload.get("bar"), dict) else {}
            risk_evidence = {
                "as_of": as_utc(feature.as_of).isoformat() if feature is not None and feature.as_of else None,
                "funding_rate": funding.get("funding_rate"),
                "realized_volatility_24": feature_payload.get("realized_volatility_24"),
                "reference_price": bar.get("close"),
            }
            intent = ExecutionIntent(
                account_id=account.id,
                user_id=account.user_id,
                signal_id=signal.id,
                deployment_id=signal.deployment_id,
                instrument_id=signal.instrument_id,
                environment=TEST_ENVIRONMENT,
                strategy_key=signal.strategy_key,
                strategy_version=signal.strategy_version,
                interval=signal.interval,
                target_exposure=signal.target_exposure,
                decision_time=signal.decision_time,
                signal_generated_at=signal.generated_at,
                signal_expires_at=signal.expires_at,
                snapshot={
                    "signal_id": signal.id,
                    "deployment_id": signal.deployment_id,
                    "strategy_key": signal.strategy_key,
                    "strategy_version": signal.strategy_version,
                    "instrument_id": signal.instrument_id,
                    "interval": signal.interval,
                    "target_exposure": str(signal.target_exposure),
                    "decision_time": as_utc(signal.decision_time).isoformat(),
                    "generated_at": as_utc(signal.generated_at).isoformat(),
                    "valid_from": as_utc(signal.valid_from).isoformat(),
                    "expires_at": as_utc(signal.expires_at).isoformat(),
                    "reason": signal.reason,
                    "evidence": signal.evidence or {},
                    "input_hash": signal.input_hash,
                    "data_hash": signal.data_hash,
                    "feature_hash": signal.feature_hash,
                    "code_hash": signal.code_hash,
                    "instrument_symbol": instrument.provider_symbol,
                    "risk_evidence": risk_evidence,
                },
                status="pending",
            )
            try:
                with db.begin_nested():
                    db.add(intent)
                    db.flush()
            except IntegrityError:
                existing = db.scalar(
                    select(ExecutionIntent).where(
                        ExecutionIntent.account_id == account.id,
                        ExecutionIntent.signal_id == signal.id,
                    )
                )
                if existing is not None:
                    continue
                raise
            created.append(intent)
    return created


def expire_leases(db: Session, *, now=None) -> int:
    moment = now or now_utc()
    rows = db.scalars(
        select(SignalLease).where(SignalLease.status == "leased", SignalLease.expires_at <= moment)
    ).all()
    count = 0
    for lease in rows:
        lease.status = "expired"
        lease.reason = "lease_expired"
        intent = db.get(ExecutionIntent, lease.intent_id)
        if intent is not None and intent.status == "leased":
            intent.status = "expired" if as_utc(intent.signal_expires_at) <= moment else "pending"
        count += 1
    # Also mark unleased projections whose signal window ended.
    count += db.execute(
        update(ExecutionIntent)
        .where(
            ExecutionIntent.status.in_(["pending", "leased", "acked"]),
            ExecutionIntent.signal_expires_at <= moment,
        )
        .values(status="expired", rejection_reason="signal_expired")
        .execution_options(synchronize_session=False)
    ).rowcount or 0
    return count


def _agent_can_account(agent: ExecutionAgent, account: ExecutionTestAccount) -> bool:
    scopes = set(agent.scopes or [])
    bound_accounts = {int(value) for value in (agent.account_ids or [])}
    bound_venues = set(agent.venues or [])
    if bound_venues and account.venue not in bound_venues:
        return False
    if bound_accounts and account.id not in bound_accounts:
        return False
    return (
        account.user_id == agent.owner_id
        or f"account:{account.id}" in scopes
        or f"account:{account.id}:read" in scopes
        or "account:all" in scopes
    )


def _has_unknown_order(db: Session, account_id: int) -> bool:
    return db.scalar(
        select(ExecutionOrder.id).where(
            ExecutionOrder.account_id == account_id,
            ExecutionOrder.environment == TEST_ENVIRONMENT,
            ExecutionOrder.status == "unknown",
        ).limit(1)
    ) is not None


def claim_next_lease(
    db: Session,
    agent: ExecutionAgent,
    *,
    account_id: int | None = None,
    now=None,
) -> SignalLease | None:
    """Atomically claim one pending intent for an owner-scoped TEST agent."""

    moment = now or now_utc()
    expire_leases(db, now=moment)
    query = select(ExecutionTestAccount).where(
        ExecutionTestAccount.environment == TEST_ENVIRONMENT,
        ExecutionTestAccount.status == "active",
        ExecutionTestAccount.user_id == agent.owner_id,
    )
    if account_id is not None:
        query = query.where(ExecutionTestAccount.id == account_id)
    accounts = db.scalars(query).all()
    settings = get_settings()
    ttl = max(1, int(getattr(settings, "execution_agent_lease_ttl_seconds", 60)))
    for account in accounts:
        if not _agent_can_account(agent, account) or _has_unknown_order(db, account.id):
            continue
        intents = db.scalars(
            select(ExecutionIntent)
            .where(
                ExecutionIntent.account_id == account.id,
                ExecutionIntent.environment == TEST_ENVIRONMENT,
                ExecutionIntent.status == "pending",
                ExecutionIntent.signal_expires_at > moment,
            )
            .order_by(ExecutionIntent.created_at, ExecutionIntent.id)
            .limit(20)
        ).all()
        for intent in intents:
            instrument = db.get(CryptoInstrument, intent.instrument_id)
            symbol = instrument.provider_symbol if instrument is not None else None
            allowed, _ = policy_allowed(
                db,
                account,
                agent_id=agent.id,
                deployment_id=intent.deployment_id,
                instrument_id=intent.instrument_id,
                symbol=symbol,
                signal_generated_at=intent.signal_generated_at,
                signal_expires_at=intent.signal_expires_at,
            )
            if not allowed:
                continue
            try:
                with db.begin_nested():
                    updated = db.execute(
                        update(ExecutionIntent)
                        .where(
                            ExecutionIntent.id == intent.id,
                            ExecutionIntent.status == "pending",
                            ExecutionIntent.signal_expires_at > moment,
                        )
                        .values(status="leased")
                        .execution_options(synchronize_session=False)
                    )
                    if not updated.rowcount:
                        continue
                    latest_attempt = db.scalar(
                        select(func.max(SignalLease.attempt)).where(SignalLease.intent_id == intent.id)
                    ) or 0
                    remaining = (as_utc(intent.signal_expires_at) - moment).total_seconds()
                    lease_seconds = min(ttl, max(0, int(remaining)))
                    if lease_seconds <= 0:
                        intent.status = "expired"
                        continue
                    lease = SignalLease(
                        intent_id=intent.id,
                        agent_id=agent.id,
                        environment=TEST_ENVIRONMENT,
                        lease_token=secrets.token_urlsafe(32),
                        attempt=int(latest_attempt) + 1,
                        leased_at=moment,
                        expires_at=moment + timedelta(seconds=lease_seconds),
                        last_heartbeat_at=moment,
                        status="leased",
                    )
                    db.add(lease)
                    db.flush()
            except IntegrityError:
                continue
            return lease
    return None


def heartbeat_lease(db: Session, agent: ExecutionAgent, lease_id: int, *, now=None) -> SignalLease:
    moment = now or now_utc()
    lease = db.scalar(select(SignalLease).where(SignalLease.id == lease_id, SignalLease.agent_id == agent.id))
    if lease is None:
        raise LookupError("租约不存在")
    if lease.status != "leased" or as_utc(lease.expires_at) <= moment:
        if lease.status == "leased":
            lease.status = "expired"
        raise RuntimeError("租约已过期")
    intent = db.get(ExecutionIntent, lease.intent_id)
    if intent is None or as_utc(intent.signal_expires_at) <= moment:
        lease.status = "expired"
        raise RuntimeError("信号已过期")
    lease.last_heartbeat_at = moment
    db.flush()
    return lease


def acknowledge_lease(
    db: Session,
    agent: ExecutionAgent,
    lease_id: int,
    *,
    accepted: bool = True,
    reason: str | None = None,
    now=None,
) -> SignalLease:
    moment = now or now_utc()
    lease = db.scalar(select(SignalLease).where(SignalLease.id == lease_id, SignalLease.agent_id == agent.id))
    if lease is None:
        raise LookupError("租约不存在")
    if lease.status != "leased" or as_utc(lease.expires_at) <= moment:
        raise RuntimeError("租约已过期或已完成")
    intent = db.get(ExecutionIntent, lease.intent_id)
    if intent is None or as_utc(intent.signal_expires_at) <= moment:
        lease.status = "expired"
        raise RuntimeError("信号已过期")
    lease.status = "acked" if accepted else "rejected"
    lease.acked_at = moment
    lease.reason = reason
    if not (accepted and intent.status == "consumed"):
        intent.status = "acked" if accepted else "rejected"
    intent.rejection_reason = reason if not accepted else None
    db.flush()
    return lease


def lease_payload(db: Session, lease: SignalLease | None) -> dict | None:
    if lease is None:
        return None
    intent = db.get(ExecutionIntent, lease.intent_id)
    if intent is None:
        return None
    policy = _active_policy(db, intent.account_id)
    instrument = db.get(CryptoInstrument, intent.instrument_id)
    if policy is None or instrument is None:
        return None
    snapshot = intent.snapshot or {}
    return {
        "wire_version": "execution-agent.v1",
        "lease_id": lease.lease_token,
        "signal_id": str(intent.signal_id),
        "account_id": str(intent.account_id),
        "environment": TEST_ENVIRONMENT,
        "venue": DEFAULT_VENUE,
        "symbol": instrument.provider_symbol,
        "instrument_id": intent.instrument_id,
        "deployment_id": intent.deployment_id,
        "target_exposure": str(intent.target_exposure),
        "issued_at": as_utc(lease.leased_at).isoformat(),
        "signal_time": as_utc(intent.signal_generated_at).isoformat(),
        "expires_at": as_utc(lease.expires_at).isoformat(),
        "policy_hash": policy.policy_hash,
        "policy": {"version": str(policy.version), "hash": policy.policy_hash, "limits": policy.limits or {}},
        "risk_evidence": snapshot.get("risk_evidence") or {},
    }


def intent_payload(intent: ExecutionIntent | None) -> dict | None:
    if intent is None:
        return None
    return {
        "id": intent.id,
        "account_id": intent.account_id,
        "user_id": intent.user_id,
        "signal_id": intent.signal_id,
        "deployment_id": intent.deployment_id,
        "instrument_id": intent.instrument_id,
        "environment": intent.environment,
        "strategy_key": intent.strategy_key,
        "strategy_version": intent.strategy_version,
        "interval": intent.interval,
        "target_exposure": intent.target_exposure,
        "decision_time": as_utc(intent.decision_time).isoformat() if intent.decision_time else None,
        "signal_generated_at": as_utc(intent.signal_generated_at).isoformat() if intent.signal_generated_at else None,
        "signal_expires_at": as_utc(intent.signal_expires_at).isoformat() if intent.signal_expires_at else None,
        "status": intent.status,
        "snapshot": intent.snapshot or {},
    }
