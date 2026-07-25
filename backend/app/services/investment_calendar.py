"""Normalized investment-calendar providers, reconciliation, persistence and relevance."""
from __future__ import annotations

import hashlib
import math
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable, Protocol
from zoneinfo import ZoneInfo

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EarningsEvent,
    InvestmentCalendarEvent,
    InvestmentCalendarEventSource,
    Portfolio,
    PortfolioPosition,
    Security,
    StockProfile,
    WatchlistItem,
)

EVENT_TYPES = {
    "earnings", "dividend_ex_date", "dividend_record_date",
    "dividend_payment_date", "dividend_declaration_date", "stock_split",
    "reverse_split", "ipo", "company_event", "macro_event", "market_holiday",
}
PROVIDER_PRIORITY = {"sec": 0, "nasdaq": 1, "finnhub": 2, "yahoo": 3, "fmp": 4}
ANALYZER_VERSION = "v0.4"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json_scalar(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_scalar(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, (date, datetime)) or hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    moment = _datetime(value)
    return moment.date() if moment else None


def stable_event_id(event: dict[str, Any]) -> str:
    event_type = str(event["event_type"])
    metadata = event.get("metadata") or {}
    identity = [event_type, str(event.get("symbol") or "MARKET").upper(), str(event["event_date"])]
    if event_type == "earnings":
        identity.extend([str(event.get("fiscal_period") or ""), str(event.get("fiscal_year") or "")])
    elif event_type.startswith("dividend_"):
        identity.append(str(metadata.get("dividend_amount") or ""))
    elif event_type in {"stock_split", "reverse_split"}:
        identity.append(str(metadata.get("split_ratio_text") or ""))
    digest = hashlib.sha256("|".join(identity).encode()).hexdigest()[:32]
    return f"cal_{digest}"


def _timing(moment: datetime | None) -> str:
    if not moment:
        return "unknown"
    local = moment.astimezone(ZoneInfo("America/New_York"))
    if local.hour < 9:
        return "before_market"
    if local.hour >= 16:
        return "after_market"
    if local.hour >= 9:
        return "during_market"
    return "unknown"


def _base_event(
    event_type: str,
    symbol: str | None,
    event_date: date,
    title: str,
    *,
    company_name: str | None = None,
    moment: datetime | None = None,
    source: str = "yahoo",
    confirmed: bool = False,
    metadata: dict | None = None,
) -> dict:
    event = {
        "event_type": event_type,
        "symbol": symbol.upper() if symbol else None,
        "company_name": company_name,
        "title": title,
        "description": None,
        "event_date": event_date,
        "event_time": moment,
        "time_status": _timing(moment),
        "timezone": "America/New_York",
        "fiscal_period": None,
        "fiscal_year": None,
        "is_confirmed": confirmed,
        "is_estimated": not confirmed,
        "confidence": "high" if confirmed else "medium",
        "impact_level": "high" if event_type == "earnings" else (
            "medium" if event_type in {"dividend_ex_date", "stock_split", "reverse_split"} else "low"
        ),
        "primary_source": source,
        "sources": [source],
        "has_conflict": False,
        "conflict_fields": [],
        "metadata": metadata or {},
        "fetched_at": datetime.now(UTC),
        "source_record_id": "",
        "source_url": None,
        "raw_payload": {},
    }
    event["id"] = stable_event_id(event)
    return event


def normalize_yahoo_earnings(symbol: str, rows: Any, company_name: str | None = None) -> list[dict]:
    if rows is None or getattr(rows, "empty", True):
        return []
    output: list[dict] = []
    for index, row in rows.iterrows():
        moment = _datetime(index)
        if moment is None:
            continue
        confirmed_raw = row.get("Is Confirmed") if hasattr(row, "get") else None
        confirmed = bool(confirmed_raw) if confirmed_raw is not None else False
        metadata = {
            "eps_estimate": _number(row.get("EPS Estimate")),
            "eps_actual": _number(row.get("Reported EPS")),
            "revenue_estimate": _number(row.get("Revenue Estimate")),
            "revenue_actual": _number(row.get("Reported Revenue")),
            "earnings_time": _timing(moment),
        }
        event = _base_event("earnings", symbol, moment.date(), "季度财报", company_name=company_name,
                            moment=moment, confirmed=confirmed, metadata=metadata)
        event["raw_payload"] = {str(key): _json_scalar(value) for key, value in row.items()}
        event["source_record_id"] = moment.isoformat()
        output.append(event)
    return output


def normalize_yahoo_calendar(symbol: str, calendar: dict[str, Any] | None, company_name: str | None = None) -> list[dict]:
    calendar = calendar or {}
    output: list[dict] = []
    amount = _number(calendar.get("Dividend Rate"))
    common = {"dividend_amount": amount, "currency": calendar.get("Currency")}
    for source_field, event_type, title in (
        ("Ex-Dividend Date", "dividend_ex_date", "除息日"),
        ("Dividend Date", "dividend_payment_date", "股息支付日"),
    ):
        event_date = _date(calendar.get(source_field))
        if event_date:
            event = _base_event(event_type, symbol, event_date, title, company_name=company_name,
                                confirmed=False, metadata={**common, "related_dividend_key": f"{symbol}:{amount}"})
            event["source_record_id"] = f"{source_field}:{event_date}"
            event["raw_payload"] = {source_field: str(calendar.get(source_field)), "Dividend Rate": amount}
            output.append(event)
    return output


def normalize_yahoo_splits(symbol: str, actions: Any, company_name: str | None = None, *, today: date | None = None) -> list[dict]:
    if actions is None or getattr(actions, "empty", True) or "Stock Splits" not in actions:
        return []
    today = today or datetime.now(UTC).date()
    output = []
    for index, value in actions["Stock Splits"].items():
        ratio = _number(value)
        event_date = _date(index)
        if not ratio or not event_date or event_date < today or ratio == 1:
            continue
        reverse = ratio < 1
        split_from, split_to = ((round(1 / ratio, 6), 1.0) if reverse else (1.0, ratio))
        metadata = {
            "split_from": split_from,
            "split_to": split_to,
            "split_ratio_text": f"{split_to:g} 比 {split_from:g}",
            "effective_date": event_date.isoformat(),
            "is_reverse_split": reverse,
        }
        event = _base_event("reverse_split" if reverse else "stock_split", symbol, event_date,
                            "反向拆股" if reverse else "股票拆分", company_name=company_name,
                            confirmed=True, metadata=metadata)
        event["source_record_id"] = f"split:{event_date}:{ratio}"
        event["raw_payload"] = {"Stock Splits": ratio}
        output.append(event)
    return output


def normalize_legacy_earnings(row: EarningsEvent, company_name: str | None = None) -> dict:
    moment = row.event_time
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    confirmed = row.confidence == "confirmed"
    event = _base_event(
        "earnings",
        row.ticker,
        moment.date(),
        "季度财报",
        company_name=company_name,
        moment=moment,
        source=row.source or "yahoo",
        confirmed=confirmed,
        metadata={"earnings_time": row.timing or _timing(moment)},
    )
    event["source_record_id"] = f"legacy-earnings:{row.id}"
    event["fetched_at"] = row.synced_at or datetime.now(UTC)
    return event


def fetch_yahoo_events(
    symbol: str,
    company_name: str | None = None,
    *,
    include_earnings: bool = True,
) -> list[dict]:
    ticker = yf.Ticker(symbol)
    failed = 0
    attempted = 2
    earnings = None
    if include_earnings:
        attempted += 1
        try:
            earnings = ticker.get_earnings_dates(limit=8)
        except Exception:
            failed += 1
    else:
        earnings = None
    try:
        calendar = ticker.get_calendar()
        if not isinstance(calendar, dict):
            calendar = {}
    except Exception:
        calendar = {}
        failed += 1
    try:
        actions = ticker.get_actions()
    except Exception:
        actions = None
        failed += 1
    output = [
        *normalize_yahoo_earnings(symbol, earnings, company_name),
        *normalize_yahoo_calendar(symbol, calendar, company_name),
        *normalize_yahoo_splits(symbol, actions, company_name),
    ]
    if include_earnings and not any(event["event_type"] == "earnings" for event in output):
        dates = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
        if dates is None:
            dates = []
        elif not isinstance(dates, (list, tuple)):
            dates = [dates]
        for value in dates:
            moment = _datetime(value)
            if moment:
                output.append(_base_event(
                    "earnings", symbol, moment.date(), "季度财报",
                    company_name=company_name, moment=moment, confirmed=False,
                ))
    if failed == attempted:
        raise ConnectionError(f"{symbol} Yahoo 日历端点均不可用")
    return output


class CalendarProviderAdapter(Protocol):
    name: str
    capabilities: frozenset[str]

    def fetch(
        self,
        symbol: str,
        company_name: str | None = None,
        *,
        include_earnings: bool = True,
    ) -> list[dict]: ...


class YahooCalendarAdapter:
    name = "yahoo"
    capabilities = frozenset({"earnings", "dividend", "splits"})

    def fetch(
        self,
        symbol: str,
        company_name: str | None = None,
        *,
        include_earnings: bool = True,
    ) -> list[dict]:
        return fetch_yahoo_events(
            symbol,
            company_name,
            include_earnings=include_earnings,
        )


CALENDAR_PROVIDERS: tuple[CalendarProviderAdapter, ...] = (YahooCalendarAdapter(),)


def reconcile_events(events: Iterable[dict]) -> list[dict]:
    """Deterministically choose one record while retaining sources and conflicts."""
    grouped: dict[str, list[dict]] = {}
    for event in events:
        event = dict(event)
        event["id"] = event.get("id") or stable_event_id(event)
        grouped.setdefault(event["id"], []).append(event)
    output = []
    for event_id, candidates in grouped.items():
        ranked = sorted(candidates, key=lambda row: (
            0 if row.get("is_confirmed") else 1,
            PROVIDER_PRIORITY.get(row.get("primary_source"), 99),
            -(row.get("fetched_at") or datetime.min.replace(tzinfo=UTC)).timestamp(),
        ))
        primary = dict(ranked[0])
        primary["sources"] = list(dict.fromkeys(
            source for row in ranked for source in (row.get("sources") or [row.get("primary_source")]) if source
        ))
        conflict_fields = []
        for field in ("event_date", "event_time", "is_confirmed"):
            if len({str(row.get(field)) for row in ranked}) > 1:
                conflict_fields.append(field)
        primary["has_conflict"] = bool(conflict_fields)
        primary["conflict_fields"] = conflict_fields
        primary["id"] = event_id
        output.append(primary)
    return sorted(output, key=lambda row: (row["event_date"], row.get("symbol") or "", row["event_type"]))


def _security_map(db: Session, symbols: list[str]) -> dict[str, Security]:
    if not symbols:
        return {}
    rows = db.scalars(select(Security).where(
        (Security.yahoo_symbol.in_(symbols)) | (Security.display_symbol.in_(symbols))
    )).all()
    mapping: dict[str, Security] = {}
    for row in rows:
        if row.yahoo_symbol:
            mapping[row.yahoo_symbol.upper()] = row
        mapping[row.display_symbol.upper()] = row
    return mapping


def tracked_symbols(db: Session) -> list[str]:
    watch = set(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
    held = set(db.scalars(select(PortfolioPosition.symbol).where(PortfolioPosition.total_quantity > 0)).all())
    return sorted(str(value).upper() for value in watch | held)


def persist_events(db: Session, events: Iterable[dict]) -> int:
    candidates = [dict(event) for event in events]
    for event in candidates:
        event["id"] = event.get("id") or stable_event_id(event)
    rows = reconcile_events(candidates)
    source_candidates: dict[str, list[dict]] = {}
    for event in candidates:
        source_candidates.setdefault(event["id"], []).append(event)
    symbols = [row["symbol"] for row in rows if row.get("symbol")]
    securities = _security_map(db, symbols)
    now = datetime.now(UTC)
    for payload in rows:
        row = db.get(InvestmentCalendarEvent, payload["id"])
        if row is None:
            row = InvestmentCalendarEvent(id=payload["id"], event_type=payload["event_type"],
                                          event_date=payload["event_date"], title=payload["title"],
                                          primary_source=payload["primary_source"])
            db.add(row)
        security = securities.get(payload.get("symbol") or "")
        row.security_id = security.id if security else None
        for field in (
            "event_type", "symbol", "company_name", "title", "description", "event_date",
            "event_time", "time_status", "timezone", "fiscal_period", "fiscal_year",
            "is_confirmed", "is_estimated", "confidence", "impact_level",
            "primary_source", "sources", "has_conflict", "conflict_fields",
        ):
            setattr(row, field, payload.get(field))
        row.metadata_payload = payload.get("metadata") or {}
        row.status = "active"
        row.last_seen_at = now
        row.fetched_at = payload.get("fetched_at") or now
        db.flush()
        for source_payload in source_candidates.get(row.id, [payload]):
            provider = source_payload["primary_source"]
            source_record_id = str(source_payload.get("source_record_id") or "")
            existing_source = db.scalar(select(InvestmentCalendarEventSource).where(
                InvestmentCalendarEventSource.event_id == row.id,
                InvestmentCalendarEventSource.provider == provider,
                InvestmentCalendarEventSource.source_record_id == source_record_id,
            ))
            if existing_source is None:
                db.add(InvestmentCalendarEventSource(
                    event_id=row.id,
                    provider=provider,
                    source_record_id=source_record_id,
                    source_url=source_payload.get("source_url"),
                    raw_payload=source_payload.get("raw_payload") or {},
                    fetched_at=source_payload.get("fetched_at") or now,
                ))
    db.flush()
    return len(rows)


def sync_calendar(db: Session) -> dict:
    symbols = tracked_symbols(db)
    profiles = {row.ticker.upper(): row.company_name for row in db.scalars(
        select(StockProfile).where(StockProfile.ticker.in_(symbols))
    ).all()}
    now = datetime.now(UTC)
    legacy_rows = db.scalars(select(EarningsEvent).where(
        EarningsEvent.ticker.in_(symbols),
        EarningsEvent.event_time.between(
            now - timedelta(days=1),
            now + timedelta(days=120),
        ),
    )).all()
    legacy_by_symbol: dict[str, list[EarningsEvent]] = {}
    for row in legacy_rows:
        legacy_by_symbol.setdefault(row.ticker.upper(), []).append(row)
    collected = [
        normalize_legacy_earnings(row, profiles.get(row.ticker.upper()))
        for row in legacy_rows
    ]
    failures = []
    for symbol in symbols:
        for provider in CALENDAR_PROVIDERS:
            try:
                collected.extend(provider.fetch(
                    symbol,
                    profiles.get(symbol),
                    include_earnings=not bool(legacy_by_symbol.get(symbol)),
                ))
            except Exception as exc:
                failures.append({
                    "symbol": symbol,
                    "provider": provider.name,
                    "error": type(exc).__name__,
                })
    count = persist_events(db, collected)
    db.commit()
    return {
        "symbols": len(symbols),
        "events": count,
        "reused_earnings": len(legacy_rows),
        "earnings_symbols_reused": len(legacy_by_symbol),
        "failures": failures,
    }


def relevance_context(db: Session, user_id: int) -> tuple[set[str], set[str], dict[str, float]]:
    watchlist = {str(value).upper() for value in db.scalars(
        select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))
    ).all()}
    portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id).limit(1))
    if not portfolio:
        return set(), watchlist, {}
    positions = db.scalars(select(PortfolioPosition).where(
        PortfolioPosition.portfolio_id == portfolio.id, PortfolioPosition.total_quantity > 0
    )).all()
    held = {row.symbol.upper() for row in positions}
    total = sum(max(row.total_cost or 0, 0) for row in positions)
    weights = {row.symbol.upper(): (max(row.total_cost or 0, 0) / total if total else 0) for row in positions}
    return held, watchlist, weights


