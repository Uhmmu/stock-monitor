"""Auditable, idempotent analytics derived from typed IBKR Flex records.

The raw Flex rows remain the evidence layer.  This module centralizes business
classification and calculation rules so routes and the frontend never infer
accounting semantics from free-form descriptions.
"""
from __future__ import annotations

import bisect
import hashlib
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, delete, or_, select
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


def _source_sort_key(row: IbkrFlexRecord) -> tuple[datetime, date, int]:
    occurred = row.occurred_at
    if occurred is not None and occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    return (occurred or datetime.min.replace(tzinfo=UTC), row.report_date or date.min, row.source_index)


def _history_identity(row: IbkrFlexRecord) -> tuple:
    fields = row.raw_payload or {}
    if row.section == "trades":
        txn = fields.get("transactionID") or fields.get("tradeID")
        if txn:
            return ("trade-id", row.account_id, str(txn))
        return ("trade-sig", row.account_id, row.symbol, row.conid, str(fields.get("buySell") or ""),
                row.occurred_at.isoformat() if row.occurred_at else None, str(row.quantity), str(row.price))
    return ("content", row.source_id)


def _newest_run_max(rows: list[IbkrFlexRecord]) -> list[IbkrFlexRecord]:
    """Keep the largest per-report multiplicity, preferring the newest report."""
    by_run: dict[int, list[IbkrFlexRecord]] = defaultdict(list)
    for row in rows:
        by_run[row.sync_run_id or 0].append(row)
    target = max((len(bucket) for bucket in by_run.values()), default=0)
    output: list[IbkrFlexRecord] = []
    kept = 0
    for run_id in sorted(by_run, reverse=True):
        take = min(len(by_run[run_id]), target - kept)
        output.extend(by_run[run_id][:take])
        kept += take
        if kept >= target:
            break
    return output


def _collapse_restatements(rows: list[IbkrFlexRecord]) -> list[IbkrFlexRecord]:
    """Collapse broker restatements across merged reports.

    The same business event can come back in a later report with slightly
    different row content — and therefore a different ``source_id`` — so
    content identity alone would double count it.  A real event appears once
    in every report covering its date, so the merged multiplicity of an
    identity is the maximum per-report count, preferring the newest report's
    rows; summing across reports would count restated rows twice.
    """
    groups: dict[tuple, list[IbkrFlexRecord]] = defaultdict(list)
    for row in rows:
        groups[_history_identity(row)].append(row)
    merged: list[IbkrFlexRecord] = []
    for bucket in groups.values():
        merged.extend(_newest_run_max(bucket))
    return merged


def record_history(db: Session, run: IbkrFlexSyncRun, sections: tuple[str, ...]) -> list[IbkrFlexRecord]:
    """Merged, window-proof source rows for a section family.

    Flex queries are commonly configured with a rolling period (for example
    ``Last365CalendarDays``), so each new report starts a little later than
    the previous one.  Reading only the newest report would silently truncate
    account history as the window slides.  Rows dated strictly before the
    current window start are therefore unioned back in from earlier imported
    runs and collapsed by business identity (see ``_collapse_restatements``),
    with the newest report winning any conflict.  Every IBKR consumer —
    analytics rebuilds, trade listings, attribution, manual-fact governance —
    must read through this boundary instead of filtering by ``sync_run_id``
    directly, so a sliding window never erases or duplicates history.
    """
    current = list(db.scalars(select(IbkrFlexRecord).where(
        IbkrFlexRecord.sync_run_id == run.id, IbkrFlexRecord.section.in_(sections),
    )).all())
    prior: list[IbkrFlexRecord] = []
    if run.report_from_date is not None:
        prior_run_ids = list(db.scalars(select(IbkrFlexSyncRun.id).where(
            IbkrFlexSyncRun.user_id == run.user_id,
            IbkrFlexSyncRun.id != run.id,
            IbkrFlexSyncRun.normalized_record_count > 0,
        )).all())
        if prior_run_ids:
            window_start = datetime.combine(run.report_from_date, datetime.min.time(), tzinfo=UTC)
            prior = list(db.scalars(select(IbkrFlexRecord).where(
                IbkrFlexRecord.sync_run_id.in_(prior_run_ids),
                IbkrFlexRecord.section.in_(sections),
                or_(
                    IbkrFlexRecord.report_date < run.report_from_date,
                    and_(
                        IbkrFlexRecord.report_date.is_(None),
                        IbkrFlexRecord.occurred_at.is_not(None),
                        IbkrFlexRecord.occurred_at < window_start,
                    ),
                ),
            ).order_by(IbkrFlexRecord.sync_run_id, IbkrFlexRecord.id)).all())
    merged = _collapse_restatements([*prior, *current])
    merged.sort(key=_source_sort_key)
    return merged


