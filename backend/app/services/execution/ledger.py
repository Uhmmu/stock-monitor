from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ExecutionAgent,
    ExecutionEvent,
    ExecutionFill,
    ExecutionIntent,
    ExecutionOrder,
    ExecutionTestAccount,
    SignalLease,
)
from app.services.execution.common import DEFAULT_VENUE, TEST_ENVIRONMENT, as_utc, canonical_hash, decimal, now_utc
from app.services.execution.intents import acknowledge_lease
from app.services.execution.redaction import redacted_event_payload
from app.services.execution.risk import validate_order_risk


EVENT_TYPES = {
    "lease_ack",
    "lease_reject",
    "order_submitted",
    "order_update",
    "fill",
    "risk_reject",
    "reconciliation",
    "alert",
}

_TRANSITIONS: dict[str, set[str]] = {
    "created": {"created", "submitted", "rejected", "unknown", "cancelled"},
    "submitted": {"submitted", "partially_filled", "filled", "cancel_requested", "cancelled", "rejected", "unknown"},
    "partially_filled": {"partially_filled", "filled", "cancel_requested", "cancelled", "unknown"},
    "cancel_requested": {"cancel_requested", "cancelled", "partially_filled", "filled", "unknown"},
    "unknown": {"unknown", "submitted", "partially_filled", "filled", "cancelled", "rejected"},
    "filled": {"filled"},
    "cancelled": {"cancelled"},
    "rejected": {"rejected"},
    "failed": {"failed", "unknown"},
}


class EventRejected(ValueError):
    pass


def deterministic_client_order_id(account_id: int, intent_id: int, attempt: int = 1) -> str:
    value = f"tst-{account_id}-{intent_id}-{attempt}"
    return value[:36]


def _parse_time(value: Any) -> datetime:
    if value is None:
        return now_utc()
    if isinstance(value, datetime):
        return as_utc(value) or now_utc()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventRejected("时间戳无效") from exc
    return as_utc(parsed) or now_utc()


def _owned_lease(db: Session, agent_id: int, lease_id: str | None) -> tuple[SignalLease | None, ExecutionIntent | None, ExecutionTestAccount | None]:
    if lease_id is None:
        return None, None, None
    lease = db.scalar(select(SignalLease).where(SignalLease.lease_token == lease_id, SignalLease.agent_id == agent_id))
    if lease is None:
        raise EventRejected("租约不属于该 agent")
    intent = db.get(ExecutionIntent, lease.intent_id)
    account = db.get(ExecutionTestAccount, intent.account_id) if intent else None
    if account is None:
        raise EventRejected("租约上下文不存在")
    return lease, intent, account


def _order_for_payload(db: Session, payload: dict[str, Any], account_id: int | None) -> ExecutionOrder | None:
    if payload.get("order_id") is not None:
        order = db.get(ExecutionOrder, int(payload["order_id"]))
        if order is not None and (account_id is None or order.account_id == account_id):
            return order
    candidates = [payload.get("client_order_id"), payload.get("provider_order_id")]
    for value in candidates:
        if not value:
            continue
        query = select(ExecutionOrder).where(ExecutionOrder.environment == TEST_ENVIRONMENT)
        if account_id is not None:
            query = query.where(ExecutionOrder.account_id == account_id)
        if value == payload.get("client_order_id"):
            query = query.where(ExecutionOrder.client_order_id == str(value))
        else:
            query = query.where(ExecutionOrder.provider_order_id == str(value))
        row = db.scalar(query.limit(1))
        if row is not None:
            return row
    return None


def _transition(order: ExecutionOrder, status: str) -> None:
    if status not in _TRANSITIONS.get(order.status, set()):
        raise EventRejected(f"非法订单状态转换: {order.status} -> {status}")
    order.status = status
    order.last_update_at = now_utc()
    if status == "submitted" and order.submitted_at is None:
        order.submitted_at = order.last_update_at


