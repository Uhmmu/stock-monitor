from datetime import UTC, datetime, timedelta
import logging

from celery import Celery
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

import hashlib

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    CongressTrade,
    DailyNewsArchive,
    EarningsEvent,
    FigurePosition,
    Investigation,
    InvestigationStatus,
    NewsItem,
    PriceSnapshot,
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
)
from app.services import archive
from app.services.alerting import evaluate_quote
from app.services.financials import quarters_from_yf
from app.services.sec_edgar import fetch_filings
from app.services.market_context import build_market_context
from app.services.llm import curate_daily_news, generate_analysis
from app.services.llm import explain_cross_model
from app.services.market_calendar import market_status
from app.services.market_data import fetch_earnings_events, fetch_quotes, fetch_yf_quarterly
from app.services.news import collect_ticker_news, filter_news
from app.services.news_store import news_for_day, persist_news
from app.services.relevance import score_news
from app.services.search import search_ticker_news
from app.services.title_translation import title_input_hash, translate_title
from app.services.cross_model import build_cross_model, fetch_cross_model_inputs, opinion_evidence
from app.services.finnhub_mcp import fetch_basic_metrics, fetch_company_peers
from app.services.graham import build_graham_from_sources, get_latest_aaa_corporate_bond_yield

settings = get_settings()
logger = logging.getLogger(__name__)
NEWS_PER_TICKER = 12  # 每只股票入库上限，按相关性取 top N
MIN_NEWS_PER_TICKER = 5  # 保底：新闻少的股票不被阈值砍光，按关联度降序至少留 N 篇
celery_app = Celery("stock_monitor", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "poll-market": {"task": "app.tasks.celery_app.poll_market", "schedule": settings.price_poll_minutes * 60},
    "advance-investigations": {"task": "app.tasks.celery_app.advance_investigations", "schedule": 60},
    "scheduled-reports": {"task": "app.tasks.celery_app.scheduled_reports", "schedule": 300},
    "sync-earnings": {"task": "app.tasks.celery_app.sync_earnings", "schedule": 21600},
    "earnings-reports": {"task": "app.tasks.celery_app.earnings_reports", "schedule": 1800},
    "poll-news": {"task": "app.tasks.celery_app.poll_news", "schedule": settings.news_poll_minutes * 60},
    "curate-daily-news": {"task": "app.tasks.celery_app.curate_daily_archives", "schedule": 1800},
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
}


def _save_report(db, key: str, ticker: str | None, report_type: ReportType, title: str, evidence: str, tier: str, sources: list[dict], start=None, end=None):
    if db.scalar(select(Report.id).where(Report.idempotency_key == key)):
        return
    if ticker:
        try:
            evidence = build_market_context(ticker) + "\n\n# 新闻线索\n" + evidence
        except Exception:
            pass
    content, model = generate_analysis(title, evidence, tier, report_type.value)
    db.add(Report(idempotency_key=key, ticker=ticker, report_type=report_type, title=title, content=content, model=model, sources=sources, period_start=start, period_end=end))


@celery_app.task(name="app.tasks.celery_app.poll_market", autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, max_retries=3)
def poll_market():
    if not market_status()["is_open"]:
        return {"skipped": "market_closed"}
    with SessionLocal() as db:
        items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
        quotes = fetch_quotes([item.ticker for item in items])
        by_ticker = {item.ticker: item for item in items}
        for quote in quotes:
            snapshot = PriceSnapshot(**quote.__dict__)
            db.add(snapshot)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                continue
            evaluate_quote(db, by_ticker[quote.ticker], snapshot)
        db.commit()
        return {"quotes": len(quotes)}


