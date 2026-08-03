from datetime import UTC, date, datetime, timedelta
import logging

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import delete, or_, select

import hashlib
import asyncio

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    CongressTrade,
    DailyNewsArchive,
    EarningsEvent,
    FigurePosition,
    FinancialStatementSnapshot,
    CompanyProfile,
    FmpSyncState,
    Investigation,
    InvestigationStatus,
    InvestmentCalendarSyncRun,
    MacroSyncRun,
    NewsItem,
    PortfolioPosition,
    QuarterlyFinancial,
    Report,
    ReportType,
    Sec13FHolding,
    SecCusipMap,
    SecEvent,
    SecFiling,
    SecFinancialPeriod,
    SecInsiderTrade,
    TrackedFigure,
    ValuationSnapshot,
    WatchlistItem,
    WeeklyNewsArchive,
)
from app.services import archive
from app.services.alerting import evaluate_quote, evaluate_user_price_alerts
from app.services.financials import quarters_from_yf
from app.services.sec_edgar import fetch_filings
from app.services.market_context import build_market_context
from app.services.llm import curate_daily_news, curate_weekly_news, generate_analysis, summarize_news
from app.services.llm import explain_cross_model
from app.services.market_calendar import market_data_collection_status, market_status
from app.services.market_data import fetch_earnings_events, fetch_yf_financial_statements, fetch_yf_quarterly
from app.services.price_snapshots import (
    collect_price_snapshot,
    get_latest_persisted_price_snapshot,
    persist_price_snapshot,
)
from app.services.marketaux import fetch_marketaux_market_news, fetch_marketaux_news
# Legacy FMP news records remain readable, but FMP is no longer scheduled as a
# news source: the provider is reserved for profile and EOD history endpoints.
from app.services.fmp_market import FmpAuthenticationError, FmpError, FmpInvalidSymbol, FmpPremiumRequired, FmpQuotaExhausted, checkpoint, sync_history as sync_fmp_history_service, sync_profile as sync_fmp_profile_service
from app.services.technical_analysis_engine import generate_for_symbol, sync_fallback_history
from app.services.company_profile_translation import translate_description
from app.services.news import MARKET_TICKER, collect_ticker_news, prepare_news
from app.services.news_store import news_for_day, persist_news
from app.services.article_fetch import fetch_article_text
from app.services.search import search_ticker_news
from app.services.title_translation import title_input_hash, translate_title
from app.services.cross_model import build_cross_model, fetch_cross_model_inputs, opinion_evidence
from app.services.finnhub_mcp import fetch_basic_metrics, fetch_company_peers, fetch_market_news
from app.services.graham import build_graham_from_sources, get_latest_aaa_corporate_bond_yield
from app.services.stock_management import cache_official_relations, effective_peer_symbols, referenced_tickers, upsert_profile, valuation_tickers
from app.services.securities import provider_symbol
from app.services.investment_calendar import sync_calendar
from app.services.ownership import refresh_share_statistics
from app.services.macro.definitions import RAW_SERIES
from app.services.macro.sync import can_start_sync, run_macro_sync

settings = get_settings()
logger = logging.getLogger(__name__)
NEWS_PER_TICKER = 12  # 每只股票入库上限；低信息时允许少于该值，避免用噪声补位。
celery_app = Celery("stock_monitor", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "poll-market": {"task": "app.tasks.celery_app.poll_market", "schedule": settings.price_poll_minutes * 60},
    "advance-investigations": {"task": "app.tasks.celery_app.advance_investigations", "schedule": 60},
    "scheduled-reports": {"task": "app.tasks.celery_app.scheduled_reports", "schedule": 300},
    "sync-earnings": {"task": "app.tasks.celery_app.sync_earnings", "schedule": 21600},
    # The database-backed due check survives beat container recreation. A raw
    # 12-hour interval restarts its clock after every deployment and can starve.
    "sync-investment-calendar": {
        "task": "app.tasks.celery_app.ensure_investment_calendar_fresh",
        "schedule": 600,
    },
    "sync-share-statistics": {"task": "app.tasks.celery_app.sync_share_statistics", "schedule": 86400},
    "earnings-reports": {"task": "app.tasks.celery_app.earnings_reports", "schedule": 1800},
    "poll-news": {"task": "app.tasks.celery_app.poll_news", "schedule": settings.news_poll_minutes * 60},
    "poll-market-news": {"task": "app.tasks.celery_app.poll_market_news", "schedule": settings.market_news_poll_minutes * 60},
    "curate-daily-news": {"task": "app.tasks.celery_app.curate_daily_archives", "schedule": 1800},
    # 每周汇总：每天跑一次，把已结束的完整 ISO 周（周一起）合并成周报后删除当周原始新闻与每日定档
    "rollup-weekly-news": {"task": "app.tasks.celery_app.rollup_weekly_archives", "schedule": 3600},
    "sync-financials": {"task": "app.tasks.celery_app.sync_financials", "schedule": 43200},
    "sync-valuations": {"task": "app.tasks.celery_app.sync_valuations", "schedule": 86400},
    "translate-news-titles": {"task": "app.tasks.celery_app.translate_news_titles", "schedule": 60},
    "summarize-sec-events": {"task": "app.tasks.celery_app.summarize_sec_events", "schedule": 120},
    "sync-sec-filings": {"task": "app.tasks.celery_app.sync_sec_filings", "schedule": 21600},
    "sync-sec-events": {"task": "app.tasks.celery_app.sync_sec_events", "schedule": 21600},
    "sync-sec-insider": {"task": "app.tasks.celery_app.sync_sec_insider", "schedule": 21600},
    "sync-sec-financials": {"task": "app.tasks.celery_app.sync_sec_financials", "schedule": 43200},
    # 13F 每季度才发布一次，每天跑一次即可（任务内部靠数据集内容判重，无新数据则空转）
    "sync-sec-13f": {"task": "app.tasks.celery_app.sync_sec_13f", "schedule": 86400},
    # 政客交易：按自选股拉相关交易（6h）；追踪名人全量交易+持仓叠加（12h）
    "sync-congress-trades": {"task": "app.tasks.celery_app.sync_congress_trades", "schedule": 21600},
    "sync-tracked-figures": {"task": "app.tasks.celery_app.sync_tracked_figures", "schedule": 43200},
    # A frequent due check makes the daily 08:00 UTC schedule survive beat
    # restarts without accidentally running twice on the same UTC day.
    "sync-us-macro-due": {"task": "app.tasks.celery_app.ensure_us_macro_fresh", "schedule": 600},
    # Flex users are enrolled only after one successful manual import. The
    # due check is cheap and request_sync provides a per-user database lock.
    "sync-ibkr-flex-due": {"task": "app.tasks.celery_app.ensure_ibkr_flex_fresh", "schedule": 900},
}


@celery_app.task(
    name="app.tasks.celery_app.sync_us_macro",
    soft_time_limit=900,
    time_limit=960,
)
def sync_us_macro(series_keys: list[str] | None = None, trigger_type: str = "scheduled"):
    with SessionLocal() as db:
        return asyncio.run(run_macro_sync(db, series_keys=series_keys, trigger_type=trigger_type))


@celery_app.task(name="app.tasks.celery_app.ensure_us_macro_fresh")
def ensure_us_macro_fresh():
    settings = get_settings()
    if not settings.alpha_vantage_macro_sync_enabled or not settings.alpha_vantage_enabled or not settings.alpha_vantage_api_key.strip():
        return {"status": "not_configured"}
    now = datetime.now(UTC)
    if now.hour != max(0, min(23, int(settings.alpha_vantage_macro_sync_hour_utc))):
        return {"status": "not_due", "hour_utc": now.hour}
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        latest = db.scalar(select(MacroSyncRun).where(
            MacroSyncRun.provider == "alpha_vantage",
        ).order_by(MacroSyncRun.finished_at.desc()).limit(1))
        if latest and latest.status == "success" and (
            latest.requested_series_count >= len(RAW_SERIES)
            or latest.trigger_type == "scheduled_retry"
        ) and latest.finished_at and latest.finished_at >= today_start:
            return {"status": "already_synced", "run_id": latest.id}
        valid_keys = {row["series_key"] for row in RAW_SERIES}
        retry_keys = [
            key for key in (latest.error_summary_json or {})
            if key in valid_keys
        ] if latest and latest.status == "partial_success" else []
        requested = retry_keys or None
        request_count = len(retry_keys) if retry_keys else len(RAW_SERIES)
        allowed, reason = can_start_sync(
            db, request_count, trigger_type="scheduled", settings=settings,
        )
        if not allowed:
            return {"status": "not_due", "reason": reason, "requested_series_count": request_count}
    task = sync_us_macro.delay(requested, "scheduled_retry" if requested else "scheduled")
    return {"status": "queued", "task_id": task.id, "series_keys": requested}


@celery_app.task(
    name="app.tasks.celery_app.sync_ibkr_flex_account",
    soft_time_limit=540,
    time_limit=600,
)
def sync_ibkr_flex_account(sync_run_id: int):
    """One read-only Flex pipeline shared by manual and future schedules."""
    from app.integrations.ibkr.sync import execute_sync
    return asyncio.run(execute_sync(sync_run_id))


@celery_app.task(name="app.tasks.celery_app.ensure_ibkr_flex_fresh")
def ensure_ibkr_flex_fresh():
    settings = get_settings()
    if not settings.ibkr_flex_enabled or not settings.ibkr_flex_auto_sync_enabled:
        return {"status": "disabled"}
    from app.integrations.ibkr.sync import request_due_syncs
    with SessionLocal() as db:
        run_ids = request_due_syncs(
            db,
            interval_hours=settings.ibkr_flex_auto_sync_interval_hours,
        )
    for run_id in run_ids:
        sync_ibkr_flex_account.delay(run_id)
    return {"status": "queued" if run_ids else "fresh", "run_ids": run_ids}


