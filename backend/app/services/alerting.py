import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AppSetting,
    Investigation,
    InvestigationStatus,
    PriceAlert,
    PriceSnapshot,
    UserPriceAlert,
    WatchlistItem,
)


PERIODS = {"20m": timedelta(minutes=20), "1h": timedelta(hours=1)}

# A quote from a different provider without a source-native previous close is
# not enough evidence for an unusually large move.  This protects the alert
# path from thin/one-sided feeds (for example an IEX quote) being compared with
# a delayed consolidated snapshot while still allowing ordinary threshold
# alerts and independently corroborated moves.
_MAX_UNCORROBORATED_CROSS_PROVIDER_MOVE_PCT = 25.0
_CORROBORATION_WINDOW = timedelta(minutes=5)
_CORROBORATION_TOLERANCE_PCT = 5.0


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


def _provider(snapshot: PriceSnapshot) -> str:
    """Return a stable provider name for current and legacy snapshots."""
    return str(getattr(snapshot, "provider", None) or "").strip().lower()


def _has_source_native_evidence(snapshot: PriceSnapshot) -> bool:
    """Whether the provider supplied a usable previous-close anchor."""
    try:
        return snapshot.previous_close is not None and snapshot.previous_close > 0
    except (TypeError, ValueError):
        return False


def _has_recent_corroboration(
    db: Session,
    current: PriceSnapshot,
) -> bool:
    """Find an independent provider agreeing with a large current move.

    The window is deliberately narrow and uses market timestamps, so an old
    baseline cannot accidentally count as corroboration.  A provider different
    from the current snapshot is required; two rows from the same feed do not
    provide independent evidence.
    """
    if current.market_timestamp is None:
        return False
    current_provider = _provider(current)
    if not current_provider:
        return False
    start = current.market_timestamp - _CORROBORATION_WINDOW
    end = current.market_timestamp + _CORROBORATION_WINDOW
    peers = db.scalars(
        select(PriceSnapshot).where(
            PriceSnapshot.symbol == current.symbol,
            PriceSnapshot.market_timestamp >= start,
            PriceSnapshot.market_timestamp <= end,
            PriceSnapshot.last_price > 0,
        )
    ).all()
    for peer in peers:
        if _provider(peer) == current_provider:
            continue
        peer_change = _change(current.last_price, peer.last_price)
        # Compare prices rather than percentage changes against the historical
        # baseline; this remains meaningful when providers use different
        # previous-close conventions.
        if abs(peer_change) <= _CORROBORATION_TOLERANCE_PCT:
            return True
    return False


def _candidate_is_supported(
    db: Session,
    current: PriceSnapshot,
    baseline: PriceSnapshot,
    *,
    change: float,
) -> bool:
    """Reject only an implausible, unsupported cross-provider candidate."""
    if _provider(current) == _provider(baseline):
        return True
    if _has_source_native_evidence(current):
        return True
    if abs(change) <= _MAX_UNCORROBORATED_CROSS_PROVIDER_MOVE_PCT:
        return True
    return _has_recent_corroboration(db, current)


