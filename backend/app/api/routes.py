import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date as date_type, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    AppSetting,
    CongressTrade,
    DailyNewsArchive,
    FigurePosition,
    FinancialStatementSnapshot,
    CompanyProfile,
    FmpSyncState,
    HistoricalPrice,
    Investigation,
    NewsItem,
    PriceAlert,
    PriceSnapshot,
    PeerExclusion,
    PeerRelation,
    QuarterlyFinancial,
    Report,
    Sec13FHolding,
    SecEvent,
    SecFiling,
    SecFinancialPeriod,
    SecInsiderTrade,
    Security,
    TrackedFigure,
    TradeLog,
    User,
    ValuationSnapshot,
    StockGroup,
    StockProfile,
    TechnicalAnalysis,
    TemporarySnapshot,
    WatchlistItem,
    WeeklyNewsArchive,
)
from app.schemas import (
    GrahamOverride,
    OrderUpdate,
    PeerCreate,
    SecurityResolveIn,
    SettingsOut,
    SettingsUpdate,
    StockGroupCreate,
    StockGroupUpdate,
    TradeLogCreate,
    TradeLogOut,
    TradeLogUpdate,
    WatchlistCreate,
    WatchlistOut,
    WatchlistUpdate,
)
from app.auth import get_admin_user, get_current_user
from app.services.fmp_market import budget_status
from app.services.finnhub_mcp import fetch_basic_metrics, fetch_recommendations
from app.services.market_data import fetch_index_quotes, fetch_yf_info_metrics, fetch_yf_recommendations
from app.services.stock_management import normalize_ticker, stock_management_payload, upsert_profile
from app.services.securities import SecuritySearchUnavailable, provider_symbol, resolve_security, search_securities
from app.services.llm import summarize_trade_log
from app.services.market_calendar import market_status
from app.services.volume_stats import volume_context

public_router = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


SNAPSHOT_SECTIONS = {"news", "fundamentals", "financials", "valuation", "sec"}


def _require_watched_ticker(db: Session, ticker: str, snapshot_section: str | None = None) -> str:
    value = (ticker or "").strip().upper()
    watched = db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == value))
    snapshot = snapshot_section and db.scalar(select(TemporarySnapshot.id).where(
        TemporarySnapshot.section.in_((snapshot_section or "").split("|")), TemporarySnapshot.ticker == value,
        TemporarySnapshot.expires_at > datetime.now(UTC),
    ))
    if not watched and not snapshot:
        raise HTTPException(404, "该股票不在自选列表中")
    return value


def _snapshot_out(row: TemporarySnapshot) -> dict:
    return {"ticker": row.ticker, "security_id": row.security_id, "section": row.section, "expires_at": row.expires_at}


def _security_out(row: Security) -> dict:
    return {
        "provider_key": f"security:{row.id}", "security_id": row.id,
        "display_symbol": row.display_symbol, "display_name": row.display_name or row.display_symbol,
        "local_symbol": row.local_symbol, "exchange": row.exchange_name,
        "exchange_code": row.exchange_code, "market": row.market, "country_code": row.country_code,
        "currency": row.currency, "instrument_type": row.instrument_type,
        "yahoo_symbol": row.yahoo_symbol, "finnhub_symbol": row.finnhub_symbol,
        "source": "local", "is_local": True,
        "yahoo_status": row.yahoo_status, "finnhub_status": row.finnhub_status,
        "mapping_method": row.mapping_method, "mapping_confidence": row.mapping_confidence,
    }


@router.get("/securities/search")
def security_search(q: str = Query(default="", max_length=80), limit: int = Query(default=12, ge=1, le=20), db: Session = Depends(get_db)):
    try:
        results = search_securities(db, q, limit)
    except SecuritySearchUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"query": " ".join(q.strip().split()), "results": results}


@router.post("/securities/resolve")
def security_resolve(payload: SecurityResolveIn, db: Session = Depends(get_db)):
    try:
        row = resolve_security(db, **payload.model_dump())
        db.commit()
        db.refresh(row)
        return _security_out(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


def _purge_temporary_ticker(db: Session, ticker: str) -> None:
    """Drop cached source data only once no temporary section still references it."""
    if db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == ticker)) or db.scalar(select(TemporarySnapshot.id).where(TemporarySnapshot.ticker == ticker)):
        return
    for model in (NewsItem, DailyNewsArchive, WeeklyNewsArchive, QuarterlyFinancial,
                  FinancialStatementSnapshot, ValuationSnapshot, SecFiling, SecEvent,
                  SecFinancialPeriod, SecInsiderTrade, PriceSnapshot):
        db.execute(delete(model).where(model.ticker == ticker))


@router.get("/snapshots/{section}")
def list_snapshots(section: str, db: Session = Depends(get_db)):
    if section not in SNAPSHOT_SECTIONS:
        raise HTTPException(404, "未知快照栏目")
    now = datetime.now(UTC)
    expired = list(db.scalars(select(TemporarySnapshot).where(TemporarySnapshot.expires_at <= now)).all())
    for row in expired:
        db.delete(row)
    db.flush()
    for row in expired:
        _purge_temporary_ticker(db, row.ticker)
    db.commit()
    return [_snapshot_out(row) for row in db.scalars(select(TemporarySnapshot).where(
        TemporarySnapshot.section == section).order_by(TemporarySnapshot.created_at.desc())).all()]


@router.post("/snapshots/{section}")
def create_snapshot(section: str, ticker: str | None = Query(default=None), security_id: int | None = Query(default=None),
                    source: str | None = Query(default=None), yahoo_symbol: str | None = Query(default=None),
                    finnhub_symbol: str | None = Query(default=None), db: Session = Depends(get_db)):
    if section not in SNAPSHOT_SECTIONS:
        raise HTTPException(404, "未知快照栏目")
    try:
        security = resolve_security(db, security_id=security_id, source=source,
                                    yahoo_symbol=yahoo_symbol or ticker, finnhub_symbol=finnhub_symbol)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    value = security.yahoo_symbol or security.finnhub_symbol
    if not value:
        raise HTTPException(422, "该证券暂无可用行情数据源")
    now = datetime.now(UTC)
    row = db.scalar(select(TemporarySnapshot).where(TemporarySnapshot.section == section, TemporarySnapshot.ticker == value))
    if not row:
        row = TemporarySnapshot(section=section, ticker=value, security_id=security.id, expires_at=now + timedelta(days=1))
        db.add(row)
    else:
        row.security_id = security.id
        row.expires_at = now + timedelta(days=1)
    db.commit()
    if section == "news":
        from app.tasks.celery_app import poll_news
        poll_news.delay(value)
    elif section in {"fundamentals", "financials"}:
        from app.tasks.celery_app import sync_ticker_financials
        sync_ticker_financials.delay(value)
    elif section == "valuation":
        from app.tasks.celery_app import sync_peer_valuation_data
        sync_peer_valuation_data.delay(value)
    elif section == "sec":
        from app.tasks.celery_app import sync_ticker_sec_all
        sync_ticker_sec_all.delay(value)
    return _snapshot_out(row)


