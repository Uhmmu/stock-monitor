"""Administrator control-plane API for the isolated TEST execution boundary."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_admin_user, verify_password
from app.database import get_db
from app.models import (
    ExecutionAgent,
    ExecutionEvent,
    ExecutionFill,
    ExecutionIntent,
    ExecutionKillSwitch,
    ExecutionOrder,
    ExecutionTestAccount,
    RiskPolicyVersion,
    SignalLease,
    User,
)
from app.services.execution.auth import create_agent
from app.services.execution.common import TEST_ENVIRONMENT, as_utc
from app.services.execution.health import health_payload
from app.services.execution.intents import create_test_account, intent_payload, project_eligible_intents
from app.services.execution.ledger import event_payload, fill_payload, order_payload
from app.services.execution.risk import create_policy, set_kill_switch


router = APIRouter(prefix="/api/execution/admin", dependencies=[Depends(get_admin_user)])


def _require_step_up(admin: User, password: str | None) -> None:
    if not password or not verify_password(password, admin.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员密码再次确认")


def _when(value):
    return as_utc(value).isoformat() if value else None


def account_out(row: ExecutionTestAccount) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "account_key": row.account_key,
        "environment": row.environment,
        "venue": row.venue,
        "base_currency": row.base_currency,
        "initial_capital": row.initial_capital,
        "initial_cash": row.initial_capital,
        "cash": row.cash,
        "status": row.status,
        "last_reconciled_at": _when(row.last_reconciled_at),
        "created_at": _when(row.created_at),
        "updated_at": _when(row.updated_at),
    }


def agent_out(row: ExecutionAgent, *, include_token: str | None = None) -> dict:
    value = {
        "id": row.id,
        "owner_id": row.owner_id,
        "name": row.name,
        "environment": row.environment,
        "scopes": row.scopes or [],
        "account_ids": row.account_ids or [],
        "venues": row.venues or [],
        "token_fingerprint": row.token_fingerprint,
        "status": row.status,
        "last_seen_at": _when(row.last_seen_at),
        "revoked_at": _when(row.revoked_at),
        "created_at": _when(row.created_at),
        "updated_at": _when(row.updated_at),
    }
    if include_token is not None:
        value["token"] = include_token
    return value


def policy_out(row: RiskPolicyVersion) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "environment": row.environment,
        "version": row.version,
        "status": row.status,
        "policy_hash": row.policy_hash,
        "limits": row.limits or {},
        "effective_at": _when(row.effective_at),
        "approved_by": row.approved_by,
        "created_by": row.created_by,
        "created_at": _when(row.created_at),
    }


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr
    user_id: int | None = Field(default=None, gt=0)
    name: str = Field(default="TEST account", min_length=1, max_length=96)
    initial_capital: Decimal | None = Field(default=None, gt=0, le=100_000_000)
    initial_cash: Decimal | None = Field(default=None, gt=0, le=100_000_000)
    venue: str = Field(default="binance_usdm", max_length=32)
    base_currency: str = Field(default="USDT", min_length=2, max_length=12)
    account_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def choose_capital(self):
        if self.initial_capital is None and self.initial_cash is None:
            self.initial_capital = Decimal("10000")
        elif self.initial_capital is None:
            self.initial_capital = self.initial_cash
        return self


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr
    account_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=96)


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr
    account_id: int = Field(gt=0)
    limits: dict = Field(default_factory=dict)
    activate: bool = True


class KillSwitchChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr
    scope_type: str = Field(min_length=1, max_length=16)
    scope_id: int | None = Field(default=None, ge=1)
    enabled: bool = True
    reason: str | None = Field(default=None, max_length=500)


class StepUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr


@router.get("/status")
def execution_status(_: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    value = health_payload(db)
    accounts = db.scalars(select(ExecutionTestAccount).where(ExecutionTestAccount.environment == TEST_ENVIRONMENT).order_by(ExecutionTestAccount.created_at.desc())).all()
    agents = db.scalars(select(ExecutionAgent).where(ExecutionAgent.environment == TEST_ENVIRONMENT).order_by(ExecutionAgent.created_at.desc())).all()
    value["active_account_count"] = value.pop("accounts", 0)
    value["active_agent_count"] = value.pop("agents", 0)
    value["accounts"] = [account_out(row) for row in accounts]
    value["agents"] = [agent_out(row) for row in agents]
    value["intent_count"] = db.scalar(select(func.count(ExecutionIntent.id)).where(ExecutionIntent.environment == TEST_ENVIRONMENT)) or 0
    value["order_count"] = db.scalar(select(func.count(ExecutionOrder.id)).where(ExecutionOrder.environment == TEST_ENVIRONMENT)) or 0
    value["fill_count"] = db.scalar(select(func.count(ExecutionFill.id)).where(ExecutionFill.environment == TEST_ENVIRONMENT)) or 0
    return value


@router.get("/accounts")
def list_accounts(
    user_id: int | None = Query(default=None, gt=0),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    query = select(ExecutionTestAccount).where(ExecutionTestAccount.environment == TEST_ENVIRONMENT)
    if user_id is not None:
        query = query.where(ExecutionTestAccount.user_id == user_id)
    rows = db.scalars(query.order_by(ExecutionTestAccount.created_at.desc())).all()
    return {"items": [account_out(row) for row in rows], "total": len(rows), "environment": TEST_ENVIRONMENT}


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    try:
        row = create_test_account(
            db,
            user_id=payload.user_id or admin.id,
            name=payload.name,
            initial_capital=payload.initial_capital or Decimal("10000"),
            venue=payload.venue,
            base_currency=payload.base_currency,
            account_key=payload.account_key,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return account_out(row)


def _account(db: Session, account_id: int) -> ExecutionTestAccount:
    row = db.scalar(select(ExecutionTestAccount).where(ExecutionTestAccount.id == account_id, ExecutionTestAccount.environment == TEST_ENVIRONMENT))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "TEST account 不存在")
    return row


@router.post("/accounts/{account_id}/pause")
def pause_account(
    account_id: int,
    payload: StepUpRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    row = _account(db, account_id)
    row.status = "paused"
    db.commit()
    return account_out(row)


@router.post("/accounts/{account_id}/resume")
def resume_account(
    account_id: int,
    payload: StepUpRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    row = _account(db, account_id)
    if row.status == "revoked":
        raise HTTPException(status.HTTP_409_CONFLICT, "已撤销的 TEST account 不能恢复")
    row.status = "active"
    db.commit()
    return account_out(row)


@router.get("/agents")
def list_agents(_: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ExecutionAgent).where(ExecutionAgent.environment == TEST_ENVIRONMENT).order_by(ExecutionAgent.created_at.desc())).all()
    return {"items": [agent_out(row) for row in rows], "total": len(rows), "environment": TEST_ENVIRONMENT}


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def register_agent(
    payload: AgentCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    account = _account(db, payload.account_id)
    try:
        agent, token = create_agent(
            db,
            owner_id=account.user_id,
            name=payload.name,
            account_ids=[account.id],
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"agent": agent_out(agent), "token": token, "warning": "token 仅显示一次"}


@router.post("/agents/{agent_id}/revoke")
def revoke_agent(
    agent_id: int,
    payload: StepUpRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    row = db.scalar(select(ExecutionAgent).where(ExecutionAgent.id == agent_id, ExecutionAgent.environment == TEST_ENVIRONMENT))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent 不存在")
    row.status = "revoked"
    from datetime import UTC, datetime

    row.revoked_at = datetime.now(UTC)
    db.commit()
    return agent_out(row)


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_risk_policy(
    payload: PolicyCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    try:
        row = create_policy(db, account_id=payload.account_id, created_by=admin.id, limits=payload.limits, activate=payload.activate)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return policy_out(row)


@router.post("/kill-switches")
def change_kill_switch(
    payload: KillSwitchChange,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    _require_step_up(admin, payload.password.get_secret_value())
    try:
        values = payload.model_dump(exclude={"password"})
        row = set_kill_switch(db, changed_by=admin.id, **values)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "id": row.id,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "environment": row.environment,
        "enabled": row.enabled,
        "reason": row.reason,
        "changed_by": row.changed_by,
        "changed_at": _when(row.changed_at),
    }


@router.get("/orders")
def list_orders(
    limit: int = Query(default=50, ge=1, le=200),
    account_id: int | None = Query(default=None, gt=0),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    query = select(ExecutionOrder).where(ExecutionOrder.environment == TEST_ENVIRONMENT)
    if account_id is not None:
        query = query.where(ExecutionOrder.account_id == account_id)
    rows = db.scalars(query.order_by(ExecutionOrder.created_at.desc()).limit(limit)).all()
    return {"items": [order_payload(row) for row in rows], "total": len(rows), "limit": limit}


@router.get("/fills")
def list_fills(limit: int = Query(default=50, ge=1, le=200), _: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ExecutionFill).where(ExecutionFill.environment == TEST_ENVIRONMENT).order_by(ExecutionFill.fill_time.desc()).limit(limit)).all()
    return {"items": [fill_payload(row) for row in rows], "total": len(rows), "limit": limit}


@router.get("/events")
def list_events(limit: int = Query(default=50, ge=1, le=200), _: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ExecutionEvent).where(ExecutionEvent.environment == TEST_ENVIRONMENT).order_by(ExecutionEvent.received_at.desc()).limit(limit)).all()
    return {"items": [event_payload(row) for row in rows], "total": len(rows), "limit": limit}


@router.get("/intents")
def list_intents(limit: int = Query(default=50, ge=1, le=200), _: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    project_eligible_intents(db)
    db.commit()
    rows = db.scalars(select(ExecutionIntent).where(ExecutionIntent.environment == TEST_ENVIRONMENT).order_by(ExecutionIntent.created_at.desc()).limit(limit)).all()
    return {"items": [intent_payload(row) for row in rows], "total": len(rows), "limit": limit}


@router.get("/leases")
def list_leases(limit: int = Query(default=50, ge=1, le=200), _: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SignalLease).where(SignalLease.environment == TEST_ENVIRONMENT).order_by(SignalLease.created_at.desc()).limit(limit)).all()
    return {
        "items": [
            {"id": row.id, "intent_id": row.intent_id, "agent_id": row.agent_id, "status": row.status, "attempt": row.attempt, "leased_at": _when(row.leased_at), "expires_at": _when(row.expires_at), "last_heartbeat_at": _when(row.last_heartbeat_at), "reason": row.reason}
            for row in rows
        ],
        "total": len(rows),
        "limit": limit,
    }
    password: SecretStr
