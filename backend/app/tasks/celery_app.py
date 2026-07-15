from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

import hashlib

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    DailyNewsArchive,
    EarningsEvent,
    Investigation,
    InvestigationStatus,
    NewsItem,
    PriceSnapshot,
    QuarterlyFinancial,
    Report,
    ReportType,
    WatchlistItem,
)
from app.services import archive
from app.services.alerting import evaluate_quote
from app.services.financials import quarters_from_yf
from app.services.market_context import build_market_context
from app.services.llm import curate_daily_news, generate_analysis
from app.services.market_calendar import market_status
from app.services.market_data import fetch_earnings_events, fetch_quotes, fetch_yf_quarterly
from app.services.news import collect_ticker_news, filter_news
from app.services.news_store import news_for_day, persist_news
from app.services.relevance import score_news
from app.services.search import search_ticker_news
from app.services.title_translation import title_input_hash, translate_title

settings = get_settings()
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
    "translate-news-titles": {"task": "app.tasks.celery_app.translate_news_titles", "schedule": 60},
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