@router.delete("/snapshots/{section}/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(section: str, ticker: str, db: Session = Depends(get_db)):
    if section not in SNAPSHOT_SECTIONS:
        raise HTTPException(404, "未知快照栏目")
    value = (ticker or "").strip().upper()
    db.execute(delete(TemporarySnapshot).where(TemporarySnapshot.section == section, TemporarySnapshot.ticker == value))
    db.flush()
    _purge_temporary_ticker(db, value)
    db.commit()


@public_router.get("/health")
def health():
    return {"status": "ok"}


@public_router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready"}


@router.get("/watchlist", response_model=list[WatchlistOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.scalars(select(WatchlistItem).order_by(WatchlistItem.ticker)).all()


@router.post("/watchlist", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
def add_watchlist(payload: WatchlistCreate, db: Session = Depends(get_db)):
    try:
        security = resolve_security(
            db, security_id=payload.security_id, source=payload.source,
            yahoo_symbol=payload.yahoo_symbol or payload.ticker, finnhub_symbol=payload.finnhub_symbol,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    ticker = security.yahoo_symbol or security.finnhub_symbol
    if not ticker:
        raise HTTPException(422, "该证券暂无可用行情数据源")
    item = WatchlistItem(ticker=ticker, security_id=security.id, threshold_20m=payload.threshold_20m,
                         threshold_1h=payload.threshold_1h, threshold_day=payload.threshold_day)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该股票已在自选列表中")
    db.refresh(item)
    if item.enabled:
        from app.tasks.celery_app import sync_ticker_full

        sync_ticker_full.delay(item.ticker)
    return item


@router.patch("/watchlist/{item_id}", response_model=WatchlistOut)
def update_watchlist(item_id: int, payload: WatchlistUpdate, db: Session = Depends(get_db)):
    item = db.get(WatchlistItem, item_id)
    if not item:
        raise HTTPException(404, "未找到股票")
    if "user_group_id" in payload.model_fields_set and payload.user_group_id is not None and not db.get(StockGroup, payload.user_group_id):
        raise HTTPException(404, "显示分区不存在")
    for key in payload.model_fields_set:
        setattr(item, key, getattr(payload, key))
    db.commit()
    db.refresh(item)
    return item


@router.delete("/watchlist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist(item_id: int, db: Session = Depends(get_db)):
    if not db.get(WatchlistItem, item_id):
        raise HTTPException(404, "未找到股票")
    db.execute(delete(WatchlistItem).where(WatchlistItem.id == item_id))
    db.commit()
    return Response(status_code=204)


def _profile_out(db: Session, symbol: str, row: CompanyProfile | None) -> dict:
    local = db.get(StockProfile, symbol)
    if not row:
        return {"symbol": symbol, "status": "pending", "company_name": local.company_name if local else None,
                "local_classification": {"sector": local.official_sector if local else None, "industry": local.official_industry if local else None}}
    return {"symbol": symbol, "status": "ready", "company_name": row.company_name, "logo_url": row.logo_url,
            "website": row.website, "ceo": row.ceo, "sector": row.sector, "industry": row.industry,
            "country": row.country, "exchange": row.exchange, "exchange_full_name": row.exchange_full_name,
            "currency": row.currency, "ipo_date": row.ipo_date, "employee_count": row.employee_count,
            "description_en": row.description_en, "description_zh": row.description_zh,
            "translation_status": row.translation_status, "profile_source": row.profile_source,
            "profile_fetched_at": row.profile_fetched_at,
            "local_classification": {"sector": local.official_sector if local else None, "industry": local.official_industry if local else None}}


@router.get("/company-profile/{symbol}")
def company_profile(symbol: str, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, symbol)
    return _profile_out(db, value, db.get(CompanyProfile, value))


def _technical_out(db: Session, symbol: str, row: TechnicalAnalysis | None) -> dict:
    profile = db.get(CompanyProfile, symbol)
    if not row:
        return {"symbol": symbol, "status": "pending", "company_name": profile.company_name if profile else None,
                "logo_url": profile.logo_url if profile else None, "chart_url": None}
    age = (datetime.now(UTC).date() - row.data_through).days if row.data_through else None
    return {"symbol": symbol, "status": row.status, "company_name": profile.company_name if profile else None,
            "logo_url": profile.logo_url if profile else None, "analysis": row.analysis, "data_through": row.data_through,
            "generated_at": row.generated_at, "stale": age is None or age > 7,
            "chart_url": f"/api/technical-analysis/{symbol}/chart?v={row.input_hash[:12]}" if row.image_path else None}


@router.get("/technical-analysis")
def technical_analysis_list(db: Session = Depends(get_db)):
    symbols = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True)).order_by(WatchlistItem.display_order, WatchlistItem.ticker)).all())
    return [_technical_out(db, symbol, db.get(TechnicalAnalysis, symbol)) for symbol in symbols]


@router.get("/technical-analysis/{symbol}")
def technical_analysis_detail(symbol: str, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, symbol)
    result = _technical_out(db, value, db.get(TechnicalAnalysis, value))
    result["profile"] = _profile_out(db, value, db.get(CompanyProfile, value))
    oldest = db.scalar(select(HistoricalPrice.date).where(HistoricalPrice.symbol == value).order_by(HistoricalPrice.date).limit(1))
    newest = db.scalar(select(HistoricalPrice.date).where(HistoricalPrice.symbol == value).order_by(HistoricalPrice.date.desc()).limit(1))
    analysis = result.get("analysis") or {}
    result["data_status"] = {"source": analysis.get("source"), "oldest_stored_date": oldest, "latest_stored_date": newest,
                             "last_successful_sync": result.get("generated_at"),
                             "profile_status": result["profile"]["status"], "analysis_status": result["status"]}
    return result


@router.get("/technical-analysis/{symbol}/chart")
def technical_analysis_chart(symbol: str, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, symbol)
    row = db.get(TechnicalAnalysis, value)
    if not row or not row.image_path:
        raise HTTPException(404, "技术图表尚未生成")
    from pathlib import Path
    path = Path(row.image_path)
    if not path.is_file():
        raise HTTPException(404, "技术图表缓存暂不可用")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/admin/fmp/status", dependencies=[Depends(get_admin_user)])
def fmp_admin_status(db: Session = Depends(get_db)):
    budget = budget_status(db)
    states = list(db.scalars(select(FmpSyncState).where(FmpSyncState.symbol != "*")).all())
    last = max(states, key=lambda row: row.last_attempt_at or datetime.min.replace(tzinfo=UTC), default=None)
    counts = {key: sum(row.status == key for row in states) for key in ("pending", "pending_quota", "failed", "completed")}
    next_run = datetime.now(UTC).replace(hour=23, minute=30, second=0, microsecond=0)
    if next_run <= datetime.now(UTC):
        next_run += timedelta(days=1)
    while next_run.weekday() >= 5:
        next_run += timedelta(days=1)
    failed_translations = db.scalar(select(func.count()).select_from(CompanyProfile).where(CompanyProfile.translation_status == "failed")) or 0
    return {"quota_day": budget.quota_day, "requests_used": budget.used, "requests_remaining": budget.remaining,
            "usable_limit": budget.usable_limit, "last_processed_ticker": last.symbol if last else None,
            "pending_profile_count": sum(row.sync_type == "profile" and row.status != "completed" for row in states),
            "pending_history_count": sum(row.sync_type == "price" and row.status != "completed" for row in states),
            "pending_analysis_count": db.scalar(select(func.count()).select_from(WatchlistItem).where(~WatchlistItem.ticker.in_(select(TechnicalAnalysis.symbol).where(TechnicalAnalysis.status == "ready")))) or 0,
            "failed_item_count": counts["failed"] + failed_translations, "status_counts": counts,
            "next_scheduled_run": next_run, "quota_timezone": "UTC"}


@router.post("/admin/fmp/sync", dependencies=[Depends(get_admin_user)], status_code=status.HTTP_202_ACCEPTED)
def fmp_admin_sync():
    from app.tasks.celery_app import sync_fmp_history, sync_fmp_profiles
    sync_fmp_profiles.delay()
    sync_fmp_history.delay()
    return {"status": "queued"}


@router.post("/admin/fmp/sync/{symbol}", dependencies=[Depends(get_admin_user)], status_code=status.HTTP_202_ACCEPTED)
def fmp_admin_sync_symbol(symbol: str, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, symbol)
    from app.tasks.celery_app import sync_fmp_symbol
    sync_fmp_symbol.delay(value)
    return {"status": "queued", "symbol": value}


@router.post("/admin/technical-analysis/regenerate/{symbol}", dependencies=[Depends(get_admin_user)], status_code=status.HTTP_202_ACCEPTED)
def regenerate_technical_analysis(symbol: str, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, symbol)
    from app.tasks.celery_app import sync_technical_analysis
    # 先从 yfinance 拉取日线历史，再重算——保证从未同步过的标的也能生成。
    sync_technical_analysis.delay(value)
    return {"status": "queued", "symbol": value}


@router.get("/stock-management")
def stock_management(db: Session = Depends(get_db)):
    return stock_management_payload(db)


@router.post("/stock-groups", status_code=status.HTTP_201_CREATED)
def create_stock_group(payload: StockGroupCreate, db: Session = Depends(get_db)):
    order = db.scalar(select(func.coalesce(func.max(StockGroup.display_order), -1))) or 0
    row = StockGroup(name=payload.name, display_order=order + 1)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "分区名称已存在")
    db.refresh(row)
    return {"id": row.id, "name": row.name, "display_order": row.display_order}


@router.patch("/stock-groups/{group_id}")
def update_stock_group(group_id: int, payload: StockGroupUpdate, db: Session = Depends(get_db)):
    row = db.get(StockGroup, group_id)
    if not row:
        raise HTTPException(404, "分区不存在")
    for key in payload.model_fields_set:
        value = getattr(payload, key)
        if key == "name" and value is not None:
            value = value.strip()
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "分区名称已存在")
    return {"id": row.id, "name": row.name, "display_order": row.display_order}


