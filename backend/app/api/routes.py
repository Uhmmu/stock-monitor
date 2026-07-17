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
    CongressTrade,
    DailyNewsArchive,
    FigurePosition,
    Investigation,
    NewsItem,
    PriceAlert,
    PriceSnapshot,
    QuarterlyFinancial,
    Report,
    Sec13FHolding,
    SecEvent,
    SecFiling,
    SecFinancialPeriod,
    SecInsiderTrade,
    TrackedFigure,
    WatchlistItem,
)
from app.schemas import SettingsOut, SettingsUpdate, WatchlistCreate, WatchlistOut, WatchlistUpdate
from app.services.article_fetch import fetch_article_text
from app.services.finnhub_mcp import fetch_basic_metrics, fetch_recommendations
from app.services.market_data import fetch_index_quotes, fetch_yf_info_metrics
from app.services.llm import summarize_news
from app.services.market_calendar import market_status
from app.services.volume_stats import volume_context

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
    if item.enabled:
        from app.tasks.celery_app import sync_ticker_congress, sync_ticker_filings, sync_ticker_financials, sync_ticker_sec_all

        sync_ticker_financials.delay(item.ticker)
        sync_ticker_filings.delay(item.ticker)
        sync_ticker_sec_all.delay(item.ticker)
        sync_ticker_congress.delay(item.ticker)
    return item


@router.patch("/watchlist/{item_id}", response_model=WatchlistOut)
def update_watchlist(item_id: int, payload: WatchlistUpdate, db: Session = Depends(get_db)):
    item = db.get(WatchlistItem, item_id)
    if not item:
        raise HTTPException(404, "未找到股票")
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
        stocks.append(
            {
                "ticker": item.ticker,
                "price": quote.price if quote else None,
                "previous_close": quote.previous_close if quote else None,
                "updated_at": quote.quote_time if quote else None,
                "volume": vol,
                "volume_ratio": ctx["ratio"],
                "volume_label": ctx["label"],
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
    full_text = fetch_article_text(item.url)
    if full_text:
        item.raw_content = full_text
        content = full_text
    else:
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


@router.get("/sec-filings")
def sec_filings(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker)
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
    value = _require_watched_ticker(db, ticker)
    from app.tasks.celery_app import sync_ticker_sec_all

    sync_ticker_sec_all.delay(value)
    return {"status": "queued", "ticker": value}


@router.get("/sec-events")
def sec_events(ticker: str = Query(...), db: Session = Depends(get_db)):
    value = _require_watched_ticker(db, ticker)
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
    value = _require_watched_ticker(db, ticker)
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
    value = _require_watched_ticker(db, ticker)
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
    value = _require_watched_ticker(db, ticker)
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
