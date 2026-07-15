import hashlib
from datetime import UTC, date as date_type, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    AppSetting,
    DailyNewsArchive,
    Investigation,
    NewsItem,
    PriceAlert,
    PriceSnapshot,
    QuarterlyFinancial,
    Report,
    WatchlistItem,
)
from app.schemas import SettingsOut, SettingsUpdate, WatchlistCreate, WatchlistOut, WatchlistUpdate
from app.services.finnhub_mcp import fetch_basic_metrics, fetch_recommendations
from app.services.market_data import fetch_yf_info_metrics
from app.services.llm import summarize_news
from app.services.market_calendar import market_status

router = APIRouter(prefix="/api")


def _require_watched_ticker(db: Session, ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not db.scalar(select(WatchlistItem.id).where(WatchlistItem.ticker == value)):
        raise HTTPException(404, "该股票不在自选列表中")
    return value


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready"}


@router.get("/watchlist", response_model=list[WatchlistOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.scalars(select(WatchlistItem).order_by(WatchlistItem.ticker)).all()


@router.post("/watchlist", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
def add_watchlist(payload: WatchlistCreate, db: Session = Depends(get_db)):
    item = WatchlistItem(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该股票已在自选列表中")
    db.refresh(item)
    return item


@router.patch("/watchlist/{item_id}", response_model=WatchlistOut)
def update_watchlist(item_id: int, payload: WatchlistUpdate, db: Session = Depends(get_db)):
    item = db.get(WatchlistItem, item_id)
    if not item:
        raise HTTPException(404, "未找到股票")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
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


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    items = db.scalars(select(WatchlistItem).where(WatchlistItem.enabled.is_(True))).all()
    stocks = []
    for item in items:
        quote = db.scalar(
            select(PriceSnapshot).where(PriceSnapshot.ticker == item.ticker).order_by(PriceSnapshot.quote_time.desc()).limit(1)
        )
        stocks.append(
            {
                "ticker": item.ticker,
                "price": quote.price if quote else None,
                "previous_close": quote.previous_close if quote else None,
                "updated_at": quote.quote_time if quote else None,
            }
        )
    return {"market": market_status(), "stocks": stocks}


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


@router.get("/reports")
def reports(report_type: str | None = None, db: Session = Depends(get_db)):
    query = select(Report).order_by(Report.created_at.desc())
    if report_type:
        query = query.where(Report.report_type == report_type)
    rows = db.scalars(query.limit(100)).all()
    return [{"id": r.id, "ticker": r.ticker, "report_type": r.report_type, "title": r.title, "model": r.model, "created_at": r.created_at} for r in rows]


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
        "image_url": item.image_url,
        "published_at": item.published_at,
        "found_at": item.found_at,
        "relevance_score": item.relevance_score,
        "sentiment_score": item.sentiment_score,
        "ai_summary": item.ai_summary,
        "ai_summary_model": item.ai_summary_model,
    }


@router.get("/news")
def list_news(ticker: str = Query(...), date: date_type | None = None, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker)
    query = select(NewsItem).where(NewsItem.ticker == value)
    if date:
        start = datetime.combine(date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(date, datetime.max.time(), tzinfo=UTC)
        query = query.where(NewsItem.found_at >= start, NewsItem.found_at <= end)
    query = query.order_by(NewsItem.published_at.desc().nullslast(), NewsItem.found_at.desc()).limit(200)
    return [_news_out(item) for item in db.scalars(query).all()]


@router.post("/news/{news_id}/summarize")
def summarize(news_id: int, db: Session = Depends(get_db)):
    item = db.get(NewsItem, news_id)
    if not item:
        raise HTTPException(404, "未找到新闻")
    content = item.raw_content or item.summary or item.title
    input_hash = hashlib.sha256(f"{item.title}\n{content}".encode("utf-8")).hexdigest()[:64]
    if item.ai_summary and item.ai_summary_input_hash == input_hash:
        return _news_out(item)
    summary, model = summarize_news(item.title, content)
    item.ai_summary = summary
    item.ai_summary_model = model
    item.ai_summary_input_hash = input_hash
    item.ai_summary_created_at = datetime.now(UTC)
    db.commit()
    db.refresh(item)
    return _news_out(item)


@router.get("/news/archive")
def news_archive(ticker: str = Query(...), date: date_type | None = None, db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker)
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
    value = _require_watched_ticker(db, ticker)
    from app.tasks.celery_app import poll_news

    poll_news.delay(value)
    return {"status": "queued", "ticker": value}


@router.get("/financials")
def financials(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker)
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
        }
        for r in rows
    ]


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


def _pick(metric: dict, keys: tuple[str, ...]):
    for key in keys:
        if metric.get(key) is not None:
            return metric[key]
    return None


@router.get("/fundamentals")
def fundamentals(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker)
    try:
        metric = fetch_basic_metrics(value)
    except Exception:
        metric = {}
    try:
        recs = fetch_recommendations(value)
    except Exception:
        recs = []
    metrics = [{"label": label, "value": _pick(metric, keys)} for keys, label in _METRIC_KEYS]
    info = fetch_yf_info_metrics(value)
    metrics += [
        {"label": "Beta", "value": info.get("beta")},
        {"label": "52周高", "value": info.get("fiftyTwoWeekHigh")},
        {"label": "52周低", "value": info.get("fiftyTwoWeekLow")},
    ]
    latest = recs[0] if recs else None
    rating = None
    if latest:
        rating = {
            "period": latest.get("period"),
            "strongBuy": latest.get("strongBuy", 0), "buy": latest.get("buy", 0),
            "hold": latest.get("hold", 0), "sell": latest.get("sell", 0),
            "strongSell": latest.get("strongSell", 0),
        }
    return {"ticker": value, "metrics": metrics, "rating": rating}


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
