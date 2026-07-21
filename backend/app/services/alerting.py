import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting, Investigation, InvestigationStatus, PriceAlert, PriceSnapshot, WatchlistItem


PERIODS = {"20m": timedelta(minutes=20), "1h": timedelta(hours=1)}


def _runtime_settings(db: Session) -> dict:
    settings = get_settings()
    spec = {
        "threshold_20m": (float, settings.default_threshold_20m),
        "threshold_1h": (float, settings.default_threshold_1h),
        "threshold_day": (float, settings.default_threshold_day),
        "alert_cooldown_minutes": (int, settings.alert_cooldown_minutes),
        "investigation_duration_minutes": (int, settings.investigation_duration_minutes),
    }
    stored = {row.key: row.value for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(spec))).all()}
    resolved = {}
    for key, (cast, fallback) in spec.items():
        raw = stored.get(key)
        try:
            resolved[key] = cast(raw) if raw is not None else fallback
        except (TypeError, ValueError):
            resolved[key] = fallback
    return resolved


def _change(current: float, baseline: float) -> float:
    return (current - baseline) / baseline * 100


def _market_day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """给定时刻所在的美东自然交易日在 UTC 下的 [起, 止) 边界。"""
    settings = get_settings()
    tz = ZoneInfo(settings.market_timezone)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(tz)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _event_key(ticker: str, moment: datetime) -> str:
    """每只股票每个美东交易日仅一个异动事件键。"""
    day_start, _ = _market_day_bounds(moment)
    day = day_start.date().isoformat()
    return hashlib.sha256(f"{ticker}:{day}".encode()).hexdigest()


def evaluate_quote(db: Session, item: WatchlistItem, current: PriceSnapshot) -> list[PriceAlert]:
    runtime = _runtime_settings(db)
    thresholds = {
        "20m": item.threshold_20m or runtime["threshold_20m"],
        "1h": item.threshold_1h or runtime["threshold_1h"],
        "day": item.threshold_day or runtime["threshold_day"],
    }
    # 一天一家公司只允许一个异动提醒/调查：当日已有则直接跳过后续任何阈值触发。
    day_start, day_end = _market_day_bounds(current.quote_time)
    existing_today = db.scalar(
        select(PriceAlert.id).where(
            PriceAlert.ticker == item.ticker,
            PriceAlert.triggered_at >= day_start,
            PriceAlert.triggered_at < day_end,
        )
    )
    if existing_today:
        return []

    candidates: list[tuple[str, float]] = []
    for period, delta in PERIODS.items():
        baseline = db.scalar(
            select(PriceSnapshot.price)
            .where(PriceSnapshot.ticker == item.ticker, PriceSnapshot.quote_time <= current.quote_time - delta)
            .order_by(PriceSnapshot.quote_time.desc())
            .limit(1)
        )
        if baseline:
            candidates.append((period, baseline))
    if current.previous_close:
        candidates.append(("day", current.previous_close))

    # 在所有越过阈值的周期里，取涨跌幅绝对值最大的作为当日代表异动。
    triggered = [
        (period, baseline, _change(current.price, baseline))
        for period, baseline in candidates
        if abs(_change(current.price, baseline)) >= thresholds[period]
    ]
    if not triggered:
        return []
    period, baseline, change = max(triggered, key=lambda row: abs(row[2]))

    key = _event_key(item.ticker, current.quote_time)
    if db.scalar(select(PriceAlert.id).where(PriceAlert.event_key == key)):
        return []
    alert = PriceAlert(
        event_key=key,
        ticker=item.ticker,
        period=period,
        baseline_price=baseline,
        current_price=current.price,
        change_percent=change,
        triggered_at=current.quote_time,
    )
    db.add(alert)
    db.flush()
    db.add(
        Investigation(
            alert_id=alert.id,
            ticker=item.ticker,
            started_at=current.quote_time,
            ends_at=current.quote_time + timedelta(minutes=runtime["investigation_duration_minutes"]),
            next_search_at=current.quote_time,
            status=InvestigationStatus.active,
        )
    )
    return [alert]
