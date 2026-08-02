from __future__ import annotations

from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from .db_models import (
    IbkrAccountDailyPerformance, IbkrDividendEvent, IbkrFlexRecord,
    IbkrFlexSyncRun, IbkrNormalizedCashFlow, IbkrPortfolioAuthorityAudit, IbkrPositionPerformanceDaily,
    IbkrTradeRoundTrip,
)

from .repository import latest_run, latest_sync_attempt, mask_account, page_records
from .sync import request_sync, sync_result

router = APIRouter(prefix="/api/ibkr", tags=["ibkr"], dependencies=[Depends(get_current_user)])

SECTION_ROUTES = {
    "positions": "positions", "trades": "trades", "orders": "orders",
    "cash-ledger": "cash_ledger", "cash-transactions": "cash_transactions",
    "dividends": "dividends", "corporate-actions": "corporate_actions",
    "performance": "performance", "fifo-performance": "fifo_performance",
    "tax-lots": "tax_lots", "fx-rates": "fx_rates", "prior-positions": "prior_positions",
}


def _run_payload(run):
    if run is None:
        return None
    return {
        "id": run.id, "account_id_masked": mask_account(run.account_id), "status": run.status,
        "report_from_date": run.report_from_date, "report_to_date": run.report_to_date,
        "generated_at": run.generated_at, "imported_at": run.imported_at,
        "completed_at": run.completed_at, "parser_version": run.parser_version,
        "section_counts": run.section_counts, "warning_count": run.warning_count,
        "warnings": run.warnings, "source": "IBKR Flex 日终账户数据",
        "stage": run.stage, "trigger_type": run.trigger_type,
        "import_counts": run.import_counts, "reconciliation": run.reconciliation,
        "propagation": run.propagation, "error_stage": run.error_stage,
        "error_code": run.error_code, "error_message": run.error_message,
    }


@router.get("/status")
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = latest_run(db, user.id)
    attempt = latest_sync_attempt(db, user.id)
    return {"configured": run is not None, "read_only": True, "latest_sync": _run_payload(run), "current_or_last_attempt": _run_payload(attempt)}


@router.get("/accounts")
def accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = latest_run(db, user.id)
    return [] if run is None else [{"account_id_masked": mask_account(run.account_id), "latest_sync_id": run.id}]


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = latest_run(db, user.id)
    if run is None:
        return {"available": False, "latest_sync": None, "position_count": 0}
    nav = db.scalar(select(IbkrFlexRecord).where(IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "account_nav").order_by(IbkrFlexRecord.source_index))
    cash_rows = db.scalars(select(IbkrFlexRecord).where(IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "cash_reports")).all()
    cash = next((row for row in cash_rows if row.currency == "BASE"), cash_rows[0] if cash_rows else None)
    nav_fields, cash_fields = (nav.raw_payload if nav else {}), (cash.raw_payload if cash else {})
    account_summary = {
        "base_currency": cash.currency if cash and cash.currency != "BASE" else nav_fields.get("currency"),
        "net_liquidation": nav_fields.get("endingValue"), "starting_value": nav_fields.get("startingValue"),
        "total_cash": cash_fields.get("endingCash"), "settled_cash": cash_fields.get("endingSettledCash"),
        "realized_pnl": nav_fields.get("realized"), "unrealized_pnl": nav_fields.get("changeInUnrealized"),
        "dividends": nav_fields.get("dividends"), "interest": nav_fields.get("interest"),
        "buying_power": None, "available_funds": None, "excess_liquidity": None,
        "initial_margin": None, "maintenance_margin": None,
    }
    latest_perf = db.scalar(select(IbkrAccountDailyPerformance).where(
        IbkrAccountDailyPerformance.user_id == user.id,
    ).order_by(IbkrAccountDailyPerformance.performance_date.desc()).limit(1))
    if latest_perf:
        account_summary.update({"net_liquidation": latest_perf.ending_nav or account_summary["net_liquidation"],
                                "total_cash": latest_perf.ending_cash or account_summary["total_cash"],
                                "max_drawdown": latest_perf.max_drawdown_to_date,
                                "investment_pnl": latest_perf.investment_pnl,
                                "data_completeness": latest_perf.data_completeness})
    return {"available": True, "latest_sync": _run_payload(run), "current_sync": _run_payload(latest_sync_attempt(db, user.id)), "account_summary": account_summary, "position_count": run.section_counts.get("positions", 0),
            "trade_count": run.section_counts.get("trades", 0), "order_count": run.section_counts.get("orders", 0),
            "cash_ledger_count": run.section_counts.get("cash_ledger", 0)}


@router.post("/sync", status_code=http_status.HTTP_202_ACCEPTED)
def start_sync(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        run, created = request_sync(db, user_id=user.id, trigger_type="manual")
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "IBKR 同步请求冲突，请稍后重试") from exc
    if created:
        from app.tasks.celery_app import sync_ibkr_flex_account
        sync_ibkr_flex_account.delay(run.id)
    return {**sync_result(run), "created": created, "read_only": True}