def serialize_event(row: InvestmentCalendarEvent, held: set[str], watchlist: set[str], weights: dict[str, float]) -> dict:
    symbol = (row.symbol or "").upper()
    portfolio_relevance = symbol in held
    watchlist_relevance = symbol in watchlist
    level = row.impact_level
    order = ["low", "medium", "high", "critical"]
    if portfolio_relevance:
        level = order[min(order.index(level) + (2 if weights.get(symbol, 0) >= .2 else 1), 3)]
    fetched_at = row.fetched_at
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    stale = fetched_at is None or datetime.now(UTC) - fetched_at > timedelta(hours=36)
    return {
        "id": row.id,
        "event_type": row.event_type,
        "symbol": row.symbol,
        "company_name": row.company_name,
        "title": row.title,
        "description": row.description,
        "event_date": row.event_date,
        "event_time": row.event_time,
        "time_status": row.time_status,
        "timezone": row.timezone,
        "fiscal_period": row.fiscal_period,
        "fiscal_year": row.fiscal_year,
        "is_confirmed": row.is_confirmed,
        "is_estimated": row.is_estimated,
        "confidence": row.confidence,
        "impact_level": level,
        "primary_source": row.primary_source,
        "sources": row.sources or [],
        "has_conflict": row.has_conflict,
        "conflict_fields": row.conflict_fields or [],
        "portfolio_relevance": portfolio_relevance,
        "watchlist_relevance": watchlist_relevance,
        "position_weight": weights.get(symbol),
        "metadata": row.metadata_payload or {},
        "fetched_at": row.fetched_at,
        "stale": stale,
        "warning": "当前展示最近一次有效缓存。" if stale else None,
    }


def calendar_capabilities() -> dict[str, bool]:
    available = set().union(*(provider.capabilities for provider in CALENDAR_PROVIDERS))
    return {
        "earnings_calendar": "earnings" in available,
        "dividend_calendar": "dividend" in available,
        "split_calendar": "splits" in available,
        "ipo_calendar": False,
        "company_events": False,
        "macro_calendar": False,
    }
