from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .flex_types import FlexParsedReport, FlexRecord, FlexStatementMetadata

PARSER_VERSION = "ibkr-flex-v1"

SECTION_TAGS = {
    "account_information": {"AccountInformation"},
    "account_nav": {"ChangeInNAV", "AssetSummary", "ChangeInPositionValue"},
    "cash_reports": {"CashReportCurrency"},
    "positions": {"OpenPosition"},
    "prior_positions": {"PriorPeriodPosition"},
    "trades": {"Trade"},
    "orders": {"Order"},
    "cash_transactions": {"CashTransaction"},
    "cash_ledger": {"StatementOfFundsLine"},
    "dividends": {"ChangeInDividendAccrual", "OpenDividendAccrual", "DividendAccrual"},
    "performance": {"EquitySummaryByReportDateInBase", "MTMPerformanceSummaryUnderlying", "SymbolSummary"},
    "fifo_performance": {"FIFOPerformanceSummaryUnderlying"},
    "tax_lots": {"Lot"},
    "instruments": {"SecurityInfo"},
    "fx_rates": {"ConversionRate"},
    "corporate_actions": {"CorporateAction"},
    "transfers": {"Transfer", "UnsettledTransfer"},
    "interest": {"InterestAccrualsCurrency", "TierInterestDetail", "BrokerFeeDetail"},
    "securities_lending": {"SecuritiesLendingActivity", "SecuritiesLendingFee"},
}

KNOWN_CONTAINER_TAGS = {
    "FlexQueryResponse", "FlexStatements", "FlexStatement", "AccountInformation",
    "OpenPositions", "Trades", "Orders", "CashTransactions", "CashReport",
    "ChangeInNAV", "EquitySummaryInBase", "RealizedUnrealizedPerformanceSummary",
    "FIFOPerformanceSummary", "PriorPeriodPositions", "PositionValueChanges",
    "StatementOfFunds", "ChangeInDividendAccruals", "FinancialInstrumentInformation",
    "HistoricalFxRates", "TaxLots",
}

DECIMAL_HINTS = re.compile(
    r"(?i)(amount|balance|cash|cost|price|value|pnl|profit|loss|commission|tax|fee|"
    r"interest|dividend|rate|quantity|position|proceeds|credit|debit|percent|weight|"
    r"margin|funds|liquidation|twr|mtm|stock|bonds|options|funds|total)$"
)
DATE_KEYS = {"reportDate", "tradeDate", "settleDate", "settleDateTarget", "exDate", "payDate", "fromDate", "toDate", "date", "issueDate", "maturity", "expiry"}
DATETIME_KEYS = {"dateTime", "openDateTime", "holdingPeriodDateTime", "orderTime", "whenGenerated", "whenRealized", "whenReopened"}


def _name(tag: str) -> str:
    return tag.split("}")[-1]


def _empty(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_decimal(value: str | None) -> Decimal | None:
    value = _empty(value)
    if value is None or value in {"--", "N/A"}:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def parse_date(value: str | None) -> date | None:
    value = _empty(value)
    if not value:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%Y%m"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def parse_datetime(value: str | None) -> datetime | None:
    value = _empty(value)
    if not value:
        return None
    normalized = value.replace(";", " ")
    for fmt in ("%Y%m%d %H%M%S", "%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d-%H:%M:%S"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or UTC)
    except ValueError:
        return None


def _typed_values(fields: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, raw in fields.items():
        if _empty(raw) is None:
            result[key] = None
        elif key in DATETIME_KEYS:
            result[key] = parse_datetime(raw)
        elif key in DATE_KEYS:
            result[key] = parse_date(raw)
        elif DECIMAL_HINTS.search(key):
            result[key] = parse_decimal(raw)
        elif raw.lower() in {"true", "false"}:
            result[key] = raw.lower() == "true"
        else:
            result[key] = raw
    return result


def _source_id(section: str, source_tag: str, index: int, fields: dict[str, str]) -> str:
    # Full canonical row content is the final identity because some valid
    # StatementOfFunds rows omit every upstream transaction identifier.
    identity = "|".join([section, source_tag, *[f"{k}={v}" for k, v in sorted(fields.items())]])
    return hashlib.sha256(identity.encode()).hexdigest()


def parse_flex_report(xml_text: str) -> FlexParsedReport:
    root = ET.fromstring(xml_text)
    statement = next((node for node in root.iter() if _name(node.tag) == "FlexStatement"), None)
    attrs = dict(statement.attrib) if statement is not None else {}
    metadata = FlexStatementMetadata(
        account_id=_empty(attrs.get("accountId")), from_date=parse_date(attrs.get("fromDate")),
        to_date=parse_date(attrs.get("toDate")), period=_empty(attrs.get("period")),
        generated_at=parse_datetime(attrs.get("whenGenerated")),
        extra_fields={k: v for k, v in attrs.items() if k not in {"accountId", "fromDate", "toDate", "period", "whenGenerated"}},
    )
    tag_to_section = {tag: section for section, tags in SECTION_TAGS.items() for tag in tags}
    records: dict[str, list[FlexRecord]] = {section: [] for section in SECTION_TAGS}
    unknown: dict[str, int] = {}
    for node in root.iter():
        tag = _name(node.tag)
        fields = {key: value for key, value in node.attrib.items()}
        if not fields or tag in {"FlexQueryResponse", "FlexStatements", "FlexStatement"}:
            continue
        section = tag_to_section.get(tag)
        if section is None:
            if tag not in KNOWN_CONTAINER_TAGS:
                unknown[tag] = unknown.get(tag, 0) + 1
            continue
        typed = _typed_values(fields)
        index = len(records[section])
        records[section].append(FlexRecord(
            section=section, source_index=index, source_id=_source_id(section, tag, index, fields),
            account_id=_empty(fields.get("accountId")), symbol=_empty(fields.get("symbol")),
            conid=_empty(fields.get("conid")), currency=_empty(fields.get("currency")),
            asset_category=_empty(fields.get("assetCategory")), description=_empty(fields.get("description")),
            report_date=parse_date(fields.get("reportDate") or fields.get("date")),
            occurred_at=parse_datetime(fields.get("dateTime") or fields.get("orderTime") or fields.get("openDateTime")),
            amount=parse_decimal(fields.get("amount") or fields.get("netCash") or fields.get("netAmount")),
            quantity=parse_decimal(fields.get("position") or fields.get("quantity") or fields.get("tradeQuantity")),
            price=parse_decimal(fields.get("markPrice") or fields.get("tradePrice") or fields.get("price")),
            values=typed, raw_fields={"sourceTag": tag, **fields},
        ))
    records = {section: rows for section, rows in records.items() if rows}
    present = sorted(records)
    warnings = [f"Flex Query 未包含 {section}" for section in SECTION_TAGS if section not in records]
    warnings.extend(f"未识别标签 {tag}: {count} 条" for tag, count in sorted(unknown.items()))
    return FlexParsedReport(
        metadata=metadata, source_hash=hashlib.sha256(xml_text.encode()).hexdigest(),
        parser_version=PARSER_VERSION, records=records, present_sections=present,
        unknown_sections=unknown, warnings=warnings,
    )