def evaluate_quote(db: Session, item: WatchlistItem, current: PriceSnapshot) -> list[PriceAlert]:
    if current.market_timestamp is None:
        return []
    runtime = _runtime_settings(db)
    thresholds = {
        "20m": item.threshold_20m or runtime["threshold_20m"],
        "1h": item.threshold_1h or runtime["threshold_1h"],
        "day": item.threshold_day or runtime["threshold_day"],
    }
    # 一天一家公司只允许一个异动提醒/调查：当日已有则直接跳过后续任何阈值触发。
    day_start, day_end = _market_day_bounds(current.market_timestamp)
    existing_today = db.scalar(
        select(PriceAlert.id).where(
            PriceAlert.ticker == item.ticker,
            PriceAlert.triggered_at >= day_start,
            PriceAlert.triggered_at < day_end,
        )
    )
    if existing_today:
        return []

    candidates: list[tuple[str, PriceSnapshot | float]] = []
    for period, delta in PERIODS.items():
        baseline = db.scalar(
            select(PriceSnapshot)
            .where(PriceSnapshot.symbol == item.ticker, PriceSnapshot.market_timestamp <= current.market_timestamp - delta)
            .order_by(PriceSnapshot.market_timestamp.desc())
            .limit(1)
        )
        if baseline and baseline.last_price:
            candidates.append((period, baseline))
    if current.previous_close:
        # A source-native previous close is already the strongest available
        # day-level anchor.  Keep the float shape here so the alert payload and
        # existing day-threshold semantics remain unchanged.
        candidates.append(("day", current.previous_close))

    # 在所有越过阈值的周期里，取涨跌幅绝对值最大的作为当日代表异动。
    triggered: list[tuple[str, float, float]] = []
    for period, baseline in candidates:
        baseline_price = baseline.last_price if isinstance(baseline, PriceSnapshot) else baseline
        change = _change(current.last_price, baseline_price)
        if abs(change) < thresholds[period]:
            continue
        if isinstance(baseline, PriceSnapshot) and not _candidate_is_supported(
            db, current, baseline, change=change
        ):
            continue
        triggered.append((period, baseline_price, change))
    if not triggered:
        return []
    period, baseline, change = max(triggered, key=lambda row: abs(row[2]))

    key = _event_key(item.ticker, current.market_timestamp)
    if db.scalar(select(PriceAlert.id).where(PriceAlert.event_key == key)):
        return []
    alert = PriceAlert(
        event_key=key,
        ticker=item.ticker,
        period=period,
        baseline_price=baseline,
        current_price=current.last_price,
        change_percent=change,
        triggered_at=current.market_timestamp,
    )
    db.add(alert)
    db.flush()
    db.add(
        Investigation(
            alert_id=alert.id,
            ticker=item.ticker,
            started_at=current.market_timestamp,
            ends_at=current.market_timestamp + timedelta(minutes=runtime["investigation_duration_minutes"]),
            next_search_at=current.market_timestamp,
            status=InvestigationStatus.active,
        )
    )
    return [alert]


def evaluate_user_price_alerts(
    db: Session, current: PriceSnapshot
) -> list[PriceAlert]:
    """Evaluate user-owned chart target lines using the already-polled quote."""
    if current.market_timestamp is None:
        return []
    rows = db.scalars(
        select(UserPriceAlert).where(
            UserPriceAlert.ticker == current.symbol,
            UserPriceAlert.enabled.is_(True),
            UserPriceAlert.triggered_at.is_(None),
        )
    ).all()
    if not rows:
        return []
    runtime = _runtime_settings(db)
    triggered: list[PriceAlert] = []
    for target in rows:
        crossed = (
            current.last_price >= target.target_price
            if target.direction == "above"
            else current.last_price <= target.target_price
        )
        if not crossed:
            continue
        event_key = hashlib.sha256(f"price-target:{target.id}".encode()).hexdigest()
        existing = db.scalar(
            select(PriceAlert).where(PriceAlert.event_key == event_key)
        )
        alert = existing or PriceAlert(
            event_key=event_key,
            ticker=current.symbol,
            period="price_target",
            baseline_price=target.target_price,
            current_price=current.last_price,
            change_percent=_change(current.last_price, target.target_price),
            triggered_at=current.market_timestamp,
        )
        if existing is None:
            db.add(alert)
            db.flush()
            db.add(
                Investigation(
                    alert_id=alert.id,
                    ticker=current.symbol,
                    started_at=current.market_timestamp,
                    ends_at=current.market_timestamp
                    + timedelta(
                        minutes=runtime["investigation_duration_minutes"]
                    ),
                    next_search_at=current.market_timestamp,
                    status=InvestigationStatus.active,
                )
            )
        target.enabled = False
        target.triggered_at = current.market_timestamp
        target.triggered_price_alert_id = alert.id
        triggered.append(alert)
    return triggered