@celery_app.task(
    name="app.tasks.celery_app.summarize_ai_conversation",
    soft_time_limit=75,
    time_limit=90,
)
def summarize_ai_conversation(snapshot_id: int):
    """Generate one idempotent incremental conversation summary snapshot."""
    from app.ai_memory.summaries import ConversationSummaryService

    with SessionLocal() as db:
        row = asyncio.run(ConversationSummaryService(db).process(snapshot_id))
        if row is None:
            return {"status": "missing", "snapshot_id": snapshot_id}
        return {
            "status": row.status,
            "snapshot_id": row.id,
            "version": row.version,
            "error_code": row.error_code,
        }
if settings.fmp_sync_enabled and settings.fmp_api_key.strip():
    celery_app.conf.beat_schedule["sync-fmp-history"] = {
        # 23:30 UTC on US trading weekdays, after the regular close in both DST modes.
        "task": "app.tasks.celery_app.sync_fmp_history", "schedule": crontab(hour=23, minute=30, day_of_week="1-5"),
    }
    celery_app.conf.beat_schedule["sync-fmp-profiles"] = {
        "task": "app.tasks.celery_app.sync_fmp_profiles", "schedule": 604800,
    }
    celery_app.conf.beat_schedule["translate-fmp-profiles"] = {
        "task": "app.tasks.celery_app.translate_fmp_profiles", "schedule": 300,
    }


@celery_app.task(
    name="app.tasks.celery_app.summarize_news_item",
    soft_time_limit=210,
    time_limit=240,
)
def summarize_news_item(news_id: int, request_id: str, force: bool = False):
    """抓取正文并生成单篇新闻总结；request_id 防止旧任务覆盖较新的请求。"""
    with SessionLocal() as db:
        item = db.get(NewsItem, news_id)
        if not item:
            return {"status": "missing", "news_id": news_id}
        if item.ai_summary_request_id != request_id:
            return {"status": "superseded", "news_id": news_id}
        item.ai_summary_status = "processing"
        item.ai_summary_last_error = None
        title = item.title
        url = item.url
        stored_content = item.raw_content or item.summary or item.title
        existing_hash = item.ai_summary_input_hash
        has_summary = bool(item.ai_summary)
        db.commit()

    try:
        full_text = fetch_article_text(url)
        content = full_text or stored_content
        input_hash = hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()[:64]
        if has_summary and existing_hash == input_hash and not force:
            summary = model = None
        else:
            summary, model = summarize_news(title, content)

        with SessionLocal() as db:
            item = db.get(NewsItem, news_id)
            if not item or item.ai_summary_request_id != request_id:
                return {"status": "superseded", "news_id": news_id}
            if full_text:
                item.raw_content = full_text
            if summary is not None:
                item.ai_summary = summary
                item.ai_summary_model = model
                item.ai_summary_input_hash = input_hash
                item.ai_summary_created_at = datetime.now(UTC)
            item.ai_summary_status = "completed"
            item.ai_summary_last_error = None
            db.commit()
        return {"status": "completed", "news_id": news_id}
    except Exception as exc:
        logger.exception("Interactive news summary failed news_id=%s", news_id)
        with SessionLocal() as db:
            item = db.get(NewsItem, news_id)
            if item and item.ai_summary_request_id == request_id:
                item.ai_summary_status = "failed"
                item.ai_summary_last_error = f"{type(exc).__name__}: {exc}"[:1000]
                db.commit()
        return {"status": "failed", "news_id": news_id}


def _save_report(db, key: str, ticker: str | None, report_type: ReportType, title: str, evidence: str, tier: str, sources: list[dict], start=None, end=None):
    if db.scalar(select(Report.id).where(Report.idempotency_key == key)):
        return
    if ticker:
        try:
            evidence = build_market_context(ticker, provider_symbol(db, ticker, "finnhub")) + "\n\n# 新闻线索\n" + evidence
        except Exception:
            pass
    content, model = generate_analysis(title, evidence, tier, report_type.value)
    db.add(Report(idempotency_key=key, ticker=ticker, report_type=report_type, title=title, content=content, model=model, sources=sources, period_start=start, period_end=end))


@celery_app.task(name="app.tasks.celery_app.poll_market", autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, max_retries=3)
def poll_market():
    collection = market_data_collection_status()
    if not collection["is_collecting"]:
        return {"skipped": "market_closed"}
    with SessionLocal() as db:
        items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
        watched_tickers = {item.ticker for item in items}
        peer_tickers = set(referenced_tickers(db))
        by_ticker = {item.ticker: item for item in items}
        stored = 0
        failed: list[str] = []
        for ticker in sorted(watched_tickers | peer_tickers):
            try:
                snapshot, created = persist_price_snapshot(
                    db, collect_price_snapshot(db, ticker)
                )
            except Exception:
                logger.warning("price_snapshot_sync_failed symbol=%s", ticker, exc_info=True)
                failed.append(ticker)
                continue
            if not created:
                continue
            stored += 1
            watched = by_ticker.get(snapshot.symbol)
            if watched and watched.alert_enabled:
                evaluate_quote(db, watched, snapshot)
            if watched:
                evaluate_user_price_alerts(db, snapshot)
        db.commit()
        return {
            "quotes": stored,
            "failed": failed,
            "market_session": collection["market_session"],
        }


def _collect_investigation_news(db, investigation: Investigation, now: datetime):
    dtos = collect_ticker_news(investigation.ticker, "sudden price movement catalyst", days=2,
                               finnhub_symbol=provider_symbol(db, investigation.ticker, "finnhub"))
    for dto in dtos:
        fingerprint = dto.fingerprint
        if db.scalar(select(NewsItem.id).where(NewsItem.fingerprint == fingerprint)):
            continue
        db.add(
            NewsItem(
                investigation_id=investigation.id, ticker=investigation.ticker, provider=dto.provider,
                external_id=dto.external_id, fingerprint=fingerprint, title=dto.title[:512], url=dto.url,
                source=dto.source, summary=dto.summary, raw_content=dto.raw_content, image_url=dto.image_url,
                raw_payload=dto.raw_payload or None, published_at=dto.published_at,
            )
        )
    investigation.next_search_at = now + timedelta(minutes=settings.investigation_interval_minutes)
    investigation.last_error = None


def _daily_archive_text(db, ticker: str, market_date) -> str:
    row = db.scalar(
        select(DailyNewsArchive).where(DailyNewsArchive.ticker == ticker, DailyNewsArchive.market_date == market_date)
    )
    return f"\n\n# 当日新闻定档（Luna 去重筛选）\n{row.content}" if row else ""


def _complete_investigation(db, investigation: Investigation):
    news = db.scalars(select(NewsItem).where(NewsItem.investigation_id == investigation.id).order_by(NewsItem.found_at)).all()
    evidence = "\n".join(f"[{index}] {item.title}\n{item.summary or item.raw_content or ''}\n{item.url}" for index, item in enumerate(news, 1))
    evidence += _daily_archive_text(db, investigation.ticker, investigation.started_at.date())
    sources = [{"title": item.title, "url": item.url} for item in news]
    key = f"movement:{investigation.id}"
    _save_report(db, key, investigation.ticker, ReportType.movement, f"{investigation.ticker} 价格异动调查报告", evidence or "调查期内未检索到相关新闻。", "important", sources, investigation.started_at, investigation.ends_at)
    investigation.status = InvestigationStatus.completed


@celery_app.task(name="app.tasks.celery_app.advance_investigations")
def advance_investigations():
    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = db.scalars(
            select(Investigation).where(Investigation.status == InvestigationStatus.active, Investigation.next_search_at <= now).with_for_update(skip_locked=True)
        ).all()
        for investigation in rows:
            try:
                if now >= investigation.ends_at:
                    investigation.status = InvestigationStatus.reporting
                    _complete_investigation(db, investigation)
                else:
                    _collect_investigation_news(db, investigation, now)
            except Exception as error:
                investigation.last_error = str(error)
                investigation.next_search_at = now + timedelta(minutes=5)
        db.commit()
        return {"processed": len(rows)}


def _scheduled_report(db, report_type: ReportType, session: str, title: str):
    items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
    for item in items:
        key = f"{report_type.value}:{session}:{item.ticker}"
        if db.scalar(select(Report.id).where(Report.idempotency_key == key)):
            continue
        results = search_ticker_news(item.ticker, title)
        evidence = "\n".join(f"[{i}] {r.title}\n{r.content}\n{r.url}" for i, r in enumerate(results, 1))
        evidence += _daily_archive_text(db, item.ticker, datetime.fromisoformat(session).date())
        _save_report(db, key, item.ticker, report_type, f"{item.ticker} {title}", evidence or "暂无相关新闻。", "medium", [{"title": r.title, "url": r.url} for r in results])


@celery_app.task(name="app.tasks.celery_app.scheduled_reports")
def scheduled_reports():
    now = datetime.now(UTC)
    status = market_status(now)
    if not status["session"]:
        return {"skipped": "not_session"}
    ny_hour = now.astimezone(__import__("zoneinfo").ZoneInfo(settings.market_timezone)).hour
    with SessionLocal() as db:
        if 7 <= ny_hour < 9:
            _scheduled_report(db, ReportType.premarket, status["session"], "盘前信息报告")
        elif 16 <= ny_hour < 19:
            _scheduled_report(db, ReportType.postmarket, status["session"], "盘后信息报告")
        db.commit()
    return {"session": status["session"]}


