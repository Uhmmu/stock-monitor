"""Auditable, idempotent analytics derived from typed IBKR Flex records.

The raw Flex rows remain the evidence layer.  This module centralizes business
classification and calculation rules so routes and the frontend never infer
accounting semantics from free-form descriptions.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import HistoricalPrice, Portfolio, Security
from .db_models import (
    IbkrAccountDailyPerformance, IbkrDividendEvent, IbkrFlexRecord,
    IbkrFlexSyncRun, IbkrNormalizedCashFlow, IbkrPositionPerformanceDaily, IbkrTradeRoundTrip,
)

CALCULATION_VERSION = "ibkr-account-v1"
ZERO = Decimal("0")


def decimal_value(fields: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = fields.get(key)
        if value in (None, "", "--", "N/A"):
            continue
        try:
            return Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError):
            continue
    return None


def date_value(fields: dict[str, Any], *keys: str) -> date | None:
    for key in keys:
        value = fields.get(key)
        if isinstance(value, date):
            return value
        if not value:
            continue
        text = str(value)
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
    return None


def datetime_value(fields: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        value = fields.get(key)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if not value:
            continue
        text = str(value).replace(";", " ")
        for fmt in ("%Y%m%d %H%M%S", "%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=UTC)
            except ValueError:
                pass
    return None


def classify_cash_flow(fields: dict[str, Any], description: str | None = None) -> tuple[str, bool, str, list[str]]:
    """Return category, external flag, rule id and warnings.

    Codes win over descriptions. Descriptions are only a conservative fallback;
    unknown entries remain visible as ``other``.
    """
    code = str(fields.get("activityCode") or fields.get("type") or fields.get("transactionType") or "").upper()
    kind = str(fields.get("category") or fields.get("transactionType") or "").upper()
    text = " ".join(filter(None, [code, kind, description, str(fields.get("activityDescription") or "")])).upper()
    rules = (
        (("DEP", "DEPOSIT", "WIRE IN", "ACH IN", "CASH RECEIPT"), "deposit", True, "external_deposit"),
        (("WDR", "WITHDRAW", "WIRE OUT", "ACH OUT", "DISBURSEMENT"), "withdrawal", True, "external_withdrawal"),
        (("BUY", "SELL", "TRADE", "SETTLEMENT"), "trade_settlement", False, "trade_settlement"),
        (("DIV", "DIVIDEND", "PAYMENT IN LIEU"), "payment_in_lieu" if "LIEU" in text else "dividend", False, "dividend"),
        (("WITHHOLD", "WHT", "TAX"), "withholding_tax", False, "withholding_tax"),
        (("COMM", "COMMISSION"), "commission", False, "commission"),
        (("MARGIN INTEREST", "DEBIT INTEREST"), "margin_interest", False, "margin_interest"),
        (("INTEREST", "CREDIT INTEREST"), "interest_income", False, "interest_income"),
        (("FX", "FOREX", "CONVERSION"), "fx_conversion", False, "fx_conversion"),
        (("ADR FEE", "MARKET DATA", "BROKER FEE", "REGULATORY FEE", "EXCHANGE FEE"), "broker_fee", False, "broker_fee"),
        (("CORPORATE ACTION", "MERGER", "SPLIT", "SPINOFF"), "corporate_action", False, "corporate_action"),
    )
    for needles, category, external, rule in rules:
        if any(needle == code or needle in text for needle in needles):
            return category, external, rule, []
    return "other", False, "unclassified_v1", ["无法可靠分类，已保留为 other"]


def calculate_return(beginning_nav: Decimal | None, ending_nav: Decimal | None, net_external_flow: Decimal | None) -> Decimal | None:
    if beginning_nav in (None, ZERO) or ending_nav is None or net_external_flow is None:
        return None
    return (ending_nav - net_external_flow) / beginning_nav - Decimal("1")


def drawdown_series(returns: list[Decimal | None]) -> list[tuple[Decimal | None, Decimal | None, Decimal | None]]:
    cumulative = Decimal("1")
    peak = Decimal("1")
    maximum = ZERO
    output = []
    for value in returns:
        if value is None:
            output.append((None, None, -maximum if maximum else ZERO))
            continue
        cumulative *= Decimal("1") + value
        peak = max(peak, cumulative)
        drawdown = cumulative / peak - Decimal("1") if peak else None
        if drawdown is not None:
            maximum = max(maximum, -drawdown)
        output.append((cumulative - Decimal("1"), drawdown, -maximum))
    return output


def _source_rows(db: Session, run_id: int, sections: tuple[str, ...]) -> list[IbkrFlexRecord]:
    return list(db.scalars(select(IbkrFlexRecord).where(
        IbkrFlexRecord.sync_run_id == run_id, IbkrFlexRecord.section.in_(sections),
    ).order_by(IbkrFlexRecord.occurred_at, IbkrFlexRecord.report_date, IbkrFlexRecord.source_index)).all())


def rebuild_cash_flows(db: Session, run: IbkrFlexSyncRun) -> int:
    db.execute(delete(IbkrNormalizedCashFlow).where(
        IbkrNormalizedCashFlow.user_id == run.user_id,
        IbkrNormalizedCashFlow.calculation_version == CALCULATION_VERSION,
    ))
    count = 0
    for row in _source_rows(db, run.id, ("cash_ledger", "cash_transactions", "interest")):
        fields = row.raw_payload or {}
        description = row.description or fields.get("activityDescription") or fields.get("description")
        category, external, rule, warnings = classify_cash_flow(fields, description)
        amount = row.amount if row.amount is not None else decimal_value(fields, "amount", "netCash", "netAmount", "credit", "debit")
        db.add(IbkrNormalizedCashFlow(
            user_id=run.user_id, account_id=row.account_id or run.account_id,
            source_record_id=row.id, source_sync_run_id=run.id,
            flow_date=row.report_date or date_value(fields, "settleDate", "date", "tradeDate"),
            occurred_at=row.occurred_at, currency=row.currency, amount=amount,
            normalized_category=category, is_external=external, classification_rule=rule,
            original_type=str(fields.get("activityCode") or fields.get("type") or fields.get("transactionType") or "") or None,
            original_description=description, warnings=warnings, calculation_version=CALCULATION_VERSION,
        ))
        count += 1
    db.flush()
    return count


def rebuild_dividends(db: Session, run: IbkrFlexSyncRun) -> int:
    db.execute(delete(IbkrDividendEvent).where(
        IbkrDividendEvent.user_id == run.user_id,
        IbkrDividendEvent.calculation_version == CALCULATION_VERSION,
    ))
    count = 0
    for row in _source_rows(db, run.id, ("dividends",)):
        fields = row.raw_payload or {}
        source_tag = str(fields.get("sourceTag") or "")
        code = str(fields.get("code") or fields.get("action") or "").upper()
        status = "reversed" if any(token in code for token in ("REV", "CANCEL", "ADJUST")) else (
            "received" if source_tag == "DividendAccrual" or fields.get("date") else "accrued"
        )
        gross = decimal_value(fields, "grossAmount", "amount", "dividendAccrualChange")
        tax = decimal_value(fields, "tax", "withholdingTax")
        net = decimal_value(fields, "netAmount", "netCash")
        if net is None and gross is not None and tax is not None:
            net = gross + tax if tax < 0 else gross - tax
        event_key = hashlib.sha256("|".join(str(value or "") for value in (
            row.account_id, row.conid, row.symbol, fields.get("exDate"), fields.get("payDate"), gross, status,
        )).encode()).hexdigest()[:64]
        db.add(IbkrDividendEvent(
            user_id=run.user_id, account_id=row.account_id or run.account_id, source_record_id=row.id,
            source_sync_run_id=run.id, conid=row.conid, symbol=row.symbol, currency=row.currency,
            ex_date=date_value(fields, "exDate"), pay_date=date_value(fields, "payDate", "date"),
            gross_dividend=gross, withholding_tax=tax, net_dividend=net, status=status,
            event_key=event_key, calculation_version=CALCULATION_VERSION,
            warnings=[] if gross is not None or net is not None else ["股息金额字段缺失"],
        ))
        count += 1
    db.flush()
    return count


def _trade_side(fields: dict[str, Any]) -> int:
    side = str(fields.get("buySell") or fields.get("side") or "").upper()
    return 1 if side in {"BUY", "BOT", "B"} else -1 if side in {"SELL", "SLD", "S"} else 0


def rebuild_round_trips(db: Session, run: IbkrFlexSyncRun) -> int:
    """FIFO fallback supporting partial closes and repeated entries.

    Explicit IBKR FIFO summaries are preserved as the source of realized P&L
    when they can be tied to a symbol; the lot matcher supplies open/close and
    price fields without pretending those are broker-provided facts.
    """
    db.execute(delete(IbkrTradeRoundTrip).where(
        IbkrTradeRoundTrip.user_id == run.user_id,
        IbkrTradeRoundTrip.calculation_version == CALCULATION_VERSION,
    ))
    securities = {row.ibkr_conid: row.id for row in db.scalars(select(Security).where(Security.ibkr_conid.is_not(None))).all()}
    explicit: dict[str, Decimal] = {}
    for row in _source_rows(db, run.id, ("fifo_performance", "tax_lots")):
        pnl = decimal_value(row.raw_payload, "fifoPnlRealized", "realizedPnl", "mtmPnl", "pnl")
        link = next((str(row.raw_payload.get(key)) for key in ("transactionID", "tradeID", "closingTransactionID") if row.raw_payload.get(key)), None)
        if pnl is not None and link:
            explicit[link] = pnl
    lots: dict[tuple[str | None, str | None], deque[dict[str, Any]]] = defaultdict(deque)
    count = 0
    for row in _source_rows(db, run.id, ("trades",)):
        fields = row.raw_payload or {}
        side = _trade_side(fields)
        quantity = abs(row.quantity or decimal_value(fields, "quantity", "tradeQuantity") or ZERO)
        price = row.price or decimal_value(fields, "tradePrice", "price")
        if side == 0 or quantity <= 0 or price is None:
            continue
        key = (row.conid, row.symbol)
        timestamp = row.occurred_at or datetime.combine(row.report_date or run.report_to_date or date.today(), datetime.min.time(), tzinfo=UTC)
        commission = abs(decimal_value(fields, "ibCommission", "commission") or ZERO)
        taxes = abs(decimal_value(fields, "taxes", "tax") or ZERO)
        remaining = quantity
        queue = lots[key]
        while remaining > 0 and queue and queue[0]["side"] != side:
            opening = queue[0]
            matched = min(remaining, opening["quantity"])
            open_fee = opening["commission"] * matched / opening["original_quantity"]
            close_fee = commission * matched / quantity
            close_tax = taxes * matched / quantity
            gross = (price - opening["price"]) * matched * Decimal(opening["side"])
            close_link = next((str(fields.get(name)) for name in ("transactionID", "tradeID") if fields.get(name)), None)
            broker_pnl = explicit.pop(close_link, None) if close_link else None
            authoritative_gross = broker_pnl if broker_pnl is not None else gross
            net = authoritative_gross - open_fee - close_fee - close_tax
            held = max(0, (timestamp.date() - opening["opened_at"].date()).days)
            source_key = hashlib.sha256(f"{opening['source_id']}|{row.source_id}|{matched}".encode()).hexdigest()[:64]
            denominator = opening["price"] * matched
            db.add(IbkrTradeRoundTrip(
                user_id=run.user_id, account_id=row.account_id or run.account_id,
                instrument_id=securities.get(row.conid), conid=row.conid, symbol=row.symbol,
                opened_at=opening["opened_at"], closed_at=timestamp, quantity=matched,
                average_entry_price=opening["price"], average_exit_price=price,
                gross_pnl=authoritative_gross, commissions=open_fee + close_fee, taxes=close_tax,
                net_pnl=net, return_pct=(net / denominator if denominator else None), holding_days=held,
                matching_method="ibkr_fifo" if broker_pnl is not None else "derived_fifo",
                source_key=source_key, source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
                warnings=[] if broker_pnl is not None else ["IBKR 明确 FIFO 关联缺失，使用项目 FIFO 推导"],
            ))
            count += 1
            remaining -= matched
            opening["quantity"] -= matched
            if opening["quantity"] <= 0:
                queue.popleft()
        if remaining > 0:
            queue.append({"side": side, "quantity": remaining, "original_quantity": quantity, "price": price,
                          "commission": commission * remaining / quantity, "opened_at": timestamp, "source_id": row.source_id})
    db.flush()
    return count


def rebuild_daily_performance(db: Session, run: IbkrFlexSyncRun) -> int:
    db.execute(delete(IbkrAccountDailyPerformance).where(
        IbkrAccountDailyPerformance.user_id == run.user_id,
        IbkrAccountDailyPerformance.calculation_version == CALCULATION_VERSION,
    ))
    flows = list(db.scalars(select(IbkrNormalizedCashFlow).where(
        IbkrNormalizedCashFlow.user_id == run.user_id,
        IbkrNormalizedCashFlow.source_sync_run_id == run.id,
        IbkrNormalizedCashFlow.calculation_version == CALCULATION_VERSION,
    )).all())
    flow_by_date: dict[date, list[IbkrNormalizedCashFlow]] = defaultdict(list)
    for flow in flows:
        if flow.flow_date:
            flow_by_date[flow.flow_date].append(flow)
    portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == run.user_id, Portfolio.slug == "default"))
    base_currency = portfolio.base_currency if portfolio else None
    candidates: list[dict[str, Any]] = []
    for row in _source_rows(db, run.id, ("performance",)):
        fields = row.raw_payload or {}
        perf_date = row.report_date or date_value(fields, "reportDate", "date")
        if not perf_date or str(fields.get("sourceTag")) not in {"EquitySummaryByReportDateInBase", "SymbolSummary"}:
            continue
        beginning = decimal_value(fields, "startingValue", "beginningNAV", "startingNAV")
        ending = decimal_value(fields, "endingValue", "endingNAV", "total")
        ending_cash = decimal_value(fields, "endingCash", "cash")
        if ending is None:
            continue
        all_daily_flows = flow_by_date.get(perf_date, [])
        daily_flows = [flow for flow in all_daily_flows if not flow.is_external or not base_currency or flow.currency == base_currency]
        excluded_external = [flow for flow in all_daily_flows if flow.is_external and base_currency and flow.currency != base_currency]
        deposits = sum((f.amount or ZERO) for f in daily_flows if f.normalized_category == "deposit")
        withdrawals = sum((abs(f.amount or ZERO) for f in daily_flows if f.normalized_category == "withdrawal"), ZERO)
        net_external = deposits - withdrawals
        warnings = (["存在非基础币种外部现金流且缺少可审计的同日换算，daily return 保持 null"] if excluded_external else [])
        candidates.append({"date": perf_date, "row": row, "beginning": beginning, "ending": ending,
                           "ending_cash": ending_cash, "deposits": deposits, "withdrawals": withdrawals,
                           "net_external": None if excluded_external else net_external, "warnings": warnings})
    candidates.sort(key=lambda item: item["date"])
    previous_nav = previous_cash = None
    for item in candidates:
        if item["beginning"] is None:
            item["beginning"] = previous_nav
            if previous_nav is None:
                item["warnings"].append("首个覆盖日缺少前一日净值，daily return 保持 null")
        item["beginning_cash"] = previous_cash
        item["daily_return"] = calculate_return(item["beginning"], item["ending"], item["net_external"])
        previous_nav, previous_cash = item["ending"], item["ending_cash"]
    drawdowns = drawdown_series([item["daily_return"] for item in candidates])
    for item, (cumulative, drawdown, max_drawdown) in zip(candidates, drawdowns):
        perf_date, row = item["date"], item["row"]
        beginning, ending = item["beginning"], item["ending"]
        deposits, withdrawals, net_external = item["deposits"], item["withdrawals"], item["net_external"]
        daily_return, warnings = item["daily_return"], item["warnings"]
        fields = row.raw_payload or {}
        ending_cash = item["ending_cash"]
        gross_position_value = ending - ending_cash if ending_cash is not None else decimal_value(fields, "grossPositionValue", "longValue", "stock")
        db.add(IbkrAccountDailyPerformance(
            user_id=run.user_id, account_id=row.account_id or run.account_id or "unknown", performance_date=perf_date,
            base_currency=row.currency or fields.get("currency"), beginning_nav=beginning, ending_nav=ending,
            beginning_cash=item["beginning_cash"], ending_cash=ending_cash,
            gross_position_value=gross_position_value,
            external_deposits=deposits, external_withdrawals=withdrawals, net_external_cash_flow=net_external,
            realized_pnl=decimal_value(fields, "realized", "realizedPnl"),
            unrealized_pnl_change=decimal_value(fields, "changeInUnrealized", "unrealizedPnl"),
            dividend_income=decimal_value(fields, "dividends", "dividendIncome"), interest_income=decimal_value(fields, "interest", "interestIncome"),
            commissions=decimal_value(fields, "commissions", "commission"), taxes=decimal_value(fields, "taxes", "tax"),
            other_fees=decimal_value(fields, "otherFees", "fees"), fx_pnl=decimal_value(fields, "fxPnl", "forexPnl"),
            investment_pnl=(ending - beginning - net_external if ending is not None and beginning is not None and net_external is not None else None),
            daily_return=daily_return, cumulative_return=cumulative, drawdown=drawdown, max_drawdown_to_date=max_drawdown,
            data_completeness=Decimal(sum(value is not None for value in (beginning, ending, daily_return, decimal_value(fields, "realized", "realizedPnl"), decimal_value(fields, "changeInUnrealized", "unrealizedPnl")))) / Decimal("5"),
            warnings=warnings, source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
        ))
    db.flush()
    return len(candidates)


def rebuild_position_performance(db: Session, run: IbkrFlexSyncRun) -> int:
    db.execute(delete(IbkrPositionPerformanceDaily).where(
        IbkrPositionPerformanceDaily.user_id == run.user_id,
        IbkrPositionPerformanceDaily.calculation_version == CALCULATION_VERSION,
    ))
    securities = {row.ibkr_conid: row.id for row in db.scalars(select(Security).where(Security.ibkr_conid.is_not(None))).all()}
    count = 0
    seen: set[tuple[date, str]] = set()
    for row in _source_rows(db, run.id, ("performance",)):
        fields = row.raw_payload or {}
        perf_date = row.report_date or date_value(fields, "reportDate", "date")
        conid = row.conid or str(fields.get("conid") or "")
        if not perf_date or not conid or not row.symbol:
            continue
        identity = (perf_date, conid)
        if identity in seen:
            continue
        seen.add(identity)
        close = db.scalar(select(HistoricalPrice).where(
            HistoricalPrice.symbol == row.symbol, HistoricalPrice.date <= perf_date,
        ).order_by(HistoricalPrice.date.desc(), HistoricalPrice.source.asc()).limit(1))
        closing_quantity = decimal_value(fields, "endingPosition", "position", "quantity")
        opening_quantity = decimal_value(fields, "startingPosition", "beginningPosition", "priorQuantity")
        net_trade = decimal_value(fields, "tradeQuantity", "netTradeQuantity")
        closing_value = Decimal(str(close.close)) * closing_quantity if close and close.close is not None and closing_quantity is not None else None
        realized = decimal_value(fields, "realized", "fifoPnlRealized", "realizedPnl")
        unrealized = decimal_value(fields, "changeInUnrealized", "unrealizedPnl")
        dividend = decimal_value(fields, "dividends", "dividendIncome")
        commissions = decimal_value(fields, "commissions", "ibCommission")
        taxes = decimal_value(fields, "taxes", "tax")
        fx_pnl = decimal_value(fields, "fxPnl", "forexPnl")
        components = (realized, unrealized, dividend, commissions, taxes, fx_pnl)
        total_pnl = sum((value for value in components if value is not None), ZERO) if any(value is not None for value in components) else None
        warnings = []
        if close is None:
            warnings.append("该日及此前无项目行情价格；未使用未来价格")
        if opening_quantity is None or closing_quantity is None:
            warnings.append("Flex 未提供完整的日初/日末数量")
        db.add(IbkrPositionPerformanceDaily(
            user_id=run.user_id, account_id=row.account_id or run.account_id or "unknown", performance_date=perf_date,
            instrument_id=securities.get(conid), conid=conid, symbol=row.symbol, currency=row.currency,
            opening_quantity=opening_quantity, closing_quantity=closing_quantity, net_trade_quantity=net_trade,
            average_cost=decimal_value(fields, "costBasisPrice", "averageCost"),
            opening_market_value=decimal_value(fields, "startingValue", "openingMarketValue"), closing_market_value=closing_value,
            portfolio_weight=decimal_value(fields, "percentOfNAV", "weight"), realized_pnl=realized,
            unrealized_pnl_change=unrealized, dividend_income=dividend, commissions=commissions, taxes=taxes,
            fx_pnl=fx_pnl, total_pnl=total_pnl, contribution_to_portfolio_return=decimal_value(fields, "contributionToReturn"),
            price_source=(close.source if close else None), price_as_of=(close.date if close else None),
            data_completeness=Decimal(sum(value is not None for value in (opening_quantity, closing_quantity, closing_value, total_pnl))) / Decimal("4"),
            warnings=warnings, source_sync_run_id=run.id, calculation_version=CALCULATION_VERSION,
        ))
        count += 1
    db.flush()
    return count


def rebuild_all_analytics(db: Session, run: IbkrFlexSyncRun) -> dict[str, int]:
    cash = rebuild_cash_flows(db, run)
    dividends = rebuild_dividends(db, run)
    round_trips = rebuild_round_trips(db, run)
    daily = rebuild_daily_performance(db, run)
    position_daily = rebuild_position_performance(db, run)
    return {"cash_flows": cash, "dividend_events": dividends, "round_trips": round_trips, "daily_performance": daily, "position_performance_daily": position_daily}
