"""Unified, user-scoped investment ledger read model.

IBKR tables remain the evidence/derivation layer and manual transactions remain
auditable user facts.  This module is the only portfolio-domain boundary that
decides which source is authoritative and turns those records into stable DTOs.
It never calls IBKR or another paid provider.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from app.integrations.ibkr.analytics import CALCULATION_VERSION, decimal_value
from app.integrations.ibkr.db_models import (
    IbkrAccountDailyPerformance,
    IbkrDividendEvent,
    IbkrFlexRecord,
    IbkrFlexSyncRun,
    IbkrNormalizedCashFlow,
    IbkrPositionPerformanceDaily,
    IbkrTradeRoundTrip,
)
from app.models import Portfolio, PortfolioPosition, PortfolioPositionLot, TradeTransaction

from .performance import build_summary as build_market_summary


def _number(value: Any) -> float | None:
    return float(value) if value is not None else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def latest_authoritative_run(db: Session, user_id: int) -> IbkrFlexSyncRun | None:
    # Some isolated unit-test/maintenance databases intentionally contain only
    # the legacy portfolio tables. Treat that exactly like an account without
    # an IBKR connection instead of coupling every consumer to integration DDL.
    if not inspect(db.connection()).has_table(IbkrFlexSyncRun.__tablename__):
        return None
    return db.scalar(
        select(IbkrFlexSyncRun)
        .where(
            IbkrFlexSyncRun.user_id == user_id,
            IbkrFlexSyncRun.status == "completed",
            IbkrFlexSyncRun.normalized_record_count > 0,
        )
        .order_by(IbkrFlexSyncRun.completed_at.desc().nullslast(), IbkrFlexSyncRun.id.desc())
        .limit(1)
    )


def _trade_side(row: IbkrFlexRecord) -> str:
    side = str((row.raw_payload or {}).get("buySell") or (row.raw_payload or {}).get("side") or "").upper()
    return "buy" if side in {"BUY", "BOT", "B"} else "sell" if side in {"SELL", "SLD", "S"} else "trade"


def govern_manual_transactions(db: Session, portfolio: Portfolio, run: IbkrFlexSyncRun) -> dict:
    """Supersede manual facts covered by a matched IBKR security, without deletion.

    Exact matching is deliberately conservative.  Older rows are superseded only
    when IBKR lot/prior-position evidence proves that they are inside the broker
    opening state; otherwise they become historical_unverified and are still
    excluded from current accounting to prevent double counting.
    """
    authority_positions = list(db.scalars(select(PortfolioPosition).where(
        PortfolioPosition.portfolio_id == portfolio.id,
        PortfolioPosition.authority_source == "ibkr_flex",
        PortfolioPosition.ibkr_sync_run_id == run.id,
    )).all())
    symbols = {row.symbol for row in authority_positions}
    if not symbols:
        return {"matched_assets": 0, "superseded": 0, "historical_unverified": 0, "unchanged": 0}
    evidence_symbols = set(db.scalars(select(IbkrFlexRecord.symbol).where(
        IbkrFlexRecord.sync_run_id == run.id,
        IbkrFlexRecord.section.in_(("tax_lots", "prior_positions", "fifo_performance")),
        IbkrFlexRecord.symbol.in_(symbols),
    )).all())
    ibkr_trades = list(db.scalars(select(IbkrFlexRecord).where(
        IbkrFlexRecord.sync_run_id == run.id,
        IbkrFlexRecord.section == "trades",
        IbkrFlexRecord.symbol.in_(symbols),
    )).all())
    by_symbol: dict[str, list[IbkrFlexRecord]] = defaultdict(list)
    for row in ibkr_trades:
        if row.symbol:
            by_symbol[row.symbol].append(row)
    manual_rows = list(db.scalars(select(TradeTransaction).where(
        TradeTransaction.portfolio_id == portfolio.id,
        TradeTransaction.symbol.in_(symbols),
        TradeTransaction.source_type.in_(("manual", "journal", "import")),
    )).all())
    now = datetime.now(UTC)
    counts = {"matched_assets": len(symbols), "superseded": 0, "historical_unverified": 0, "unchanged": 0}
    for txn in manual_rows:
        exact: tuple[IbkrFlexRecord, float, str] | None = None
        for candidate in by_symbol.get(txn.symbol, []):
            if candidate.report_date != txn.trade_date or _trade_side(candidate) != txn.transaction_type:
                continue
            qty_equal = candidate.quantity is not None and abs(float(abs(candidate.quantity)) - txn.quantity) < 1e-7
            price_equal = candidate.price is not None and abs(float(candidate.price) - txn.price) < 0.01
            if qty_equal and price_equal:
                exact = (candidate, 1.0, "date_side_quantity_price")
                break
            if qty_equal:
                exact = (candidate, 0.85, "date_side_quantity")
        before_coverage = bool(run.report_from_date and txn.trade_date < run.report_from_date)
        if exact:
            candidate, confidence, method = exact
            status = "superseded"
            txn.superseded_by_record_id = candidate.id
            txn.match_confidence = confidence
            txn.match_method = method
        elif before_coverage and txn.symbol not in evidence_symbols:
            status = "historical_unverified"
            txn.superseded_by_record_id = None
            txn.match_confidence = None
            txn.match_method = "ibkr_account_ledger_without_provable_precoverage_lot"
        else:
            status = "superseded"
            txn.superseded_by_record_id = None
            txn.match_confidence = 0.6 if before_coverage else 0.75
            txn.match_method = "ibkr_account_ledger" if not before_coverage else "ibkr_opening_position_or_lot"
        txn.authority_status = status
        txn.superseded_by_source = "ibkr_flex"
        txn.superseded_at = now
        txn.superseded_sync_run_id = run.id
        counts[status] += 1
    db.flush()
    return counts


def assert_manual_write_allowed(db: Session, portfolio: Portfolio, symbol: str) -> None:
    row = db.scalar(select(PortfolioPosition).where(
        PortfolioPosition.portfolio_id == portfolio.id,
        PortfolioPosition.symbol == symbol.upper(),
        PortfolioPosition.authority_source == "ibkr_flex",
    ))
    if row is not None:
        raise ValueError("该持仓由 IBKR 同步管理。请在券商侧完成交易后重新同步。")


def _latest_run_filter(model, run: IbkrFlexSyncRun | None):
    return model.source_sync_run_id == run.id if run else False


def performance_series(db: Session, portfolio: Portfolio, *, start: date | None = None, end: date | None = None) -> dict:
    run = latest_authoritative_run(db, portfolio.user_id)
    if run is None:
        return {"items": [], "source": None, "calculation_method": "unavailable", "data_completeness": 0.0,
                "warnings": ["尚无 IBKR 账户绩效记录；不会用当前持仓倒推历史收益"]}
    filters = [_latest_run_filter(IbkrAccountDailyPerformance, run), IbkrAccountDailyPerformance.calculation_version == CALCULATION_VERSION]
    if end:
        filters.append(IbkrAccountDailyPerformance.performance_date <= end)
    rows = list(db.scalars(select(IbkrAccountDailyPerformance).where(*filters).order_by(
        IbkrAccountDailyPerformance.performance_date
    )).all())
    cumulative_contributions = Decimal("0")
    items = []
    for row in rows:
        cumulative_contributions += row.net_external_cash_flow or Decimal("0")
        point = {
            "date": row.performance_date,
            "nav": _number(row.ending_nav),
            "net_contributions": _number(cumulative_contributions),
            "investment_value": _number((row.ending_nav or Decimal("0")) - cumulative_contributions) if row.ending_nav is not None else None,
            "daily_return": _number(row.daily_return),
            "cumulative_return": _number(row.cumulative_return),
            "drawdown": _number(row.drawdown),
            "benchmark_return": None,
            "data_completeness": _number(row.data_completeness) or 0.0,
        }
        if start is None or row.performance_date >= start:
            items.append(point)
    selected_rows = [row for row in rows if start is None or row.performance_date >= start]
    return {
        "items": items,
        "source": "ibkr_flex",
        "calculation_method": "cash_flow_adjusted_time_weighted_return",
        "period": {"start": selected_rows[0].performance_date if selected_rows else start, "end": selected_rows[-1].performance_date if selected_rows else end},
        "data_completeness": min((_number(r.data_completeness) or 0 for r in selected_rows), default=0.0),
        "warnings": sorted({warning for row in selected_rows for warning in (row.warnings or [])}),
        "latest_sync_at": run.completed_at,
    }


def _period_return(rows: list[IbkrAccountDailyPerformance], predicate) -> float | None:
    selected = [r for r in rows if predicate(r.performance_date) and r.daily_return is not None]
    if not selected:
        return None
    product = Decimal("1")
    for row in selected:
        product *= Decimal("1") + row.daily_return
    return float(product - Decimal("1"))


def _symbol_totals(db: Session, user_id: int, run: IbkrFlexSyncRun | None) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = defaultdict(lambda: {"realized_pnl": 0.0, "dividend_income": 0.0, "fees": 0.0, "taxes": 0.0})
    if run is None:
        return output
    for row in db.scalars(select(IbkrTradeRoundTrip).where(_latest_run_filter(IbkrTradeRoundTrip, run))).all():
        item = output[row.symbol or "UNKNOWN"]
        item["realized_pnl"] += _number(row.gross_pnl) or 0.0
        item["fees"] += _number(row.commissions) or 0.0
        item["taxes"] += _number(row.taxes) or 0.0
    for row in db.scalars(select(IbkrDividendEvent).where(
        _latest_run_filter(IbkrDividendEvent, run), IbkrDividendEvent.status == "received"
    )).all():
        item = output[row.symbol or "UNKNOWN"]
        item["dividend_income"] += _number(row.gross_dividend) or 0.0
        item["taxes"] += abs(_number(row.withholding_tax) or 0.0)
    return output


def position_summaries(db: Session, portfolio: Portfolio, *, cached_fx_only: bool = False) -> list[dict]:
    market = build_market_summary(db, portfolio, cached_fx_only=cached_fx_only)
    run = latest_authoritative_run(db, portfolio.user_id)
    totals = _symbol_totals(db, portfolio.user_id, run)
    first_trades: dict[str, datetime | date] = {}
    if run:
        for row in db.scalars(select(IbkrFlexRecord).where(
            IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "trades"
        ).order_by(IbkrFlexRecord.occurred_at, IbkrFlexRecord.report_date)).all():
            if row.symbol and row.symbol not in first_trades:
                first_trades[row.symbol] = row.occurred_at or row.report_date
    today = datetime.now(UTC).date()
    for item in market["positions"]:
        values = totals[item["symbol"]]
        unrealized = item.get("unrealized_pnl") or 0.0
        total_pnl = unrealized + values["realized_pnl"] + values["dividend_income"] - values["fees"] - values["taxes"]
        fx_rate = item.get("fx_rate") if item.get("valuation_available") else None
        invested = item.get("total_cost") or 0.0
        opened = first_trades.get(item["symbol"])
        opened_date = opened.date() if isinstance(opened, datetime) else opened
        item.update({
            **values,
            "fees_and_taxes": values["fees"] + values["taxes"],
            "total_pnl": round(total_pnl, 4),
            "base_currency_realized_pnl": round(values["realized_pnl"] * fx_rate, 4) if fx_rate is not None else None,
            "base_currency_dividend_income": round(values["dividend_income"] * fx_rate, 4) if fx_rate is not None else None,
            "base_currency_fees": round(values["fees"] * fx_rate, 4) if fx_rate is not None else None,
            "base_currency_taxes": round(values["taxes"] * fx_rate, 4) if fx_rate is not None else None,
            "base_currency_total_pnl": round(total_pnl * fx_rate, 4) if fx_rate is not None else None,
            "total_return_pct": round(total_pnl / invested * 100, 4) if invested > 0 else None,
            "daily_pnl": None,
            "daily_return_pct": None,
            "holding_days": (today - opened_date).days if opened_date else None,
            "first_trade_at": _iso(opened),
            "authority_source": item.get("authority_source") or "manual",
            "data_completeness": "complete" if item.get("valuation_available") and item.get("authority_source") == "ibkr_flex" else "partial",
        })
    return market["positions"]


def overview(db: Session, portfolio: Portfolio, *, cached_fx_only: bool = False) -> dict:
    market = build_market_summary(db, portfolio, cached_fx_only=cached_fx_only)
    positions = position_summaries(db, portfolio, cached_fx_only=cached_fx_only)
    run = latest_authoritative_run(db, portfolio.user_id)
    rows = list(db.scalars(select(IbkrAccountDailyPerformance).where(
        _latest_run_filter(IbkrAccountDailyPerformance, run)
    ).order_by(IbkrAccountDailyPerformance.performance_date)).all()) if run else []
    today = datetime.now(UTC).date()
    latest = rows[-1] if rows else None
    contributions = sum((r.net_external_cash_flow or Decimal("0") for r in rows), Decimal("0"))
    def converted_total(key: str) -> Decimal:
        return sum((Decimal(str(p[key])) * Decimal(str(p.get("fx_rate") or 0)) for p in positions), Decimal("0"))
    if rows:
        realized = sum((row.realized_pnl or Decimal("0") for row in rows), Decimal("0"))
        dividends = sum((row.dividend_income or Decimal("0") for row in rows), Decimal("0"))
        fees = sum((abs(row.commissions or Decimal("0")) + abs(row.other_fees or Decimal("0")) for row in rows), Decimal("0"))
        taxes = sum((abs(row.taxes or Decimal("0")) for row in rows), Decimal("0"))
    else:
        realized = converted_total("realized_pnl")
        dividends = converted_total("dividend_income")
        fees = converted_total("fees")
        taxes = converted_total("taxes")
    # Current NAV combines broker-authoritative quantity/cash with current
    # project prices. Keep the dated broker-reported NAV separately so consumers
    # never mistake an EOD report mark for the current market valuation.
    nav = market["total_net_liquidation"]
    return {
        **market,
        "positions": positions,
        "net_asset_value": nav,
        "ibkr_reported_nav": _number(latest.ending_nav) if latest else None,
        "invested_market_value": market["total_market_value"],
        "cash": _number(latest.ending_cash) if latest and latest.ending_cash is not None else portfolio.cash_balance,
        "net_contributions": _number(contributions),
        "investment_pnl": (nav - float(contributions)) if nav is not None else None,
        "simple_cumulative_return": ((nav - float(contributions)) / float(contributions)) if nav is not None and contributions > 0 else None,
        "latest_daily_return": _number(latest.daily_return) if latest else None,
        "month_return": _period_return(rows, lambda d: d.year == today.year and d.month == today.month),
        "year_return": _period_return(rows, lambda d: d.year == today.year),
        "time_weighted_return": _number(latest.cumulative_return) if latest else None,
        "realized_pnl": _number(realized),
        "unrealized_pnl": market["total_unrealized_pnl"],
        "dividend_income": _number(dividends),
        "fees": _number(fees),
        "taxes": _number(taxes),
        "max_drawdown": _number(latest.max_drawdown_to_date) if latest else None,
        "latest_sync_at": run.completed_at if run else None,
        "account_data_source": "ibkr_flex" if run else "manual",
        "market_price_source": "project_market_data",
        "data_completeness": min((_number(r.data_completeness) or 0 for r in rows), default=0.0) if run else 0.5,
    }


def transaction_events(
    db: Session, portfolio: Portfolio, *, symbol: str | None = None, event_type: str | None = None,
    start: date | None = None, end: date | None = None, account: str | None = None,
    currency: str | None = None, include_superseded: bool = False,
) -> list[dict]:
    run = latest_authoritative_run(db, portfolio.user_id)
    events: list[dict] = []
    if run:
        filters = [IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "trades"]
        if symbol: filters.append(IbkrFlexRecord.symbol == symbol.upper())
        if currency: filters.append(IbkrFlexRecord.currency == currency.upper())
        rows = db.scalars(select(IbkrFlexRecord).where(*filters)).all()
        for row in rows:
            occurred = row.occurred_at or (datetime.combine(row.report_date, datetime.min.time(), tzinfo=UTC) if row.report_date else None)
            if start and (not occurred or occurred.date() < start): continue
            if end and (not occurred or occurred.date() > end): continue
            kind = _trade_side(row)
            if event_type and kind != event_type: continue
            fields = row.raw_payload or {}
            quantity = abs(_number(row.quantity) or 0.0)
            price = _number(row.price)
            gross = _number(row.amount)
            commission = abs(_number(decimal_value(fields, "ibCommission", "commission")) or 0.0)
            tax = abs(_number(decimal_value(fields, "taxes", "tax")) or 0.0)
            events.append({
                "event_id": f"ibkr:{row.id}", "instrument_id": None, "symbol": row.symbol,
                "event_type": kind, "occurred_at": occurred, "quantity": quantity, "price": price,
                "gross_amount": gross if gross is not None else (quantity * price if price is not None else None),
                "commission": commission, "tax": tax,
                "net_amount": gross - commission - tax if gross is not None else None,
                "currency": row.currency, "account": row.account_id, "position_quantity_after": None,
                "realized_pnl": _number(decimal_value(fields, "fifoPnlRealized", "realizedPnl")),
                "source_type": "ibkr_flex", "authority_source": "ibkr_flex", "authority_status": "authoritative",
                "is_authoritative": True, "is_editable": False, "note": None,
            })
        dividend_filters = [_latest_run_filter(IbkrDividendEvent, run)]
        if symbol: dividend_filters.append(IbkrDividendEvent.symbol == symbol.upper())
        if currency: dividend_filters.append(IbkrDividendEvent.currency == currency.upper())
        for row in db.scalars(select(IbkrDividendEvent).where(*dividend_filters)).all():
            occurred = row.pay_date or row.ex_date
            if start and (not occurred or occurred < start): continue
            if end and (not occurred or occurred > end): continue
            if event_type and event_type != "dividend": continue
            events.append({
                "event_id": f"ibkr-dividend:{row.id}", "instrument_id": None, "symbol": row.symbol,
                "event_type": "dividend", "occurred_at": occurred, "quantity": None, "price": None,
                "gross_amount": _number(row.gross_dividend), "commission": 0.0,
                "tax": abs(_number(row.withholding_tax) or 0.0), "net_amount": _number(row.net_dividend),
                "currency": row.currency, "account": row.account_id, "position_quantity_after": None,
                "realized_pnl": None, "source_type": "ibkr_flex", "authority_source": "ibkr_flex",
                "authority_status": row.status, "is_authoritative": True, "is_editable": False, "note": None,
            })
        # Account-level cash activity has no reliable security identity. Keep it
        # in the global ledger, but never guess a symbol for a position timeline.
        if symbol is None:
            cash_filters = [_latest_run_filter(IbkrNormalizedCashFlow, run)]
            if currency: cash_filters.append(IbkrNormalizedCashFlow.currency == currency.upper())
            if account: cash_filters.append(IbkrNormalizedCashFlow.account_id == account)
            if start: cash_filters.append(IbkrNormalizedCashFlow.flow_date >= start)
            if end: cash_filters.append(IbkrNormalizedCashFlow.flow_date <= end)
            for row in db.scalars(select(IbkrNormalizedCashFlow).where(*cash_filters)).all():
                if row.normalized_category in {"trade_settlement", "dividend"}:
                    continue
                if event_type and event_type != row.normalized_category:
                    continue
                events.append({
                    "event_id": f"ibkr-cash:{row.id}", "instrument_id": None, "symbol": None,
                    "event_type": row.normalized_category, "occurred_at": row.occurred_at or row.flow_date,
                    "quantity": None, "price": None, "gross_amount": _number(row.amount),
                    "commission": abs(_number(row.amount) or 0.0) if row.normalized_category == "commission" else 0.0,
                    "tax": abs(_number(row.amount) or 0.0) if row.normalized_category == "withholding_tax" else 0.0,
                    "net_amount": _number(row.amount), "currency": row.currency, "account": row.account_id,
                    "position_quantity_after": None, "realized_pnl": None, "source_type": "ibkr_flex",
                    "authority_source": "ibkr_flex", "authority_status": "authoritative",
                    "is_authoritative": True, "is_editable": False, "note": row.original_description,
                })
    manual_filters = [TradeTransaction.portfolio_id == portfolio.id]
    if not include_superseded:
        manual_filters.append(TradeTransaction.authority_status == "active")
    if symbol: manual_filters.append(TradeTransaction.symbol == symbol.upper())
    if event_type: manual_filters.append(TradeTransaction.transaction_type == event_type)
    if start: manual_filters.append(TradeTransaction.trade_date >= start)
    if end: manual_filters.append(TradeTransaction.trade_date <= end)
    if account: manual_filters.append(TradeTransaction.account == account)
    if currency: manual_filters.append(TradeTransaction.currency == currency.upper())
    for row in db.scalars(select(TradeTransaction).where(*manual_filters)).all():
        events.append({
            "event_id": f"manual:{row.id}", "instrument_id": row.security_id, "symbol": row.symbol,
            "event_type": row.transaction_type, "occurred_at": row.trade_date, "quantity": row.quantity,
            "price": row.price, "gross_amount": row.quantity * row.price, "commission": row.fees,
            "tax": 0.0, "net_amount": None, "currency": row.currency, "account": row.account,
            "position_quantity_after": None, "realized_pnl": None, "source_type": row.source_type,
            "authority_source": row.authority_source, "authority_status": row.authority_status,
            "is_authoritative": row.authority_status == "active", "is_editable": row.authority_status == "active",
            "note": row.note, "superseded_by_source": row.superseded_by_source,
            "match_confidence": row.match_confidence, "match_method": row.match_method,
        })
    events.sort(key=lambda item: (str(item.get("occurred_at") or ""), item["event_id"]), reverse=True)
    return events


def position_detail(db: Session, portfolio: Portfolio, symbol: str) -> dict | None:
    symbol = symbol.upper()
    summary = next((row for row in position_summaries(db, portfolio) if row["symbol"] == symbol), None)
    if summary is None:
        return None
    run = latest_authoritative_run(db, portfolio.user_id)
    curve_rows = list(db.scalars(select(IbkrPositionPerformanceDaily).where(
        _latest_run_filter(IbkrPositionPerformanceDaily, run),
        IbkrPositionPerformanceDaily.symbol == symbol,
    ).order_by(IbkrPositionPerformanceDaily.performance_date)).all()) if run else []
    cumulative_investment = Decimal("0")
    cumulative_pnl = Decimal("0")
    curve = []
    for row in curve_rows:
        cumulative_pnl += row.total_pnl or Decimal("0")
        if row.net_trade_quantity and row.average_cost:
            cumulative_investment += row.net_trade_quantity * row.average_cost
        curve.append({
            "date": row.performance_date, "market_value": _number(row.closing_market_value),
            "cumulative_investment": _number(cumulative_investment), "cumulative_pnl": _number(cumulative_pnl),
            "return_pct": _number(cumulative_pnl / abs(cumulative_investment)) if cumulative_investment else None,
            "data_completeness": _number(row.data_completeness) or 0.0,
        })
    round_trips = list(db.scalars(select(IbkrTradeRoundTrip).where(
        _latest_run_filter(IbkrTradeRoundTrip, run), IbkrTradeRoundTrip.symbol == symbol
    ).order_by(IbkrTradeRoundTrip.closed_at.desc())).all()) if run else []
    raw_lots = list(db.scalars(select(IbkrFlexRecord).where(
        IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.symbol == symbol,
        IbkrFlexRecord.section == "tax_lots",
    )).all()) if run else []
    if raw_lots:
        lots = [{
            "lot_id": f"ibkr:{row.id}", "opened_at": (row.raw_payload or {}).get("openDateTime") or (row.raw_payload or {}).get("holdingPeriodDateTime"),
            "quantity": _number(row.quantity) or _number(decimal_value(row.raw_payload or {}, "quantity")),
            "cost_basis": _number(decimal_value(row.raw_payload or {}, "costBasisMoney", "costBasis")),
            "cost_per_share": _number(decimal_value(row.raw_payload or {}, "costBasisPrice")),
            "unrealized_pnl": _number(decimal_value(row.raw_payload or {}, "fifoPnlUnrealized", "unrealizedPnl")),
            "status": "open", "matching_method": "ibkr_tax_lot", "source_type": "ibkr_flex",
        } for row in raw_lots]
    else:
        lots = [{
            "lot_id": f"manual:{row.id}", "opened_at": row.purchase_date, "quantity": row.remaining_quantity,
            "cost_basis": row.remaining_quantity * row.purchase_price + row.allocated_fees,
            "cost_per_share": row.purchase_price, "unrealized_pnl": None, "status": row.status,
            "matching_method": "manual_average_cost", "source_type": "manual",
        } for row in db.scalars(select(PortfolioPositionLot).where(
            PortfolioPositionLot.portfolio_id == portfolio.id, PortfolioPositionLot.symbol == symbol
        )).all()]
    return {
        "summary": summary,
        "performance_curve": curve,
        "timeline": transaction_events(db, portfolio, symbol=symbol),
        "open_lots": lots,
        "completed_trades": [{
            "id": row.id, "opened_at": row.opened_at, "closed_at": row.closed_at,
            "quantity": _number(row.quantity), "average_entry_price": _number(row.average_entry_price),
            "average_exit_price": _number(row.average_exit_price), "gross_pnl": _number(row.gross_pnl),
            "commissions": _number(row.commissions), "taxes": _number(row.taxes), "net_pnl": _number(row.net_pnl),
            "return_pct": _number(row.return_pct), "holding_days": row.holding_days,
            "matching_method": row.matching_method, "source_type": "ibkr_flex", "warnings": row.warnings,
        } for row in round_trips],
        "data_sources": {"account_facts": "ibkr_flex" if run else "manual", "market_prices": "project_market_data", "derived": "stock_monitor"},
        "latest_sync_at": run.completed_at if run else None,
    }


def return_attribution(db: Session, portfolio: Portfolio, *, start: date | None = None, end: date | None = None) -> dict:
    run = latest_authoritative_run(db, portfolio.user_id)
    if run is None:
        return {"items": [], "source": None, "warnings": ["尚无 IBKR 归因数据"]}
    filters = [_latest_run_filter(IbkrPositionPerformanceDaily, run)]
    if start: filters.append(IbkrPositionPerformanceDaily.performance_date >= start)
    if end: filters.append(IbkrPositionPerformanceDaily.performance_date <= end)
    grouped: dict[str, dict] = defaultdict(lambda: {"total_pnl": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0, "dividends": 0.0, "fees": 0.0, "taxes": 0.0, "fx_pnl": 0.0})
    for row in db.scalars(select(IbkrPositionPerformanceDaily).where(*filters)).all():
        item = grouped[row.symbol or "UNKNOWN"]
        item["total_pnl"] += _number(row.total_pnl) or 0.0
        item["realized_pnl"] += _number(row.realized_pnl) or 0.0
        item["unrealized_pnl"] += _number(row.unrealized_pnl_change) or 0.0
        item["dividends"] += _number(row.dividend_income) or 0.0
        item["fees"] += _number(row.commissions) or 0.0
        item["taxes"] += _number(row.taxes) or 0.0
        item["fx_pnl"] += _number(row.fx_pnl) or 0.0
    items = [{"symbol": symbol, **values} for symbol, values in grouped.items()]
    items.sort(key=lambda item: item["total_pnl"], reverse=True)
    return {"items": items, "source": "ibkr_facts_and_project_derived", "warnings": [], "latest_sync_at": run.completed_at}


def completed_trades(db: Session, portfolio: Portfolio, *, symbol: str | None = None) -> list[dict]:
    run = latest_authoritative_run(db, portfolio.user_id)
    if run is None:
        return []
    filters = [_latest_run_filter(IbkrTradeRoundTrip, run)]
    if symbol:
        filters.append(IbkrTradeRoundTrip.symbol == symbol.upper())
    rows = db.scalars(select(IbkrTradeRoundTrip).where(*filters).order_by(
        IbkrTradeRoundTrip.closed_at.desc().nullslast(), IbkrTradeRoundTrip.id.desc()
    )).all()
    return [{
        "id": row.id, "symbol": row.symbol, "account": row.account_id,
        "opened_at": row.opened_at, "closed_at": row.closed_at, "quantity": _number(row.quantity),
        "average_entry_price": _number(row.average_entry_price), "average_exit_price": _number(row.average_exit_price),
        "gross_pnl": _number(row.gross_pnl), "commissions": _number(row.commissions), "taxes": _number(row.taxes),
        "net_pnl": _number(row.net_pnl), "return_pct": _number(row.return_pct), "holding_days": row.holding_days,
        "matching_method": row.matching_method, "source_type": "ibkr_flex", "is_authoritative": True,
        "warnings": row.warnings,
    } for row in rows]


def open_lots(db: Session, portfolio: Portfolio, *, symbol: str | None = None) -> list[dict]:
    run = latest_authoritative_run(db, portfolio.user_id)
    rows: list[dict] = []
    if run:
        filters = [IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section == "tax_lots"]
        if symbol:
            filters.append(IbkrFlexRecord.symbol == symbol.upper())
        for row in db.scalars(select(IbkrFlexRecord).where(*filters)).all():
            fields = row.raw_payload or {}
            rows.append({
                "lot_id": f"ibkr:{row.id}", "symbol": row.symbol, "account": row.account_id,
                "opened_at": fields.get("openDateTime") or fields.get("holdingPeriodDateTime"),
                "quantity": _number(row.quantity) or _number(decimal_value(fields, "quantity")),
                "cost_basis": _number(decimal_value(fields, "costBasisMoney", "costBasis")),
                "cost_per_share": _number(decimal_value(fields, "costBasisPrice")),
                "currency": row.currency, "unrealized_pnl": _number(decimal_value(fields, "fifoPnlUnrealized", "unrealizedPnl")),
                "status": "open", "matching_method": "ibkr_tax_lot", "source_type": "ibkr_flex",
                "is_authoritative": True,
            })
    manual_filters = [
        PortfolioPositionLot.portfolio_id == portfolio.id,
        PortfolioPositionLot.status.in_(("open", "partial")),
    ]
    if symbol:
        manual_filters.append(PortfolioPositionLot.symbol == symbol.upper())
    for row in db.scalars(select(PortfolioPositionLot).where(*manual_filters)).all():
        authority = db.scalar(select(PortfolioPosition.authority_source).where(
            PortfolioPosition.portfolio_id == portfolio.id, PortfolioPosition.symbol == row.symbol
        ))
        if authority == "ibkr_flex":
            continue
        rows.append({
            "lot_id": f"manual:{row.id}", "symbol": row.symbol, "account": None,
            "opened_at": row.purchase_date, "quantity": row.remaining_quantity,
            "cost_basis": row.remaining_quantity * row.purchase_price + row.allocated_fees,
            "cost_per_share": row.purchase_price, "currency": row.currency, "unrealized_pnl": None,
            "status": row.status, "matching_method": "manual_average_cost", "source_type": "manual",
            "is_authoritative": True,
        })
    return rows