@celery_app.task(name="app.tasks.celery_app.sync_earnings")
def sync_earnings():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        events = fetch_earnings_events(tickers)
        now = datetime.now(UTC)
        inserted = refreshed = 0
        for ticker, event_time in events:
            existing = db.scalar(select(EarningsEvent).where(
                EarningsEvent.ticker == ticker,
                EarningsEvent.event_time == event_time,
            ))
            if existing is None:
                db.add(EarningsEvent(ticker=ticker, event_time=event_time, confidence="estimated"))
                inserted += 1
            else:
                existing.synced_at = now
                refreshed += 1
        db.commit()
        return {
            "fetched": len(events),
            "future_fetched": sum(event_time >= now for _, event_time in events),
            "inserted": inserted,
            "refreshed": refreshed,
        }


@celery_app.task(name="app.tasks.celery_app.sync_investment_calendar")
def sync_investment_calendar():
    with SessionLocal() as db:
        return sync_calendar(db)


@celery_app.task(name="app.tasks.celery_app.ensure_investment_calendar_fresh")
def ensure_investment_calendar_fresh():
    now = datetime.now(UTC)
    with SessionLocal() as db:
        running = db.scalar(select(InvestmentCalendarSyncRun).where(
            InvestmentCalendarSyncRun.status == "running",
        ).order_by(InvestmentCalendarSyncRun.started_at.desc()).limit(1))
        if running:
            started_at = running.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            if now - started_at < timedelta(hours=2):
                return {"skipped": "already_running", "run_id": running.id}
        latest = db.scalar(select(InvestmentCalendarSyncRun).where(
            InvestmentCalendarSyncRun.status.in_(("succeeded", "partial")),
            InvestmentCalendarSyncRun.successful_symbols > 0,
        ).order_by(InvestmentCalendarSyncRun.completed_at.desc()).limit(1))
        if latest and latest.completed_at:
            completed_at = latest.completed_at
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=UTC)
            if now - completed_at < timedelta(hours=10):
                return {"skipped": "fresh", "run_id": latest.id}
        return sync_calendar(db)


