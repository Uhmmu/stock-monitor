"""Manual Client Portal Gateway position sync.

Semantics (deliberately different from Flex in sync.py):

* Gateway sync reads the *current* account state: one fetch of accounts +
  paginated positions, normalized, then persisted as a current-state
  replacement in a single transaction. It never writes ``portfolio_positions``
  and never propagates portfolio authority — Flex remains the portfolio
  authority source.
* Trigger is manual only. There is no beat schedule and no auto-sync here.
* An empty position list is treated as a real empty account only because the
  brokerage session was verified connected and the account was validated
  against the session's account allowlist right before the fetch. Any
  upstream failure keeps the previously stored positions untouched.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal

from .client_portal_client import IbkrClientPortalClient
from .db_models import IbkrCpPosition, IbkrCpSyncRun
from .exceptions import (
    IbkrAuthenticationRequiredError, IbkrBrokerageSessionError, IbkrConfigurationError, IbkrError,
)
from .service import IbkrReadOnlyService

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed")
KNOWN_ASSET_CLASSES = {
    "STK", "ETF", "ADR", "OPT", "FUT", "FOP", "CASH", "BOND", "MF", "IND", "CMDTY", "CRYPTO", "WAR",
}

# Gateway returns bare local symbols for some foreign listings; map the known
# one to its project/Yahoo form so both sources display the same ticker.
GATEWAY_SYMBOL_ALIASES = {"1578": "1578.T"}


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, IbkrError):
        text = exc.message.replace("\n", " ").strip()
        return (text or type(exc).__name__)[:1000]
    return f"同步内部错误（{type(exc).__name__}）"


def request_cp_sync(db: Session, *, user_id: int, trigger_type: str = "manual") -> tuple[IbkrCpSyncRun, bool]:
    """Create one Gateway sync run per user; a live run is returned, not duplicated."""
    now = _now()
    active = db.scalar(select(IbkrCpSyncRun).where(
        IbkrCpSyncRun.user_id == user_id, IbkrCpSyncRun.status.in_(ACTIVE_STATUSES),
    ).order_by(IbkrCpSyncRun.id.desc()).limit(1))
    if active:
        heartbeat = active.heartbeat_at or active.started_at or active.created_at
        if heartbeat and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        if heartbeat and now - heartbeat <= timedelta(hours=2):
            return active, False
        active.status = "failed"
        active.stage = "failed"
        active.error_stage = active.stage
        active.error_code = "STALE_SYNC_RECOVERED"
        active.error_message = "上一次 Gateway 同步超过两小时未更新，已安全标记失败"
        active.completed_at = now
        db.commit()
    run = IbkrCpSyncRun(
        user_id=user_id, trigger_type=trigger_type, status="queued", stage="requested",
        started_at=now, heartbeat_at=now,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = db.scalar(select(IbkrCpSyncRun).where(
            IbkrCpSyncRun.user_id == user_id, IbkrCpSyncRun.status.in_(ACTIVE_STATUSES),
        ).order_by(IbkrCpSyncRun.id.desc()).limit(1))
        if active:
            return active, False
        raise
    db.refresh(run)
    return run, True


def select_account(account_ids: list[str], configured: str) -> str:
    if configured:
        if configured not in account_ids:
            raise IbkrConfigurationError("IBKR_CP_ACCOUNT_ID 指定的账户不在当前 Gateway 会话返回的账户列表中")
        return configured
    if len(account_ids) == 1:
        return account_ids[0]
    raise IbkrConfigurationError(
        f"Gateway 会话返回 {len(account_ids)} 个账户，请在服务端配置 IBKR_CP_ACCOUNT_ID 后重试"
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def normalize_cp_positions(rows: list[dict[str, Any]], *, account_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn service-normalized positions into DB-ready dicts.

    Unknown asset classes and duplicate conids produce warnings, never a
    failure. Rows without a usable conid or quantity are skipped with a
    warning because they cannot represent a current position.
    """
    warnings: list[str] = []
    prepared_by_conid: dict[str, dict[str, Any]] = {}
    for row in rows:
        conid = row.get("conid")
        conid = str(conid) if conid is not None and str(conid).strip() else None
        quantity = _decimal(row.get("position"))
        symbol = (row.get("symbol") or None)
        if symbol:
            symbol = GATEWAY_SYMBOL_ALIASES.get(symbol, symbol)
        if conid is None:
            warnings.append(f"跳过缺少 conid 的仓位记录（symbol={symbol or '未知'}）")
            continue
        if quantity is None:
            warnings.append(f"跳过数量缺失或无效的仓位记录（symbol={symbol or conid}）")
            continue
        if conid in prepared_by_conid:
            warnings.append(f"Gateway 返回重复 conid {conid}，已保留最后一条")
        asset_class = row.get("asset_class")
        if asset_class and asset_class not in KNOWN_ASSET_CLASSES:
            warnings.append(f"未知资产类型 {asset_class}（symbol={symbol or conid}）已按原样保存")
        prepared_by_conid[conid] = {
            "account_id": account_id,
            "conid": conid,
            "symbol": symbol,
            "asset_class": asset_class,
            "currency": row.get("currency"),
            "exchange": row.get("exchange"),
            "quantity": quantity,
            "average_cost": _decimal(row.get("average_cost")),
            "market_price": _decimal(row.get("market_price")),
            "market_value": _decimal(row.get("market_value")),
            "unrealized_pnl": _decimal(row.get("unrealized_pnl")),
            "realized_pnl": _decimal(row.get("realized_pnl")),
            "raw_payload": {key: value for key, value in row.items() if key != "account_id"},
        }
    return list(prepared_by_conid.values()), warnings