@router.delete("/stock-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stock_group(group_id: int, db: Session = Depends(get_db)):
    row = db.get(StockGroup, group_id)
    if not row:
        raise HTTPException(404, "分区不存在")
    if db.scalar(select(WatchlistItem.id).where(WatchlistItem.user_group_id == group_id).limit(1)):
        raise HTTPException(409, "分区仍包含股票，请先移出")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


def _latest_official_peers(db: Session, base: str) -> list[str]:
    snapshot = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == base).order_by(ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc()).limit(1))
    if not snapshot:
        return []
    peers = snapshot.payload.get("peers", {})
    return peers.get("official_symbols") or peers.get("symbols") or []


@router.get("/peers/{base_ticker}")
def list_peers(base_ticker: str, db: Session = Depends(get_db)):
    base = _require_watched_ticker(db, base_ticker)
    official = _latest_official_peers(db, base)
    manual = db.scalars(select(PeerRelation).where(PeerRelation.base_ticker == base, PeerRelation.enabled.is_(True)).order_by(PeerRelation.display_order, PeerRelation.id)).all()
    excluded = set(db.scalars(select(PeerExclusion.peer_ticker).where(PeerExclusion.base_ticker == base)).all())
    watched = set(db.scalars(select(WatchlistItem.ticker)).all())
    items = []
    for order, ticker in enumerate(official):
        items.append({"ticker": ticker, "source": "official", "excluded": ticker in excluded, "display_order": order, "is_watchlisted": ticker in watched})
    official_set = set(official)
    items.extend({"ticker": row.peer_ticker, "source": "manual", "excluded": False, "display_order": row.display_order, "is_watchlisted": row.peer_ticker in watched} for row in manual if row.peer_ticker not in official_set)
    return {"base_ticker": base, "items": items}


@router.post("/peers/{base_ticker}", status_code=status.HTTP_201_CREATED)
def add_manual_peer(base_ticker: str, payload: PeerCreate, db: Session = Depends(get_db)):
    base = _require_watched_ticker(db, base_ticker)
    try:
        security = resolve_security(db, security_id=payload.security_id, source=payload.source,
                                    yahoo_symbol=payload.yahoo_symbol or payload.ticker,
                                    finnhub_symbol=payload.finnhub_symbol)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    peer = security.yahoo_symbol or security.finnhub_symbol
    if not peer:
        raise HTTPException(422, "该证券暂无可用行情数据源")
    if base == peer:
        raise HTTPException(422, "股票不能把自己设为同行")
    upsert_profile(db, peer, {"symbol": peer, "longName": security.display_name})
    if peer in _latest_official_peers(db, base):
        raise HTTPException(409, "该股票已是官方同行")
    existing = db.scalar(select(PeerRelation).where(PeerRelation.base_ticker == base, PeerRelation.peer_ticker == peer))
    if existing and existing.enabled:
        raise HTTPException(409, "该同行关系已存在")
    order = db.scalar(select(func.coalesce(func.max(PeerRelation.display_order), -1)).where(PeerRelation.base_ticker == base)) or 0
    if existing:
        existing.enabled = True
        existing.source = "manual"
        existing.peer_security_id = security.id
        existing.display_order = order + 1
    else:
        db.add(PeerRelation(base_ticker=base, peer_ticker=peer, peer_security_id=security.id, display_order=order + 1))
    exclusion = db.scalar(select(PeerExclusion).where(PeerExclusion.base_ticker == base, PeerExclusion.peer_ticker == peer))
    if exclusion:
        db.delete(exclusion)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该同行关系已存在")
    from app.tasks.celery_app import sync_peer_valuation_data, sync_ticker_valuation
    if not db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == peer)):
        sync_peer_valuation_data.delay(peer)
    sync_ticker_valuation.delay(base)
    return {"base_ticker": base, "peer_ticker": peer, "source": "manual"}


