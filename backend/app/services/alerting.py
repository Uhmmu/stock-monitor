import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Investigation, InvestigationStatus, PriceAlert, PriceSnapshot, WatchlistItem


PERIODS = {"20m": timedelta(minutes=20), "1h": timedelta(hours=1)}


def _change(current: float, baseline: float) -> float:
    return (current - baseline) / baseline * 100


def _event_key(ticker: str, period: str, moment: datetime, cooldown: int) -> str:
    bucket = int(moment.timestamp()) // (cooldown * 60)
    return hashlib.sha256(f"{ticker}:{period}:{bucket}".encode()).hexdigest()


def evaluate_quote(db: Session, item: WatchlistItem, current: PriceSnapshot) -> list[PriceAlert]:
    settings = get_settings()
    thresholds = {
        "20m": item.threshold_20m or settings.default_threshold_20m,
        "1h": item.threshold_1h or settings.default_threshold_1h,
        "day": item.threshold_day or settings.default_threshold_day,
    }
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

    alerts: list[PriceAlert] = []
    for period, baseline in candidates:
        change = _change(current.price, baseline)
        if abs(change) < thresholds[period]:
            continue
        key = _event_key(item.ticker, period, current.quote_time, settings.alert_cooldown_minutes)
        if db.scalar(select(PriceAlert.id).where(PriceAlert.event_key == key)):
            continue
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
                ends_at=current.quote_time + timedelta(minutes=settings.investigation_duration_minutes),
                next_search_at=current.quote_time,
                status=InvestigationStatus.active,
            )
        )
        alerts.append(alert)
    return alerts
