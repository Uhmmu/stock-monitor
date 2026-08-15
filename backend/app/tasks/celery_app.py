from datetime import UTC, date, datetime, timedelta
import logging
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import and_, case, delete, func, or_, select

import hashlib
import asyncio
import json

from app.config import get_settings
from app.model_fallbacks import model_candidates, model_matches
from app.database import SessionLocal
from app.models import (
    CongressTrade,
    DailyNewsArchive,
    EarningsEvent,
    FigurePosition,
    FinancialStatementSnapshot,
    CompanyProfile,
    FmpSyncState,
    HistoricalPrice,
    Investigation,
    InvestigationStatus,
    InvestmentCalendarSyncRun,
    MacroSyncRun,
    IndustryPulseSyncRun,
    IndustryPulseInstrument,
    IndustryPulseNode,
    OptionsChainCache,
    OptionsSnapshot,
    OptionsSyncRun,
    Security,
    StockGroup,
    StockProfile,
    NewsItem,
    NewsProviderState,
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
from app.services.llm import curate_daily_news, curate_weekly_news, generate_analysis, summarize_news
from app.services.llm import explain_cross_model
from app.services.market_calendar import market_data_collection_status, market_status
from app.services.market_data import fetch_earnings_events, fetch_yf_financial_statements, fetch_yf_quarterly
from app.services.price_snapshots import (
    collect_price_snapshot,
    get_latest_persisted_price_snapshot,
    persist_price_snapshot,
    price_snapshot_out,
)
from app.services.intraday_market import intraday_summary
from app.services.marketaux import fetch_marketaux_market_news, fetch_marketaux_news
# Legacy FMP news records remain readable, but FMP is no longer scheduled as a
# news source: the provider is reserved for profile and EOD history endpoints.
from app.services.fmp_market import FmpAuthenticationError, FmpError, FmpInvalidSymbol, FmpPremiumRequired, FmpQuotaExhausted, checkpoint, sync_history as sync_fmp_history_service, sync_profile as sync_fmp_profile_service
from app.services.technical_analysis_engine import generate_for_symbol, sync_fallback_history
from app.services.company_profile_translation import translate_description
from app.services.news import MARKET_TICKER, collect_ticker_news, prepare_news
from app.services.news_store import news_for_day, persist_news
from app.services.news_tiingo import fetch_tiingo_news
from app.services.article_fetch import fetch_article
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
from app.services.industry_pulse.service import _snapshot_payload, sync_pulse
from app.services.industry_pulse.narrative import generate_node_narrative
from app.services.options.service import semantic_options_context
from app.services.options.analytics import compute_options_analytics, filter_contracts
from app.services.options.provider import fetch_options_chain
from app.services.options.universe import build_options_universe
from app.services.finnhub_mcp import fetch_quote as fetch_finnhub_quote

settings = get_settings()
logger = logging.getLogger(__name__)
NEWS_PER_TICKER = 12  # 每只股票入库上限；低信息时允许少于该值，避免用噪声补位。


def _record_news_provider_health(
    provider: str, *, connected: bool, last_success: datetime | None = None,
    articles: int = 0, requests: int = 0, errors: list[str] | None = None,
) -> None:
    """Best-effort diagnostics only; provider failure never fails news ingestion."""
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.setex(
            f"news:provider:{provider}:health", 7 * 86400,
            json.dumps({
                "provider": provider, "connected": connected,
                "last_fetch": datetime.now(UTC).isoformat(),
                "last_success": last_success.isoformat() if last_success else None,
                "articles_fetched": articles, "request_count": requests,
                "errors": (errors or [])[:10],
            }, separators=(",", ":")),
        )
    except Exception:
        logger.debug("news provider health cache unavailable provider=%s", provider)


celery_app = Celery("stock_monitor", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "poll-market": {"task": "app.tasks.celery_app.poll_market", "schedule": settings.price_poll_minutes * 60},
    "advance-investigations": {"task": "app.tasks.celery_app.advance_investigations", "schedule": 60},
    "sync-earnings": {"task": "app.tasks.celery_app.sync_earnings", "schedule": 21600},
    # The database-backed due check survives beat container recreation. A raw
    # 12-hour interval restarts its clock after every deployment and can starve.
    "sync-investment-calendar": {
        "task": "app.tasks.celery_app.ensure_investment_calendar_fresh",
        "schedule": 600,
    },
    "sync-share-statistics": {"task": "app.tasks.celery_app.sync_share_statistics", "schedule": 86400},
    "poll-news": {"task": "app.tasks.celery_app.poll_news", "schedule": settings.news_poll_minutes * 60},
    "poll-market-news": {"task": "app.tasks.celery_app.poll_market_news", "schedule": settings.market_news_poll_minutes * 60},
    "curate-daily-news": {"task": "app.tasks.celery_app.curate_daily_archives", "schedule": 1800},
    # 每周汇总：每天跑一次，把已结束的完整 ISO 周（周一起）合并成周报后删除当周原始新闻与每日定档
    "rollup-weekly-news": {"task": "app.tasks.celery_app.rollup_weekly_archives", "schedule": 3600},
    "sync-financials": {"task": "app.tasks.celery_app.sync_financials", "schedule": 43200},
    "sync-valuations": {"task": "app.tasks.celery_app.sync_valuations", "schedule": 86400},
    "translate-news-titles": {"task": "app.tasks.celery_app.translate_news_titles", "schedule": 60},
    "reconcile-news-enrichment": {"task": "app.tasks.celery_app.reconcile_news_enrichment", "schedule": 300},
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
    "preload-portfolio-analyses": {
        "task": "app.tasks.celery_app.ensure_portfolio_analysis_fresh",
        "schedule": 3600,
    },
    "sync-global-market-data": {
        "task": "app.tasks.celery_app.sync_global_market_data",
        "schedule": 3600,
    },
    "sync-industry-pulse-due": {
        "task": "app.tasks.celery_app.ensure_industry_pulse_fresh",
        "schedule": 1800,
    },
    "sync-options-due": {
        "task": "app.tasks.celery_app.ensure_options_fresh",
        "schedule": 1800,
    },
}


NEWS_SUMMARY_VERSION = "news_summary_v2"


def _news_enrichment_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Yesterday + today in the application's market timezone."""
    current = (now or datetime.now(UTC)).astimezone(ZoneInfo(settings.market_timezone))
    start = datetime.combine(current.date() - timedelta(days=1), datetime.min.time(), tzinfo=current.tzinfo)
    end = datetime.combine(current.date() + timedelta(days=1), datetime.min.time(), tzinfo=current.tzinfo)
    return start.astimezone(UTC), end.astimezone(UTC)


def _retryable_news_error(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    return status is None or status in {408, 429} or (isinstance(status, int) and status >= 500)


def _retryable_fetch_error(code: str | None) -> bool:
    if code in {"network_error", "network_timeout", "http_error", "browser_error", "browser_busy", "browser_unavailable"}:
        return True
    if not code:
        return False
    try:
        status = int(code.rsplit("_", 1)[-1])
    except ValueError:
        return False
    return status in {408, 429} or status >= 500


@celery_app.task(name="app.tasks.celery_app.reconcile_news_enrichment")
def reconcile_news_enrichment():
    """Claim a bounded recent batch; older history is deliberately never backfilled."""
    now = datetime.now(UTC)
    start, end = _news_enrichment_bounds(now)
    with SessionLocal() as db:
        rows = db.scalars(
            select(NewsItem)
            .where(
                func.coalesce(NewsItem.published_at, NewsItem.found_at) >= start,
                func.coalesce(NewsItem.published_at, NewsItem.found_at) < end,
                or_(
                    NewsItem.ai_summary_status.in_(("idle", "pending", "failed")),
                    and_(
                        NewsItem.ai_summary_status == "degraded",
                        NewsItem.ai_summary_next_retry_at.isnot(None),
                        NewsItem.ai_summary_next_retry_at <= now,
                    ),
                    and_(
                        NewsItem.ai_summary_status.in_(("queued", "processing")),
                        NewsItem.ai_summary_requested_at <= now - timedelta(minutes=10),
                    ),
                    and_(
                        NewsItem.ai_summary_status.in_(("completed", "degraded")),
                        or_(
                            NewsItem.ai_summary_version.is_(None),
                            NewsItem.ai_summary_version != NEWS_SUMMARY_VERSION,
                            NewsItem.ai_summary_model.is_(None),
                            NewsItem.ai_summary_model.notin_(model_candidates(settings.model_medium)),
                        ),
                    ),
                ),
                NewsItem.ai_summary_attempts < settings.news_enrichment_max_attempts,
                or_(NewsItem.ai_summary_next_retry_at.is_(None), NewsItem.ai_summary_next_retry_at <= now),
            )
            .order_by(
                case(
                    (NewsItem.ai_summary_status.in_(("idle", "pending", "failed")), 0),
                    (NewsItem.ai_summary_status.in_(("queued", "processing")), 1),
                    else_=2,
                ),
                NewsItem.importance_score.desc().nullslast(),
                NewsItem.id,
            )
            .limit(settings.news_enrichment_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        claimed = []
        for row in rows:
            request_id = str(uuid4())
            row.ai_summary_status = "queued"
            row.ai_summary_request_id = request_id
            row.ai_summary_requested_at = now
            row.ai_summary_next_retry_at = None
            claimed.append((row.id, request_id))
        db.commit()
    queued = 0
    for news_id, request_id in claimed:
        try:
            summarize_news_item.apply_async(args=[news_id, request_id], priority=7)
            queued += 1
        except Exception as error:
            logger.warning("news_enrichment_enqueue_failed news_id=%s error=%s", news_id, type(error).__name__)
            with SessionLocal() as db:
                row = db.get(NewsItem, news_id)
                if row and row.ai_summary_request_id == request_id:
                    row.ai_summary_status = "pending"
                    row.ai_summary_last_error = f"{type(error).__name__}: {error}"[:1000]
                    db.commit()
    return {"claimed": len(claimed), "queued": queued, "window_start": start.isoformat(), "window_end": end.isoformat()}


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
    queue="ibkr",
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
    """Fetch once, generate once, persist once; request_id blocks stale workers."""
    with SessionLocal() as db:
        item = db.get(NewsItem, news_id)
        if not item:
            return {"status": "missing", "news_id": news_id}
        if item.ai_summary_request_id != request_id:
            return {"status": "superseded", "news_id": news_id}
        if (
            not force
            and item.ai_summary_status in {"completed", "degraded"}
            and item.ai_summary_version == NEWS_SUMMARY_VERSION
            and model_matches(settings.model_medium, item.ai_summary_model)
            and item.ai_summary_next_retry_at is None
        ):
            return {"status": item.ai_summary_status, "news_id": news_id}
        item.ai_summary_status = "processing"
        item.ai_summary_last_error = None
        item.ai_summary_attempts += 1
        item.ai_summary_last_attempt_at = datetime.now(UTC)
        title = item.title
        known_tickers = list(dict.fromkeys(
            ticker for ticker in [item.ticker, *(item.symbols or [])]
            if ticker and ticker != MARKET_TICKER
        ))
        url = item.url
        provider_summary = item.summary
        normalized_url = item.normalized_url
        existing_article_content = item.article_content
        existing_content_hash = item.article_content_hash
        existing_final_url = item.content_final_url
        existing_fetch_method = item.content_fetch_method
        existing_fetch_quality = item.content_fetch_quality
        existing_fetched_at = item.content_fetched_at
        db.commit()

    try:
        cached = None
        if normalized_url:
            with SessionLocal() as db:
                cached = db.scalar(select(NewsItem).where(
                    NewsItem.id != news_id,
                    NewsItem.normalized_url == normalized_url,
                    NewsItem.content_fetch_status.in_(("completed", "degraded")),
                    NewsItem.article_content.isnot(None),
                ).order_by(NewsItem.content_fetched_at.desc().nullslast()).limit(1))
        if cached:
            fetched = type("CachedFetch", (), {
                "content": cached.article_content, "final_url": cached.content_final_url or url,
                "method": "cache", "success": True, "quality_score": cached.content_fetch_quality or 1.0,
                "error": None, "error_code": None, "fetched_at": datetime.now(UTC), "latency_ms": 0,
            })()
        else:
            fetched = fetch_article(url)
        article_content = fetched.content if fetched.success else existing_article_content
        fetch_method = fetched.method if fetched.success else existing_fetch_method or "metadata_fallback"
        fetch_quality = fetched.quality_score if fetched.success else existing_fetch_quality or fetched.quality_score
        final_url = fetched.final_url if fetched.success else existing_final_url or fetched.final_url
        fetched_at = fetched.fetched_at if fetched.success or not existing_fetched_at else existing_fetched_at
        content = article_content or provider_summary or title
        source_quality = "high" if article_content and fetch_quality >= .7 else "medium" if article_content else "low"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        input_hash = hashlib.sha256(
            f"{title}\n{','.join(known_tickers)}\n{content_hash}\n{settings.model_medium}\n{NEWS_SUMMARY_VERSION}".encode("utf-8")
        ).hexdigest()

        with SessionLocal() as db:
            item = db.get(NewsItem, news_id)
            if not item or item.ai_summary_request_id != request_id:
                return {"status": "superseded", "news_id": news_id}
            item.article_content = article_content
            item.article_content_hash = hashlib.sha256(article_content.encode("utf-8")).hexdigest() if article_content else existing_content_hash
            item.content_final_url = final_url
            item.content_fetch_method = fetch_method
            item.content_fetch_status = "completed" if fetched.success else "degraded"
            item.content_fetch_quality = fetch_quality
            item.content_fetched_at = fetched_at
            item.content_fetch_error_code = fetched.error_code
            db.commit()

        cached_analysis = None
        if not force:
            with SessionLocal() as db:
                current = db.get(NewsItem, news_id)
                if (
                    current
                    and current.ai_summary_input_hash == input_hash
                    and current.ai_summary_version == NEWS_SUMMARY_VERSION
                    and model_matches(settings.model_medium, current.ai_summary_model)
                    and current.ai_analysis
                ):
                    cached_analysis = current
                else:
                    cached_analysis = db.scalar(select(NewsItem).where(
                        NewsItem.id != news_id,
                        NewsItem.ai_summary_input_hash == input_hash,
                        NewsItem.ai_summary_version == NEWS_SUMMARY_VERSION,
                        NewsItem.ai_summary_status.in_(("completed", "degraded")),
                        NewsItem.ai_analysis.isnot(None),
                    ).order_by(NewsItem.ai_summary_created_at.desc().nullslast()).limit(1))
        ai_started = perf_counter()
        if cached_analysis:
            analysis = dict(cached_analysis.ai_analysis or {})
            model = cached_analysis.ai_summary_model or settings.model_medium
            usage = {"input_tokens": 0, "output_tokens": 0, "cache_hit": True}
        else:
            analysis, model, usage = summarize_news(
                title,
                content,
                source_quality=source_quality,
                known_tickers=known_tickers,
            )
        ai_latency_ms = round((perf_counter() - ai_started) * 1000, 2)

        with SessionLocal() as db:
            item = db.get(NewsItem, news_id)
            if not item or item.ai_summary_request_id != request_id:
                return {"status": "superseded", "news_id": news_id}
            item.ai_summary = analysis["summary_zh"]
            item.ai_analysis = analysis
            item.ai_event_type = analysis["event_type"]
            item.ai_sentiment = analysis["sentiment"]
            item.ai_importance = analysis["importance"]
            item.ai_market_impact = analysis["market_impact"]
            item.ai_summary_model = model
            item.ai_summary_version = NEWS_SUMMARY_VERSION
            item.ai_summary_input_hash = input_hash
            item.ai_summary_created_at = datetime.now(UTC)
            item.ai_summary_status = "completed" if fetched.success else "degraded"
            item.ai_summary_last_error = None
            item.ai_summary_next_retry_at = (
                datetime.now(UTC) + timedelta(minutes=2 ** item.ai_summary_attempts)
                if not fetched.success
                and _retryable_fetch_error(fetched.error_code)
                and item.ai_summary_attempts < settings.news_enrichment_max_attempts
                else None
            )
            db.commit()
        logger.info(
            "news_enrichment_completed news_id=%s status=%s fetch_method=%s fetch_quality=%.3f fetch_latency_ms=%s fetch_error=%s ai_latency_ms=%s input_tokens=%s output_tokens=%s",
            news_id, "completed" if fetched.success else "degraded", fetch_method,
            fetched.quality_score, fetched.latency_ms, fetched.error_code, ai_latency_ms,
            usage.get("input_tokens"), usage.get("output_tokens"),
        )
        return {"status": "completed" if fetched.success else "degraded", "news_id": news_id}
    except Exception as exc:
        logger.exception("News enrichment failed news_id=%s", news_id)
        with SessionLocal() as db:
            item = db.get(NewsItem, news_id)
            if item and item.ai_summary_request_id == request_id:
                item.ai_summary_status = "failed"
                item.ai_summary_last_error = f"{type(exc).__name__}: {exc}"[:1000]
                if _retryable_news_error(exc) and item.ai_summary_attempts < settings.news_enrichment_max_attempts:
                    item.ai_summary_next_retry_at = datetime.now(UTC) + timedelta(minutes=2 ** item.ai_summary_attempts)
                db.commit()
        return {"status": "failed", "news_id": news_id}


def _save_report(db, key: str, ticker: str, title: str, evidence: str, sources: list[dict], start=None, end=None):
    if db.scalar(select(Report.id).where(Report.idempotency_key == key)):
        return
    # Reports consume the same persisted aggregate as the Options page and
    # Chat tools. Missing history stays explicit and never blocks a report.
    try:
        options = semantic_options_context(db, symbol=ticker)
        evidence += "\n\n# 已持久化期权分析（无 provider 实时调用）\n" + json.dumps(options, ensure_ascii=False, default=str)
    except Exception:
        logger.debug("options_report_context_unavailable ticker=%s", ticker, exc_info=True)
    content, model = generate_analysis(title, evidence, "important", ReportType.movement.value)
    db.add(Report(idempotency_key=key, ticker=ticker, report_type=ReportType.movement, title=title, content=content, model=model, sources=sources, period_start=start, period_end=end))


@celery_app.task(name="app.tasks.celery_app.poll_market", autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, max_retries=3)
def poll_market():
    collection = market_data_collection_status()
    if not collection["is_collecting"]:
        return {"skipped": "market_closed"}
    with SessionLocal() as db:
        items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
        watched_tickers = {item.ticker for item in items}
        peer_tickers = set(referenced_tickers(db))
        held_tickers = set(db.scalars(
            select(PortfolioPosition.symbol).where(PortfolioPosition.total_quantity > 0)
        ).all())
        by_ticker = {item.ticker: item for item in items}
        stored = 0
        failed: list[str] = []
        for ticker in sorted(watched_tickers | peer_tickers | held_tickers):
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
    final, _stats = prepare_news(dtos, scope="company", now=now, limit=NEWS_PER_TICKER)
    persist_news(db, investigation.ticker, now.astimezone(ZoneInfo(settings.market_timezone)).date(), final)
    fingerprints = [dto.fingerprint for dto in final]
    if fingerprints:
        for item in db.scalars(select(NewsItem).where(
            NewsItem.ticker == investigation.ticker,
            NewsItem.fingerprint.in_(fingerprints),
        )).all():
            item.investigation_id = investigation.id
    investigation.next_search_at = now + timedelta(minutes=settings.investigation_interval_minutes)
    investigation.last_error = None


def _daily_archive_text(db, ticker: str, market_date) -> str:
    row = db.scalar(
        select(DailyNewsArchive).where(DailyNewsArchive.ticker == ticker, DailyNewsArchive.market_date == market_date)
    )
    return f"\n\n# 当日新闻定档（Luna 去重筛选）\n{row.content}" if row else ""


def _movement_market_evidence(db, ticker: str, through: datetime) -> str:
    """Persisted facts only; the model, not code, decides what explains the move."""
    snapshot = get_latest_persisted_price_snapshot(db, ticker)
    candidates = list(db.scalars(
        select(HistoricalPrice)
        .where(HistoricalPrice.symbol == ticker, HistoricalPrice.date <= through.date())
        .order_by(HistoricalPrice.date.desc(), HistoricalPrice.source)
        .limit(60)
    ).all())
    by_date = {}
    for row in candidates:
        by_date.setdefault(row.date, row)
    rows = [by_date[value] for value in sorted(by_date)[-20:]]
    volumes = [float(row.volume) for row in rows if row.volume is not None]
    payload = {
        "latest_price_snapshot": price_snapshot_out(snapshot) if snapshot else None,
        "intraday_ohlcv": intraday_summary(db, ticker, now=through),
        "daily_ohlcv": [
            {
                "date": row.date, "open": float(row.open), "high": float(row.high),
                "low": float(row.low), "close": float(row.close),
                "volume": row.volume, "source": row.source,
            }
            for row in rows
        ],
        "derived_statistics": {
            "avg_volume_5d": sum(volumes[-5:]) / len(volumes[-5:]) if volumes[-5:] else None,
            "avg_volume_20d": sum(volumes) / len(volumes) if volumes else None,
            "high_5d": max((float(row.high) for row in rows[-5:]), default=None),
            "low_5d": min((float(row.low) for row in rows[-5:]), default=None),
            "high_20d": max((float(row.high) for row in rows), default=None),
            "low_20d": min((float(row.low) for row in rows), default=None),
        },
    }
    return "# 已持久化行情工具上下文\n" + json.dumps(payload, ensure_ascii=False, default=str)


def _complete_investigation(db, investigation: Investigation):
    timestamp = func.coalesce(NewsItem.published_at, NewsItem.found_at)
    news = db.scalars(select(NewsItem).where(
        NewsItem.ticker == investigation.ticker,
        timestamp >= investigation.started_at - timedelta(days=3),
        timestamp <= investigation.ends_at,
    ).order_by(NewsItem.ai_importance.desc().nullslast(), timestamp)).all()
    evidence = _movement_market_evidence(db, investigation.ticker, investigation.ends_at)
    evidence += "\n\n# 相关新闻（T-3 至异动结束）\n" + "\n\n".join(
        _news_analysis_evidence(item, index) for index, item in enumerate(news, 1)
    )
    market_day = investigation.started_at.astimezone(ZoneInfo(settings.market_timezone)).date()
    evidence += _daily_archive_text(db, investigation.ticker, market_day)
    sources = [{"title": item.title, "url": item.url} for item in news]
    key = f"movement:{investigation.id}"
    _save_report(db, key, investigation.ticker, f"{investigation.ticker} 价格异动调查报告", evidence or "调查期内未检索到相关新闻。", sources, investigation.started_at, investigation.ends_at)
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
                    _complete_investigation(db, investigation)
                else:
                    _collect_investigation_news(db, investigation, now)
            except Exception as error:
                investigation.last_error = str(error)
                investigation.next_search_at = now + timedelta(minutes=5)
        db.commit()
        if rows:
            reconcile_news_enrichment.delay()
        return {"processed": len(rows)}


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
        tracked = {item.ticker.upper() for item in items}
        tracked.update(value.upper() for value in db.scalars(
            select(PortfolioPosition.symbol).where(PortfolioPosition.total_quantity > 0)
        ).all())
        tracked.update(value.upper() for value in referenced_tickers(db))
        # A manually requested ticker is intentionally not promoted into the watchlist.
        if ticker:
            tracked = {ticker.upper()}
        items = [type("TrackedTicker", (), {"ticker": value})() for value in sorted(tracked)]
        total = 0
        now = datetime.now(UTC)
        marketaux_items: dict[str, list] = {}
        tiingo_items: dict[str, list] = {}
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
        try:
            tiingo_result = fetch_tiingo_news([item.ticker for item in items], config=settings, now=now)
            tiingo_items = tiingo_result.items_by_ticker
            state = db.get(NewsProviderState, "tiingo")
            if state is None:
                state = NewsProviderState(
                    provider="tiingo", quota_utc_date=now.date(),
                    request_count=0, next_batch_index=0,
                )
                db.add(state)
            if state.quota_utc_date != now.date():
                state.quota_utc_date = now.date(); state.request_count = 0
            state.request_count += len(tiingo_result.batches)
            state.last_execution_at = now
            if len(tiingo_result.failed_batches) < len(tiingo_result.batches):
                state.last_successful_fetch = now
            _record_news_provider_health(
                "tiingo", connected=not bool(tiingo_result.failed_batches),
                last_success=state.last_successful_fetch,
                articles=tiingo_result.returned, requests=len(tiingo_result.batches),
                errors=list(tiingo_result.errors),
            )
        except Exception as exc:
            logger.warning("Tiingo News scheduler integration failed: %s", type(exc).__name__)
            _record_news_provider_health("tiingo", connected=False, errors=[type(exc).__name__])
        for item in items:
            dtos = (
                collect_ticker_news(item.ticker, finnhub_symbol=provider_symbol(db, item.ticker, "finnhub"))
                + marketaux_items.get(item.ticker.upper(), [])
                + tiingo_items.get(item.ticker.upper(), [])
            )
            final, stats = prepare_news(dtos, scope="company", now=now, limit=NEWS_PER_TICKER)
            if not final:
                continue
            saved = persist_news(db, item.ticker, parsed, final, [(dto.importance_score, None) for dto in final])
            logger.info("news provider/company ticker=%s fetched=%d accepted=%d filtered=%d clustered=%d inserted=%d", item.ticker, stats["fetched"], stats["accepted"], stats["filtered"], stats["clustered"], len(saved))
            total += len(saved)
        db.commit()
        if total:
            translate_news_titles.delay()
            reconcile_news_enrichment.delay()
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
        if saved:
            translate_news_titles.delay()
            reconcile_news_enrichment.delay()
        logger.info("news provider=combined scope=market fetched=%d accepted=%d filtered=%d clustered=%d inserted=%d", stats["fetched"], stats["accepted"], stats["filtered"], stats["clustered"], len(saved))
        return {**stats, "inserted": len(saved)}


def _daily_input_hash(news: list[NewsItem]) -> str:
    basis = "|".join(sorted(
        f"{item.fingerprint}:{item.ai_summary_input_hash or ''}:{item.ai_summary_status}"
        for item in news
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]


def _news_analysis_evidence(item: NewsItem, index: int) -> str:
    analysis = item.ai_analysis or {}
    facts = analysis.get("key_points") or []
    body = item.ai_summary or (item.article_content or "")[:2000] or item.summary or "数据不足"
    return (
        f"[{index}] ({item.provider}) {item.title}\n"
        f"结构化摘要：{body}\n"
        f"关键事实：{'；'.join(str(value) for value in facts) or '数据不足'}\n"
        f"事件类型：{item.ai_event_type or '数据不足'}；情绪：{item.ai_sentiment or '数据不足'}；"
        f"重要性：{item.ai_importance if item.ai_importance is not None else '数据不足'}\n"
        f"市场影响分析：{item.ai_market_impact or '数据不足'}\n{item.url}"
    )


@celery_app.task(name="app.tasks.celery_app.curate_daily_archives")
def curate_daily_archives():
    parsed = datetime.now(UTC).astimezone(ZoneInfo(settings.market_timezone)).date()
    market_date = parsed.isoformat()
    with SessionLocal() as db:
        tickers = set(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        tickers.update(db.scalars(select(PortfolioPosition.symbol).where(PortfolioPosition.total_quantity > 0)).all())
        tickers.update(referenced_tickers(db))
        curated = 0
        failed = []
        for ticker in sorted(tickers):
            news = news_for_day(db, ticker, parsed)
            if not news:
                continue
            input_hash = _daily_input_hash(news)
            existing = db.scalar(
                select(DailyNewsArchive).where(DailyNewsArchive.ticker == ticker, DailyNewsArchive.market_date == parsed)
            )
            if existing and existing.input_hash == input_hash:
                continue
            evidence = "\n\n".join(_news_analysis_evidence(item, i) for i, item in enumerate(news, 1))
            try:
                content, model = curate_daily_news(ticker, market_date, evidence)
            except Exception as error:
                logger.warning("daily_news_archive_failed ticker=%s error=%s", ticker, type(error).__name__)
                failed.append(ticker)
                continue
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
        return {"curated": curated, "failed": failed}


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
    """把已结束的完整 ISO 周（周一起）合并成周报并删除冗余每日定档。

    - 只处理周一严格早于“本周周一”的完整周，绝不动本周数据。
    - 逐 ticker 逐周：合并当周每日定档的关键事实 → 落库 WeeklyNewsArchive → 删除 DailyNewsArchive。
    - NewsItem 是统一研究数据源，永久保留供 Chat、报告和详情复用。
    """
    today = datetime.now(UTC).astimezone(ZoneInfo(settings.market_timezone)).date()
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
        deleted_daily = db.execute(
            delete(DailyNewsArchive).where(DailyNewsArchive.market_date < current_monday)
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
        row.source = "yfinance"
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
    sync_options_symbol.delay(value)
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
    from app.services.discovery.exa import ExaError
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
        except (SearchError, PerplexityError, ExaError) as exc:
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


@celery_app.task(name="app.tasks.celery_app.ensure_portfolio_analysis_fresh")
def ensure_portfolio_analysis_fresh(force: bool = False):
    """Hourly due check for the bounded weekly portfolio-analysis preload."""
    from app.services.portfolio_analysis.jobs import schedule_due_preloads

    with SessionLocal() as db:
        return schedule_due_preloads(db, force=force)


@celery_app.task(name="app.tasks.celery_app.sync_industry_pulse")
def sync_industry_pulse():
    """Daily deterministic Industry Pulse update; AI remains post-commit optional."""
    if not settings.industry_pulse_enabled:
        return {"status": "disabled"}
    lock = None
    try:
        import redis
        lock = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).lock("stock-monitor:industry-pulse:sync", timeout=settings.industry_pulse_sync_lock_seconds, blocking=False)
        if not lock.acquire(blocking=False):
            return {"status": "running"}
    except Exception:
        lock = None
        logger.debug("Industry Pulse Redis lock unavailable; using durable active-run guard", exc_info=True)
    db = None
    try:
        db = SessionLocal()
        try:
            result = sync_pulse(db, trigger_type="scheduled")
        except Exception as exc:
            db.rollback()
            run = db.scalar(select(IndustryPulseSyncRun).where(IndustryPulseSyncRun.status == "running").order_by(IndustryPulseSyncRun.started_at.desc()).limit(1))
            if run:
                run.status, run.finished_at = "failed", datetime.now(UTC)
                run.error_summary_json = {"error": type(exc).__name__, "message": str(exc)[:500]}
                db.commit()
            raise
        if settings.industry_pulse_ai_enabled and settings.openai_api_key and result.get("status") == "completed":
            from app.models import IndustryPulseNode, IndustryPulseSnapshot
            as_of = date.fromisoformat(result["trading_date"])
            generated = 0
            rows = db.scalars(select(IndustryPulseSnapshot).join(IndustryPulseNode, IndustryPulseNode.id == IndustryPulseSnapshot.node_id).where(
                IndustryPulseSnapshot.trading_date == as_of,
                or_(
                    and_(IndustryPulseNode.taxonomy == "base", IndustryPulseNode.level == "sector"),
                    and_(IndustryPulseNode.taxonomy == "ai", IndustryPulseNode.level == "group"),
                ),
            )).all()
            for snapshot in rows:
                node = db.get(IndustryPulseNode, snapshot.node_id)
                if not node:
                    continue
                generated_result = generate_node_narrative(db, node_id=node.id, trading_date=as_of, node={"id": node.id, "name": node.name, "node_key": node.node_key}, snapshot=_snapshot_payload(db, snapshot))
                generated += int(generated_result.get("status") == "completed" and not generated_result.get("cached"))
            run = db.get(IndustryPulseSyncRun, result.get("run_id"))
            if run:
                run.ai_summaries_generated = generated
                run.luna_calls = generated
            db.commit()
            result["ai_summaries_generated"] = generated
        logger.info(
            "industry pulse sync status=%s etf_total=%s yfinance=%s finnhub=%s failed=%s sectors=%s unavailable=%s focus=%s duration_ms=%s",
            result.get("status"), result.get("etf_total"), result.get("yfinance_success"), result.get("finnhub_fallback"),
            result.get("failed"), result.get("sector_calculated"), result.get("sector_unavailable"), result.get("focus_signal_count"), result.get("duration_ms"),
        )
        return result
    finally:
        if db:
            db.close()
        if lock:
            try:
                lock.release()
            except Exception:
                logger.debug("Industry Pulse Redis lock release failed", exc_info=True)


@celery_app.task(name="app.tasks.celery_app.sync_global_market_data")
def sync_global_market_data_task(full_backfill: bool = False):
    """Shared P0/P1/P2 daily-price update; each batch commits its checkpoint."""
    from app.services.industry_pulse.service import ensure_seed_data
    from app.services.market_data_coordinator import sync_global_market_data

    with SessionLocal() as db:
        ensure_seed_data(db)
        db.commit()
        if db.get_bind().dialect.name == "postgresql" and not db.scalar(select(func.pg_try_advisory_xact_lock(81730122))):
            return {"status": "running"}
        return {"status": "completed", **sync_global_market_data(db, full_backfill=full_backfill)}


@celery_app.task(name="app.tasks.celery_app.ensure_industry_pulse_fresh")
def ensure_industry_pulse_fresh(force: bool = False):
    """Cheap DB due check so beat restarts do not duplicate a daily run."""
    if not settings.industry_pulse_enabled:
        return {"status": "disabled"}
    market = market_status()
    market_hour = datetime.now(ZoneInfo(settings.market_timezone)).hour
    if not force and (market.get("session") is None or market.get("is_open") or market_hour < 17):
        return {"status": "waiting_for_market_close"}
    with SessionLocal() as db:
        active = db.scalar(select(IndustryPulseSyncRun).where(IndustryPulseSyncRun.status == "running", IndustryPulseSyncRun.started_at >= datetime.now(UTC) - timedelta(seconds=settings.industry_pulse_sync_lock_seconds)).order_by(IndustryPulseSyncRun.started_at.desc()).limit(1))
        if active and not force:
            return {"status": "running", "run_id": active.id}
        latest = db.scalar(select(IndustryPulseSyncRun).where(IndustryPulseSyncRun.status == "completed").order_by(IndustryPulseSyncRun.finished_at.desc()).limit(1))
        due = force or latest is None or latest.finished_at is None or latest.finished_at <= datetime.now(UTC) - timedelta(hours=settings.industry_pulse_refresh_hours)
    if not due:
        return {"status": "not_due", "run_id": latest.id if latest else None}
    queued = sync_industry_pulse.delay()
    return {"status": "queued", "task_id": queued.id}


def _options_jobs(db, only_symbol: str | None = None):
    watched = list(db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all())
    payload = []
    security_by_ticker = {}
    for item in watched:
        security = db.get(Security, item.security_id) if item.security_id else None
        profile = db.get(StockProfile, item.ticker)
        group = db.get(StockGroup, item.user_group_id) if item.user_group_id else None
        security_by_ticker[item.ticker] = security
        payload.append({
            "ticker": item.ticker,
            "company_name": (security.display_name if security else None) or (profile.company_name if profile else None),
            "official_sector": profile.official_sector if profile else None,
            "official_industry": profile.official_industry if profile else None,
            "group": group.name if group else None,
        })
    nodes = {row.node_key: row for row in db.scalars(select(IndustryPulseNode).where(IndustryPulseNode.taxonomy == "base")).all()}
    classifications = {}
    priority = case((IndustryPulseInstrument.classification_source == "MANUAL_CURATED_SEED", 0), (IndustryPulseInstrument.classification_source == "MANUAL", 1), (IndustryPulseInstrument.classification_source == "AI_CLASSIFIED", 2), else_=3)
    for mapping in db.scalars(select(IndustryPulseInstrument).where(IndustryPulseInstrument.ticker.in_([item.ticker for item in watched]), IndustryPulseInstrument.mapping_type == "primary_industry", IndustryPulseInstrument.enabled.is_(True)).order_by(priority, IndustryPulseInstrument.confidence.desc())).all():
        node = db.get(IndustryPulseNode, mapping.node_id)
        seen = set()
        while node and node.level != "sector" and node.parent_id and node.id not in seen:
            seen.add(node.id); node = db.get(IndustryPulseNode, node.parent_id)
        if node and node.level == "sector":
            classifications.setdefault(mapping.ticker, node.node_key)
    rows = build_options_universe(payload, classifications=classifications)
    jobs = []
    for row in rows:
        if only_symbol and row["symbol"] != only_symbol.upper():
            continue
        security = security_by_ticker.get(row["symbol"])
        provider_symbol_value = security.yahoo_symbol if security and security.yahoo_symbol else row["symbol"]
        jobs.append({
            **row,
            "security_id": security.id if security else None,
            "provider_symbol": provider_symbol_value,
            "finnhub_symbol": security.finnhub_symbol if security else None,
            "sector_node_id": nodes.get(row.get("sector_id")).id if nodes.get(row.get("sector_id")) else None,
        })
    return jobs


def _persist_options_symbol(db, job):
    market_day = datetime.now(ZoneInfo(settings.market_timezone)).date()
    history_rows = list(db.scalars(select(OptionsSnapshot).where(OptionsSnapshot.symbol == job["symbol"], OptionsSnapshot.trading_date != market_day).order_by(OptionsSnapshot.trading_date.desc()).limit(60)).all())
    history = list(reversed(history_rows))
    validator = None
    if job.get("finnhub_symbol") and settings.finnhub_api_key:
        validator = lambda _symbol: fetch_finnhub_quote(job["finnhub_symbol"])
    raw = fetch_options_chain(job["provider_symbol"], timeout_seconds=settings.options_provider_timeout_seconds, quote_validator=validator)
    raw.update({"symbol": job["symbol"], "asset_type": job["asset_type"], "sector_node_id": job.get("sector_node_id")})
    values = compute_options_analytics(raw, history)
    row = db.scalar(select(OptionsSnapshot).where(OptionsSnapshot.symbol == job["symbol"], OptionsSnapshot.trading_date == market_day))
    failure_statuses = {"PROVIDER_ERROR", "NO_VALID_EXPIRATION", "NO_OPTIONS"}
    if row is not None and values.get("status") in failure_statuses:
        # A transient refresh failure must not erase a good same-day snapshot.
        # Keep the failure in the run counters/return value while retaining the
        # last valid aggregate for readers.
        warning = f"refresh_failed:{values['status']}"
        row.warnings = list(dict.fromkeys((row.warnings or []) + [warning]))
        values["preserved_existing"] = True
        return values, 0, 0
    if row is None:
        row = OptionsSnapshot(symbol=job["symbol"], trading_date=market_day, fetched_at=datetime.now(UTC), asset_type=job["asset_type"], status=values["status"])
        db.add(row)
    for key in (
        "asset_type", "sector_node_id", "status", "provider", "underlying_price", "days_to_expiration", "active_contracts",
        "call_volume", "put_volume", "call_open_interest", "put_open_interest", "put_call_volume_ratio", "put_call_oi_ratio",
        "atm_iv", "near_term_iv", "next_term_iv", "iv_change", "downside_skew", "upside_skew", "activity_score",
        "activity_status", "quality_score", "coverage", "sample_size", "warnings", "metrics_json",
    ):
        setattr(row, key, values.get(key))
    row.security_id = job.get("security_id")
    row.nearest_expiration = date.fromisoformat(values["nearest_expiration"]) if values.get("nearest_expiration") else None
    row.next_expiration = date.fromisoformat(values["next_expiration"]) if values.get("next_expiration") else None
    row.fetched_at = datetime.fromisoformat(values["fetched_at"]) if values.get("fetched_at") else datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.options_chain_cache_hours)
    for expiration in raw.get("expirations", []):
        expiration_date = date.fromisoformat(expiration["expiration"])
        cache = db.scalar(select(OptionsChainCache).where(OptionsChainCache.symbol == job["symbol"], OptionsChainCache.expiration == expiration_date))
        if cache is None:
            cache = OptionsChainCache(symbol=job["symbol"], expiration=expiration_date, fetched_at=datetime.now(UTC), expires_at=expires_at)
            db.add(cache)
        cache.provider = raw.get("provider", "yfinance")
        cache.calls_json = filter_contracts(expiration.get("calls", []), raw.get("underlying_price"))
        cache.puts_json = filter_contracts(expiration.get("puts", []), raw.get("underlying_price"))
        cache.contract_count = len(cache.calls_json) + len(cache.puts_json)
        cache.fetched_at, cache.expires_at = datetime.now(UTC), expires_at
    return values, sum(item.get("contract_count", 0) for item in raw.get("expirations", [])), sum(len(filter_contracts(item.get(side, []), raw.get("underlying_price"))) for item in raw.get("expirations", []) for side in ("calls", "puts"))


@celery_app.task(name="app.tasks.celery_app.sync_options_symbol")
def sync_options_symbol(symbol: str):
    if not settings.options_enabled:
        return {"status": "disabled"}
    with SessionLocal() as db:
        jobs = _options_jobs(db, symbol)
        if not jobs:
            return {"status": "not_eligible", "symbol": symbol.upper()}
        result, received, filtered = _persist_options_symbol(db, jobs[0])
        db.commit()
        return {"symbol": symbol.upper(), "status": result["status"], "contracts_received": received, "contracts_filtered": filtered}


@celery_app.task(name="app.tasks.celery_app.sync_options")
def sync_options():
    if not settings.options_enabled:
        return {"status": "disabled"}
    lock = None
    try:
        import redis
        lock = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).lock("stock-monitor:options:sync", timeout=settings.options_sync_lock_seconds, blocking=False)
        if not lock.acquire(blocking=False):
            return {"status": "running"}
    except Exception:
        lock = None
        logger.debug("options Redis lock unavailable; using durable active-run guard", exc_info=True)
    started = perf_counter()
    try:
        with SessionLocal() as db:
            active = db.scalar(select(OptionsSyncRun).where(OptionsSyncRun.status == "running", OptionsSyncRun.started_at >= datetime.now(UTC) - timedelta(seconds=settings.options_sync_lock_seconds)).order_by(OptionsSyncRun.started_at.desc()).limit(1))
            if active:
                return {"status": "running", "run_id": active.id}
            jobs = _options_jobs(db)
            run = OptionsSyncRun(trigger_type="scheduled", symbols_requested=len(jobs))
            db.add(run); db.commit(); db.refresh(run)
            errors = {}
            for job in jobs:
                try:
                    result, received, filtered = _persist_options_symbol(db, job)
                    run.contracts_received += received
                    run.contracts_filtered += filtered
                    failed = result.get("status") in {"PROVIDER_ERROR", "NO_VALID_EXPIRATION", "NO_OPTIONS"}
                    run.symbols_success += int(not failed)
                    run.symbols_failed += int(failed)
                    run.low_quality_symbols += int(float(result.get("quality_score") or 0) < .45)
                    if failed:
                        errors[job["symbol"]] = result.get("warnings", [])
                    db.commit()
                except Exception as exc:
                    db.rollback(); run = db.get(OptionsSyncRun, run.id)
                    run.symbols_failed += 1; errors[job["symbol"]] = [type(exc).__name__]
                    db.commit()
                    logger.warning("options_symbol_refresh_failed symbol=%s", job["symbol"], exc_info=True)
            run = db.get(OptionsSyncRun, run.id)
            run.status, run.finished_at = "completed", datetime.now(UTC)
            run.duration_ms = int((perf_counter() - started) * 1000)
            run.error_summary_json = errors
            db.query(OptionsChainCache).filter(OptionsChainCache.expires_at <= datetime.now(UTC)).delete(synchronize_session=False)
            db.query(OptionsSnapshot).filter(OptionsSnapshot.trading_date < date.today() - timedelta(days=settings.options_history_days)).delete(synchronize_session=False)
            db.commit()
            logger.info("options_refresh_completed run_id=%s symbols_requested=%s symbols_success=%s symbols_failed=%s contracts_received=%s contracts_filtered=%s low_quality_symbols=%s", run.id, run.symbols_requested, run.symbols_success, run.symbols_failed, run.contracts_received, run.contracts_filtered, run.low_quality_symbols)
            return {"run_id": run.id, "status": run.status, "symbols_requested": run.symbols_requested, "symbols_success": run.symbols_success, "symbols_failed": run.symbols_failed}
    finally:
        if lock:
            try: lock.release()
            except Exception: logger.debug("options Redis lock release failed", exc_info=True)


@celery_app.task(name="app.tasks.celery_app.ensure_options_fresh")
def ensure_options_fresh(force: bool = False):
    if not settings.options_enabled:
        return {"status": "disabled"}
    now = datetime.now(ZoneInfo(settings.market_timezone))
    if not force and (market_status().get("session") is None or not 10 <= now.hour <= 20):
        return {"status": "outside_refresh_window"}
    with SessionLocal() as db:
        active = db.scalar(select(OptionsSyncRun).where(OptionsSyncRun.status == "running", OptionsSyncRun.started_at >= datetime.now(UTC) - timedelta(seconds=settings.options_sync_lock_seconds)).order_by(OptionsSyncRun.started_at.desc()).limit(1))
        if active and not force:
            return {"status": "running", "run_id": active.id}
        latest = db.scalar(select(OptionsSyncRun).where(OptionsSyncRun.status == "completed").order_by(OptionsSyncRun.finished_at.desc()).limit(1))
        due = force or latest is None or latest.finished_at is None or latest.finished_at <= datetime.now(UTC) - timedelta(hours=settings.options_refresh_hours)
    if not due:
        return {"status": "not_due", "run_id": latest.id if latest else None}
    queued = sync_options.delay()
    return {"status": "queued", "task_id": queued.id}
