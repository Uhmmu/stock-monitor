from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import IbkrFlexRecord, IbkrFlexSyncRun
from .flex_parser import parse_flex_report


def mask_account(value: str | None) -> str | None:
    if not value:
        return None
    return value[:2] + "*" * max(4, len(value) - 4) + value[-2:]


def inspect_existing_report(path: str | Path) -> dict[str, Any]:
    report = parse_flex_report(Path(path).read_text(encoding="utf-8"))
    return {
        "source_hash": report.source_hash,
        "parser_version": report.parser_version,
        "report_from_date": report.metadata.from_date,
        "report_to_date": report.metadata.to_date,
        "generated_at": report.metadata.generated_at,
        "account_id_masked": mask_account(report.metadata.account_id),
        "section_counts": {section: len(rows) for section, rows in report.records.items()},
        "raw_record_count": report.record_count,
        "warnings": report.warnings,
    }


def import_existing_report(db: Session, *, user_id: int, path: str | Path, dry_run: bool = True) -> dict[str, Any]:
    report = parse_flex_report(Path(path).read_text(encoding="utf-8"))
    existing = db.scalar(select(IbkrFlexSyncRun).where(
        IbkrFlexSyncRun.user_id == user_id, IbkrFlexSyncRun.source_hash == report.source_hash,
    ))
    counts = {section: len(rows) for section, rows in report.records.items()}
    result = {
        "dry_run": dry_run, "idempotent_existing": existing is not None,
        "source_hash": report.source_hash, "account_id_masked": mask_account(report.metadata.account_id),
        "section_counts": counts, "raw_record_count": report.record_count,
        "records_to_insert": 0 if existing else report.record_count, "warning_count": len(report.warnings),
        "warnings": report.warnings,
    }
    if dry_run or existing:
        if existing:
            result["sync_run_id"] = existing.id
        return result
    now = datetime.now(UTC)
    run = IbkrFlexSyncRun(
        user_id=user_id, account_id=report.metadata.account_id,
        report_from_date=report.metadata.from_date, report_to_date=report.metadata.to_date,
        report_period=report.metadata.period, generated_at=report.metadata.generated_at,
        completed_at=now, status="completed", source_hash=report.source_hash,
        parser_version=report.parser_version, raw_record_count=report.record_count,
        normalized_record_count=report.record_count, warning_count=len(report.warnings),
        section_counts=counts, warnings=report.warnings,
    )
    db.add(run)
    db.flush()
    for section, rows in report.records.items():
        db.add_all([IbkrFlexRecord(
            sync_run_id=run.id, section=section, source_id=row.source_id, source_index=row.source_index,
            account_id=row.account_id, symbol=row.symbol, conid=row.conid, currency=row.currency,
            asset_category=row.asset_category, description=row.description, report_date=row.report_date,
            occurred_at=row.occurred_at, amount=row.amount, quantity=row.quantity, price=row.price,
            raw_payload=row.raw_fields,
        ) for row in rows])
    db.commit()
    result.update({"sync_run_id": run.id, "records_to_insert": report.record_count})
    return result


def latest_run(db: Session, user_id: int) -> IbkrFlexSyncRun | None:
    return db.scalar(select(IbkrFlexSyncRun).where(
        IbkrFlexSyncRun.user_id == user_id,
        IbkrFlexSyncRun.normalized_record_count > 0,
    ).order_by(IbkrFlexSyncRun.completed_at.desc(), IbkrFlexSyncRun.id.desc()).limit(1))


def latest_sync_attempt(db: Session, user_id: int) -> IbkrFlexSyncRun | None:
    return db.scalar(select(IbkrFlexSyncRun).where(IbkrFlexSyncRun.user_id == user_id).order_by(
        IbkrFlexSyncRun.started_at.desc().nullslast(), IbkrFlexSyncRun.id.desc(),
    ).limit(1))


def page_records(
    db: Session, *, user_id: int, section: str, page: int = 1, page_size: int = 50,
    symbol: str | None = None, currency: str | None = None,
) -> dict[str, Any]:
    run = latest_run(db, user_id)
    if run is None:
        return {"items": [], "page": page, "page_size": page_size, "total": 0, "has_more": False}
    filters = [IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == section]
    if symbol:
        filters.append(IbkrFlexRecord.symbol == symbol.upper())
    if currency:
        filters.append(IbkrFlexRecord.currency == currency.upper())
    total = db.scalar(select(func.count()).select_from(IbkrFlexRecord).where(*filters)) or 0
    rows = db.scalars(select(IbkrFlexRecord).where(*filters).order_by(
        IbkrFlexRecord.occurred_at.desc().nullslast(), IbkrFlexRecord.report_date.desc().nullslast(), IbkrFlexRecord.source_index,
    ).offset((page - 1) * page_size).limit(page_size)).all()
    items = [{
        "id": row.id, "section": row.section, "symbol": row.symbol, "conid": row.conid,
        "currency": row.currency, "asset_category": row.asset_category, "description": row.description,
        "report_date": row.report_date, "occurred_at": row.occurred_at,
        "amount": row.amount, "quantity": row.quantity, "price": row.price,
        "fields": {k: v for k, v in row.raw_payload.items() if k not in {"accountId", "acctAlias"}},
        "source": "IBKR Flex",
    } for row in rows]
    return {"items": items, "page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total}