@celery_app.task(name="app.tasks.celery_app.sync_share_statistics")
def sync_share_statistics():
    with SessionLocal() as db:
        tickers = set(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        tickers.update(db.scalars(select(PortfolioPosition.symbol).where(PortfolioPosition.total_quantity > 0)).all())
        updated, failures = 0, []
        for ticker in sorted(tickers):
            try:
                refresh_share_statistics(db, ticker)
                db.commit()
                updated += 1
            except Exception as exc:
                db.rollback()
                failures.append({"symbol": ticker, "error": type(exc).__name__})
        return {"updated": updated, "failures": failures}


def _translation_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    return status_code is None or status_code == 408 or status_code == 429 or status_code >= 500


@celery_app.task(name="app.tasks.celery_app.translate_news_titles")
def translate_news_titles():
    if not settings.translation_api_key:
        return {"skipped": "translation_api_key_missing"}

    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = db.scalars(
            select(NewsItem)
            .where(
                or_(
                    NewsItem.title_translation_status == "pending",
                    (
                        NewsItem.title_translation_status == "failed"
                    )
                    & (NewsItem.title_translation_attempts < settings.translation_max_attempts)
                    & (
                        (NewsItem.title_translation_next_retry_at.is_(None))
                        | (NewsItem.title_translation_next_retry_at <= now)
                    ),
                    (
                        NewsItem.title_translation_status == "processing"
                    )
                    & (NewsItem.title_translation_next_retry_at <= now),
                )
            )
            .order_by(NewsItem.id)
            .limit(settings.translation_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        claimed = [(row.id, row.title, title_input_hash(row.title)) for row in rows]
        for row in rows:
            row.title_translation_status = "processing"
            row.title_translation_attempts += 1
            row.title_translation_next_retry_at = now + timedelta(minutes=5)
        db.commit()

    translated = 0
    failed = 0
    for item_id, title, input_hash in claimed:
        try:
            value, model = translate_title(title)
        except Exception as error:
            with SessionLocal() as db:
                item = db.get(NewsItem, item_id)
                if item and item.title == title:
                    retryable = _translation_retryable(error)
                    exhausted = item.title_translation_attempts >= settings.translation_max_attempts
                    item.title_translation_status = "failed"
                    item.title_translation_last_error = str(error)[:1000]
                    item.title_translation_next_retry_at = (
                        now + timedelta(minutes=2 ** item.title_translation_attempts)
                        if retryable and not exhausted
                        else None
                    )
                    db.commit()
            failed += 1
            continue

        with SessionLocal() as db:
            item = db.get(NewsItem, item_id)
            if not item or item.title != title:
                continue
            item.translated_title = value
            item.title_translation_model = model
            item.title_translation_input_hash = input_hash
            item.title_translated_at = datetime.now(UTC)
            item.title_translation_status = "completed" if model else "skipped"
            item.title_translation_last_error = None
            item.title_translation_next_retry_at = None
            db.commit()
            translated += 1
    return {"claimed": len(claimed), "translated": translated, "failed": failed}


@celery_app.task(name="app.tasks.celery_app.summarize_sec_events")
def summarize_sec_events():
    """对已入库的 8-K/6-K 事件正文做 Haiku 中文翻译+总结（默认队列，纯 API 调用）。"""
    if not settings.translation_api_key:
        return {"skipped": "translation_api_key_missing"}

    from app.services.sec_extract import summarize_sec_event

    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = db.scalars(
            select(SecEvent)
            .where(
                SecEvent.text.isnot(None),
                SecEvent.text != "",
                or_(
                    SecEvent.summary_status == "pending",
                    (SecEvent.summary_status == "failed")
                    & (SecEvent.summary_attempts < settings.translation_max_attempts)
                    & (
                        (SecEvent.summary_next_retry_at.is_(None))
                        | (SecEvent.summary_next_retry_at <= now)
                    ),
                    (SecEvent.summary_status == "processing")
                    & (SecEvent.summary_next_retry_at <= now),
                ),
            )
            .order_by(SecEvent.id)
            .limit(settings.translation_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        claimed = [(r.id, r.item_label, r.form, r.text) for r in rows]
        for row in rows:
            row.summary_status = "processing"
            row.summary_attempts += 1
            row.summary_next_retry_at = now + timedelta(minutes=5)
        db.commit()

    summarized = 0
    failed = 0
    for event_id, item_label, form, text in claimed:
        input_hash = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        try:
            value, model = summarize_sec_event(item_label, form, text)
        except Exception as error:
            with SessionLocal() as db:
                item = db.get(SecEvent, event_id)
                if item and item.text == text:
                    retryable = _translation_retryable(error)
                    exhausted = item.summary_attempts >= settings.translation_max_attempts
                    item.summary_status = "failed"
                    item.summary_last_error = str(error)[:1000]
                    item.summary_next_retry_at = (
                        now + timedelta(minutes=2 ** item.summary_attempts)
                        if retryable and not exhausted
                        else None
                    )
                    db.commit()
            failed += 1
            continue

        with SessionLocal() as db:
            item = db.get(SecEvent, event_id)
            if not item or item.text != text:
                continue
            item.summary_zh = value or None
            item.summary_model = model
            item.summary_input_hash = input_hash
            item.summary_status = "completed" if model else "skipped"
            item.summary_last_error = None
            item.summary_next_retry_at = None
            db.commit()
            summarized += 1
    return {"claimed": len(claimed), "summarized": summarized, "failed": failed}


@celery_app.task(name="app.tasks.celery_app.poll_news")
def poll_news(ticker: str | None = None):
    market_date = market_status()["checked_at"][:10]
    parsed = datetime.fromisoformat(market_date).date()
    with SessionLocal() as db:
        items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
        # A manually requested ticker is intentionally not promoted into the watchlist.
        if ticker:
            items = [item for item in items if item.ticker == ticker] or [type("SnapshotTicker", (), {"ticker": ticker.upper()})()]
        total = 0
        now = datetime.now(UTC)
        marketaux_items: dict[str, list] = {}
        # Manual single-ticker refreshes retain their old behavior and do not
        # consume a batch request. Scheduled full polls fetch exactly one batch.
        if ticker is None:
            try:
                marketaux_items = fetch_marketaux_news(
                    db,
                    [item.ticker for item in items],
                    now=now,
                ).items_by_ticker
            except Exception as exc:
                db.rollback()
                logger.error("Marketaux scheduler integration failed: %s", type(exc).__name__)
        for item in items:
            dtos = collect_ticker_news(item.ticker, finnhub_symbol=provider_symbol(db, item.ticker, "finnhub")) + marketaux_items.get(item.ticker.upper(), [])
            final, stats = prepare_news(dtos, scope="company", now=now, limit=NEWS_PER_TICKER)
            if not final:
                continue
            saved = persist_news(db, item.ticker, parsed, final, [(dto.importance_score, None) for dto in final])
            logger.info("news provider/company ticker=%s fetched=%d accepted=%d filtered=%d clustered=%d inserted=%d", item.ticker, stats["fetched"], stats["accepted"], stats["filtered"], stats["clustered"], len(saved))
            total += len(saved)
        db.commit()
        if total:
            translate_news_titles.delay()
        return {"tickers": len(items), "new": total}


@celery_app.task(name="app.tasks.celery_app.poll_market_news")
def poll_market_news():
    if not settings.market_news_enabled:
        return {"skipped": "disabled"}
    now = datetime.now(UTC); inputs = []
    with SessionLocal() as db:
        if settings.finnhub_market_news_enabled:
            try: inputs.extend(fetch_market_news())
            except Exception as exc: logger.warning("Finnhub market collection failed: %s", type(exc).__name__)
        if settings.marketaux_market_news_enabled:
            try: inputs.extend(fetch_marketaux_market_news(db, now=now))
            except Exception as exc: db.rollback(); logger.warning("Marketaux market collection failed: %s", type(exc).__name__)
        final, stats = prepare_news(inputs, scope="market", now=now, limit=settings.market_news_max_items)
        saved = persist_news(db, MARKET_TICKER, now.date(), final, [(dto.importance_score, None) for dto in final])
        db.commit()
        if saved: translate_news_titles.delay()
        logger.info("news provider=combined scope=market fetched=%d accepted=%d filtered=%d clustered=%d inserted=%d", stats["fetched"], stats["accepted"], stats["filtered"], stats["clustered"], len(saved))
        return {**stats, "inserted": len(saved)}


def _daily_input_hash(news: list[NewsItem]) -> str:
    basis = "|".join(sorted(item.fingerprint for item in news))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]


@celery_app.task(name="app.tasks.celery_app.curate_daily_archives")
def curate_daily_archives():
    market_date = market_status()["checked_at"][:10]
    parsed = datetime.fromisoformat(market_date).date()
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        curated = 0
        for ticker in tickers:
            news = news_for_day(db, ticker, parsed)
            if not news:
                continue
            input_hash = _daily_input_hash(news)
            existing = db.scalar(
                select(DailyNewsArchive).where(DailyNewsArchive.ticker == ticker, DailyNewsArchive.market_date == parsed)
            )
            if existing and existing.input_hash == input_hash:
                continue
            evidence = "\n".join(
                f"[{i}] ({item.provider}) {item.title}\n{item.summary or item.raw_content or ''}\n{item.url}"
                for i, item in enumerate(news, 1)
            )
            content, model = curate_daily_news(ticker, market_date, evidence)
            included = [item.id for item in news]
            manifest = {"ticker": ticker, "market_date": market_date, "model": model, "input_hash": input_hash, "news_ids": included}
            file_path = archive.write_daily_archive(ticker, parsed, content, manifest)
            if existing:
                existing.content = content
                existing.included_news_ids = included
                existing.model = model
                existing.input_hash = input_hash
                existing.version += 1
                existing.file_path = file_path
            else:
                db.add(
                    DailyNewsArchive(
                        ticker=ticker, market_date=parsed, content=content, included_news_ids=included,
                        excluded_news_ids=[], model=model, input_hash=input_hash, version=1, file_path=file_path,
                    )
                )
            curated += 1
        db.commit()
        return {"curated": curated}


def _iso_week_bounds(d) -> tuple[int, int, "date", "date"]:
    """返回 (iso_year, iso_week, 周一, 周日)。"""
    iso_year, iso_week, iso_weekday = d.isocalendar()
    monday = d - timedelta(days=iso_weekday - 1)
    return iso_year, iso_week, monday, monday + timedelta(days=6)


def _weekly_input_hash(archives: list[DailyNewsArchive]) -> str:
    basis = "|".join(f"{a.market_date.isoformat()}:{a.input_hash}" for a in sorted(archives, key=lambda x: x.market_date))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]


@celery_app.task(name="app.tasks.celery_app.rollup_weekly_archives")
def rollup_weekly_archives():
    """把已结束的完整 ISO 周（周一起）合并成周报，随后删除当周的原始新闻与每日定档。

    - 只处理周一严格早于“本周周一”的完整周，绝不动本周数据。
    - 逐 ticker 逐周：合并当周每日定档的关键事实 → 落库 WeeklyNewsArchive → 删除当周 NewsItem + DailyNewsArchive。
    - 整周删除（非滚动）；缺失一次调度也能在下次自愈。
    """
    from datetime import time

    market_date = market_status()["checked_at"][:10]
    today = datetime.fromisoformat(market_date).date()
    _, _, current_monday, _ = _iso_week_bounds(today)

    rolled, deleted_news, deleted_daily = 0, 0, 0
    with SessionLocal() as db:
        # 过去完整周里仍存在每日定档的行，按 ticker 分组
        past = db.scalars(
            select(DailyNewsArchive).where(DailyNewsArchive.market_date < current_monday)
        ).all()
        groups: dict[tuple[str, int, int], list[DailyNewsArchive]] = {}
        for row in past:
            iso_year, iso_week, _, _ = _iso_week_bounds(row.market_date)
            groups.setdefault((row.ticker, iso_year, iso_week), []).append(row)

        for (ticker, iso_year, iso_week), archives in groups.items():
            _, _, week_start, week_end = _iso_week_bounds(archives[0].market_date)
            week_label = f"{week_start.isoformat()} ~ {week_end.isoformat()}"
            input_hash = _weekly_input_hash(archives)
            existing = db.scalar(
                select(WeeklyNewsArchive).where(
                    WeeklyNewsArchive.ticker == ticker,
                    WeeklyNewsArchive.iso_year == iso_year,
                    WeeklyNewsArchive.iso_week == iso_week,
                )
            )
            if existing and existing.input_hash == input_hash:
                content, model = existing.content, existing.model
            else:
                evidence = "\n\n".join(
                    f"—— {a.market_date.isoformat()} ——\n{a.content}"
                    for a in sorted(archives, key=lambda x: x.market_date)
                )
                content, model = curate_weekly_news(ticker, week_label, evidence)
            included_dates = [a.market_date.isoformat() for a in sorted(archives, key=lambda x: x.market_date)]
            manifest = {
                "ticker": ticker, "iso_year": iso_year, "iso_week": iso_week,
                "week": week_label, "model": model, "input_hash": input_hash, "dates": included_dates,
            }
            file_path = archive.write_weekly_archive(ticker, iso_year, iso_week, content, manifest)
            if existing:
                existing.content = content
                existing.included_dates = included_dates
                existing.model = model
                existing.input_hash = input_hash
                existing.week_start = week_start
                existing.week_end = week_end
                existing.version += 1
                existing.file_path = file_path
            else:
                db.add(
                    WeeklyNewsArchive(
                        ticker=ticker, iso_year=iso_year, iso_week=iso_week,
                        week_start=week_start, week_end=week_end, content=content,
                        included_dates=included_dates, model=model, input_hash=input_hash,
                        version=1, file_path=file_path,
                    )
                )
            rolled += 1

        db.flush()
        # 删除过去完整周的每日定档
        deleted_daily = db.execute(
            delete(DailyNewsArchive).where(DailyNewsArchive.market_date < current_monday)
        ).rowcount or 0
        # 删除过去完整周的原始新闻（整周删除；本周之前的调查早已完成，报告来源已固化到 Report.sources）
        cutoff = datetime.combine(current_monday, time.min, tzinfo=UTC)
        deleted_news = db.execute(
            delete(NewsItem).where(NewsItem.found_at < cutoff)
        ).rowcount or 0
        db.commit()
    return {"rolled": rolled, "deleted_daily": deleted_daily, "deleted_news": deleted_news}


def _sync_ticker_financials(db, ticker: str) -> bool:
    """同步单只财报到 DB + 归档。成功返回 True，无数据/异常返回 False。"""
    try:
        rows = fetch_yf_quarterly(ticker)
        statement_rows = [
            (frequency, item)
            for frequency in ("annual", "quarterly")
            for item in fetch_yf_financial_statements(ticker, frequency)
        ]
    except Exception:
        return False
    quarters = quarters_from_yf(rows)
    if not quarters and not statement_rows:
        return False
    synced_at = datetime.now(UTC)
    for quarter in quarters:
        row = db.scalar(
            select(QuarterlyFinancial).where(
                QuarterlyFinancial.ticker == ticker,
                QuarterlyFinancial.fiscal_year == quarter.fiscal_year,
                QuarterlyFinancial.fiscal_period == quarter.fiscal_period,
            )
        )
        if not row:
            row = QuarterlyFinancial(ticker=ticker, fiscal_year=quarter.fiscal_year, fiscal_period=quarter.fiscal_period)
            db.add(row)
        row.period_end = quarter.period_end
        row.filed_at = quarter.filed_at
        row.currency = quarter.currency
        row.revenue = quarter.revenue
        row.eps = quarter.eps
        row.net_income = quarter.net_income
        row.operating_income = quarter.operating_income
        row.gross_margin = quarter.gross_margin
        row.net_margin = quarter.net_margin
        row.operating_cash_flow = quarter.operating_cash_flow
        row.free_cash_flow = quarter.free_cash_flow
        row.raw_payload = quarter.raw_payload
        row.synced_at = synced_at
        archive.write_quarter(ticker, quarter.label, quarter.raw_payload)
    for frequency, item in statement_rows:
        snapshot = db.scalar(select(FinancialStatementSnapshot).where(
            FinancialStatementSnapshot.ticker == ticker,
            FinancialStatementSnapshot.frequency == frequency,
            FinancialStatementSnapshot.period_end == item["period_end"],
        ))
        if not snapshot:
            snapshot = FinancialStatementSnapshot(ticker=ticker, frequency=frequency, period_end=item["period_end"], fiscal_year=item["fiscal_year"], fiscal_period=item["fiscal_period"])
            db.add(snapshot)
        snapshot.fiscal_year = item["fiscal_year"]
        snapshot.fiscal_period = item["fiscal_period"]
        snapshot.currency = item["currency"]
        snapshot.income_statement = item["income_statement"]
        snapshot.balance_sheet = item["balance_sheet"]
        snapshot.cash_flow = item["cash_flow"]
        snapshot.synced_at = synced_at
    if quarters:
        keep_labels = [q.label for q in quarters]
        keep_pairs = {(q.fiscal_year, q.fiscal_period) for q in quarters}
        for row in db.scalars(select(QuarterlyFinancial).where(QuarterlyFinancial.ticker == ticker)).all():
            if (row.fiscal_year, row.fiscal_period) not in keep_pairs:
                db.delete(row)
        archive.prune_quarters(ticker, keep_labels)
    return True


@celery_app.task(name="app.tasks.celery_app.sync_financials")
def sync_financials():
    with SessionLocal() as db:
        tickers = valuation_tickers(db)
        synced = 0
        # 单只提交：外部源变慢或个别代码失败时，已完成的三表仍可立即被估值与前端使用。
        for ticker in tickers:
            if _sync_ticker_financials(db, ticker):
                synced += 1
            db.commit()
        return {"synced": synced}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_financials")
def sync_ticker_financials(ticker: str):
    with SessionLocal() as db:
        ok = _sync_ticker_financials(db, ticker)
        db.commit()
        return {"ticker": ticker, "synced": ok}


def _sync_ticker_valuation(db, ticker: str, explain: bool = True) -> bool:
    """抓取分类、Finnhub 同行与 Yahoo 原料，计算后按日 upsert；Luna 仅解释。"""
    finnhub_ticker = provider_symbol(db, ticker, "finnhub")
    try:
        official_peers = fetch_company_peers(finnhub_ticker) if finnhub_ticker else []
    except Exception:
        official_peers = []
    # Finnhub 免费额度经常临时返回空/限流；此时回退到最近一份仍有官方同行的快照，
    # 避免把已有官方同行整批清空（今日快照可能已被清空，故需跳过空结果向前找）。
    if not official_peers:
        recent = db.scalars(select(ValuationSnapshot).where(ValuationSnapshot.ticker == ticker).order_by(ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc()).limit(5)).all()
        for snap in recent:
            cached = list((snap.payload.get("peers") or {}).get("official_symbols") or [])
            if cached:
                official_peers = cached
                break
    is_watched = bool(db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == ticker, WatchlistItem.enabled.is_(True))))
    # 仅在确有官方结果时刷新官方关系缓存，空结果不落库以免误禁用。
    if is_watched and official_peers:
        cache_official_relations(db, ticker, official_peers)
    peers = effective_peer_symbols(db, ticker, official_peers)
    statement_rows = db.scalars(select(FinancialStatementSnapshot).where(
        FinancialStatementSnapshot.ticker == ticker,
        FinancialStatementSnapshot.frequency == "annual",
    ).order_by(FinancialStatementSnapshot.period_end.desc()).limit(4)).all()
    stored_financials = None
    if statement_rows:
        periods = []
        for row in statement_rows:
            balance = dict(row.balance_sheet or {})
            # 估值模块沿用历史命名；快照 API 使用更易读的 shareholders_equity。
            balance["stockholders_equity"] = balance.pop("shareholders_equity", None)
            periods.append({"date": row.period_end.isoformat(), **(row.income_statement or {}), **balance, **(row.cash_flow or {})})
        stored_financials = {"source": "financial_statement_snapshots", "periods": periods}
    info, peer_infos, financials = fetch_cross_model_inputs(ticker, peers, financials=stored_financials)
    if not info:
        return False
    upsert_profile(db, ticker, info)
    for peer_info in peer_infos:
        symbol = peer_info.get("_peerTicker") or peer_info.get("symbol")
        if symbol:
            upsert_profile(db, symbol, peer_info)
    quarterly_statement_rows = db.scalars(select(FinancialStatementSnapshot).where(
        FinancialStatementSnapshot.ticker == ticker,
        FinancialStatementSnapshot.frequency == "quarterly",
    ).order_by(FinancialStatementSnapshot.period_end.desc()).limit(4)).all()
    quarter_inputs = [{
        "period_end": row.period_end.isoformat(), "eps": (row.income_statement or {}).get("eps"),
        "net_income": (row.income_statement or {}).get("net_income"), "revenue": (row.income_statement or {}).get("revenue"),
        "free_cash_flow": (row.cash_flow or {}).get("free_cash_flow"),
    } for row in quarterly_statement_rows]
    if not quarter_inputs:  # 兼容首次同步尚未生成三表快照的旧数据。
        quarters = db.scalars(
            select(QuarterlyFinancial).where(QuarterlyFinancial.ticker == ticker)
            .order_by(QuarterlyFinancial.period_end.desc()).limit(4)
        ).all()
        quarter_inputs = [
            {"period_end": row.period_end.isoformat(), "eps": row.eps, "net_income": row.net_income,
             "revenue": row.revenue, "free_cash_flow": row.free_cash_flow}
            for row in quarters
        ]
    latest_quote = get_latest_persisted_price_snapshot(db, ticker)
    quote_input = ({"price": latest_quote.last_price, "source": latest_quote.provider,
                    "as_of": (latest_quote.market_timestamp or latest_quote.fetched_at).isoformat()
                    if latest_quote.market_timestamp or latest_quote.fetched_at else None} if latest_quote else None)
    try:
        finnhub_metrics = fetch_basic_metrics(finnhub_ticker) if finnhub_ticker else {}
    except Exception as exc:
        logger.warning("%s Finnhub Graham 基本面获取失败: %s", ticker, exc)
        finnhub_metrics = {}
    aaa_yield = get_latest_aaa_corporate_bond_yield()
    graham = build_graham_from_sources(
        ticker, info, finnhub_metrics, quarter_inputs, financials, quote_input, aaa_yield,
    )
    payload = build_cross_model(
        ticker, info,
        quarter_inputs, peer_infos, peers, financials, graham,
    )
    payload["peers"]["official_symbols"] = official_peers
    payload["peers"]["source"] = "Finnhub official + manual overrides"
    ai_model = None
    opinion = payload["ai_opinion"]
    if explain:
        try:
            opinion, ai_model = explain_cross_model(opinion_evidence(payload))
            payload["ai_opinion"] = opinion
            payload["ai_model"] = ai_model
        except Exception:
            pass
    today = datetime.now(UTC).date()
    row = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == ticker, ValuationSnapshot.snapshot_date == today))
    if not row:
        row = ValuationSnapshot(ticker=ticker, snapshot_date=today)
        db.add(row)
    row.payload = payload
    row.ai_opinion = opinion
    row.ai_model = ai_model
    row.source_version = "cross-model-v5"
    return True