@router.delete("/peers/{base_ticker}/{peer_ticker}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manual_peer(base_ticker: str, peer_ticker: str, db: Session = Depends(get_db)):
    base, peer = _require_watched_ticker(db, base_ticker), normalize_ticker(peer_ticker)
    row = db.scalar(select(PeerRelation).where(PeerRelation.base_ticker == base, PeerRelation.peer_ticker == peer, PeerRelation.source == "manual"))
    if not row:
        raise HTTPException(404, "手动同行关系不存在")
    db.delete(row)
    db.commit()
    from app.tasks.celery_app import sync_ticker_valuation
    sync_ticker_valuation.delay(base)
    return Response(status_code=204)


@router.post("/peers/{base_ticker}/{peer_ticker}/exclude")
def exclude_official_peer(base_ticker: str, peer_ticker: str, db: Session = Depends(get_db)):
    base, peer = _require_watched_ticker(db, base_ticker), normalize_ticker(peer_ticker)
    if peer not in _latest_official_peers(db, base):
        raise HTTPException(422, "该股票不是当前官方同行")
    if not db.scalar(select(PeerExclusion.id).where(PeerExclusion.base_ticker == base, PeerExclusion.peer_ticker == peer)):
        db.add(PeerExclusion(base_ticker=base, peer_ticker=peer))
        relation = db.scalar(select(PeerRelation).where(PeerRelation.base_ticker == base, PeerRelation.peer_ticker == peer, PeerRelation.source == "official"))
        if relation:
            relation.enabled = False
        db.commit()
    from app.tasks.celery_app import sync_ticker_valuation
    sync_ticker_valuation.delay(base)
    return {"status": "excluded", "ticker": peer}


@router.delete("/peers/{base_ticker}/{peer_ticker}/exclude", status_code=status.HTTP_204_NO_CONTENT)
def restore_official_peer(base_ticker: str, peer_ticker: str, db: Session = Depends(get_db)):
    base, peer = _require_watched_ticker(db, base_ticker), normalize_ticker(peer_ticker)
    db.execute(delete(PeerExclusion).where(PeerExclusion.base_ticker == base, PeerExclusion.peer_ticker == peer))
    relation = db.scalar(select(PeerRelation).where(PeerRelation.base_ticker == base, PeerRelation.peer_ticker == peer, PeerRelation.source == "official"))
    if relation:
        relation.enabled = True
    db.commit()
    from app.tasks.celery_app import sync_ticker_valuation
    sync_ticker_valuation.delay(base)
    return Response(status_code=204)


@router.patch("/peers/{base_ticker}/{peer_ticker}/order")
def update_peer_order(base_ticker: str, peer_ticker: str, payload: OrderUpdate, db: Session = Depends(get_db)):
    base, peer = _require_watched_ticker(db, base_ticker), normalize_ticker(peer_ticker)
    row = db.scalar(select(PeerRelation).where(PeerRelation.base_ticker == base, PeerRelation.peer_ticker == peer, PeerRelation.source == "manual"))
    if not row:
        raise HTTPException(404, "仅手动同行支持排序")
    row.display_order = payload.display_order
    db.commit()
    return {"ticker": peer, "display_order": row.display_order}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
    stocks = []
    for item in items:
        quote = db.scalar(
            select(PriceSnapshot).where(PriceSnapshot.ticker == item.ticker).order_by(PriceSnapshot.quote_time.desc()).limit(1)
        )
        vol = quote.volume if quote else None
        ctx = volume_context(item.ticker, float(vol)) if vol else {"ratio": None, "label": None}
        profile = db.get(CompanyProfile, item.ticker)
        stocks.append(
            {
                "ticker": item.ticker,
                "price": quote.price if quote else None,
                "previous_close": quote.previous_close if quote else None,
                "updated_at": quote.quote_time if quote else None,
                "volume": vol,
                "volume_ratio": ctx["ratio"],
                "volume_label": ctx["label"],
                "company_name": profile.company_name if profile else None,
                "logo_url": profile.logo_url if profile else None,
            }
        )
    return {"market": market_status(), "stocks": stocks}


_INDICES_CACHE_KEY = "indices:quotes"
_INDICES_CACHE_TTL = 90  # 秒；前端每 30-60s 轮询，缓存避免每次都打 yfinance


@router.get("/indices")
def indices():
    """三大指数实时点位。Redis 缓存 90s，多客户端共享，避免频繁打 yfinance。"""
    import json

    import redis

    settings = get_settings()
    client = None
    try:
        client = redis.Redis.from_url(settings.redis_url)
        cached = client.get(_INDICES_CACHE_KEY)
        if cached:
            return {"indices": json.loads(cached), "market": market_status()}
    except Exception:
        client = None
    data = fetch_index_quotes()
    if client is not None:
        try:
            client.setex(_INDICES_CACHE_KEY, _INDICES_CACHE_TTL, json.dumps(data))
        except Exception:
            pass
    return {"indices": data, "market": market_status()}


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)):
    rows = db.scalars(select(PriceAlert).order_by(PriceAlert.triggered_at.desc()).limit(100)).all()
    return [{"id": r.id, "ticker": r.ticker, "period": r.period, "change_percent": r.change_percent, "triggered_at": r.triggered_at} for r in rows]


@router.get("/investigations")
def investigations(db: Session = Depends(get_db)):
    rows = db.scalars(select(Investigation).order_by(Investigation.started_at.desc()).limit(100)).all()
    return [
        {
            "id": row.id,
            "ticker": row.ticker,
            "status": row.status,
            "started_at": row.started_at,
            "ends_at": row.ends_at,
            "next_search_at": row.next_search_at,
            "news_count": len(db.scalars(select(NewsItem).where(NewsItem.investigation_id == row.id)).all()),
            "last_error": row.last_error,
        }
        for row in rows
    ]


_CONFIDENCE_RE = re.compile(r"因果置信度[^高中低]{0,8}?([高中低])")


def _extract_confidence(content: str | None) -> str | None:
    """从异动报告正文中解析“因果置信度：高/中/低”，仅取首个匹配。"""
    if not content:
        return None
    match = _CONFIDENCE_RE.search(content)
    return match.group(1) if match else None


@router.get("/reports")
def reports(report_type: str | None = None, db: Session = Depends(get_db)):
    query = select(Report).order_by(Report.created_at.desc())
    if report_type:
        query = query.where(Report.report_type == report_type)
    rows = db.scalars(query.limit(100)).all()
    return [{"id": r.id, "ticker": r.ticker, "report_type": r.report_type, "title": r.title, "model": r.model, "created_at": r.created_at, "confidence": _extract_confidence(r.content)} for r in rows]


@router.get("/reports/{report_id}")
def report_detail(report_id: int, db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "未找到报告")
    return report


def _news_out(item: NewsItem) -> dict:
    return {
        "id": item.id,
        "ticker": item.ticker,
        "provider": item.provider,
        "title": item.title,
        "translated_title": item.translated_title,
        "title_translation_model": item.title_translation_model,
        "title_translated_at": item.title_translated_at,
        "url": item.url,
        "source": item.source,
        "summary": item.summary,
        "symbols": item.symbols or [],
        "scope": item.scope,
        "topic": item.topic,
        "importance_score": item.importance_score,
        "quality_score": item.quality_score,
        "news_type": item.news_type,
        "published_at": item.published_at,
        "found_at": item.found_at,
        "relevance_score": item.relevance_score,
        "sentiment_score": item.sentiment_score,
        "ai_summary": item.ai_summary,
        "ai_summary_model": item.ai_summary_model,
        "ai_summary_status": item.ai_summary_status,
        "ai_summary_requested_at": item.ai_summary_requested_at,
    }


def _current_week_start() -> date_type:
    """本 ISO 周的周一（UTC）。原始新闻与每日定档只保留本周，历史归入每周汇总。"""
    today = datetime.now(UTC).date()
    return today - timedelta(days=today.isocalendar()[2] - 1)


