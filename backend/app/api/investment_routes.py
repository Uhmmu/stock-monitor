"""Ownership and investment-calendar APIs."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    InvestmentCalendarEvent,
    InvestmentCalendarSyncRun,
    Sec13FHolding,
    SecInsiderTrade,
    Security,
    TemporarySnapshot,
    User,
    WatchlistItem,
)
from app.services.investment_calendar import (
    EVENT_TYPES,
    calendar_capabilities,
    calendar_provider_capabilities,
    relevance_context,
    serialize_event,
)
from app.services.ownership import (
    classify_sec_transaction_code,
    get_share_statistics,
    ownership_capabilities,
    serialize_share_statistics,
)

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


def _allowed_symbol(db: Session, raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    allowed = db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == symbol))
    temporary = db.scalar(select(TemporarySnapshot.id).where(
        TemporarySnapshot.ticker == symbol,
        TemporarySnapshot.section.in_(("fundamentals", "financials")),
        TemporarySnapshot.expires_at > datetime.now(UTC),
    ))
    security = db.scalar(select(Security.id).where(or_(
        Security.display_symbol == symbol, Security.yahoo_symbol == symbol,
    )))
    if not (allowed or temporary or security):
        raise HTTPException(404, "请先从基本面栏目选择该证券")
    return symbol


def _is_us(db: Session, symbol: str) -> bool:
    security = db.scalar(select(Security).where(or_(
        Security.display_symbol == symbol, Security.yahoo_symbol == symbol,
    )).limit(1))
    if security and security.country_code:
        return security.country_code == "US"
    return "." not in symbol


@router.get("/equity/{symbol}/ownership/capabilities")
def ownership_capability_report(symbol: str, db: Session = Depends(get_db)):
    value = _allowed_symbol(db, symbol)
    return {
        "symbol": value,
        "market_supported": _is_us(db, value),
        "capabilities": ownership_capabilities(is_us_market=_is_us(db, value)),
    }


@router.get("/equity/{symbol}/ownership/summary")
def ownership_summary(symbol: str, db: Session = Depends(get_db)):
    value = _allowed_symbol(db, symbol)
    row, stale, warning = get_share_statistics(db, value)
    if row is None:
        return {
            "symbol": value,
            "data": None,
            "stale": False,
            "warning": warning or "当前数据源暂不支持该市场",
            "capabilities": ownership_capabilities(is_us_market=_is_us(db, value)),
        }
    return {
        "symbol": value,
        "data": serialize_share_statistics(row, stale=stale, warning=warning),
        "stale": stale,
        "warning": warning,
        "capabilities": ownership_capabilities(is_us_market=_is_us(db, value)),
    }


def _page(offset: int, limit: int, total: int, items: list[dict]) -> dict:
    next_cursor = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "next_cursor": next_cursor}


@router.get("/equity/{symbol}/ownership/holders")
def ownership_holders(symbol: str, offset: int = 0, limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    value = _allowed_symbol(db, symbol)
    return {
        **_page(offset, limit, 0, []),
        "symbol": value,
        "available": False,
        "message": "当前已配置数据源未提供可靠的主要持有人明细；不会用 13F 推断实时持股。",
    }


@router.get("/equity/{symbol}/ownership/insider-transactions")
def ownership_insider_transactions(
    symbol: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    value = _allowed_symbol(db, symbol)
    if not _is_us(db, value):
        return {**_page(offset, limit, 0, []), "symbol": value, "available": False,
                "message": "当前数据源暂不支持该市场"}
    base = select(SecInsiderTrade).where(SecInsiderTrade.ticker == value)
    total = db.scalar(select(func.count()).select_from(SecInsiderTrade).where(SecInsiderTrade.ticker == value)) or 0
    rows = db.scalars(base.order_by(SecInsiderTrade.transaction_date.desc(), SecInsiderTrade.id.desc())
                      .offset(offset).limit(limit)).all()
    items = [{
        "id": row.id,
        "symbol": value,
        "insider_name": row.insider_name,
        "insider_title": row.insider_title,
        "transaction_type": classify_sec_transaction_code(row.transaction_code),
        "transaction_code": row.transaction_code,
        "transaction_date": row.transaction_date,
        "filing_date": None,
        "shares": row.shares,
        "price": row.price,
        "transaction_value": row.value,
        "shares_owned_after": row.shares_owned_after,
        "security_title": None,
        "is_derivative": None,
        "source": "sec",
        "source_url": row.filing_url,
        "fetched_at": row.synced_at,
    } for row in rows]
    return {**_page(offset, limit, total, items), "symbol": value, "available": True,
            "delayed_notice": "Form 4 为监管申报数据；交易日期与申报日期可能不同。"}


@router.get("/equity/{symbol}/ownership/13f")
def ownership_13f(
    symbol: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    value = _allowed_symbol(db, symbol)
    if not _is_us(db, value):
        return {**_page(offset, limit, 0, []), "symbol": value, "available": False,
                "message": "当前数据源暂不支持该市场"}
    total = db.scalar(select(func.count()).select_from(Sec13FHolding).where(Sec13FHolding.ticker == value)) or 0
    rows = db.scalars(select(Sec13FHolding).where(Sec13FHolding.ticker == value)
                      .order_by(Sec13FHolding.report_period.desc(), Sec13FHolding.value_usd.desc().nullslast())
                      .offset(offset).limit(limit)).all()
    items = [{
        "id": row.id,
        "symbol": value,
        "report_period": row.report_period,
        "filing_date": row.filing_date,
        "filer": row.manager_name,
        "issuer": None,
        "security_class": None,
        "cusip": row.cusip,
        "shares": row.shares,
        "reported_value": row.value_usd,
        "put_call": row.put_call,
        "discretion": None,
        "source": "sec",
        "fetched_at": row.synced_at,
    } for row in rows]
    return {**_page(offset, limit, total, items), "symbol": value, "available": True,
            "delayed_notice": "13F 通常在季度结束后最多约 45 天申报，不能视为实时机构持仓。"}


def _calendar_query(
    db: Session,
    *,
    start_date: date,
    end_date: date,
    symbols: list[str] | None,
    event_types: list[str] | None,
):
    query = select(InvestmentCalendarEvent).where(
        InvestmentCalendarEvent.event_date.between(start_date, end_date),
        InvestmentCalendarEvent.status == "active",
    )
    if symbols:
        query = query.where(InvestmentCalendarEvent.symbol.in_([value.upper() for value in symbols]))
    if event_types:
        invalid = set(event_types) - EVENT_TYPES
        if invalid:
            raise HTTPException(422, f"不支持的事件类型：{', '.join(sorted(invalid))}")
        query = query.where(InvestmentCalendarEvent.event_type.in_(event_types))
    return query


@router.get("/calendar/capabilities")
def calendar_capability_report():
    return {
        "capabilities": calendar_capabilities(),
        "providers": calendar_provider_capabilities(),
        "analyzer_version": "v0.4",
        "parameter_set_version": "v0.4",
    }


@router.get("/calendar/status")
def calendar_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = datetime.now(UTC).date()
    held, watchlist, _ = relevance_context(db, user.id)
    relevant = held | watchlist
    tracked_count = len(relevant)
    future_earnings_symbols = 0
    next_30_day_symbols = 0
    if relevant:
        future_earnings_symbols = db.scalar(select(func.count(func.distinct(
            InvestmentCalendarEvent.symbol
        ))).where(
            InvestmentCalendarEvent.status == "active",
            InvestmentCalendarEvent.event_type == "earnings",
            InvestmentCalendarEvent.symbol.in_(relevant),
            InvestmentCalendarEvent.event_date.between(today, today + timedelta(days=120)),
        )) or 0
        next_30_day_symbols = db.scalar(select(func.count(func.distinct(
            InvestmentCalendarEvent.symbol
        ))).where(
            InvestmentCalendarEvent.status == "active",
            InvestmentCalendarEvent.symbol.in_(relevant),
            InvestmentCalendarEvent.event_date.between(today, today + timedelta(days=30)),
        )) or 0
    latest = db.scalar(select(InvestmentCalendarSyncRun).order_by(
        InvestmentCalendarSyncRun.started_at.desc(),
        InvestmentCalendarSyncRun.id.desc(),
    ).limit(1))
    last_successful = db.scalar(select(InvestmentCalendarSyncRun).where(
        InvestmentCalendarSyncRun.status.in_(("succeeded", "partial")),
        InvestmentCalendarSyncRun.successful_symbols > 0,
    ).order_by(
        InvestmentCalendarSyncRun.completed_at.desc(),
        InvestmentCalendarSyncRun.id.desc(),
    ).limit(1))
    return {
        "scope": "tracked",
        "tracked_symbols": tracked_count,
        "future_earnings_symbols": future_earnings_symbols,
        "earnings_coverage_percent": round(
            future_earnings_symbols / tracked_count * 100, 1
        ) if tracked_count else 0,
        "next_30_day_symbols": next_30_day_symbols,
        "providers": calendar_provider_capabilities(),
        "latest_run": {
            "id": latest.id,
            "status": latest.status,
            "started_at": latest.started_at,
            "completed_at": latest.completed_at,
            "successful_symbols": latest.successful_symbols,
            "tracked_symbols": latest.tracked_symbols,
            "events_seen": latest.events_seen,
            "provider_counts": latest.provider_counts,
            "failures": latest.failures,
            "error_type": latest.error_type,
        } if latest else None,
        "last_successful_sync_at": last_successful.completed_at if last_successful else None,
        "generated_at": datetime.now(UTC),
    }


@router.get("/calendar/events")
def calendar_events(
    start_date: date = Query(default_factory=lambda: datetime.now(UTC).date()),
    end_date: date = Query(default_factory=lambda: datetime.now(UTC).date() + timedelta(days=30)),
    symbols: list[str] | None = Query(None),
    event_types: list[str] | None = Query(None),
    portfolio_only: bool = False,
    watchlist_only: bool = False,
    relevant_only: bool = False,
    provider: str | None = None,
    limit: int = Query(100, ge=1, le=250),
    cursor: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if end_date < start_date or (end_date - start_date).days > 366:
        raise HTTPException(422, "日期范围无效或超过 366 天")
    if portfolio_only and watchlist_only:
        raise HTTPException(422, "持仓与自选股范围不能同时设为仅限")
    supported_providers = set(calendar_provider_capabilities()) | {"yfinance"}
    if provider and provider not in supported_providers:
        raise HTTPException(422, "不支持的数据源筛选")
    held, watchlist, weights = relevance_context(db, user.id)
    query = _calendar_query(db, start_date=start_date, end_date=end_date, symbols=symbols, event_types=event_types)
    if provider:
        query = query.where(InvestmentCalendarEvent.primary_source == provider)
    if portfolio_only:
        query = query.where(InvestmentCalendarEvent.symbol.in_(held or {"__none__"}))
    if watchlist_only:
        query = query.where(InvestmentCalendarEvent.symbol.in_(watchlist or {"__none__"}))
    if relevant_only:
        query = query.where(InvestmentCalendarEvent.symbol.in_((held | watchlist) or {"__none__"}))
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(InvestmentCalendarEvent.event_date, InvestmentCalendarEvent.event_time,
                                     InvestmentCalendarEvent.symbol).offset(cursor).limit(limit)).all()
    return {
        **_page(cursor, limit, total, [serialize_event(row, held, watchlist, weights) for row in rows]),
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.now(UTC),
        "capabilities": calendar_capabilities(),
    }


@router.get("/calendar/summary")
def calendar_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = datetime.now(UTC).date()
    held, watchlist, weights = relevance_context(db, user.id)
    if not (held or watchlist):
        return {
            "today": 0,
            "next_7_days": 0,
            "next_30_days": 0,
            "high_impact": 0,
            "portfolio_events": 0,
            "generated_at": datetime.now(UTC),
        }
    rows = db.scalars(_calendar_query(
        db, start_date=today, end_date=today + timedelta(days=30),
        symbols=list(held | watchlist), event_types=None,
    )).all()
    items = [serialize_event(row, held, watchlist, weights) for row in rows]
    return {
        "today": sum(item["event_date"] == today for item in items),
        "next_7_days": sum(item["event_date"] <= today + timedelta(days=7) for item in items),
        "next_30_days": len(items),
        "high_impact": sum(item["impact_level"] in {"high", "critical"} for item in items),
        "portfolio_events": sum(item["portfolio_relevance"] for item in items),
        "generated_at": datetime.now(UTC),
    }


@router.get("/calendar/symbol/{symbol}")
def calendar_symbol(
    symbol: str,
    start_date: date = Query(default_factory=lambda: datetime.now(UTC).date()),
    end_date: date = Query(default_factory=lambda: datetime.now(UTC).date() + timedelta(days=90)),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    value = symbol.strip().upper()
    held, watchlist, weights = relevance_context(db, user.id)
    rows = db.scalars(_calendar_query(
        db, start_date=start_date, end_date=end_date, symbols=[value], event_types=None,
    ).order_by(InvestmentCalendarEvent.event_date)).all()
    return {"symbol": value, "items": [serialize_event(row, held, watchlist, weights) for row in rows]}