@celery_app.task(name="app.tasks.celery_app.sync_valuations")
def sync_valuations():
    with SessionLocal() as db:
        tickers = valuation_tickers(db)
        watched = set(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        synced = sum(1 for ticker in tickers if _sync_ticker_valuation(db, ticker, explain=ticker in watched))
        db.commit()
        return {"synced": synced}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_valuation")
def sync_ticker_valuation(ticker: str):
    with SessionLocal() as db:
        value = ticker.upper()
        watched = bool(db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == value, WatchlistItem.enabled.is_(True))))
        ok = _sync_ticker_valuation(db, value, explain=watched)
        db.commit()
        return {"ticker": value, "synced": ok}


@celery_app.task(name="app.tasks.celery_app.sync_peer_valuation_data")
def sync_peer_valuation_data(ticker: str):
    """匹配股票最小同步：报价、财务、基础资料与估值；不触发新闻/SEC/Insider。"""
    value = ticker.upper()
    with SessionLocal() as db:
        financials_ok = _sync_ticker_financials(db, value)
        quotes = 0
        try:
            _, created = persist_price_snapshot(db, collect_price_snapshot(db, value))
            quotes = int(created)
        except Exception:
            logger.warning("peer_price_snapshot_sync_failed symbol=%s", value, exc_info=True)
        valuation_ok = _sync_ticker_valuation(db, value, explain=False)
        db.commit()
        return {"ticker": value, "financials": financials_ok, "valuation": valuation_ok, "quotes": quotes}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_price_snapshot")
def sync_ticker_price_snapshot(ticker: str):
    """Explicit refresh action; readers never call an upstream quote provider."""
    value = ticker.upper()
    with SessionLocal() as db:
        snapshot, created = persist_price_snapshot(
            db, collect_price_snapshot(db, value)
        )
        db.commit()
        return {
            "ticker": value,
            "snapshot_id": snapshot.id,
            "provider": snapshot.provider,
            "created": created,
        }


@celery_app.task(name="app.tasks.celery_app.sync_ticker_full")
def sync_ticker_full(ticker: str):
    """自选股初始化入口；保持现有各同步任务独立与幂等。"""
    value = ticker.upper()
    sync_ticker_financials.delay(value)
    sync_ticker_filings.delay(value)
    sync_ticker_sec_all.delay(value)
    sync_ticker_congress.delay(value)
    sync_ticker_valuation.delay(value)
    sync_ticker_price_snapshot.delay(value)
    poll_news.delay(value)
    sync_fmp_symbol.delay(value)  # FMP 优先，其失败时内部回退 yahoo，并生成技术分析
    return {"ticker": value, "status": "queued_full_sync"}


def _fmp_symbols(db):
    return list(
        db.scalars(
            select(WatchlistItem.ticker)
            .where(WatchlistItem.enabled.is_(True))
            .order_by(WatchlistItem.created_at, WatchlistItem.ticker)
        ).all()
    )


def _run_fmp_symbol(db, symbol: str, position: int = 0, *, profile: bool = True, history: bool = True):
    now = datetime.now(UTC)
    result = {"symbol": symbol}
    if profile and settings.fmp_profile_sync_enabled:
        try:
            result["profile"] = sync_fmp_profile_service(db, symbol)
            checkpoint(
                db, "profiles", symbol, "profile",
                status="completed" if result["profile"]["status"] == "completed" else "empty",
                now=now, position=position,
            )
        except FmpQuotaExhausted as exc:
            checkpoint(db, "profiles", symbol, "profile", status="pending", now=now, error=exc, position=position)
            raise
        except FmpError as exc:
            checkpoint(db, "profiles", symbol, "profile", status="failed", now=now, error=exc, position=position)
            if isinstance(exc, FmpAuthenticationError):
                raise
    if history and settings.fmp_price_sync_enabled:
        try:
            synced = sync_fmp_history_service(db, symbol)
            result["history"] = synced
            checkpoint(
                db, "history", symbol, "price", status="completed", now=now,
                successful_date=synced["latest"], position=position,
            )
            if synced["changed"]:
                result["analysis"] = generate_for_symbol(db, symbol)
        except FmpQuotaExhausted as exc:
            checkpoint(db, "history", symbol, "price", status="pending", now=now, error=exc, position=position)
            raise
        except (FmpPremiumRequired, FmpInvalidSymbol) as exc:
            # FMP 套餐不覆盖该标的（402）或代码无效（404）：回退 yfinance 免费日线源。
            checkpoint(db, "history", symbol, "price", status="failed", now=now, error=exc, position=position)
            try:
                result["history"] = sync_fallback_history(db, symbol, today=now.date())
                result["history_source"] = "yahoo"
            except Exception:
                logger.exception("[technical-analysis] yahoo fallback failed symbol=%s", symbol)
        except FmpError as exc:
            checkpoint(db, "history", symbol, "price", status="failed", now=now, error=exc, position=position)
            if isinstance(exc, FmpAuthenticationError):
                raise
    return result