@router.get("/news")
def list_news(ticker: str = Query(...), date: date_type | None = None, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "news")
    query = select(NewsItem).where(NewsItem.ticker == value, NewsItem.scope == "company")
    if date:
        start = datetime.combine(date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(date, datetime.max.time(), tzinfo=UTC)
        query = query.where(NewsItem.found_at >= start, NewsItem.found_at <= end)
    else:
        # 仅本周：早于本周的原始新闻已被每周汇总任务清理，这里也做上界防御
        week_start = datetime.combine(_current_week_start(), datetime.min.time(), tzinfo=UTC)
        query = query.where(NewsItem.found_at >= week_start)
    query = query.order_by(NewsItem.importance_score.desc().nullslast(), NewsItem.quality_score.desc().nullslast(), NewsItem.published_at.desc().nullslast(), NewsItem.found_at.desc()).limit(200)
    return [_news_out(item) for item in db.scalars(query).all()]


@router.get("/news/market")
def list_market_news(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), topic: str | None = None, db: Session = Depends(get_db)):
    query = select(NewsItem).where(NewsItem.scope == "market")
    if topic:
        query = query.where(NewsItem.topic == topic)
    total = len(db.scalars(query).all())
    rows = db.scalars(query.order_by(NewsItem.importance_score.desc().nullslast(), NewsItem.quality_score.desc().nullslast(), NewsItem.published_at.desc().nullslast()).offset(offset).limit(limit)).all()
    return {"items": [_news_out(item) for item in rows], "total": total, "generated_at": datetime.now(UTC), "last_updated_at": max((item.found_at for item in rows), default=None), "sources": sorted({item.provider for item in rows})}


@router.post("/news/market/refresh")
def refresh_market_news():
    from app.tasks.celery_app import poll_market_news
    poll_market_news.delay()
    return {"status": "queued", "scope": "market"}


@router.post("/news/{news_id}/summarize")
def summarize(news_id: int, force: bool = False, db: Session = Depends(get_db)):
    item = db.get(NewsItem, news_id)
    if not item:
        raise HTTPException(404, "未找到新闻")
    if item.ai_summary_status in {"queued", "processing"}:
        return _news_out(item)
    from uuid import uuid4
    from app.tasks.celery_app import summarize_news_item

    request_id = str(uuid4())
    item.ai_summary_status = "queued"
    item.ai_summary_request_id = request_id
    item.ai_summary_requested_at = datetime.now(UTC)
    item.ai_summary_last_error = None
    db.commit()
    db.refresh(item)
    try:
        summarize_news_item.apply_async(args=[news_id, request_id, force], priority=9)
    except Exception as exc:
        item.ai_summary_status = "failed"
        item.ai_summary_last_error = f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        raise HTTPException(503, "AI 总结任务暂时无法排队，请稍后重试") from exc
    return _news_out(item)


@router.get("/news/archive")
def news_archive(ticker: str = Query(...), date: date_type | None = None, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "news")
    query = select(DailyNewsArchive).where(DailyNewsArchive.ticker == value)
    if date:
        query = query.where(DailyNewsArchive.market_date == date)
    row = db.scalar(query.order_by(DailyNewsArchive.market_date.desc()).limit(1))
    if not row:
        return None
    return {
        "ticker": row.ticker,
        "market_date": row.market_date,
        "content": row.content,
        "included_news_ids": row.included_news_ids,
        "model": row.model,
        "version": row.version,
        "updated_at": row.updated_at,
    }


@router.post("/news/refresh")
def refresh_news(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "news")
    from app.tasks.celery_app import poll_news

    poll_news.delay(value)
    return {"status": "queued", "ticker": value}


