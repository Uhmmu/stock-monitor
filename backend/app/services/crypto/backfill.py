"""Historical backfill and ongoing gap repair (crypto/quant program WP 2.4).

REST klines are paged by time ascending from a bounded history window; the
per-instrument watermark makes reruns incremental and restart-safe. Forming
candles are excluded (not errors); unresolved gaps keep the run partial and
are never silently marked complete.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CryptoInstrument, CryptoSyncState
from app.services.crypto import candles as candle_repo
from app.services.crypto.providers.binance import BinancePublicClient, BinancePublicError
from app.services.crypto.semantics import INTERVAL_MODULO_MS

DAY_MS = 86_400_000
KLINE_PAGE_LIMIT = 1000
DEFAULT_HISTORY_DAYS = 365
DEFAULT_MAX_PAGES = 200
DEFAULT_PAGE_PAUSE_SECONDS = 0.15
DEFAULT_FINALIZE_DELAY_MS = 5 * 60_000  # wait 5 min after close before final fetch

PROVIDER_BY_MARKET = {"spot": "binance_spot", "usdm": "binance_usdm"}


class BackfillAborted(Exception):
    pass


@dataclass
class BackfillResult:
    instrument_id: int
    interval: str
    pages: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_forming: int = 0
    rejected: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    error: str | None = None
    status: str = "success"  # success | partial | failed

    def to_payload(self) -> dict:
        return {
            "instrument_id": self.instrument_id,
            "interval": self.interval,
            "status": self.status,
            "pages": self.pages,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_forming": self.skipped_forming,
            "rejected": self.rejected,
            "gaps": self.gaps,
            "warnings": self.warnings,
            "error": self.error,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_sync_state(
    db: Session, *, instrument_id: int, provider: str, data_kind: str, interval: str = ""
) -> CryptoSyncState:
    state = db.scalar(
        select(CryptoSyncState).where(
            CryptoSyncState.instrument_id == instrument_id,
            CryptoSyncState.provider == provider,
            CryptoSyncState.data_kind == data_kind,
            CryptoSyncState.interval == interval,
        )
    )
    if state is None:
        state = CryptoSyncState(
            instrument_id=instrument_id, provider=provider, data_kind=data_kind, interval=interval
        )
        db.add(state)
        db.flush()
    return state


def _advance_watermark(state: CryptoSyncState, open_time_ms: int) -> None:
    if state.watermark_ms is None or open_time_ms > state.watermark_ms:
        state.watermark_ms = open_time_ms


def _due_delay_ms(interval: str) -> int:
    return {"1h": 10 * 60_000, "4h": 10 * 60_000, "1d": 30 * 60_000}.get(interval, 10 * 60_000)


def backfill_instrument_candles(
    db: Session,
    *,
    client: BinancePublicClient,
    instrument: CryptoInstrument,
    interval: str,
    now_ms: int | None = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_pause_seconds: float = DEFAULT_PAGE_PAUSE_SECONDS,
    provider: str | None = None,
    page_limit: int = KLINE_PAGE_LIMIT,
) -> BackfillResult:
    """Backfill and top-up closed candles for one instrument/interval.

    ``page_limit`` matches the provider's per-request cap; smaller values are
    used by tests to exercise pagination edges without 1000-candle fixtures.
    """
    provider = provider or PROVIDER_BY_MARKET.get(instrument.market, f"binance_{instrument.market}")
    modulo = INTERVAL_MODULO_MS[interval]
    now_ms = now_ms if now_ms is not None else int(_utcnow().timestamp() * 1000)
    # only candles whose close is safely in the past are eligible
    latest_closed_open = (now_ms - DEFAULT_FINALIZE_DELAY_MS) // modulo * modulo
    history_start = max(0, (now_ms - history_days * DAY_MS))

    state = get_or_create_sync_state(
        db, instrument_id=instrument.id, provider=provider, data_kind="candles", interval=interval
    )
    state.last_attempt_at = _utcnow()
    result = BackfillResult(instrument_id=instrument.id, interval=interval)

    cursor = history_start if state.watermark_ms is None else max(history_start, state.watermark_ms + modulo)
    try:
        while cursor <= latest_closed_open and result.pages < max_pages:
            klines = client.klines(
                instrument.market,
                instrument.provider_symbol,
                interval,
                start_time_ms=cursor,
                end_time_ms=latest_closed_open,
                limit=page_limit,
            )
            result.pages += 1
            if page_pause_seconds > 0 and result.pages < max_pages:
                time.sleep(page_pause_seconds)
            if not klines:
                break
            closed = [k for k in klines if k.closed]
            result.skipped_forming += len(klines) - len(closed)
            summary = candle_repo.persist_klines(db, instrument_id=instrument.id, provider=provider, klines=closed)
            result.inserted += summary.inserted
            result.updated += summary.updated
            result.unchanged += summary.unchanged
            result.rejected.extend(summary.rejected)
            last_open = klines[-1].open_time_ms
            _advance_watermark(state, last_open)
            # page-level durability: a later page failure keeps earlier pages
            db.commit()
            if len(klines) < page_limit:
                break
            cursor = last_open + modulo
    except BinancePublicError as exc:
        db.rollback()
        result.status = "failed" if result.pages == 0 else "partial"
        result.error = f"{exc.kind}: {exc.message}"
        # rollback removed the in-flight state row; recreate it so the error
        # and persisted watermark survive the failure
        state = get_or_create_sync_state(
            db, instrument_id=instrument.id, provider=provider, data_kind="candles", interval=interval
        )
        state.last_attempt_at = _utcnow()
        state.last_error = result.error

    # restart-safety: recompute watermark from persisted truth
    from app.models import MarketCandle

    persisted_max = db.scalar(
        select(MarketCandle.open_time_ms)
        .where(
            MarketCandle.instrument_id == instrument.id,
            MarketCandle.interval == interval,
            MarketCandle.provider == provider,
        )
        .order_by(MarketCandle.open_time_ms.desc())
        .limit(1)
    )
    if persisted_max is not None:
        state.watermark_ms = persisted_max

    coverage = candle_repo.candle_coverage(db, instrument_id=instrument.id, interval=interval, provider=provider)
    result.gaps = [
        {"start_ms": start, "end_ms": end} for start, end in coverage.missing_ranges
    ]
    if coverage.missing_count > 0:
        if result.status == "success":
            result.status = "partial"
        result.warnings.append(f"{coverage.missing_count} missing candles inside coverage window")

    if result.status == "success":
        state.last_error = None
        state.last_success_at = _utcnow()
        due_ms = now_ms + modulo + _due_delay_ms(interval)
        state.next_due_at = datetime.fromtimestamp(due_ms / 1000, tz=timezone.utc)
    else:
        # failed or partial: error recorded above; retry due soon
        state.last_error = result.error
        state.next_due_at = _utcnow() + timedelta(minutes=15)
    state.missing_count = coverage.missing_count
    db.commit()
    return result


def due_candle_work(
    db: Session,
    *,
    instruments: list[CryptoInstrument],
    intervals: list[str],
    provider_for_market=PROVIDER_BY_MARKET,
    now: datetime | None = None,
) -> list[tuple[CryptoInstrument, str]]:
    """Instruments/interval pairs whose next_due has arrived (or never ran)."""
    now = now or _utcnow()
    work: list[tuple[CryptoInstrument, str]] = []
    for instrument in instruments:
        for interval in intervals:
            provider = provider_for_market.get(instrument.market, f"binance_{instrument.market}")
            state = db.scalar(
                select(CryptoSyncState).where(
                    CryptoSyncState.instrument_id == instrument.id,
                    CryptoSyncState.provider == provider,
                    CryptoSyncState.data_kind == "candles",
                    CryptoSyncState.interval == interval,
                )
            )
            if state is None:
                work.append((instrument, interval))
                continue
            if state.next_due_at is None:
                work.append((instrument, interval))
                continue
            due_at = state.next_due_at
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            if due_at <= now:
                work.append((instrument, interval))
    return work


def sync_candles_for_universe(
    db: Session,
    *,
    client: BinancePublicClient,
    instruments: list[CryptoInstrument],
    intervals: list[str],
    history_days: int = DEFAULT_HISTORY_DAYS,
    max_pages_per_instrument: int = DEFAULT_MAX_PAGES,
) -> list[dict]:
    """Per-instrument isolated backfill loop; one failure never aborts others."""
    payloads: list[dict] = []
    for instrument in instruments:
        for interval in intervals:
            if interval not in INTERVAL_MODULO_MS:
                payloads.append(
                    {"instrument_id": instrument.id, "interval": interval, "status": "failed", "error": "unsupported interval"}
                )
                continue
            try:
                result = backfill_instrument_candles(
                    db,
                    client=client,
                    instrument=instrument,
                    interval=interval,
                    history_days=history_days,
                    max_pages=max_pages_per_instrument,
                )
                payloads.append(result.to_payload())
            except Exception as exc:  # isolation boundary: log and continue
                payloads.append(
                    {"instrument_id": instrument.id, "interval": interval, "status": "failed", "error": str(exc)[:300]}
                )
    return payloads
