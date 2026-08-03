from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.services.portfolio import get_or_create_default_portfolio, govern_manual_transactions
from app.services.portfolio.journal_drafts import create_ibkr_journal_drafts
from .analytics import rebuild_all_analytics
from .analytics import decimal_value
from .db_models import IbkrFlexRecord, IbkrFlexSyncRun
from .flex_client import IbkrFlexClient
from .flex_parser import PARSER_VERSION, parse_flex_report
from .exceptions import IbkrError
from .propagation import invalidate_portfolio_consumers
from .reconciliation import reconcile_positions

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "partial_failed")


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, IbkrError):
        text = exc.message.replace("\n", " ").strip()
        return (text or type(exc).__name__)[:1000]
    return f"同步内部错误（{type(exc).__name__}）"


def _archive_xml(xml_text: str, run_id: int) -> str:
    root = Path(get_settings().archive_dir) / "ibkr" / "flex"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    target = root / f"flex-report-{_now().strftime('%Y%m%dT%H%M%SZ')}-run-{run_id}.xml"
    fd, temporary = tempfile.mkstemp(prefix=".ibkr-flex-", suffix=".tmp", dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(xml_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


def request_sync(db: Session, *, user_id: int, trigger_type: str = "manual") -> tuple[IbkrFlexSyncRun, bool]:
    now = _now()
    active = db.scalar(select(IbkrFlexSyncRun).where(
        IbkrFlexSyncRun.user_id == user_id, IbkrFlexSyncRun.status.in_(ACTIVE_STATUSES),
    ).order_by(IbkrFlexSyncRun.id.desc()).limit(1))
    if active:
        heartbeat = active.heartbeat_at or active.started_at or active.imported_at
        if heartbeat and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        if heartbeat and now - heartbeat <= timedelta(hours=2):
            return active, False
        active.status = "failed"
        active.stage = "failed"
        active.error_stage = active.stage
        active.error_code = "STALE_SYNC_RECOVERED"
        active.error_message = "上一次同步超过两小时未更新，已安全标记失败"
        active.completed_at = now
        db.commit()
    run = IbkrFlexSyncRun(
        user_id=user_id, trigger_type=trigger_type, status="queued", stage="requested",
        started_at=now, heartbeat_at=now, parser_version=PARSER_VERSION,
        raw_record_count=0, normalized_record_count=0, source_hash=None,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = db.scalar(select(IbkrFlexSyncRun).where(
            IbkrFlexSyncRun.user_id == user_id, IbkrFlexSyncRun.status.in_(ACTIVE_STATUSES),
        ).order_by(IbkrFlexSyncRun.id.desc()).limit(1))
        if active:
            return active, False
        raise
    db.refresh(run)
    return run, True


def request_due_syncs(db: Session, *, now: datetime | None = None, interval_hours: int = 6) -> list[int]:
    """Create idempotent scheduled runs only for users who previously enabled Flex."""
    current = now or _now()
    cutoff = current - timedelta(hours=max(1, interval_hours))
    user_ids = list(db.scalars(select(IbkrFlexSyncRun.user_id).where(
        IbkrFlexSyncRun.status == "completed",
    ).distinct()).all())
    created_ids: list[int] = []
    for user_id in user_ids:
        latest = db.scalar(select(IbkrFlexSyncRun).where(
            IbkrFlexSyncRun.user_id == user_id,
            IbkrFlexSyncRun.status == "completed",
        ).order_by(IbkrFlexSyncRun.completed_at.desc().nullslast(), IbkrFlexSyncRun.id.desc()).limit(1))
        completed_at = latest.completed_at if latest else None
        if completed_at and completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        if completed_at and completed_at > cutoff:
            continue
        run, created = request_sync(db, user_id=user_id, trigger_type="scheduled")
        if created:
            created_ids.append(run.id)
    return created_ids


def _stage(db: Session, run: IbkrFlexSyncRun, stage: str, **values: Any) -> None:
    run.stage = stage
    run.status = "running" if stage not in {"completed", "failed"} else stage
    run.heartbeat_at = _now()
    for key, value in values.items():
        setattr(run, key, value)
    db.commit()


def _import_report(db: Session, run: IbkrFlexSyncRun, report) -> int:
    run.account_id = report.metadata.account_id
    run.report_from_date = report.metadata.from_date
    run.report_to_date = report.metadata.to_date
    run.report_period = report.metadata.period
    run.generated_at = report.metadata.generated_at
    run.source_hash = report.source_hash
    run.parser_version = report.parser_version
    run.raw_record_count = report.record_count
    run.normalized_record_count = report.record_count
    run.section_counts = {section: len(rows) for section, rows in report.records.items()}
    run.warnings = report.warnings
    run.warning_count = len(report.warnings)
    for section, rows in report.records.items():
        db.add_all([IbkrFlexRecord(
            sync_run_id=run.id, section=section, source_id=row.source_id, source_index=row.source_index,
            account_id=row.account_id, symbol=row.symbol, conid=row.conid, currency=row.currency,
            asset_category=row.asset_category, description=row.description, report_date=row.report_date,
            occurred_at=row.occurred_at, amount=row.amount, quantity=row.quantity, price=row.price,
            raw_payload=row.raw_fields,
        ) for row in rows])
    db.flush()
    return report.record_count


def _apply_account_cash(db: Session, run: IbkrFlexSyncRun, portfolio) -> dict[str, Any]:
    rows = list(db.scalars(select(IbkrFlexRecord).where(
        IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "cash_reports",
    )).all())
    base = next((row for row in rows if row.currency in {"BASE", portfolio.base_currency}), None)
    if base is None:
        return {"updated": False, "warning": "Flex 未提供可识别的基础币种现金汇总"}
    amount = decimal_value(base.raw_payload or {}, "endingCash", "endingSettledCash", "cash")
    if amount is None:
        return {"updated": False, "warning": "Flex 基础币种现金汇总缺少 endingCash"}
    previous = portfolio.cash_balance
    portfolio.cash_balance = float(amount)
    portfolio.updated_at = _now()
    return {"updated": True, "previous": previous, "value": str(amount), "source": "IBKR Flex"}


async def execute_sync(sync_run_id: int, client: IbkrFlexClient | None = None) -> dict[str, Any]:
    owned_client = client is None
    client = client or IbkrFlexClient()
    with SessionLocal() as db:
        run = db.get(IbkrFlexSyncRun, sync_run_id)
        if run is None:
            return {"sync_run_id": sync_run_id, "status": "missing"}
        if run.status in TERMINAL_STATUSES:
            return sync_result(run)
        stage = "requested"
        try:
            _stage(db, run, "downloading")
            stage = "downloading"
            downloaded = await client.download_complete_report()
            run.flex_reference_hint = f"******{downloaded['reference_code'][-4:]}"
            _stage(db, run, "downloaded")
            run.archive_path = _archive_xml(downloaded["xml"], run.id)
            _stage(db, run, "parsing")
            stage = "parsing"
            report = parse_flex_report(downloaded["xml"])
            existing = db.scalar(select(IbkrFlexSyncRun).where(
                IbkrFlexSyncRun.user_id == run.user_id, IbkrFlexSyncRun.source_hash == report.source_hash,
                IbkrFlexSyncRun.id != run.id, IbkrFlexSyncRun.normalized_record_count > 0,
            ).order_by(IbkrFlexSyncRun.id.desc()).limit(1))
            if existing:
                run.status = "completed"; run.stage = "completed"; run.completed_at = _now()
                run.account_id = existing.account_id; run.report_from_date = existing.report_from_date; run.report_to_date = existing.report_to_date
                run.section_counts = existing.section_counts; run.raw_record_count = existing.raw_record_count
                run.import_counts = {"total": 0, "inserted": 0, "skipped": report.record_count, "reused_sync_run_id": existing.id}
                portfolio = get_or_create_default_portfolio(db, run.user_id)
                governance = govern_manual_transactions(db, portfolio, existing)
                journal_drafts = create_ibkr_journal_drafts(
                    db, user_id=run.user_id, sync_run_id=existing.id
                )
                propagation = invalidate_portfolio_consumers(run.user_id)
                run.reconciliation = {
                    "reused_sync_run_id": existing.id,
                    "applied_updates": governance["superseded"],
                    "manual_transaction_governance": governance,
                    "journal_drafts": journal_drafts,
                }
                run.propagation = {
                    "portfolio_updated": True, "derived_data_rebuilt": True,
                    "ai_context_updated": True, "idempotent_reuse": True,
                    "caches_invalidated": propagation["invalidated"],
                    "warnings": propagation["warnings"],
                    "portfolio_propagated_at": _now().isoformat(),
                }
                db.commit()
                return sync_result(run)
            _stage(db, run, "importing")
            stage = "importing"
            inserted = _import_report(db, run, report)
            run.import_counts = {"total": report.record_count, "inserted": inserted, "updated": 0, "skipped": 0,
                                 **{key: len(value) for key, value in report.records.items()}}
            db.commit()
            stage = "reconciling"
            run.stage = stage; run.heartbeat_at = _now()
            portfolio = get_or_create_default_portfolio(db, run.user_id)
            reconciliation = reconcile_positions(
                db, user_id=run.user_id, sync_run_id=run.id, dry_run=False, commit=False,
                allow_closure="positions" in report.present_sections,
            )
            reconciliation["manual_transaction_governance"] = govern_manual_transactions(db, portfolio, run)
            reconciliation["cash"] = _apply_account_cash(db, run, portfolio)
            stage = "rebuilding"
            run.stage = stage; run.heartbeat_at = _now()
            derived = rebuild_all_analytics(db, run)
            reconciliation["journal_drafts"] = create_ibkr_journal_drafts(
                db, user_id=run.user_id, sync_run_id=run.id
            )
            propagation = invalidate_portfolio_consumers(run.user_id)
            run.reconciliation = reconciliation
            run.propagation = {
                "portfolio_updated": True, "derived_data_rebuilt": True,
                "derived_counts": derived, "caches_invalidated": propagation["invalidated"],
                "ai_context_updated": True, "warnings": propagation["warnings"],
                "portfolio_propagated_at": _now().isoformat(),
            }
            run.status = "completed"; run.stage = "completed"; run.completed_at = _now(); run.heartbeat_at = _now()
            db.commit()
            return sync_result(run)
        except Exception as exc:
            db.rollback()
            run = db.get(IbkrFlexSyncRun, sync_run_id)
            if run:
                run.status = "partial_failed" if run.normalized_record_count else "failed"
                run.stage = "failed"; run.error_stage = stage; run.error_code = type(exc).__name__
                run.error_message = _safe_error(exc); run.completed_at = _now(); run.heartbeat_at = _now()
                db.commit()
                return sync_result(run)
            raise
        finally:
            if owned_client:
                await client.close()


def sync_result(run: IbkrFlexSyncRun) -> dict[str, Any]:
    return {
        "sync_run_id": run.id, "status": run.status, "stage": run.stage,
        "started_at": run.started_at, "completed_at": run.completed_at,
        "imported": run.import_counts or {}, "reconciliation": run.reconciliation or {},
        "propagation": run.propagation or {}, "warnings": run.warnings or [],
        "error": ({"stage": run.error_stage, "code": run.error_code, "message": run.error_message} if run.error_code else None),
    }