@celery_app.task(name="app.tasks.celery_app.sync_fmp_symbol")
def sync_fmp_symbol(symbol: str):
    if not settings.fmp_sync_enabled:
        return {"skipped": "disabled"}
    with SessionLocal() as db:
        try:
            return _run_fmp_symbol(db, symbol.upper())
        except FmpQuotaExhausted:
            return {"symbol": symbol.upper(), "status": "pending_quota"}


@celery_app.task(name="app.tasks.celery_app.sync_fmp_history")
def sync_fmp_history():
    if not settings.fmp_sync_enabled or not settings.fmp_price_sync_enabled:
        return {"skipped": "disabled"}
    with SessionLocal() as db:
        completed = 0
        symbols = _fmp_symbols(db)
        queue = db.scalar(
            select(FmpSyncState).where(
                FmpSyncState.task_name == "history_queue",
                FmpSyncState.symbol == "*",
                FmpSyncState.sync_type == "queue",
            )
        )
        start = min(queue.cursor_position if queue else 0, len(symbols))
        for position in range(start, len(symbols)):
            symbol = symbols[position]
            try:
                _run_fmp_symbol(db, symbol, position, profile=False)
                completed += 1
                checkpoint(
                    db, "history_queue", "*", "queue", status="completed",
                    now=datetime.now(UTC), position=position + 1,
                )
            except FmpQuotaExhausted:
                checkpoint(
                    db, "history_queue", "*", "queue", status="pending",
                    now=datetime.now(UTC), position=position,
                )
                return {"completed": completed, "status": "quota_exhausted", "next": symbol}
        checkpoint(
            db, "history_queue", "*", "queue", status="completed",
            now=datetime.now(UTC), position=0,
        )
        return {"completed": completed}


@celery_app.task(name="app.tasks.celery_app.sync_fmp_profiles")
def sync_fmp_profiles():
    if not settings.fmp_sync_enabled or not settings.fmp_profile_sync_enabled:
        return {"skipped": "disabled"}
    cutoff = datetime.now(UTC) - timedelta(days=settings.fmp_profile_refresh_days)
    with SessionLocal() as db:
        completed = 0
        for position, symbol in enumerate(_fmp_symbols(db)):
            profile = db.get(CompanyProfile, symbol)
            if profile and profile.profile_fetched_at and profile.profile_fetched_at >= cutoff and profile.description_en:
                continue
            try:
                _run_fmp_symbol(db, symbol, position, history=False)
                completed += 1
            except FmpQuotaExhausted:
                return {"completed": completed, "status": "quota_exhausted", "next": symbol}
        return {"completed": completed}


@celery_app.task(name="app.tasks.celery_app.translate_fmp_profiles")
def translate_fmp_profiles():
    if not settings.fmp_translation_enabled:
        return {"skipped": "disabled"}
    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(CompanyProfile)
                .where(
                    CompanyProfile.translation_status.in_(["pending", "failed"]),
                    CompanyProfile.description_en.is_not(None),
                    or_(CompanyProfile.translation_next_retry_at.is_(None), CompanyProfile.translation_next_retry_at <= now),
                )
                .order_by(CompanyProfile.updated_at)
                .limit(10)
            ).all()
        )
        completed = 0
        for row in rows:
            try:
                row.description_zh, row.translation_model = translate_description(row.description_en or "")
                row.translation_status = "completed"
                row.translation_updated_at = now
                row.translation_last_error = None
                completed += 1
                logger.info("[FMP] profile translation completed symbol=%s", row.symbol)
            except Exception as exc:
                row.translation_attempts += 1
                row.translation_status = "failed"
                row.translation_last_error = type(exc).__name__
                row.translation_next_retry_at = now + timedelta(minutes=min(360, 2 ** row.translation_attempts))
                logger.warning("[FMP] profile translation failed symbol=%s error=%s", row.symbol, type(exc).__name__)
            db.commit()
        return {"completed": completed, "attempted": len(rows)}


@celery_app.task(name="app.tasks.celery_app.generate_technical_analysis")
def generate_technical_analysis(symbol: str, force: bool = False):
    with SessionLocal() as db:
        return generate_for_symbol(db, symbol.upper(), force=force)


@celery_app.task(name="app.tasks.celery_app.sync_technical_analysis")
def sync_technical_analysis(symbol: str):
    """单只技术分析同步：FMP 优先，其数据无法覆盖时回退 yfinance，随后强制重算。

    供自选股初始化与管理端 regenerate 使用。FMP 已禁用/无 key 时直接走 yahoo 回退。
    """
    value = symbol.upper()
    with SessionLocal() as db:
        if settings.fmp_sync_enabled and settings.fmp_api_key.strip():
            try:
                _run_fmp_symbol(db, value, profile=False)
            except FmpQuotaExhausted:
                return {"symbol": value, "status": "pending_quota"}
            except FmpError:
                logger.exception("[technical-analysis] fmp sync failed symbol=%s", value)
        # 若上面 FMP 成功写入了 fmp 源、或回退写入了 yahoo 源，force 重算确保出图。
        analysis = generate_for_symbol(db, value, force=True)
        if analysis.get("status") == "pending":
            # FMP 完全不可用且尚无任何历史：直接尝试 yahoo 回退。
            try:
                return sync_fallback_history(db, value)
            except Exception:
                logger.exception("[technical-analysis] yahoo fallback failed symbol=%s", value)
        return {"symbol": value, "analysis": analysis}


def _sync_ticker_filings(db, ticker: str) -> int:
    """同步单只 SEC filing 到 DB（按 accession 去重 upsert）。返回新增/更新条数。"""
    try:
        filings = fetch_filings(ticker)
    except Exception:
        return 0
    changed = 0
    for dto in filings:
        if not dto.accession_number:
            continue
        row = db.scalar(
            select(SecFiling).where(
                SecFiling.ticker == dto.ticker,
                SecFiling.accession_number == dto.accession_number,
            )
        )
        if not row:
            row = SecFiling(ticker=dto.ticker, accession_number=dto.accession_number)
            db.add(row)
        row.cik = dto.cik
        row.form = dto.form
        row.form_label = dto.form_label
        row.items = dto.items
        row.event_labels = dto.event_labels
        row.priority = dto.priority
        row.filing_date = dto.filing_date
        row.report_date = dto.report_date
        row.primary_document = dto.primary_document
        row.filing_url = dto.filing_url
        row.raw_payload = dto.raw_payload
        changed += 1
    return changed


@celery_app.task(name="app.tasks.celery_app.sync_sec_filings")
def sync_sec_filings():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        total = sum(_sync_ticker_filings(db, ticker) for ticker in tickers)
        db.commit()
        return {"tickers": len(tickers), "filings": total}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_filings")
def sync_ticker_filings(ticker: str):
    with SessionLocal() as db:
        changed = _sync_ticker_filings(db, ticker)
        db.commit()
        return {"ticker": ticker, "filings": changed}


# ---------------------------------------------------------------- SEC edgartools 深挖抽取
# 以下任务经 edgartools 解析 XBRL/正文，内存开销大，统一路由到 sec_heavy 队列
# （独立 --concurrency=1 worker），保证永不并发解析，规避 2.9G VPS 的 OOM。

_SEC_EVENT_FORMS = ("8-K", "6-K")


def _recent_accessions(db, ticker: str, forms: tuple[str, ...], limit: int = 15):
    """从 sec_filings 索引取某 ticker 指定 form 的近期 filing。"""
    rows = db.scalars(
        select(SecFiling)
        .where(SecFiling.ticker == ticker, SecFiling.form.in_(forms))
        .order_by(SecFiling.filing_date.desc(), SecFiling.id.desc())
        .limit(limit)
    ).all()
    return rows


def _sync_ticker_sec_events(db, ticker: str) -> int:
    from app.services.sec_extract import extract_events

    filings = _recent_accessions(db, ticker, _SEC_EVENT_FORMS)
    if not filings:
        return 0
    cik = filings[0].cik
    rows = [(f.accession_number, f.form, f.filing_date, f.filing_url) for f in filings]
    try:
        events = extract_events(ticker, cik, rows)
    except Exception:
        return 0
    changed = 0
    for dto in events:
        row = db.scalar(
            select(SecEvent).where(
                SecEvent.accession_number == dto.accession_number,
                SecEvent.item_code == dto.item_code,
            )
        )
        if not row:
            row = SecEvent(accession_number=dto.accession_number, item_code=dto.item_code)
            db.add(row)
        row.ticker = dto.ticker
        row.cik = dto.cik
        row.form = dto.form
        row.item_label = dto.item_label
        row.priority = dto.priority
        if row.text != dto.text:
            # 正文变化才重置总结状态，避免每次重扫都重新翻译
            row.text = dto.text
            row.summary_status = "pending"
            row.summary_next_retry_at = None
            row.summary_attempts = 0
        row.filing_date = dto.filing_date
        row.filing_url = dto.filing_url
        changed += 1
    return changed


