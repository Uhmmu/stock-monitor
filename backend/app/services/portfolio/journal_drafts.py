"""Create idempotent, broker-fact journal drafts after position reconciliation."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.ibkr.analytics import decimal_value
from app.integrations.ibkr.db_models import (
    IbkrFlexRecord,
    IbkrFlexSyncRun,
    IbkrPortfolioAuthorityAudit,
)
from app.models import PortfolioPosition, TradeLog


def _float(value):
    return float(value) if value is not None else None


def _side(row: IbkrFlexRecord) -> str:
    fields = row.raw_payload or {}
    value = str(fields.get("buySell") or fields.get("side") or "").upper()
    return "卖出" if value in {"SELL", "SLD", "S"} or (row.quantity or 0) < 0 else "买入"


def create_ibkr_journal_drafts(db: Session, *, user_id: int, sync_run_id: int) -> dict[str, int]:
    """Create one pending journal per changed position in this exact sync run.

    The unique database key makes retries harmless. Only applied reconciliation
    audits qualify, so merely re-downloading an unchanged Flex report creates no
    new journal entry.
    """
    run = db.get(IbkrFlexSyncRun, sync_run_id)
    if run is None or run.user_id != user_id:
        raise ValueError("IBKR sync run not found")
    audits = list(db.scalars(select(IbkrPortfolioAuthorityAudit).where(
        IbkrPortfolioAuthorityAudit.user_id == user_id,
        IbkrPortfolioAuthorityAudit.sync_run_id == sync_run_id,
        IbkrPortfolioAuthorityAudit.application_status == "applied",
    ).order_by(IbkrPortfolioAuthorityAudit.id)).all())
    grouped: dict[int, list[IbkrPortfolioAuthorityAudit]] = defaultdict(list)
    for audit in audits:
        grouped[audit.portfolio_position_id].append(audit)
    if not grouped:
        return {"created": 0, "reused": 0, "changed_positions": 0}

    previous_run = db.scalar(select(IbkrFlexSyncRun).where(
        IbkrFlexSyncRun.user_id == user_id,
        IbkrFlexSyncRun.id != sync_run_id,
        IbkrFlexSyncRun.status == "completed",
        IbkrFlexSyncRun.report_to_date <= run.report_to_date,
    ).order_by(IbkrFlexSyncRun.report_to_date.desc(), IbkrFlexSyncRun.id.desc()).limit(1)) if run.report_to_date else None
    trades = list(db.scalars(select(IbkrFlexRecord).where(
        IbkrFlexRecord.sync_run_id == sync_run_id,
        IbkrFlexRecord.section == "trades",
    ).order_by(IbkrFlexRecord.occurred_at.desc(), IbkrFlexRecord.id.desc())).all())
    created = reused = 0
    for position_id, position_audits in grouped.items():
        existing = db.scalar(select(TradeLog.id).where(
            TradeLog.user_id == user_id,
            TradeLog.ibkr_sync_run_id == sync_run_id,
            TradeLog.ibkr_position_id == position_id,
        ))
        if existing:
            reused += 1
            continue
        position = db.get(PortfolioPosition, position_id)
        if position is None:
            continue
        symbol_trades = [row for row in trades if (row.symbol or "").upper() == position.symbol.upper()]
        if previous_run and previous_run.report_to_date:
            recent = [row for row in symbol_trades if (row.report_date and row.report_date > previous_run.report_to_date)]
            if recent:
                symbol_trades = recent
        # A full Flex report repeats historical trades. If the report boundary
        # cannot isolate the delta (including two refreshes on the same day),
        # keep only executions from the latest trade date instead of copying the
        # complete statement history into one journal card.
        if symbol_trades:
            latest_trade_date = (symbol_trades[0].occurred_at.date() if symbol_trades[0].occurred_at else symbol_trades[0].report_date)
            symbol_trades = [row for row in symbol_trades if (
                row.occurred_at.date() if row.occurred_at else row.report_date
            ) == latest_trade_date]
        changes = {row.conflict_type: {"before": row.previous_value, "after": row.authoritative_value} for row in position_audits}
        quantity_change = changes.get("quantity") or changes.get("position_closed")
        before = Decimal(str(quantity_change["before"])) if quantity_change and quantity_change["before"] not in (None, "") else None
        after = Decimal(str(quantity_change["after"])) if quantity_change and quantity_change["after"] not in (None, "") else None
        delta = after - before if before is not None and after is not None else None
        direction = "买入" if delta is not None and delta > 0 else "卖出" if delta is not None and delta < 0 else "调整"
        execution_rows = []
        for trade in reversed(symbol_trades):
            fields = trade.raw_payload or {}
            execution_rows.append({
                "security_id": position.security_id,
                "ticker": position.symbol,
                "direction": _side(trade),
                "quantity": abs(_float(trade.quantity) or 0),
                "price": _float(trade.price),
                "fee": abs(_float(decimal_value(fields, "ibCommission", "commission")) or 0),
                "strategy": "IBKR 自动填充",
                "result": f"{trade.occurred_at.isoformat() if trade.occurred_at else trade.report_date or ''} · {trade.currency or position.currency}",
            })
        anchor = symbol_trades[0] if symbol_trades else None
        anchor_fields = anchor.raw_payload if anchor else {}
        price = _float(anchor.price) if anchor else position.ibkr_market_price
        quantity = abs(_float(delta)) if delta is not None else abs(_float(anchor.quantity) or 0) if anchor else None
        facts = {
            "source": "IBKR Flex authoritative reconciliation",
            "sync_run_id": sync_run_id,
            "account_id": run.account_id,
            "report_date": (position.ibkr_report_date or run.report_to_date).isoformat() if (position.ibkr_report_date or run.report_to_date) else None,
            "symbol": position.symbol,
            "currency": position.currency,
            "change_type": direction,
            "position_changes": changes,
            "quantity_before": _float(before),
            "quantity_after": _float(after),
            "quantity_change": _float(delta),
            "average_cost": position.average_cost,
            "total_cost": position.total_cost,
            "market_price": position.ibkr_market_price,
            "market_value": position.ibkr_market_value,
            "unrealized_pnl": position.ibkr_unrealized_pnl,
            "fx_rate_to_base": position.ibkr_fx_rate_to_base,
            "execution_price": price,
            "commission": abs(_float(decimal_value(anchor_fields or {}, "ibCommission", "commission")) or 0) if anchor else None,
            "tax": abs(_float(decimal_value(anchor_fields or {}, "taxes", "tax")) or 0) if anchor else None,
            "executions": [{
                "record_id": row.id, "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                "side": _side(row), "quantity": abs(_float(row.quantity) or 0), "price": _float(row.price),
                "currency": row.currency,
            } for row in symbol_trades],
            "audit_ids": [row.id for row in position_audits],
            "generated_at": datetime.now(UTC).isoformat(),
        }
        db.add(TradeLog(
            user_id=user_id, ticker=position.symbol, direction=direction, quantity=quantity, price=price,
            trade_date=position.ibkr_report_date or run.report_to_date or datetime.now(UTC).date(),
            note=None, content=None, table_rows=execution_rows, photo_urls=[], status="draft",
            source_type="ibkr_sync", objective_facts=facts, ibkr_sync_run_id=sync_run_id,
            ibkr_position_id=position_id,
        ))
        created += 1
    db.flush()
    return {"created": created, "reused": reused, "changed_positions": len(grouped)}