def _persist_positions(
    db: Session, run: IbkrCpSyncRun, prepared: list[dict[str, Any]],
) -> dict[str, int]:
    """Replace the current-state position set in one transaction.

    Rows absent from this fetch are soft-marked ``removed`` (never deleted)
    so the previous state stays auditable and a later re-appearance reuses
    the same row via the (user, account, conid) unique key.
    """
    now = _now()
    existing = db.scalars(select(IbkrCpPosition).where(
        IbkrCpPosition.user_id == run.user_id, IbkrCpPosition.account_id == run.account_id,
    )).all()
    by_conid = {row.conid: row for row in existing}
    incoming = {row["conid"]: row for row in prepared}
    inserted = updated = removed = 0
    for conid, data in incoming.items():
        current = by_conid.get(conid)
        if current is None:
            db.add(IbkrCpPosition(
                user_id=run.user_id, last_sync_run_id=run.id, last_synced_at=now,
                status="active", removed_at=None, removed_run_id=None, **data,
            ))
            inserted += 1
        else:
            for key, value in data.items():
                setattr(current, key, value)
            current.source = "client_portal_gateway"
            current.status = "active"
            current.removed_at = None
            current.removed_run_id = None
            current.last_sync_run_id = run.id
            current.last_synced_at = now
            updated += 1
    for conid, current in by_conid.items():
        if conid in incoming or current.status != "active":
            continue
        current.status = "removed"
        current.removed_at = now
        current.removed_run_id = run.id
        removed += 1
    counts = {"inserted": inserted, "updated": updated, "removed": removed}
    run.position_count = len(incoming)
    run.inserted_count = inserted
    run.updated_count = updated
    run.removed_count = removed
    return counts


def _stage(db: Session, run: IbkrCpSyncRun, stage: str, **values: Any) -> None:
    run.stage = stage
    run.status = "running" if stage not in {"completed", "failed"} else stage
    run.heartbeat_at = _now()
    for key, value in values.items():
        setattr(run, key, value)
    db.commit()


def _build_service() -> IbkrReadOnlyService:
    return IbkrReadOnlyService(IbkrClientPortalClient())


async def execute_cp_sync(sync_run_id: int, service: IbkrReadOnlyService | None = None) -> dict[str, Any]:
    owned = service is None
    service = service or _build_service()
    began = time.perf_counter()
    with SessionLocal() as db:
        run = db.get(IbkrCpSyncRun, sync_run_id)
        if run is None:
            return {"sync_run_id": sync_run_id, "status": "missing"}
        if run.status in TERMINAL_STATUSES:
            return cp_sync_result(run)
        stage = "requested"
        try:
            _stage(db, run, "connecting")
            stage = "connecting"
            auth = (await service.auth_status())["normalized"]
            if not auth["authenticated"]:
                raise IbkrAuthenticationRequiredError("Gateway 会话尚未完成认证，请先在管理页登录")
            if not auth["connected"]:
                await service.initialize_session()
                rechecked = (await service.auth_status())["normalized"]
                if not rechecked["connected"]:
                    raise IbkrBrokerageSessionError("Brokerage Session 初始化后仍未连接")

            _stage(db, run, "fetching")
            stage = "fetching"
            accounts = (await service.accounts(force=True))["normalized"]
            account_ids = [row["account_id"] for row in accounts]
            if not account_ids:
                raise IbkrAuthenticationRequiredError("Gateway 会话未返回任何可用账户")
            account_id = select_account(account_ids, get_settings().ibkr_cp_account_id)
            run.account_id = account_id
            fetched = (await service.positions(account_id))["normalized"]
            prepared, warnings = normalize_cp_positions(fetched, account_id=account_id)

            _stage(db, run, "persisting", warnings=warnings)
            stage = "persisting"
            counts = _persist_positions(db, run, prepared)
            # Gateway is the highest-priority source for current position
            # quantities: propagate immediately in the same transaction.
            from .cp_propagation import propagate_cp_positions_to_portfolio
            propagation = propagate_cp_positions_to_portfolio(db, user_id=run.user_id, run_id=run.id, prepared=prepared)
            run.propagation = propagation
            run.status = "completed"
            run.stage = "completed"
            run.completed_at = _now()
            run.heartbeat_at = _now()
            run.duration_ms = round((time.perf_counter() - began) * 1000)
            db.commit()
            if propagation.get("applied"):
                from .propagation import invalidate_portfolio_consumers
                invalidate_portfolio_consumers(run.user_id)
            return cp_sync_result(run)
        except Exception as exc:
            db.rollback()
            run = db.get(IbkrCpSyncRun, sync_run_id)
            if run:
                run.status = "failed"
                run.stage = "failed"
                run.error_stage = stage
                run.error_code = type(exc).__name__ if not isinstance(exc, IbkrError) else exc.code
                run.error_message = _safe_error(exc)
                run.completed_at = _now()
                run.heartbeat_at = _now()
                run.duration_ms = round((time.perf_counter() - began) * 1000)
                db.commit()
                return cp_sync_result(run)
            raise
        finally:
            if owned:
                await service.client.close()


def cp_sync_result(run: IbkrCpSyncRun) -> dict[str, Any]:
    return {
        "sync_run_id": run.id, "status": run.status, "stage": run.stage,
        "trigger_type": run.trigger_type, "started_at": run.started_at,
        "completed_at": run.completed_at, "duration_ms": run.duration_ms,
        "position_count": run.position_count, "counts": {
            "inserted": run.inserted_count, "updated": run.updated_count, "removed": run.removed_count,
        },
        "warnings": run.warnings or [],
        "propagation": run.propagation or {},
        "error": ({"stage": run.error_stage, "code": run.error_code, "message": run.error_message}
                  if run.error_code else None),
    }