def _order_submitted(
    db: Session,
    payload: dict[str, Any],
    lease: SignalLease | None,
    intent: ExecutionIntent | None,
    account: ExecutionTestAccount | None,
    agent_id: int,
) -> tuple[ExecutionOrder, ExecutionFill | None]:
    if account is None:
        raise EventRejected("订单必须绑定 TEST account")
    intent_id = intent.id if intent else payload.get("intent_id")
    if intent is None and intent_id is not None:
        intent = db.get(ExecutionIntent, int(intent_id))
    instrument_id = int(payload.get("instrument_id") or (intent.instrument_id if intent else 0))
    quantity = decimal(payload.get("quantity"))
    if quantity is None or quantity <= 0:
        raise EventRejected("订单数量必须为正数")
    side = str(payload.get("side", "")).lower()
    if side not in {"buy", "sell"}:
        raise EventRejected("订单方向无效")
    price = decimal(payload.get("price"))
    allowed, reason = validate_order_risk(
        db,
        account,
        agent_id=agent_id,
        deployment_id=intent.deployment_id if intent else None,
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        price=price,
        symbol=str(payload.get("symbol") or "").upper() or None,
    )
    if not allowed:
        raise EventRejected(f"risk_rejected:{reason}")
    client_order_id = str(payload.get("client_order_id") or deterministic_client_order_id(account.id, intent.id if intent else 0, lease.attempt if lease else 1))
    if len(client_order_id) > 36:
        raise EventRejected("client_order_id 超过 36 字符")
    existing = db.scalar(
        select(ExecutionOrder).where(
            ExecutionOrder.environment == TEST_ENVIRONMENT,
            ExecutionOrder.account_id == account.id,
            ExecutionOrder.venue == DEFAULT_VENUE,
            ExecutionOrder.client_order_id == client_order_id,
        )
    )
    if existing is not None:
        # Query-before-retry: an UNKNOWN order is returned unchanged and must
        # be reconciled before another submission can be accepted.
        if existing.status == "unknown":
            raise EventRejected("order_unknown_query_before_retry")
        return existing, None
    order = ExecutionOrder(
        account_id=account.id,
        user_id=account.user_id,
        intent_id=intent.id if intent else None,
        lease_id=lease.id if lease else None,
        agent_id=agent_id,
        instrument_id=instrument_id,
        environment=TEST_ENVIRONMENT,
        venue=DEFAULT_VENUE,
        client_order_id=client_order_id,
        provider_order_id=str(payload["provider_order_id"]) if payload.get("provider_order_id") is not None else None,
        side=side,
        order_type=str(payload.get("order_type") or "market"),
        time_in_force=str(payload["time_in_force"]) if payload.get("time_in_force") is not None else None,
        quantity=quantity,
        price=price,
        status="submitted",
        reason=str(payload.get("reason")) if payload.get("reason") else None,
        metadata_json=redacted_event_payload(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        submitted_at=now_utc(),
        last_update_at=now_utc(),
    )
    db.add(order)
    try:
        db.flush()
    except IntegrityError as exc:
        raise EventRejected("订单幂等键冲突") from exc
    return order, None


def _order_update(db: Session, payload: dict[str, Any], account_id: int | None) -> ExecutionOrder:
    order = _order_for_payload(db, payload, account_id)
    if order is None:
        raise EventRejected("订单不存在")
    desired = str(payload.get("status", "")).lower()
    if desired not in _TRANSITIONS:
        raise EventRejected("订单状态无效")
    _transition(order, desired)
    if payload.get("provider_order_id") is not None:
        order.provider_order_id = str(payload["provider_order_id"])
    if payload.get("reason"):
        order.reason = str(payload["reason"])
    return order


def _fill(db: Session, payload: dict[str, Any], account: ExecutionTestAccount | None, agent_id: int) -> tuple[ExecutionOrder, ExecutionFill]:
    order = _order_for_payload(db, payload, account.id if account else None)
    if order is None:
        raise EventRejected("订单不存在")
    if account is None or order.account_id != account.id:
        raise EventRejected("订单 account scope 无效")
    provider_trade_id = str(payload["provider_trade_id"]) if payload.get("provider_trade_id") is not None else None
    if provider_trade_id:
        duplicate = db.scalar(
            select(ExecutionFill).where(
                ExecutionFill.environment == TEST_ENVIRONMENT,
                ExecutionFill.account_id == account.id,
                ExecutionFill.venue == order.venue,
                ExecutionFill.provider_trade_id == provider_trade_id,
            )
        )
        if duplicate is not None:
            return order, duplicate
    quantity = decimal(payload.get("quantity"))
    price = decimal(payload.get("price"))
    if quantity is None or quantity <= 0 or price is None or price <= 0:
        raise EventRejected("成交数量和价格必须为正数")
    filled = sum((Decimal(str(row.quantity)) for row in db.scalars(select(ExecutionFill).where(ExecutionFill.order_id == order.id)).all()), Decimal("0"))
    if filled + quantity > Decimal(str(order.quantity)):
        raise EventRejected("成交数量超过订单数量")
    side = str(payload.get("side") or order.side).lower()
    if side not in {"buy", "sell"}:
        raise EventRejected("成交方向无效")
    fee = decimal(payload.get("fee"), Decimal("0")) or Decimal("0")
    fill = ExecutionFill(
        order_id=order.id,
        account_id=account.id,
        user_id=account.user_id,
        agent_id=agent_id,
        environment=TEST_ENVIRONMENT,
        venue=order.venue,
        provider_trade_id=provider_trade_id,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        fee_asset=str(payload["fee_asset"]) if payload.get("fee_asset") is not None else None,
        fill_time=_parse_time(payload.get("fill_time")),
    )
    db.add(fill)
    db.flush()
    total = filled + quantity
    _transition(order, "filled" if total >= Decimal(str(order.quantity)) else "partially_filled")
    if total >= Decimal(str(order.quantity)) and order.intent_id:
        intent = db.get(ExecutionIntent, order.intent_id)
        if intent is not None:
            intent.status = "consumed"
            intent.consumed_at = now_utc()
    return order, fill


def record_event(
    db: Session,
    *,
    agent_id: int,
    event_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    event_nonce: str | None = None,
    account_id: int | None = None,
    lease_id: str | None = None,
    occurred_at: Any = None,
) -> ExecutionEvent:
    if not event_id or len(event_id) > 128:
        raise EventRejected("event_id 无效")
    if event_type not in EVENT_TYPES:
        raise EventRejected("event_type 无效")
    safe_payload = redacted_event_payload(payload)
    payload_hash = canonical_hash(safe_payload)
    existing = db.scalar(
        select(ExecutionEvent).where(
            ExecutionEvent.environment == TEST_ENVIRONMENT,
            ExecutionEvent.event_id == event_id,
        )
    )
    if existing is not None:
        if existing.payload_hash == payload_hash and existing.agent_id == agent_id and existing.event_type == event_type:
            return existing
        raise EventRejected("event_id 已用于其他事件")
    lease, intent, lease_account = _owned_lease(db, agent_id, lease_id)
    account = lease_account
    if account_id is not None:
        supplied = db.get(ExecutionTestAccount, int(account_id))
        if supplied is None or supplied.environment != TEST_ENVIRONMENT:
            raise EventRejected("account 不存在")
        if account is not None and supplied.id != account.id:
            raise EventRejected("account 与租约不匹配")
        account = supplied
    order: ExecutionOrder | None = None
    fill: ExecutionFill | None = None
    if event_type in {"lease_ack", "lease_reject"}:
        if lease is None:
            raise EventRejected("租约事件缺少 lease_id")
        acknowledge_lease(
            db,
            db.get(ExecutionAgent, agent_id),
            lease.id,
            accepted=event_type == "lease_ack",
            reason=str(safe_payload.get("reason")) if safe_payload.get("reason") else None,
        )
    elif event_type == "order_submitted":
        order, _ = _order_submitted(db, safe_payload, lease, intent, account, agent_id)
    elif event_type == "order_update":
        order = _order_update(db, safe_payload, account.id if account else None)
    elif event_type == "fill":
        order, fill = _fill(db, safe_payload, account, agent_id)
    elif event_type == "reconciliation":
        reconciliation_status = str(safe_payload.get("status", "")).lower()
        if reconciliation_status == "ok" and account is not None:
            account.last_reconciled_at = now_utc()
        elif reconciliation_status in {"mismatch", "unknown"}:
            order = _order_for_payload(db, safe_payload, account.id if account else None)
            if order is not None:
                _transition(order, "unknown")
    event_hash = canonical_hash(
        {
            "event_id": event_id,
            "event_nonce": event_nonce,
            "agent_id": agent_id,
            "account_id": account.id if account else account_id,
            "lease_id": lease.id if lease else None,
            "event_type": event_type,
            "payload_hash": payload_hash,
        }
    )
    event = ExecutionEvent(
        event_id=event_id,
        event_nonce=event_nonce,
        agent_id=agent_id,
        account_id=account.id if account else account_id,
        intent_id=intent.id if intent else (order.intent_id if order else None),
        lease_id=lease.id if lease else None,
        order_id=order.id if order else None,
        fill_id=fill.id if fill else None,
        environment=TEST_ENVIRONMENT,
        venue=account.venue if account else (order.venue if order else None),
        event_type=event_type,
        payload=safe_payload,
        payload_hash=payload_hash,
        event_hash=event_hash,
        occurred_at=_parse_time(occurred_at),
        received_at=now_utc(),
    )
    if fill is not None:
        fill.event_hash = event_hash
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        raise EventRejected("事件幂等键冲突") from exc
    return event


def order_payload(order: ExecutionOrder | None) -> dict | None:
    if order is None:
        return None
    return {
        "id": order.id,
        "account_id": order.account_id,
        "user_id": order.user_id,
        "intent_id": order.intent_id,
        "lease_id": order.lease_id,
        "agent_id": order.agent_id,
        "instrument_id": order.instrument_id,
        "environment": order.environment,
        "venue": order.venue,
        "client_order_id": order.client_order_id,
        "provider_order_id": order.provider_order_id,
        "side": order.side,
        "order_type": order.order_type,
        "time_in_force": order.time_in_force,
        "quantity": order.quantity,
        "price": order.price,
        "status": order.status,
        "reason": order.reason,
        "submitted_at": as_utc(order.submitted_at).isoformat() if order.submitted_at else None,
        "last_update_at": as_utc(order.last_update_at).isoformat() if order.last_update_at else None,
        "created_at": as_utc(order.created_at).isoformat() if order.created_at else None,
    }


def fill_payload(fill: ExecutionFill | None) -> dict | None:
    if fill is None:
        return None
    return {
        "id": fill.id,
        "order_id": fill.order_id,
        "account_id": fill.account_id,
        "provider_trade_id": fill.provider_trade_id,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "fee": fill.fee,
        "fee_asset": fill.fee_asset,
        "fill_time": as_utc(fill.fill_time).isoformat() if fill.fill_time else None,
        "event_hash": fill.event_hash,
    }


def event_payload(event: ExecutionEvent) -> dict:
    return {
        "id": event.id,
        "event_id": event.event_id,
        "event_nonce": event.event_nonce,
        "agent_id": event.agent_id,
        "account_id": event.account_id,
        "intent_id": event.intent_id,
        "lease_id": event.lease_id,
        "order_id": event.order_id,
        "fill_id": event.fill_id,
        "environment": event.environment,
        "venue": event.venue,
        "event_type": event.event_type,
        "payload": event.payload,
        "payload_hash": event.payload_hash,
        "event_hash": event.event_hash,
        "occurred_at": as_utc(event.occurred_at).isoformat() if event.occurred_at else None,
        "received_at": as_utc(event.received_at).isoformat() if event.received_at else None,
    }