@router.get("/news/weekly")
def news_weekly(ticker: str = Query(...), db: Session = Depends(get_db)):
    """历史每周新闻汇总，按周倒序。"""
    value = _require_watched_ticker(db, ticker, "news")
    rows = db.scalars(
        select(WeeklyNewsArchive)
        .where(WeeklyNewsArchive.ticker == value)
        .order_by(WeeklyNewsArchive.week_start.desc())
        .limit(52)
    ).all()
    return [
        {
            "ticker": row.ticker,
            "iso_year": row.iso_year,
            "iso_week": row.iso_week,
            "week_start": row.week_start,
            "week_end": row.week_end,
            "content": row.content,
            "included_dates": row.included_dates,
            "model": row.model,
            "version": row.version,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/financials")
def financials(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "fundamentals|financials")
    rows = db.scalars(
        select(QuarterlyFinancial).where(QuarterlyFinancial.ticker == value).order_by(QuarterlyFinancial.period_end.desc()).limit(4)
    ).all()
    return [
        {
            "fiscal_year": r.fiscal_year,
            "fiscal_period": r.fiscal_period,
            "period_end": r.period_end,
            "filed_at": r.filed_at,
            "currency": r.currency,
            "revenue": r.revenue,
            "eps": r.eps,
            "net_income": r.net_income,
            "operating_income": r.operating_income,
            "gross_margin": r.gross_margin,
            "net_margin": r.net_margin,
            "operating_cash_flow": r.operating_cash_flow,
            "free_cash_flow": r.free_cash_flow,
            "source": r.source,
            "synced_at": r.synced_at,
        }
        for r in rows
    ]


@router.get("/financial-statements")
def financial_statements(ticker: str = Query(...), frequency: str = Query("annual"), db: Session = Depends(get_db)):
    """Yahoo 三大报表展示数据；年度/季度各取最近四期。"""
    value = _require_watched_ticker(db, ticker, "financials")
    if frequency not in {"annual", "quarterly"}:
        raise HTTPException(422, "frequency 必须是 annual 或 quarterly")
    rows = db.scalars(select(FinancialStatementSnapshot).where(
        FinancialStatementSnapshot.ticker == value,
        FinancialStatementSnapshot.frequency == frequency,
    ).order_by(FinancialStatementSnapshot.period_end.desc()).limit(4)).all()
    return [{
        "fiscal_year": row.fiscal_year, "fiscal_period": row.fiscal_period, "period_end": row.period_end,
        "currency": row.currency, "income_statement": row.income_statement,
        "balance_sheet": row.balance_sheet, "cash_flow": row.cash_flow, "source": row.source,
        "synced_at": row.synced_at,
    } for row in rows]


@router.get("/cross-model")
def cross_model(ticker: str = Query(...), db: Session = Depends(get_db)):
    """读取最新每日估值快照；页面不在请求期间实时打外部数据源。"""
    value = _require_watched_ticker(db, ticker, "valuation")
    row = db.scalar(
        select(ValuationSnapshot).where(ValuationSnapshot.ticker == value)
        .order_by(ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc()).limit(1)
    )
    if not row:
        raise HTTPException(404, "估值快照尚未生成，请先触发刷新")
    return {**row.payload, "snapshot_date": row.snapshot_date, "generated_at": row.updated_at, "ai_model": row.ai_model}


@router.post("/cross-model/refresh")
def refresh_cross_model(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "valuation")
    from app.tasks.celery_app import sync_ticker_valuation
    sync_ticker_valuation.delay(value)
    return {"status": "queued", "ticker": value}


@router.post("/cross-model/graham")
def graham_with_overrides(payload: GrahamOverride, ticker: str = Query(...), db: Session = Depends(get_db)):
    """使用最新快照输入临时重算 Graham；不访问第三方，也不覆盖原始快照。"""
    from app.services.graham import apply_graham_overrides

    value = _require_watched_ticker(db, ticker, "valuation")
    row = db.scalar(
        select(ValuationSnapshot).where(ValuationSnapshot.ticker == value)
        .order_by(ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc()).limit(1)
    )
    if not row or not row.payload.get("graham"):
        raise HTTPException(404, "Graham 估值快照尚未生成，请先刷新今日数据")
    return apply_graham_overrides(row.payload["graham"], **payload.model_dump())


# 每项按候选 key 依次取第一个有值的（不同股票 Finnhub 填充的字段不一）
_METRIC_KEYS = [
    (("peTTM", "peBasicExclExtraTTM", "peAnnual"), "P/E"),
    (("pbAnnual", "pbQuarterly"), "P/B"),
    (("psTTM", "psAnnual"), "P/S"),
    (("grossMarginTTM", "grossMarginAnnual"), "毛利率 %"),
    (("netProfitMarginTTM", "netProfitMarginAnnual"), "净利率 %"),
    (("operatingMarginTTM", "operatingMarginAnnual"), "营业利润率 %"),
    (("roeTTM", "roeRfy"), "ROE %"), (("roaTTM", "roaRfy"), "ROA %"),
    (("revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy"), "营收增速 YoY %"),
    (("epsGrowthTTMYoy", "epsGrowthQuarterlyYoy"), "EPS增速 YoY %"),
    (("marketCapitalization",), "市值(百万)"),
]

_YAHOO_METRIC_KEYS = {
    "P/E": ("trailingPE", "forwardPE"),
    "P/B": ("priceToBook",),
    "P/S": ("priceToSalesTrailing12Months",),
    "毛利率 %": ("grossMargins",),
    "净利率 %": ("profitMargins",),
    "营业利润率 %": ("operatingMargins",),
    "ROE %": ("returnOnEquity",),
    "ROA %": ("returnOnAssets",),
    "营收增速 YoY %": ("revenueGrowth",),
    "EPS增速 YoY %": ("earningsGrowth",),
    "市值(百万)": ("marketCap",),
    "Beta": ("beta",),
    "52周高": ("fiftyTwoWeekHigh",),
    "52周低": ("fiftyTwoWeekLow",),
}
_PERCENT_METRICS = {"毛利率 %", "净利率 %", "营业利润率 %", "ROE %", "ROA %", "营收增速 YoY %", "EPS增速 YoY %"}


def _pick(metric: dict, keys: tuple[str, ...]):
    for key in keys:
        if metric.get(key) is not None:
            return metric[key]
    return None


def _yahoo_metric(info: dict, label: str):
    value = _pick(info, _YAHOO_METRIC_KEYS[label])
    if not isinstance(value, (int, float)):
        return None
    if label in _PERCENT_METRICS:
        return value * 100
    if label == "市值(百万)":
        return value / 1_000_000
    return value


@router.get("/fundamentals")
def fundamentals(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "fundamentals")
    yahoo_value = provider_symbol(db, value, "yahoo") or value
    finnhub_value = provider_symbol(db, value, "finnhub")
    # These are independent upstream calls. Run them together so an optional
    # slow provider cannot serially hold the whole fundamentals page hostage.
    with ThreadPoolExecutor(max_workers=4) as pool:
        info_future = pool.submit(fetch_yf_info_metrics, yahoo_value)
        yahoo_recs_future = pool.submit(fetch_yf_recommendations, yahoo_value)
        metric_future = pool.submit(fetch_basic_metrics, finnhub_value) if finnhub_value else None
        finnhub_recs_future = pool.submit(fetch_recommendations, finnhub_value) if finnhub_value else None
        try:
            info = info_future.result()
        except Exception:
            info = {}
        try:
            yahoo_recs = yahoo_recs_future.result()
        except Exception:
            yahoo_recs = []
        try:
            metric = metric_future.result() if metric_future else {}
        except Exception:
            metric = {}
        try:
            finnhub_recs = finnhub_recs_future.result() if finnhub_recs_future else []
        except Exception:
            finnhub_recs = []
    finnhub_available = bool(metric or finnhub_recs)
    metrics = []
    for finnhub_keys, label in _METRIC_KEYS:
        yahoo_value_for_metric = _yahoo_metric(info, label)
        finnhub_value_for_metric = _pick(metric, finnhub_keys)
        metrics.append({
            "label": label,
            "value": yahoo_value_for_metric if yahoo_value_for_metric is not None else finnhub_value_for_metric,
            "source": "yahoo" if yahoo_value_for_metric is not None else ("finnhub" if finnhub_value_for_metric is not None else None),
        })
    for label in ("Beta", "52周高", "52周低"):
        yahoo_value_for_metric = _yahoo_metric(info, label)
        metrics.append({"label": label, "value": yahoo_value_for_metric,
                        "source": "yahoo" if yahoo_value_for_metric is not None else None})
    recs = finnhub_recs or yahoo_recs
    latest = recs[0] if recs else None
    rating = None
    if latest:
        rating = {
            "period": latest.get("period"),
            "strongBuy": latest.get("strongBuy", 0), "buy": latest.get("buy", 0),
            "hold": latest.get("hold", 0), "sell": latest.get("sell", 0),
            "strongSell": latest.get("strongSell", 0),
        }
    yahoo_available = any(item["source"] == "yahoo" for item in metrics)
    return {"ticker": value, "metrics": metrics, "rating": rating,
            "as_of": datetime.now(UTC), "data_mode": "live",
            "source_support": {"yahoo": yahoo_available, "finnhub": finnhub_available}}


@router.get("/sec-filings")
def sec_filings(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "sec")
    rows = db.scalars(
        select(SecFiling)
        .where(SecFiling.ticker == value)
        .order_by(SecFiling.filing_date.desc(), SecFiling.id.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": r.id,
            "form": r.form,
            "form_label": r.form_label,
            "items": r.items,
            "event_labels": r.event_labels or [],
            "priority": r.priority,
            "filing_date": r.filing_date,
            "report_date": r.report_date,
            "filing_url": r.filing_url,
        }
        for r in rows
    ]


@router.post("/sec-filings/refresh")
def refresh_sec_filings(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "sec")
    from app.tasks.celery_app import sync_ticker_sec_all

    sync_ticker_sec_all.delay(value)
    return {"status": "queued", "ticker": value}


@router.get("/sec-events")
def sec_events(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "sec")
    rows = db.scalars(
        select(SecEvent)
        .where(SecEvent.ticker == value)
        .order_by(SecEvent.filing_date.desc(), SecEvent.id.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": r.id,
            "form": r.form,
            "item_code": r.item_code,
            "item_label": r.item_label,
            "priority": r.priority,
            "text": r.text,
            "summary_zh": r.summary_zh,
            "summary_model": r.summary_model,
            "summary_status": r.summary_status,
            "filing_date": r.filing_date,
            "filing_url": r.filing_url,
        }
        for r in rows
    ]


@router.get("/sec-financials")
def sec_financials(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "sec")
    rows = db.scalars(
        select(SecFinancialPeriod)
        .where(SecFinancialPeriod.ticker == value)
        .order_by(SecFinancialPeriod.period_end.desc())
        .limit(8)
    ).all()
    return [
        {
            "fiscal_year": r.fiscal_year,
            "fiscal_period": r.fiscal_period,
            "form": r.form,
            "period_end": r.period_end,
            "currency": r.currency,
            "revenue": r.revenue,
            "net_income": r.net_income,
            "operating_income": r.operating_income,
            "gross_profit": r.gross_profit,
            "eps_basic": r.eps_basic,
            "eps_diluted": r.eps_diluted,
            "cash_and_equivalents": r.cash_and_equivalents,
            "total_debt": r.total_debt,
            "shares_outstanding": r.shares_outstanding,
            "operating_cash_flow": r.operating_cash_flow,
        }
        for r in rows
    ]


@router.get("/sec-insider")
def sec_insider(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker, "sec")
    rows = db.scalars(
        select(SecInsiderTrade)
        .where(SecInsiderTrade.ticker == value)
        .order_by(SecInsiderTrade.transaction_date.desc().nullslast(), SecInsiderTrade.id.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": r.id,
            "insider_name": r.insider_name,
            "insider_title": r.insider_title,
            "transaction_date": r.transaction_date,
            "transaction_code": r.transaction_code,
            "shares": r.shares,
            "price": r.price,
            "value": r.value,
            "shares_owned_after": r.shares_owned_after,
            "flag": r.flag,
            "filing_url": r.filing_url,
        }
        for r in rows
    ]


@router.get("/sec-13f")
def sec_13f(ticker: str = Query(...), db: Session = Depends(get_db)):
    """13F 机构持仓：返回最新季度的持有机构（按市值降序），附环比增减。"""
    value = _require_watched_ticker(db, ticker, "sec")
    latest_period = db.scalar(
        select(Sec13FHolding.report_period)
        .where(Sec13FHolding.ticker == value)
        .order_by(Sec13FHolding.report_period.desc())
        .limit(1)
    )
    if latest_period is None:
        return {"report_period": None, "prev_period": None, "holdings": []}
    rows = db.scalars(
        select(Sec13FHolding)
        .where(Sec13FHolding.ticker == value, Sec13FHolding.report_period == latest_period)
        .order_by(Sec13FHolding.value_usd.desc().nullslast())
        .limit(50)
    ).all()
    prev_period = db.scalar(
        select(Sec13FHolding.report_period)
        .where(Sec13FHolding.ticker == value, Sec13FHolding.report_period < latest_period)
        .order_by(Sec13FHolding.report_period.desc())
        .limit(1)
    )
    prev_shares: dict[str, float] = {}
    if prev_period is not None:
        for r in db.scalars(
            select(Sec13FHolding).where(Sec13FHolding.ticker == value, Sec13FHolding.report_period == prev_period)
        ).all():
            if r.shares is not None:
                prev_shares[r.manager_name] = prev_shares.get(r.manager_name, 0.0) + r.shares
    holdings = []
    for r in rows:
        prev = prev_shares.get(r.manager_name)
        share_change = None
        if r.shares is not None and prev is not None:
            share_change = r.shares - prev
        elif prev is None and prev_period is not None:
            share_change = None  # 新建仓，前端据 is_new 展示
        holdings.append(
            {
                "id": r.id,
                "manager_name": r.manager_name,
                "shares": r.shares,
                "value_usd": r.value_usd,
                "put_call": r.put_call,
                "share_change": share_change,
                "is_new": prev is None and prev_period is not None,
                "filing_date": r.filing_date,
            }
        )
    return {"report_period": latest_period, "prev_period": prev_period, "holdings": holdings}


@router.post("/sec-13f/refresh")
def refresh_sec_13f(db: Session = Depends(get_db)):
    """手动触发 13F 全市场数据集重新采集（强制下载，忽略季度幂等）。"""
    from app.tasks.celery_app import sync_sec_13f

    sync_sec_13f.delay(force=True)
    return {"status": "queued"}


def _trade_dict(t: CongressTrade) -> dict:
    return {
        "id": t.id,
        "filer_id": t.filer_id,
        "filer_name": t.filer_name,
        "chamber": t.chamber,
        "party": t.party,
        "state": t.state,
        "ticker": t.ticker,
        "asset_name": t.asset_name,
        "transaction_type": t.transaction_type,
        "transaction_date": t.transaction_date,
        "filing_date": t.filing_date,
        "amount_label": t.amount_label,
        "is_late": t.is_late,
    }


def _trade_log_out(row: TradeLog) -> dict:
    return {
        "id": row.id,
        "trade_date": row.trade_date,
        "ticker": row.ticker,
        "direction": row.direction,
        "quantity": row.quantity,
        "price": row.price,
        "note": row.note,
        "content": row.content,
        "table_rows": row.table_rows or [],
        "photo_urls": row.photo_urls or [],
        "ai_summary": row.ai_summary,
        "ai_summary_model": row.ai_summary_model,
        "ai_summary_created_at": row.ai_summary_created_at,
        "created_at": row.created_at,
    }


def _resolve_trade_log_securities(db: Session, payload: TradeLogCreate | TradeLogUpdate) -> None:
    for item in payload.table_rows:
        if not item.ticker:
            item.security_id = None
            continue
        try:
            security = resolve_security(db, security_id=item.security_id, source="yahoo", yahoo_symbol=item.ticker)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, f"交易标的 {item.ticker} 无法验证，请重新搜索选择") from exc
        item.security_id = security.id
        item.ticker = security.display_symbol


def _trade_log_evidence(row: TradeLog) -> str:
    table_lines = []
    for index, item in enumerate(row.table_rows or [], 1):
        table_lines.append(
            f"{index}. 标的={item.get('ticker') or '数据不足'}，方向={item.get('direction') or '数据不足'}，"
            f"数量={item.get('quantity') if item.get('quantity') is not None else '数据不足'}，"
            f"价格={item.get('price') if item.get('price') is not None else '数据不足'}，"
            f"费用={item.get('fee') if item.get('fee') is not None else '数据不足'}，"
            f"策略={item.get('strategy') or '数据不足'}，结果={item.get('result') or '数据不足'}"
        )
    return "\n".join(
        [
            f"日期：{row.trade_date}",
            f"主标的：{row.ticker or '数据不足'}",
            f"方向：{row.direction or '数据不足'}",
            f"数量：{row.quantity if row.quantity is not None else '数据不足'}",
            f"价格：{row.price if row.price is not None else '数据不足'}",
            f"简短备注：{row.note or '数据不足'}",
            f"文字记录：\n{row.content or '数据不足'}",
            "表格记录：\n" + ("\n".join(table_lines) if table_lines else "数据不足"),
            f"照片数量：{len(row.photo_urls or [])}",
        ]
    )


@router.get("/trade-logs", response_model=list[TradeLogOut])
def list_trade_logs(
    date: date_type | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(TradeLog).where(TradeLog.user_id == user.id)
    if date:
        query = query.where(TradeLog.trade_date == date)
    rows = db.scalars(query.order_by(TradeLog.trade_date.desc(), TradeLog.created_at.desc()).limit(200)).all()
    return [_trade_log_out(row) for row in rows]


@router.post("/trade-logs", response_model=TradeLogOut, status_code=status.HTTP_201_CREATED)
def create_trade_log(
    payload: TradeLogCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _resolve_trade_log_securities(db, payload)
    row = TradeLog(user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _trade_log_out(row)


@router.patch("/trade-logs/{log_id}", response_model=TradeLogOut)
def update_trade_log(
    log_id: int,
    payload: TradeLogUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(TradeLog).where(TradeLog.id == log_id, TradeLog.user_id == user.id))
    if not row:
        raise HTTPException(404, "未找到交易日志")
    _resolve_trade_log_securities(db, payload)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.ai_summary = None
    row.ai_summary_model = None
    row.ai_summary_input_hash = None
    row.ai_summary_created_at = None
    db.commit()
    db.refresh(row)
    return _trade_log_out(row)


@router.delete("/trade-logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trade_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(TradeLog).where(TradeLog.id == log_id, TradeLog.user_id == user.id))
    if not row:
        raise HTTPException(404, "未找到交易日志")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/trade-logs/{log_id}/summarize", response_model=TradeLogOut)
def summarize_trade_log_route(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(TradeLog).where(TradeLog.id == log_id, TradeLog.user_id == user.id))
    if not row:
        raise HTTPException(404, "未找到交易日志")
    evidence = _trade_log_evidence(row)
    input_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:64]
    if row.ai_summary and row.ai_summary_input_hash == input_hash:
        return _trade_log_out(row)
    summary, model = summarize_trade_log(evidence)
    row.ai_summary = summary
    row.ai_summary_model = model
    row.ai_summary_input_hash = input_hash
    row.ai_summary_created_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return _trade_log_out(row)


@router.get("/congress/trades")
def congress_trades(ticker: str = Query(...), db: Session = Depends(get_db)):
    """某股相关的政客交易（个股页时间轴）。ticker 需在自选列表。"""
    value = _require_watched_ticker(db, ticker)
    rows = db.scalars(
        select(CongressTrade)
        .where(CongressTrade.ticker == value)
        .order_by(CongressTrade.transaction_date.desc().nullslast())
        .limit(100)
    ).all()
    return [_trade_dict(t) for t in rows]


@router.get("/congress/figures")
def congress_figures(db: Session = Depends(get_db)):
    """追踪名人列表（种子三位 + 已订阅政客）。"""
    figs = db.scalars(select(TrackedFigure).order_by(TrackedFigure.is_seed.desc(), TrackedFigure.display_name)).all()
    return [
        {
            "slug": f.slug,
            "display_name": f.display_name,
            "kind": f.kind,
            "photo_url": f.photo_url,
            "note": f.note,
            "is_seed": f.is_seed,
            "has_positions": f.is_seed,
        }
        for f in figs
    ]


@router.get("/congress/figure/{slug}")
def congress_figure(slug: str, db: Session = Depends(get_db)):
    """名人详情：档案 + 持仓（饼图，已按类别聚合）+ 交易时间轴 +（木头姐）调仓看板。"""
    fig = db.scalar(select(TrackedFigure).where(TrackedFigure.slug == slug))
    if not fig:
        raise HTTPException(404, "未找到该名人")
    positions = []
    if fig.is_seed:
        rows = db.scalars(
            select(FigurePosition).where(FigurePosition.figure_slug == slug)
        ).all()
        for p in rows:
            value = p.adjusted_value if not p.is_percent else p.baseline_value
            if value <= 0:
                continue
            positions.append({
                "ticker": p.ticker,
                "asset_name": p.asset_name,
                "category": p.category,
                "value": value,
                "is_percent": p.is_percent,
                "note": p.note,
            })
        positions.sort(key=lambda x: x["value"], reverse=True)
    trades = []
    if fig.kadoa_filer_id:
        rows = db.scalars(
            select(CongressTrade)
            .where(CongressTrade.filer_id == fig.kadoa_filer_id)
            .order_by(CongressTrade.transaction_date.desc().nullslast())
            .limit(80)
        ).all()
        trades = [_trade_dict(t) for t in rows]
    return {
        "slug": fig.slug,
        "display_name": fig.display_name,
        "kind": fig.kind,
        "photo_url": fig.photo_url,
        "note": fig.note,
        "is_seed": fig.is_seed,
        "positions": positions,
        "positions_are_percent": bool(positions and positions[0]["is_percent"]),
        "trades": trades,
        "moves": (fig.extra or {}).get("moves"),
    }


@router.get("/congress/search")
def congress_search(q: str = Query(..., min_length=2)):
    """按名字搜 kadoa filer 名单。返回可订阅候选。"""
    from app.services import congress as cg

    try:
        index = cg.fetch_filers_index()
    except Exception:
        raise HTTPException(502, "数据源暂不可用")
    ql = q.strip().lower()
    hits = [f for f in index if ql in (f.get("full_name") or "").lower()]
    return [
        {
            "filer_id": f.get("id"),
            "full_name": f.get("full_name"),
            "chamber": f.get("chamber"),
            "branch": f.get("branch"),
            "party": f.get("party"),
            "state": f.get("state"),
            "trade_count": f.get("trade_count"),
        }
        for f in hits[:20]
    ]


@router.post("/congress/subscribe")
def congress_subscribe(payload: dict, db: Session = Depends(get_db)):
    """订阅一位政客（非种子）：加入追踪表并异步拉其全部交易。"""
    filer_id = (payload.get("filer_id") or "").strip()
    full_name = (payload.get("full_name") or "").strip()
    if not filer_id:
        raise HTTPException(400, "缺少 filer_id")
    slug = filer_id  # kadoa filer_id 本身唯一，直接当 slug
    existing = db.scalar(select(TrackedFigure).where(TrackedFigure.slug == slug))
    if existing:
        raise HTTPException(409, "已订阅该政客")
    db.add(TrackedFigure(
        slug=slug,
        display_name=full_name or filer_id,
        kind="politician",
        kadoa_filer_id=filer_id,
        is_seed=False,
    ))
    db.commit()
    from app.tasks.celery_app import sync_subscribed_figure

    sync_subscribed_figure.delay(filer_id)
    return {"status": "subscribed", "slug": slug}


@router.delete("/congress/figure/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def congress_unsubscribe(slug: str, db: Session = Depends(get_db)):
    """取消订阅（仅限非种子人物）。"""
    fig = db.scalar(select(TrackedFigure).where(TrackedFigure.slug == slug))
    if not fig:
        raise HTTPException(404, "未找到该名人")
    if fig.is_seed:
        raise HTTPException(403, "种子人物不可删除")
    db.execute(delete(TrackedFigure).where(TrackedFigure.slug == slug))
    db.commit()
    return Response(status_code=204)


def _settings_values(db: Session) -> dict:
    defaults = get_settings()
    keys = ["threshold_20m", "threshold_1h", "threshold_day", "alert_cooldown_minutes", "investigation_interval_minutes", "investigation_duration_minutes"]
    fallback = {
        "threshold_20m": defaults.default_threshold_20m,
        "threshold_1h": defaults.default_threshold_1h,
        "threshold_day": defaults.default_threshold_day,
        "alert_cooldown_minutes": defaults.alert_cooldown_minutes,
        "investigation_interval_minutes": defaults.investigation_interval_minutes,
        "investigation_duration_minutes": defaults.investigation_duration_minutes,
    }
    stored = {row.key: row.value for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(keys))).all()}
    return {**fallback, **{key: type(fallback[key])(value) for key, value in stored.items()}, "price_poll_minutes": defaults.price_poll_minutes}


@router.get("/settings", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db)):
    return _settings_values(db)


@router.patch("/settings", response_model=SettingsOut)
def write_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    for key, value in payload.model_dump().items():
        row = db.get(AppSetting, key)
        if row:
            row.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    db.commit()
    return _settings_values(db)