def _sync_ticker_sec_insider(db, ticker: str) -> int:
    from app.services.sec_extract import extract_insider

    filings = _recent_accessions(db, ticker, ("4",), limit=20)
    if not filings:
        return 0
    cik = filings[0].cik
    rows = [(f.accession_number, f.filing_url) for f in filings]
    try:
        trades = extract_insider(ticker, cik, rows)
    except Exception:
        return 0
    changed = 0
    for dto in trades:
        row = db.scalar(
            select(SecInsiderTrade).where(
                SecInsiderTrade.accession_number == dto.accession_number,
                SecInsiderTrade.insider_name == dto.insider_name,
                SecInsiderTrade.transaction_date == dto.transaction_date,
                SecInsiderTrade.transaction_code == dto.transaction_code,
                SecInsiderTrade.shares == dto.shares,
            )
        )
        if not row:
            row = SecInsiderTrade(
                accession_number=dto.accession_number, insider_name=dto.insider_name,
                transaction_date=dto.transaction_date, transaction_code=dto.transaction_code,
                shares=dto.shares,
            )
            db.add(row)
        row.ticker = dto.ticker
        row.cik = dto.cik
        row.insider_title = dto.insider_title
        row.price = dto.price
        row.value = dto.value
        row.shares_owned_after = dto.shares_owned_after
        row.flag = dto.flag
        row.filing_url = dto.filing_url
        changed += 1
    return changed


def _sync_ticker_sec_financials(db, ticker: str) -> int:
    """XBRL 解析昂贵：仅当出现未入库的新 10-K/10-Q 时才解析。"""
    from app.services.sec_extract import extract_financials

    latest = db.scalar(
        select(SecFiling)
        .where(SecFiling.ticker == ticker, SecFiling.form.in_(("10-K", "10-Q", "20-F")))
        .order_by(SecFiling.filing_date.desc(), SecFiling.id.desc())
        .limit(1)
    )
    if latest is None:
        return 0
    already = db.scalar(
        select(SecFinancialPeriod.id).where(
            SecFinancialPeriod.ticker == ticker,
            SecFinancialPeriod.accession_number == latest.accession_number,
        )
    )
    if already:
        return 0  # 无新财报，跳过昂贵解析
    try:
        periods = extract_financials(ticker, form=latest.form)
    except Exception:
        return 0
    changed = 0
    for dto in periods:
        row = db.scalar(
            select(SecFinancialPeriod).where(
                SecFinancialPeriod.ticker == dto.ticker,
                SecFinancialPeriod.fiscal_year == dto.fiscal_year,
                SecFinancialPeriod.fiscal_period == dto.fiscal_period,
                SecFinancialPeriod.form == dto.form,
            )
        )
        if not row:
            row = SecFinancialPeriod(
                ticker=dto.ticker, fiscal_year=dto.fiscal_year,
                fiscal_period=dto.fiscal_period, form=dto.form,
            )
            db.add(row)
        row.period_end = dto.period_end
        row.filed_at = dto.filed_at
        row.accession_number = latest.accession_number
        row.revenue = dto.revenue
        row.net_income = dto.net_income
        row.operating_income = dto.operating_income
        row.gross_profit = dto.gross_profit
        row.eps_basic = dto.eps_basic
        row.eps_diluted = dto.eps_diluted
        row.cash_and_equivalents = dto.cash_and_equivalents
        row.total_debt = dto.total_debt
        row.shares_outstanding = dto.shares_outstanding
        row.operating_cash_flow = dto.operating_cash_flow
        row.currency = dto.currency
        row.raw_payload = dto.raw_payload
        changed += 1
    return changed


@celery_app.task(name="app.tasks.celery_app.sync_sec_events", queue="sec_heavy")
def sync_sec_events():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        total = 0
        for ticker in tickers:
            total += _sync_ticker_sec_events(db, ticker)
            db.commit()
        return {"tickers": len(tickers), "events": total}


@celery_app.task(name="app.tasks.celery_app.sync_sec_insider", queue="sec_heavy")
def sync_sec_insider():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        total = 0
        for ticker in tickers:
            total += _sync_ticker_sec_insider(db, ticker)
            db.commit()
        return {"tickers": len(tickers), "insider_trades": total}


@celery_app.task(name="app.tasks.celery_app.sync_sec_financials", queue="sec_heavy")
def sync_sec_financials():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        total = 0
        for ticker in tickers:
            total += _sync_ticker_sec_financials(db, ticker)
            db.commit()
        return {"tickers": len(tickers), "periods": total}


def _known_cusip_map(db) -> dict[str, str]:
    """已持久化的 cusip→ticker 映射（供 13F 精确过滤）。"""
    rows = db.scalars(select(SecCusipMap)).all()
    return {r.cusip: r.ticker for r in rows}


def _sync_13f(db, force: bool = False) -> dict:
    """下载最新 13F 数据集，按 CUSIP 反查自选股持仓并 upsert。

    幂等：若最新季度持仓已入库且非强制，则跳过下载（13F 季度才更新，避免每天重下 90MB）。
    """
    from app.services.sec_13f import collect_13f_holdings

    tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
    if not tickers:
        return {"skipped": "no_watchlist"}
    if not force:
        # 若已有任意持仓在近 80 天内同步过，说明本季度已采集，跳过（13F 季度才更新，避免每天重下 90MB）
        recent = db.scalar(
            select(Sec13FHolding.id).where(Sec13FHolding.synced_at >= datetime.now(UTC) - timedelta(days=80)).limit(1)
        )
        if recent:
            return {"skipped": "already_synced_this_quarter"}
    known = _known_cusip_map(db)
    holdings, discovered = collect_13f_holdings(tickers, known)
    # 回写新发现的 CUSIP 映射
    for cusip, (ticker, issuer) in discovered.items():
        exists = db.scalar(select(SecCusipMap.id).where(SecCusipMap.ticker == ticker, SecCusipMap.cusip == cusip))
        if not exists:
            db.add(SecCusipMap(ticker=ticker, cusip=cusip, issuer_name=issuer[:200], source="issuer_match"))
    db.flush()
    # upsert 持仓（唯一键 ticker+accession+report_period）
    inserted = 0
    for h in holdings:
        if h.report_period is None:
            continue
        existing = db.scalar(
            select(Sec13FHolding).where(
                Sec13FHolding.ticker == h.ticker,
                Sec13FHolding.accession_number == h.accession_number,
                Sec13FHolding.report_period == h.report_period,
            )
        )
        if existing:
            existing.manager_name = h.manager_name
            existing.value_usd = h.value_usd
            existing.shares = h.shares
            existing.put_call = h.put_call
            existing.filing_date = h.filing_date
            existing.synced_at = datetime.now(UTC)
        else:
            db.add(
                Sec13FHolding(
                    ticker=h.ticker, cusip=h.cusip, manager_name=h.manager_name,
                    accession_number=h.accession_number, report_period=h.report_period,
                    filing_date=h.filing_date, value_usd=h.value_usd, shares=h.shares,
                    put_call=h.put_call,
                )
            )
            inserted += 1
    return {"tickers": len(tickers), "holdings": len(holdings), "inserted": inserted, "new_cusips": len(discovered)}


@celery_app.task(name="app.tasks.celery_app.sync_sec_13f", queue="sec_heavy")
def sync_sec_13f(force: bool = False):
    with SessionLocal() as db:
        result = _sync_13f(db, force=force)
        db.commit()
        return result


@celery_app.task(name="app.tasks.celery_app.sync_ticker_sec_all", queue="sec_heavy")
def sync_ticker_sec_all(ticker: str):
    """单只串行深挖：先确保 filing 索引已入库，再抽 events + insider + financials。"""
    with SessionLocal() as db:
        _sync_ticker_filings(db, ticker)
        db.commit()
        events = _sync_ticker_sec_events(db, ticker)
        db.commit()
        insider = _sync_ticker_sec_insider(db, ticker)
        db.commit()
        periods = _sync_ticker_sec_financials(db, ticker)
        db.commit()
        if events:
            summarize_sec_events.delay()
        return {"ticker": ticker, "events": events, "insider_trades": insider, "periods": periods}