@router.get("/sync/{sync_run_id}")
def sync_detail(sync_run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = db.scalar(select(IbkrFlexSyncRun).where(IbkrFlexSyncRun.id == sync_run_id, IbkrFlexSyncRun.user_id == user.id))
    if run is None:
        raise HTTPException(404, "未找到该同步运行")
    return sync_result(run)


def _date_filters(model, user_id: int, start_date: date | None, end_date: date | None, column):
    filters = [model.user_id == user_id]
    if start_date: filters.append(column >= start_date)
    if end_date: filters.append(column <= end_date)
    return filters


@router.get("/performance/daily")
def performance_daily(start_date: date | None = None, end_date: date | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(IbkrAccountDailyPerformance).where(*_date_filters(
        IbkrAccountDailyPerformance, user.id, start_date, end_date, IbkrAccountDailyPerformance.performance_date,
    )).order_by(IbkrAccountDailyPerformance.performance_date)).all()
    return {"items": [{key: getattr(row, key) for key in (
        "performance_date", "base_currency", "beginning_nav", "ending_nav", "beginning_cash", "ending_cash",
        "external_deposits", "external_withdrawals", "net_external_cash_flow", "realized_pnl", "unrealized_pnl_change",
        "dividend_income", "interest_income", "commissions", "taxes", "other_fees", "fx_pnl", "investment_pnl",
        "daily_return", "cumulative_return", "drawdown", "max_drawdown_to_date", "data_completeness", "warnings",
    )} for row in rows], "calculation_version": rows[-1].calculation_version if rows else None}


@router.get("/performance/monthly")
def performance_monthly(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = performance_daily(user=user, db=db)["items"]
    groups = {}
    for row in rows:
        month = row["performance_date"].strftime("%Y-%m")
        group = groups.setdefault(month, {"month": month, "beginning_nav": row["beginning_nav"], "ending_nav": row["ending_nav"], "net_external_cash_flow": 0, "investment_pnl": 0, "warnings": []})
        group["ending_nav"] = row["ending_nav"]
        for key in ("net_external_cash_flow", "investment_pnl"):
            group[key] = (group[key] or 0) + (row[key] or 0)
        group["warnings"].extend(row["warnings"] or [])
    return {"items": list(groups.values())}


@router.get("/performance/attribution")
def performance_attribution(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    daily_rows = db.scalars(select(IbkrPositionPerformanceDaily).where(IbkrPositionPerformanceDaily.user_id == user.id).order_by(IbkrPositionPerformanceDaily.performance_date)).all()
    if daily_rows:
        by_symbol = {}
        for row in daily_rows:
            item = by_symbol.setdefault(row.symbol or "UNKNOWN", {"symbol": row.symbol, "total_pnl": 0, "dividends": 0, "commissions": 0, "taxes": 0, "fx_pnl": 0, "days": 0, "warnings": []})
            for source, target in (("total_pnl", "total_pnl"), ("dividend_income", "dividends"), ("commissions", "commissions"), ("taxes", "taxes"), ("fx_pnl", "fx_pnl")):
                item[target] += getattr(row, source) or 0
            item["days"] += 1; item["warnings"].extend(row.warnings or [])
        return {"items": sorted(by_symbol.values(), key=lambda item: item["total_pnl"], reverse=True), "source": "IBKR account facts + project historical prices without look-ahead"}
    rows = db.scalars(select(IbkrTradeRoundTrip).where(IbkrTradeRoundTrip.user_id == user.id).order_by(IbkrTradeRoundTrip.closed_at.desc())).all()
    by_symbol = {}
    for row in rows:
        item = by_symbol.setdefault(row.symbol or "UNKNOWN", {"symbol": row.symbol, "realized_pnl": 0, "commissions": 0, "taxes": 0, "trade_count": 0})
        for key in ("realized_pnl", "commissions", "taxes"):
            value = row.net_pnl if key == "realized_pnl" else getattr(row, key)
            item[key] += value or 0
        item["trade_count"] += 1
    return {"items": sorted(by_symbol.values(), key=lambda item: item["realized_pnl"], reverse=True), "warnings": ["首版归因覆盖已闭合交易；每日持仓行情归因缺失时不会使用未来价格"]}


@router.get("/trades/round-trips")
def round_trips(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), symbol: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = [IbkrTradeRoundTrip.user_id == user.id]
    if symbol: filters.append(IbkrTradeRoundTrip.symbol == symbol.upper())
    total = db.scalar(select(func.count()).select_from(IbkrTradeRoundTrip).where(*filters)) or 0
    rows = db.scalars(select(IbkrTradeRoundTrip).where(*filters).order_by(IbkrTradeRoundTrip.closed_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    keys = ("id", "symbol", "conid", "opened_at", "closed_at", "quantity", "average_entry_price", "average_exit_price", "gross_pnl", "commissions", "taxes", "net_pnl", "return_pct", "holding_days", "matching_method", "warnings")
    return {"items": [{key: getattr(row, key) for key in keys} for row in rows], "page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total}


@router.get("/cash-flows/summary")
def cash_flow_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(IbkrNormalizedCashFlow.normalized_category, IbkrNormalizedCashFlow.currency,
        func.count(IbkrNormalizedCashFlow.id), func.sum(IbkrNormalizedCashFlow.amount)).where(
        IbkrNormalizedCashFlow.user_id == user.id).group_by(IbkrNormalizedCashFlow.normalized_category, IbkrNormalizedCashFlow.currency)).all()
    return {"items": [{"category": row[0], "currency": row[1], "count": row[2], "amount": row[3]} for row in rows]}


@router.get("/dividends/summary")
def dividend_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(IbkrDividendEvent).where(IbkrDividendEvent.user_id == user.id).order_by(IbkrDividendEvent.pay_date.desc().nullslast())).all()
    received = [row for row in rows if row.status == "received"]
    return {"items": [{key: getattr(row, key) for key in ("id", "symbol", "currency", "ex_date", "pay_date", "gross_dividend", "withholding_tax", "net_dividend", "status", "warnings")} for row in rows],
            "received_totals": [{"currency": currency, "gross": sum((row.gross_dividend or 0 for row in received if row.currency == currency), 0),
                                 "tax": sum((row.withholding_tax or 0 for row in received if row.currency == currency), 0),
                                 "net": sum((row.net_dividend or 0 for row in received if row.currency == currency), 0)}
                                for currency in sorted({row.currency for row in received if row.currency})],
            "accounting_note": "仅 received 进入到账汇总；accrued 与 reversed 单独展示，不重复计入。"}


@router.get("/fees/summary")
def fees_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    categories = ("commission", "withholding_tax", "margin_interest", "broker_fee")
    rows = db.execute(select(IbkrNormalizedCashFlow.normalized_category, IbkrNormalizedCashFlow.currency, func.sum(IbkrNormalizedCashFlow.amount)).where(
        IbkrNormalizedCashFlow.user_id == user.id, IbkrNormalizedCashFlow.normalized_category.in_(categories)).group_by(IbkrNormalizedCashFlow.normalized_category, IbkrNormalizedCashFlow.currency)).all()
    return {"items": [{"category": row[0], "currency": row[1], "amount": row[2]} for row in rows]}


@router.get("/fx/exposure")
def fx_exposure(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = latest_run(db, user.id)
    if not run: return {"items": [], "warnings": ["尚无 IBKR 数据"]}
    rows = db.scalars(select(IbkrFlexRecord).where(IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section.in_(("positions", "cash_reports")))).all()
    grouped = {}
    for row in rows:
        item = grouped.setdefault(row.currency or "UNKNOWN", {"currency": row.currency, "position_value": 0, "cash": 0, "fx_rate_to_base": None})
        fields = row.raw_payload or {}
        if row.section == "positions": item["position_value"] += float(fields.get("positionValue") or 0); item["fx_rate_to_base"] = fields.get("fxRateToBase")
        else: item["cash"] += float(fields.get("endingCash") or 0)
    return {"items": list(grouped.values()), "source": "IBKR Flex report values; current market valuation remains project-price authoritative"}


@router.get("/data-health")
def data_health(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = latest_run(db, user.id); attempt = latest_sync_attempt(db, user.id)
    if not run: return {"available": False, "current_sync": _run_payload(attempt)}
    unknown = sum(count for key, count in (run.section_counts or {}).items() if key == "unknown")
    audit_count = db.scalar(select(func.count()).select_from(IbkrPortfolioAuthorityAudit).where(IbkrPortfolioAuthorityAudit.user_id == user.id, IbkrPortfolioAuthorityAudit.sync_run_id == run.id)) or 0
    recon = run.reconciliation or {}
    expected = {"positions", "trades", "cash_ledger", "performance"}
    return {"available": True, "latest_success": _run_payload(run), "current_or_last_attempt": _run_payload(attempt),
        "coverage": {"from": run.report_from_date, "to": run.report_to_date}, "archive_exists": bool(run.archive_path and Path(run.archive_path).is_file()),
        "section_counts": run.section_counts, "missing_sections": sorted(expected - set(run.section_counts or {})),
        "unrecognized_records": unknown, "duplicate_records": (run.import_counts or {}).get("skipped", 0),
        "position_match_rate": (recon.get("matched", 0) / recon.get("ibkr_positions", 1) if recon.get("ibkr_positions") else None),
        "reconciliation": recon, "authority_audit_count": audit_count,
        "derived_data": (run.propagation or {}).get("derived_counts", {}),
        "portfolio_propagated_at": (run.propagation or {}).get("portfolio_propagated_at"),
        "data_completeness": "partial" if run.warning_count else "complete_for_present_sections",
        "explicit_gaps": {"corporate_actions": run.section_counts.get("corporate_actions", 0), "buying_power": None, "margin": None}}


@router.get("/{resource}")
def records(
    resource: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    symbol: str | None = None, currency: str | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    section = SECTION_ROUTES.get(resource)
    if section is None:
        return {"items": [], "page": page, "page_size": page_size, "total": 0, "has_more": False}
    return page_records(db, user_id=user.id, section=section, page=page, page_size=page_size, symbol=symbol, currency=currency)
