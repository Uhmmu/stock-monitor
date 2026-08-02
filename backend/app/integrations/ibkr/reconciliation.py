from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Portfolio, PortfolioPosition, Security
from .db_models import IbkrFlexRecord, IbkrFlexSyncRun, IbkrPortfolioAuthorityAudit


def _decimal(fields: dict, key: str) -> Decimal | None:
    value = fields.get(key)
    if value in (None, "", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def reconcile_positions(
    db: Session, *, user_id: int, sync_run_id: int, dry_run: bool = True,
    commit: bool = True, allow_closure: bool = True,
) -> dict:
    run = db.scalar(select(IbkrFlexSyncRun).where(IbkrFlexSyncRun.id == sync_run_id, IbkrFlexSyncRun.user_id == user_id))
    if run is None:
        raise ValueError("IBKR sync run not found")
    portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.slug == "default"))
    if portfolio is None:
        raise ValueError("Default portfolio not found")
    snapshots = db.scalars(select(IbkrFlexRecord).where(IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "positions")).all()
    positions = db.scalars(select(PortfolioPosition).where(PortfolioPosition.portfolio_id == portfolio.id)).all()
    securities = db.scalars(select(Security)).all()
    by_symbol = {row.symbol.upper(): row for row in positions}
    by_conid = {row.ibkr_conid: row for row in securities if row.ibkr_conid}
    by_isin = {row.isin: row for row in securities if row.isin}
    by_figi = {row.figi: row for row in securities if row.figi}
    matched_ids: set[int] = set()
    section_complete = "positions" in (run.section_counts or {})
    summary = {"dry_run": dry_run, "ibkr_positions": len(snapshots), "matched": 0, "unmatched": 0, "quantity_conflicts": 0, "cost_conflicts": 0, "currency_conflicts": 0, "updated": 0, "applied_updates": 0, "existing_not_in_ibkr": 0, "closed": 0, "closure_skipped": not section_complete or not allow_closure}
    for snapshot in snapshots:
        fields = snapshot.raw_payload
        security = by_conid.get(snapshot.conid) or by_isin.get(fields.get("isin")) or by_figi.get(fields.get("figi"))
        position = next((row for row in positions if security and row.security_id == security.id), None)
        match_method = "provider_identifier"
        if position is None and snapshot.symbol:
            candidate = by_symbol.get(snapshot.symbol.upper())
            if candidate and candidate.currency.upper() == (snapshot.currency or candidate.currency).upper():
                position, match_method = candidate, "symbol_currency"
        if position is None and security is not None:
            canonical_symbol = (security.yahoo_symbol or security.display_symbol or snapshot.symbol or "").upper()
            if canonical_symbol:
                position = PortfolioPosition(
                    portfolio_id=portfolio.id,
                    security_id=security.id,
                    symbol=canonical_symbol,
                    total_quantity=0.0,
                    average_cost=0.0,
                    total_cost=0.0,
                    currency=snapshot.currency or security.currency or portfolio.base_currency,
                    authority_source="ibkr_flex",
                )
                db.add(position)
                db.flush()
                positions.append(position)
                by_symbol[position.symbol] = position
                match_method = "provider_identifier_new_position"
        if position is None:
            summary["unmatched"] += 1
            continue
        summary["matched"] += 1
        matched_ids.add(position.id)
        quantity = _decimal(fields, "position")
        average_cost = _decimal(fields, "costBasisPrice")
        total_cost = _decimal(fields, "costBasisMoney")
        conflicts = []
        for field, old, new in (("quantity", Decimal(str(position.total_quantity)), quantity), ("average_cost", Decimal(str(position.average_cost)), average_cost)):
            if new is not None and abs(old - new) > Decimal("0.00000001"):
                conflicts.append({"field": field, "previous_source": position.authority_source, "previous_value": str(old), "ibkr_value": str(new), "resolution": "ibkr_flex"})
                summary[f"{field}_conflicts" if field == "quantity" else "cost_conflicts"] += 1
        if snapshot.currency and snapshot.currency != position.currency:
            summary["currency_conflicts"] += 1
            conflicts.append({"field": "currency", "previous_source": position.authority_source, "previous_value": position.currency, "ibkr_value": snapshot.currency, "resolution": "ibkr_flex"})
        if dry_run:
            continue
        if security:
            security.ibkr_conid = snapshot.conid or security.ibkr_conid
            security.figi = fields.get("figi") or security.figi
            security.cusip = fields.get("cusip") or security.cusip
        position.authority_source = "ibkr_flex"
        position.ibkr_sync_run_id = run.id
        position.ibkr_conid = snapshot.conid
        if quantity is not None: position.total_quantity = float(quantity)
        if average_cost is not None: position.average_cost = float(average_cost)
        if total_cost is not None: position.total_cost = float(abs(total_cost))
        if snapshot.currency: position.currency = snapshot.currency
        position.ibkr_market_price = float(value) if (value := _decimal(fields, "markPrice")) is not None else None
        position.ibkr_market_value = float(value) if (value := _decimal(fields, "positionValue")) is not None else None
        position.ibkr_unrealized_pnl = float(value) if (value := _decimal(fields, "fifoPnlUnrealized")) is not None else None
        position.ibkr_fx_rate_to_base = float(value) if (value := _decimal(fields, "fxRateToBase")) is not None else None
        position.ibkr_report_date = snapshot.report_date
        position.ibkr_details = {k: v for k, v in fields.items() if k not in {"accountId", "acctAlias"}}
        position.authority_conflicts = conflicts
        position.updated_at = datetime.now(UTC)
        summary["updated"] += 1
        summary["applied_updates"] += len(conflicts)
        for conflict in conflicts:
            db.add(IbkrPortfolioAuthorityAudit(
                user_id=user_id, portfolio_position_id=position.id, sync_run_id=run.id,
                flex_record_id=snapshot.id, conflict_type=conflict["field"],
                previous_source=conflict.get("previous_source"), previous_value=conflict.get("previous_value"),
                authoritative_value=conflict.get("ibkr_value"), application_status="applied",
                details={"match_method": match_method, "resolution": "ibkr_flex"},
            ))
    summary["existing_not_in_ibkr"] = len([row for row in positions if row.id not in matched_ids])
    if not dry_run and section_complete and allow_closure:
        for position in positions:
            if position.id in matched_ids or position.authority_source != "ibkr_flex" or not position.ibkr_conid:
                continue
            previous = str(position.total_quantity)
            position.total_quantity = 0.0
            position.total_cost = 0.0
            position.ibkr_sync_run_id = run.id
            position.ibkr_report_date = run.report_to_date
            position.updated_at = datetime.now(UTC)
            db.add(IbkrPortfolioAuthorityAudit(
                user_id=user_id, portfolio_position_id=position.id, sync_run_id=run.id,
                flex_record_id=None, conflict_type="position_closed", previous_source="ibkr_flex",
                previous_value=previous, authoritative_value="0", application_status="applied",
                details={"reason": "complete_current_positions_section_absent"},
            ))
            summary["closed"] += 1
            summary["applied_updates"] += 1
    if not dry_run:
        db.flush()
        if commit:
            db.commit()
    return summary