def _collect_investigation_news(db, investigation: Investigation, now: datetime):
    dtos = collect_ticker_news(investigation.ticker, "sudden price movement catalyst", days=2)
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
        for ticker, event_time in events:
            exists = db.scalar(select(EarningsEvent.id).where(EarningsEvent.ticker == ticker, EarningsEvent.event_time == event_time))
            if not exists:
                db.add(EarningsEvent(ticker=ticker, event_time=event_time, confidence="estimated"))
        db.commit()
        return {"events": len(events)}


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
        query = select(WatchlistItem).where(WatchlistItem.enabled.is_(True))
        if ticker:
            query = query.where(WatchlistItem.ticker == ticker)
        items = db.scalars(query).all()
        total = 0
        now = datetime.now(UTC)
        for item in items:
            dtos = collect_ticker_news(item.ticker)
            kept = [dto for dto in dtos if filter_news(dto, now)]
            if not kept:
                continue
            scores = score_news(item.ticker, [(dto.title, dto.summary or dto.raw_content or "") for dto in kept])
            threshold = settings.news_relevance_threshold
            # 全部按相关性降序（无分的排最后）
            ranked = sorted(
                ((dto, *scores.get(index, (None, None))) for index, dto in enumerate(kept)),
                key=lambda row: row[1] if row[1] is not None else -1.0,
                reverse=True,
            )
            # 达标的（≥阈值）优先；若达标不足 MIN_NEWS_PER_TICKER，按关联度降序补齐保底篇数
            above = [row for row in ranked if row[1] is not None and row[1] >= threshold]
            scored = above if len(above) >= MIN_NEWS_PER_TICKER else ranked[:MIN_NEWS_PER_TICKER]
            scored = scored[:NEWS_PER_TICKER]
            final = [row[0] for row in scored]
            final_scores = [(row[1], row[2]) for row in scored]
            saved = persist_news(db, item.ticker, parsed, final, final_scores)
            total += len(saved)
        db.commit()
        if total:
            translate_news_titles.delay()
        return {"tickers": len(items), "new": total}


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


def _sync_ticker_financials(db, ticker: str) -> bool:
    """同步单只财报到 DB + 归档。成功返回 True，无数据/异常返回 False。"""
    try:
        rows = fetch_yf_quarterly(ticker)
    except Exception:
        return False
    quarters = quarters_from_yf(rows)
    if not quarters:
        return False
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
        archive.write_quarter(ticker, quarter.label, quarter.raw_payload)
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
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        synced = sum(1 for ticker in tickers if _sync_ticker_financials(db, ticker))
        db.commit()
        return {"synced": synced}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_financials")
def sync_ticker_financials(ticker: str):
    with SessionLocal() as db:
        ok = _sync_ticker_financials(db, ticker)
        db.commit()
        return {"ticker": ticker, "synced": ok}


def _sync_ticker_valuation(db, ticker: str) -> bool:
    """抓取分类、Finnhub 同行与 Yahoo 原料，计算后按日 upsert；Luna 仅解释。"""
    try:
        peers = fetch_company_peers(ticker)
    except Exception:
        peers = []
    info, peer_infos, financials = fetch_cross_model_inputs(ticker, peers)
    if not info:
        return False
    quarters = db.scalars(
        select(QuarterlyFinancial).where(QuarterlyFinancial.ticker == ticker)
        .order_by(QuarterlyFinancial.period_end.desc()).limit(4)
    ).all()
    quarter_inputs = [
        {"period_end": row.period_end.isoformat(), "eps": row.eps, "net_income": row.net_income,
         "revenue": row.revenue, "free_cash_flow": row.free_cash_flow}
        for row in quarters
    ]
    latest_quote = db.scalar(
        select(PriceSnapshot).where(PriceSnapshot.ticker == ticker)
        .order_by(PriceSnapshot.quote_time.desc()).limit(1)
    )
    quote_input = ({"price": latest_quote.price, "source": latest_quote.source,
                    "as_of": latest_quote.quote_time.isoformat()} if latest_quote else None)
    try:
        finnhub_metrics = fetch_basic_metrics(ticker)
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
    ai_model = None
    try:
        opinion, ai_model = explain_cross_model(opinion_evidence(payload))
        payload["ai_opinion"] = opinion
        payload["ai_model"] = ai_model
    except Exception:
        opinion = payload["ai_opinion"]
    today = datetime.now(UTC).date()
    row = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == ticker, ValuationSnapshot.snapshot_date == today))
    if not row:
        row = ValuationSnapshot(ticker=ticker, snapshot_date=today)
        db.add(row)
    row.payload = payload
    row.ai_opinion = opinion
    row.ai_model = ai_model
    row.source_version = "cross-model-v4"
    return True


@celery_app.task(name="app.tasks.celery_app.sync_valuations")
def sync_valuations():
    with SessionLocal() as db:
        tickers = list(db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all())
        synced = sum(1 for ticker in tickers if _sync_ticker_valuation(db, ticker))
        db.commit()
        return {"synced": synced}


@celery_app.task(name="app.tasks.celery_app.sync_ticker_valuation")
def sync_ticker_valuation(ticker: str):
    with SessionLocal() as db:
        ok = _sync_ticker_valuation(db, ticker.upper())
        db.commit()
        return {"ticker": ticker.upper(), "synced": ok}


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
    from app.services.sec_13f import collect_13f_holdings, latest_dataset_url

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