def rebuild_cash_flows(db: Session, run: IbkrFlexSyncRun) -> int:
    db.execute(delete(IbkrNormalizedCashFlow).where(
        IbkrNormalizedCashFlow.user_id == run.user_id,
        IbkrNormalizedCashFlow.calculation_version == CALCULATION_VERSION,
    ))
    count = 0
    source_rows = record_history(db, run, ("cash_ledger", "cash_transactions", "transfers", "interest"))
    portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == run.user_id, Portfolio.slug == "default"))
    base_currency = portfolio.base_currency if portfolio else None

    # Flex commonly represents one external transfer three times: a detailed
    # CashTransaction in the funding currency, a StatementOfFunds currency row,
    # and a StatementOfFunds BaseCurrency row.  Keep exactly one authoritative
    # representation per transfer, preferring the broker-provided base-currency
    # row.  The group retains multiplicity, so two equal deposits on one day are
    # still two deposits rather than one; merged across reports that
    # multiplicity is the maximum seen in any single report (restated rows in
    # older reports must not add to it).
    external_groups: dict[
        tuple[date | None, str, Decimal | None],
        dict[int, list[tuple[Any, Decimal | None, list[str]]]],
    ] = defaultdict(lambda: defaultdict(list))
    internal_groups: dict[tuple, list[tuple[Any, str, bool, str, list[str], Decimal | None]]] = defaultdict(list)
    for row in source_rows:
        fields = row.raw_payload or {}
        description = row.description or fields.get("activityDescription") or fields.get("description")
        category, external, rule, warnings = classify_cash_flow(fields, description)
        amount = row.amount if row.amount is not None else decimal_value(fields, "amount", "netCash", "netAmount", "credit", "debit")
        if not external:
            flow_date = row.report_date or date_value(fields, "settleDate", "date", "tradeDate")
            internal_groups[(flow_date, category, amount, row.currency, row.symbol, row.conid)].append(
                (row, category, external, rule, warnings, amount))
            continue
        fx_rate = decimal_value(fields, "fxRateToBase")
        level = str(fields.get("levelOfDetail") or "")
        is_base_row = level == "BaseCurrency" and (not base_currency or row.currency == base_currency)
        converted = amount if is_base_row or not base_currency or row.currency == base_currency else (
            amount * fx_rate if amount is not None and fx_rate is not None else None
        )
        if converted is None and amount is not None and row.currency != base_currency:
            warnings = [*warnings, "外部现金流缺少可审计的基础币种换算"]
        signature_amount = converted.quantize(Decimal("0.000001")) if converted is not None else amount
        signature = (row.report_date or date_value(fields, "settleDate", "date", "tradeDate"), category, signature_amount)
        priority = 0 if is_base_row else 1 if str(fields.get("sourceTag") or "") == "CashTransaction" else 2
        external_groups[signature][priority].append((row, converted, warnings))

    def keep_newest_run_max(items: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
        kept_ids = {row.id for row in _newest_run_max([item[0] for item in items])}
        return [item for item in items if item[0].id in kept_ids]

    normalized_rows: list[tuple[Any, str, bool, str, list[str], Decimal | None]] = []
    for bucket in internal_groups.values():
        normalized_rows.extend(keep_newest_run_max(bucket))
    for (_, category, _), representations in external_groups.items():
        priority = min(representations)
        for row, converted, warnings in keep_newest_run_max(representations[priority]):
            fields = row.raw_payload or {}
            description = row.description or fields.get("activityDescription") or fields.get("description")
            _, external, rule, _ = classify_cash_flow(fields, description)
            normalized_rows.append((row, category, external, rule, warnings, converted))

    normalized_rows.sort(key=lambda item: _source_sort_key(item[0]))
    for row, category, external, rule, warnings, amount in normalized_rows:
        fields = row.raw_payload or {}
        description = row.description or fields.get("activityDescription") or fields.get("description")
        db.add(IbkrNormalizedCashFlow(
            user_id=run.user_id, account_id=row.account_id or run.account_id,
            source_record_id=row.id, source_sync_run_id=run.id,
            flow_date=row.report_date or date_value(fields, "settleDate", "date", "tradeDate"),
            occurred_at=row.occurred_at,
            currency=((base_currency or row.currency) if external and amount is not None else row.currency),
            amount=amount,
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
    # The event key is stable business identity, but the same payout can come
    # back across reports as rows with drifted content (different source_id);
    # keep the newest report's version of each key so the unique constraint
    # on (user, event_key, calculation_version) can never be violated.
    chosen: dict[str, tuple[IbkrFlexRecord, str]] = {}
    for row in record_history(db, run, ("dividends",)):
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
        existing = chosen.get(event_key)
        if existing is None or (row.sync_run_id or 0) >= (existing[0].sync_run_id or 0):
            chosen[event_key] = (row, status)
    for row, status in sorted(chosen.values(), key=lambda item: _source_sort_key(item[0])):
        fields = row.raw_payload or {}
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
    for row in record_history(db, run, ("fifo_performance", "tax_lots")):
        pnl = decimal_value(row.raw_payload, "fifoPnlRealized", "realizedPnl", "mtmPnl", "pnl")
        link = next((str(row.raw_payload.get(key)) for key in ("transactionID", "tradeID", "closingTransactionID") if row.raw_payload.get(key)), None)
        if pnl is not None and link:
            explicit[link] = pnl
    lots: dict[tuple[str | None, str | None], deque[dict[str, Any]]] = defaultdict(deque)
    count = 0
    for row in record_history(db, run, ("trades",)):
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
    candidates_by_date: dict[date, dict[str, Any]] = {}
    for row in record_history(db, run, ("performance",)):
        fields = row.raw_payload or {}
        perf_date = row.report_date or date_value(fields, "reportDate", "date")
        if not perf_date or str(fields.get("sourceTag")) not in {"EquitySummaryByReportDateInBase", "SymbolSummary"}:
            continue
        beginning = decimal_value(fields, "startingValue", "beginningNAV", "startingNAV")
        ending = decimal_value(fields, "endingValue", "endingNAV", "total")
        ending_cash = decimal_value(fields, "endingCash", "cash")
        if ending is None:
            continue
        # The same day can appear in several historical reports with a
        # different source_id when the broker restates early values; keep the
        # newest report's version only.
        previous = candidates_by_date.get(perf_date)
        if previous is not None and (previous["row"].sync_run_id or 0) >= (row.sync_run_id or 0):
            continue
        all_daily_flows = flow_by_date.get(perf_date, [])
        daily_flows = [flow for flow in all_daily_flows if not flow.is_external or not base_currency or flow.currency == base_currency]
        excluded_external = [flow for flow in all_daily_flows if flow.is_external and base_currency and flow.currency != base_currency]
        deposits = sum((f.amount or ZERO) for f in daily_flows if f.normalized_category == "deposit")
        withdrawals = sum((abs(f.amount or ZERO) for f in daily_flows if f.normalized_category == "withdrawal"), ZERO)
        net_external = deposits - withdrawals
        warnings = (["存在非基础币种外部现金流且缺少可审计的同日换算，daily return 保持 null"] if excluded_external else [])
        candidates_by_date[perf_date] = {"date": perf_date, "row": row, "beginning": beginning, "ending": ending,
                                         "ending_cash": ending_cash, "deposits": deposits, "withdrawals": withdrawals,
                                         "net_external": None if excluded_external else net_external, "warnings": warnings,
                                         "excluded_external": bool(excluded_external)}
    candidates = sorted(candidates_by_date.values(), key=lambda item: item["date"])
    # External transfers dated before the first covered equity-summary day
    # (Flex leaves the account's opening days blank) still belong to the
    # capital base; attach them to the next covered day so cumulative
    # contributions stay complete.
    candidate_dates = [item["date"] for item in candidates]
    for flow in flows:
        if not candidates or not flow.is_external or not flow.flow_date or flow.flow_date in candidates_by_date:
            continue
        position = bisect.bisect_left(candidate_dates, flow.flow_date)
        if position >= len(candidates):
            position = len(candidates) - 1
        target = candidates[position]
        if base_currency and flow.currency != base_currency:
            target["excluded_external"] = True
            target["net_external"] = None
            if "存在非基础币种外部现金流且缺少可审计的同日换算，daily return 保持 null" not in target["warnings"]:
                target["warnings"].append("存在非基础币种外部现金流且缺少可审计的同日换算，daily return 保持 null")
            continue
        if flow.normalized_category == "deposit":
            target["deposits"] += flow.amount or ZERO
        elif flow.normalized_category == "withdrawal":
            target["withdrawals"] += abs(flow.amount or ZERO)
        if not target["excluded_external"]:
            target["net_external"] = target["deposits"] - target["withdrawals"]
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
    winners: dict[tuple[date, str], tuple[IbkrFlexRecord, date, str]] = {}
    for row in record_history(db, run, ("performance",)):
        fields = row.raw_payload or {}
        perf_date = row.report_date or date_value(fields, "reportDate", "date")
        conid = row.conid or str(fields.get("conid") or "")
        if not perf_date or not conid or not row.symbol:
            continue
        identity = (perf_date, conid)
        winner = winners.get(identity)
        if winner is not None and (winner[0].sync_run_id or 0) >= (row.sync_run_id or 0):
            continue
        winners[identity] = (row, perf_date, conid)
    for row, perf_date, conid in sorted(winners.values(), key=lambda item: item[1]):
        fields = row.raw_payload or {}
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