def _financials_text(db, ticker: str) -> str:
    rows = db.scalars(
        select(QuarterlyFinancial).where(QuarterlyFinancial.ticker == ticker).order_by(QuarterlyFinancial.period_end.desc()).limit(4)
    ).all()
    if not rows:
        return "\n\n# 近四季度财报\n数据不足"
    def _v(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "数据不足"

    lines = ["\n\n# 近四季度财报（SEC 原始）"]
    for row in rows:
        lines.append(
            f"- {row.fiscal_year} {row.fiscal_period}（截至 {row.period_end}）："
            f"营收={_v(row.revenue)}，净利润={_v(row.net_income)}，"
            f"营业利润={_v(row.operating_income)}，EPS={_v(row.eps)}，"
            f"毛利率={_v(round(row.gross_margin, 1) if row.gross_margin is not None else None, '%')}，"
            f"净利率={_v(round(row.net_margin, 1) if row.net_margin is not None else None, '%')}，"
            f"经营现金流={_v(row.operating_cash_flow)}"
        )
    return "\n".join(lines)


@celery_app.task(name="app.tasks.celery_app.earnings_reports")
def earnings_reports():
    now = datetime.now(UTC)
    future = now + timedelta(days=settings.earnings_lookahead_days)
    recent = now - timedelta(days=1)
    with SessionLocal() as db:
        events = db.scalars(select(EarningsEvent).where(EarningsEvent.event_time.between(recent, future))).all()
        for event in events:
            before = event.event_time > now
            report_type = ReportType.earnings_before if before else ReportType.earnings_after
            key = f"{report_type.value}:{event.id}"
            if db.scalar(select(Report.id).where(Report.idempotency_key == key)):
                continue
            context = "upcoming earnings expectations guidance analyst estimates" if before else "earnings results revenue EPS guidance reaction"
            try:
                results = search_ticker_news(event.ticker, context)
                evidence = "\n".join(f"[{i}] {r.title}\n{r.content}\n{r.url}" for i, r in enumerate(results, 1))
                evidence += _financials_text(db, event.ticker)
                label = "财报前瞻报告" if before else "财报复盘报告"
                _save_report(db, key, event.ticker, report_type, f"{event.ticker} {label}", evidence or "暂无相关新闻。", "important", [{"title": r.title, "url": r.url} for r in results])
            except Exception:
                continue
        db.commit()
        return {"events": len(events)}


def _upsert_congress_trade(db, raw: dict, filer_meta: dict | None = None) -> bool:
    """把一条 kadoa 交易 upsert 进 congress_trades（按 source_uid 去重）。返回是否新增。"""
    from app.services import congress as cg

    uid = raw.get("id")
    if not uid:
        return False
    existing = db.scalar(select(CongressTrade).where(CongressTrade.source_uid == uid))
    if existing:
        return False
    low, high, label = cg.amount_bounds(raw)
    meta = filer_meta or {}
    ticker = (raw.get("ticker") or "").strip().upper() or None
    db.add(CongressTrade(
        source_uid=uid,
        filer_id=raw.get("filer_id") or meta.get("id") or "",
        filer_name=meta.get("full_name") or raw.get("filer_name") or raw.get("filer_id") or "",
        chamber=meta.get("chamber"),
        branch=meta.get("branch"),
        party=meta.get("party"),
        state=meta.get("state"),
        ticker=ticker,
        asset_name=raw.get("asset_name"),
        asset_type=raw.get("asset_type"),
        transaction_type=raw.get("transaction_type"),
        transaction_date=cg.parse_date(raw.get("transaction_date")),
        filing_date=cg.parse_date(raw.get("filing_date")),
        amount_low=low,
        amount_high=high,
        amount_label=label,
        is_late=bool(raw.get("is_late")),
        comment=raw.get("comment"),
    ))
    return True


def _sync_ticker_congress(db, ticker: str) -> int:
    """按 ticker 拉 kadoa 相关交易入库。返回新增条数。"""
    from app.services import congress as cg

    try:
        trades = cg.fetch_ticker_trades(ticker)
    except Exception:
        return 0
    added = 0
    for raw in trades:
        if not raw.get("filer_name") and raw.get("filer_id"):
            raw = {**raw, "filer_name": raw.get("filer_id")}
        if _upsert_congress_trade(db, raw):
            added += 1
    return added


@celery_app.task(name="app.tasks.celery_app.sync_congress_trades")
def sync_congress_trades():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        total = sum(_sync_ticker_congress(db, t) for t in tickers)
        db.commit()
        return {"tickers": len(tickers), "added": total}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_congress")
def sync_ticker_congress(ticker: str):
    with SessionLocal() as db:
        added = _sync_ticker_congress(db, ticker)
        db.commit()
        return {"ticker": ticker, "added": added}


def _seed_figures_and_positions(db) -> None:
    """把种子人物档案 + 持仓基线写入 DB（幂等：已存在则跳过档案，持仓重置基线）。"""
    from app.data import figure_seed as fs

    for f in fs.FIGURES:
        row = db.scalar(select(TrackedFigure).where(TrackedFigure.slug == f["slug"]))
        if not row:
            row = TrackedFigure(slug=f["slug"])
            db.add(row)
        row.display_name = f["display_name"]
        row.kind = f["kind"]
        row.kadoa_filer_id = f["kadoa_filer_id"]
        row.photo_url = f["photo_url"]
        row.note = f["note"]
        row.is_seed = True
        row.extra = {"baseline_date": f.get("baseline_date")}
    positions = fs.all_positions()
    for slug, (rows, is_percent) in positions.items():
        for ticker, name, cat, value, note in rows:
            pos = db.scalar(select(FigurePosition).where(
                FigurePosition.figure_slug == slug,
                FigurePosition.ticker.is_(ticker) if ticker is None else FigurePosition.ticker == ticker,
                FigurePosition.asset_name == name,
            ))
            if not pos:
                pos = FigurePosition(figure_slug=slug, ticker=ticker, asset_name=name)
                db.add(pos)
            pos.category = cat
            pos.baseline_value = float(value)
            pos.adjusted_value = float(value)  # 叠加时从基线重算
            pos.is_percent = is_percent
            pos.note = note
    if fs.CATHIE_MOVES:
        cw = db.scalar(select(TrackedFigure).where(TrackedFigure.slug == "cathie_wood"))
        if cw:
            cw.extra = {**(cw.extra or {}), "moves": fs.CATHIE_MOVES}


def _apply_trades_to_positions(db, slug: str, filer_id: str, baseline_date) -> None:
    """把基线日期后的交易叠加到该 slug 的股票持仓（Full→归零/Partial→减/Purchase→加/Exchange→跳过）。"""
    from app.services import congress as cg

    positions = {
        p.ticker: p for p in db.scalars(select(FigurePosition).where(FigurePosition.figure_slug == slug)).all()
        if p.ticker
    }
    # 先把 adjusted 重置回基线，避免重复叠加
    for p in positions.values():
        p.adjusted_value = p.baseline_value
    trades = db.scalars(
        select(CongressTrade).where(CongressTrade.filer_id == filer_id).order_by(CongressTrade.transaction_date)
    ).all()
    base = cg.parse_date(baseline_date) if isinstance(baseline_date, str) else baseline_date
    for t in trades:
        if not t.ticker or t.ticker not in positions:
            continue
        if base and t.transaction_date and t.transaction_date <= base:
            continue
        pos = positions[t.ticker]
        mid = ((t.amount_low or 0) + (t.amount_high or 0)) / 2 if (t.amount_low or t.amount_high) else 0
        tt = (t.transaction_type or "").lower()
        if "purchase" in tt:
            pos.adjusted_value += mid
        elif "full" in tt:
            pos.adjusted_value = 0.0
        elif "partial" in tt or "sale" in tt:
            pos.adjusted_value = max(0.0, pos.adjusted_value - mid)
        # exchange 跳过


@celery_app.task(name="app.tasks.celery_app.sync_subscribed_figure")
def sync_subscribed_figure(filer_id: str):
    """订阅新政客后立即拉其全部交易入库（非种子，不做持仓叠加）。"""
    from app.services import congress as cg

    with SessionLocal() as db:
        try:
            data = cg.fetch_filer(filer_id)
        except Exception:
            return {"filer_id": filer_id, "added": 0, "error": "fetch_failed"}
        if not data:
            return {"filer_id": filer_id, "added": 0}
        meta = data.get("filer") or {}
        added = 0
        for raw in data.get("trades", []):
            raw = {**raw, "filer_id": filer_id}
            if _upsert_congress_trade(db, raw, meta):
                added += 1
        db.commit()
        return {"filer_id": filer_id, "added": added}


@celery_app.task(name="app.tasks.celery_app.sync_tracked_figures")
def sync_tracked_figures():
    from app.services import congress as cg

    with SessionLocal() as db:
        _seed_figures_and_positions(db)
        db.commit()
        figures = db.scalars(select(TrackedFigure)).all()
        result = {}
        for fig in figures:
            if not fig.kadoa_filer_id:
                continue
            try:
                data = cg.fetch_filer(fig.kadoa_filer_id)
            except Exception:
                continue
            if not data:
                continue
            meta = data.get("filer") or {}
            added = 0
            for raw in data.get("trades", []):
                raw = {**raw, "filer_id": fig.kadoa_filer_id}
                if _upsert_congress_trade(db, raw, meta):
                    added += 1
            db.commit()
            if fig.is_seed:
                baseline_date = (fig.extra or {}).get("baseline_date")
                _apply_trades_to_positions(db, fig.slug, fig.kadoa_filer_id, baseline_date)
                db.commit()
            result[fig.slug] = added
        return result


@celery_app.task(bind=True, name="app.tasks.celery_app.run_stock_discovery", max_retries=3)
def run_stock_discovery(self, run_id: int):
    from app.models import StockDiscoveryRun
    from app.services.discovery.locks import discovery_lock
    from app.services.discovery.perplexity import PerplexityError
    from app.services.discovery.search import SearchError
    from app.services.discovery.service import execute_discovery_run

    with SessionLocal() as db:
        run = db.get(StockDiscoveryRun, run_id)
        if not run:
            return {"status": "missing", "run_id": run_id}
        user_id = run.user_id
    with discovery_lock(user_id) as acquired:
        if acquired is False:
            return {"status": "duplicate_locked", "run_id": run_id}
        try:
            with SessionLocal() as db:
                run = execute_discovery_run(db, run_id)
                return {"status": run.status, "run_id": run_id}
        except (SearchError, PerplexityError) as exc:
            if exc.retryable and self.request.retries < self.max_retries:
                countdown = min(300, 30 * (2 ** self.request.retries))
                raise self.retry(exc=exc, countdown=countdown)
            with SessionLocal() as db:
                run = db.get(StockDiscoveryRun, run_id)
                if run:
                    run.status = "failed"; run.stage = "failed"; run.completed_at = datetime.now(UTC)
                    run.failure_code = exc.code; run.failure_reason = str(exc)[:1000]; db.commit()
            return {"status": "failed", "run_id": run_id}


@celery_app.task(name="app.tasks.celery_app.run_portfolio_analysis")
def run_portfolio_analysis(run_id: int):
    """Unified deterministic portfolio-analysis worker entrypoint."""
    from app.services.portfolio_analysis.jobs import execute_analysis_job

    with SessionLocal() as db:
        result = execute_analysis_job(db, run_id)
        return {"job_id": run_id, "status": result.get("status", "completed")}
