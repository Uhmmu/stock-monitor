from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models import MacroApiUsage, MacroObservation, MacroSeries, MacroSyncRun

from .definitions import RAW_SERIES, SOURCE_NAME, get_series_definition
from .normalizer import MacroObservationInput, normalize_provider_rows
from .provider import AlphaVantageError, AlphaVantageRateLimitError, AlphaVantageMacroProvider

logger = logging.getLogger(__name__)
PROVIDER = "alpha_vantage"
LOCK_KEY = "stock-monitor:macro:alpha-vantage-sync"
ACTIVE_RUN_MAX_AGE = timedelta(hours=2)


class MacroQuotaExceeded(RuntimeError):
    code = "daily_budget_exhausted"


class MacroSyncAlreadyRunning(RuntimeError):
    code = "sync_already_running"


@dataclass(frozen=True)
class MacroUsageStatus:
    usage_date_utc: date
    used: int
    successful: int
    failed: int
    rate_limited: int
    daily_limit: int
    reserved_requests: int

    @property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.used)

    @property
    def automatic_remaining(self) -> int:
        return max(0, self.daily_limit - self.reserved_requests - self.used)

    def as_dict(self) -> dict[str, Any]:
        return {
            "usage_date_utc": self.usage_date_utc,
            "used": self.used,
            "successful": self.successful,
            "failed": self.failed,
            "rate_limited": self.rate_limited,
            "daily_limit": self.daily_limit,
            "reserved_requests": self.reserved_requests,
            "remaining": self.remaining,
            "automatic_remaining": self.automatic_remaining,
            "automatic_usable_limit": max(0, self.daily_limit - self.reserved_requests),
        }


def _usage_row(db, today: date | None = None) -> MacroApiUsage:
    today = today or datetime.now(UTC).date()
    row = db.scalar(select(MacroApiUsage).where(MacroApiUsage.provider == PROVIDER, MacroApiUsage.usage_date_utc == today))
    if row:
        return row
    row = MacroApiUsage(provider=PROVIDER, usage_date_utc=today)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        row = db.scalar(select(MacroApiUsage).where(MacroApiUsage.provider == PROVIDER, MacroApiUsage.usage_date_utc == today))
        if row is None:
            raise
    return row


def usage_status(db, settings: Settings | None = None) -> MacroUsageStatus:
    settings = settings or get_settings()
    row = db.scalar(select(MacroApiUsage).where(
        MacroApiUsage.provider == PROVIDER,
        MacroApiUsage.usage_date_utc == datetime.now(UTC).date(),
    ))
    return MacroUsageStatus(
        usage_date_utc=datetime.now(UTC).date(),
        used=row.request_count if row else 0,
        successful=row.successful_count if row else 0,
        failed=row.failed_count if row else 0,
        rate_limited=row.rate_limited_count if row else 0,
        daily_limit=max(0, int(settings.alpha_vantage_daily_request_limit)),
        reserved_requests=max(0, int(settings.alpha_vantage_reserved_requests)),
    )


def _allowed_limit(settings: Settings, trigger_type: str) -> int:
    total = max(0, int(settings.alpha_vantage_daily_request_limit))
    reserve = max(0, int(settings.alpha_vantage_reserved_requests))
    # Scheduled automation never spends the protected reserve. Manual admin
    # actions may use it after an explicit click, but never exceed the total.
    return max(0, total - reserve) if trigger_type == "scheduled" else total


def reserve_request(db, settings: Settings | None = None, *, trigger_type: str = "manual") -> MacroUsageStatus:
    settings = settings or get_settings()
    row = _usage_row(db)
    limit = _allowed_limit(settings, trigger_type)
    if row.request_count >= limit:
        raise MacroQuotaExceeded(f"Alpha Vantage daily protection limit reached ({limit} requests)")
    row.request_count += 1
    row.last_request_at = datetime.now(UTC)
    db.flush()
    return usage_status(db, settings)


def mark_request_result(db, *, error_code: str | None = None) -> None:
    row = _usage_row(db)
    if error_code is None:
        row.successful_count += 1
    else:
        row.failed_count += 1
        if error_code == "rate_limit":
            row.rate_limited_count += 1
    row.updated_at = datetime.now(UTC)
    db.flush()


def ensure_series_definitions(db) -> dict[str, MacroSeries]:
    rows = {row.series_key: row for row in db.scalars(select(MacroSeries).where(MacroSeries.provider == PROVIDER)).all()}
    changed = False
    for definition in RAW_SERIES:
        row = rows.get(definition["series_key"])
        if row is None:
            row = MacroSeries(
                series_key=definition["series_key"], provider=PROVIDER,
                provider_function=definition["provider_function"],
                provider_parameters_json=definition["provider_parameters"], country_code="US",
                display_name_zh=definition["display_name_zh"], display_name_en=definition["display_name_en"],
                description_zh=definition["description_zh"], unit=definition["unit"], frequency=definition["frequency"],
                category=definition["category"], source_name=definition.get("source_name", SOURCE_NAME),
                is_derived=False, enabled=True,
            )
            db.add(row)
            rows[row.series_key] = row
            changed = True
    if changed:
        db.flush()
    return rows


def _acquire_redis_lock(settings: Settings):
    """Best-effort distributed lock; DB active-run check remains the fallback."""
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        lock = client.lock(LOCK_KEY, timeout=45 * 60, blocking=False)
        if lock.acquire(blocking=False):
            return lock
    except Exception:
        logger.debug("macro sync Redis lock unavailable", exc_info=True)
    return None


def _active_run(db) -> MacroSyncRun | None:
    cutoff = datetime.now(UTC) - ACTIVE_RUN_MAX_AGE
    return db.scalar(select(MacroSyncRun).where(
        MacroSyncRun.provider == PROVIDER,
        MacroSyncRun.status == "running",
        MacroSyncRun.started_at >= cutoff,
    ).order_by(MacroSyncRun.started_at.desc()))


def can_start_sync(db, count: int, *, trigger_type: str = "manual", settings: Settings | None = None) -> tuple[bool, str | None]:
    settings = settings or get_settings()
    if _active_run(db):
        return False, MacroSyncAlreadyRunning.code
    status = usage_status(db, settings)
    remaining = status.automatic_remaining if trigger_type == "scheduled" else status.remaining
    if count > remaining:
        return False, MacroQuotaExceeded.code
    return True, None


def _persist_observations(db, series: MacroSeries, inputs: list[MacroObservationInput], fetched_at: datetime) -> tuple[int, int, int]:
    inserted = updated = unchanged = 0
    for item in inputs:
        existing = db.scalar(select(MacroObservation).where(
            MacroObservation.series_id == series.id,
            MacroObservation.observation_date == item.observation_date,
        ))
        if existing is None:
            db.add(MacroObservation(
                series_id=series.id, observation_date=item.observation_date,
                value=item.value, raw_value=item.value, unit=item.unit, provider=item.provider,
                source_name=item.source_name, metadata_json=item.metadata,
                first_fetched_at=fetched_at, last_fetched_at=fetched_at,
            ))
            inserted += 1
            continue
        if Decimal(str(existing.value)) != item.value:
            existing.value = item.value
            existing.raw_value = item.value
            existing.revision_number = int(existing.revision_number or 0) + 1
            updated += 1
        else:
            unchanged += 1
        existing.unit = item.unit
        existing.provider = item.provider
        existing.source_name = item.source_name
        existing.metadata_json = item.metadata
        existing.last_fetched_at = fetched_at
    return inserted, updated, unchanged


async def run_macro_sync(
    db,
    *,
    series_keys: list[str] | None = None,
    trigger_type: str = "scheduled",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    requested = list(dict.fromkeys(series_keys or [row["series_key"] for row in RAW_SERIES]))
    valid = {row["series_key"] for row in RAW_SERIES}
    requested = [key for key in requested if key in valid]
    if not requested:
        return {"status": "invalid_request", "requested_series_count": 0, "errors": {"series": "no valid series selected"}}
    if not settings.alpha_vantage_enabled or not settings.alpha_vantage_api_key.strip():
        return {"status": "not_configured", "requested_series_count": len(requested), "errors": {"provider": "Alpha Vantage 宏观数据源未配置"}}

    redis_lock = _acquire_redis_lock(settings)
    if _active_run(db):
        if redis_lock:
            with suppress(Exception): redis_lock.release()
        raise MacroSyncAlreadyRunning("a macro sync is already running")

    series_map = ensure_series_definitions(db)
    run = MacroSyncRun(
        provider=PROVIDER, status="running", trigger_type=trigger_type,
        requested_series_count=len(requested), error_summary_json={},
    )
    db.add(run)
    db.commit()
    provider = AlphaVantageMacroProvider(settings)
    errors: dict[str, dict[str, str]] = {}
    successful = 0
    inserted = updated = unchanged = used = 0
    try:
        async with provider:
            for key in requested:
                definition = get_series_definition(key)
                series = series_map[key]
                try:
                    reserve_request(db, settings, trigger_type=trigger_type)
                    used += 1
                    run.api_requests_used = used
                    db.commit()
                    payload = await provider.fetch_series(definition["provider_function"], **definition["provider_parameters"])
                    normalized, missing_count = normalize_provider_rows(
                        key, payload.get("data", []), unit=definition["unit"],
                        source_name=definition.get("source_name", SOURCE_NAME),
                    )
                    if not normalized:
                        raise ValueError("provider returned no usable observations")
                    fetched_at = datetime.now(UTC)
                    i_count, u_count, n_count = _persist_observations(db, series, normalized, fetched_at)
                    mark_request_result(db)
                    inserted += i_count; updated += u_count; unchanged += n_count
                    run.inserted_count = inserted; run.updated_count = updated; run.unchanged_count = unchanged
                    run.successful_series_count = successful + 1
                    if missing_count:
                        errors.setdefault("warnings", {})[key] = f"filtered {missing_count} missing provider values"
                    successful += 1
                    db.commit()
                except MacroQuotaExceeded as exc:
                    errors[key] = {"code": exc.code, "message": str(exc)}
                    run.failed_series_count = len([k for k in errors if k in valid])
                    db.commit()
                    break
                except Exception as exc:
                    db.rollback()
                    # The request was reserved before the provider call. Do
                    # not lose that accounting when persisting a failed item.
                    try:
                        mark_request_result(db, error_code=getattr(exc, "code", "provider_error"))
                        run = db.get(MacroSyncRun, run.id)
                        errors[key] = {"code": getattr(exc, "code", "provider_error"), "message": " ".join(str(exc).split())[:240]}
                        run.failed_series_count = len([k for k in errors if k in valid])
                        run.api_requests_used = used
                        db.commit()
                    except Exception:
                        db.rollback()
                        logger.exception("Failed to persist macro sync error for %s", key)
    finally:
        run = db.get(MacroSyncRun, run.id)
        if run:
            run.finished_at = datetime.now(UTC)
            run.status = "success" if successful == len(requested) else "partial_success" if successful else "failed"
            run.successful_series_count = successful
            run.failed_series_count = len([key for key in requested if key in errors])
            run.api_requests_used = used
            run.inserted_count = inserted
            run.updated_count = updated
            run.unchanged_count = unchanged
            run.error_summary_json = errors
            db.commit()
        with suppress(Exception):
            await provider.aclose()
        if redis_lock:
            with suppress(Exception):
                redis_lock.release()
    return {
        "status": run.status if run else "failed", "run_id": run.id if run else None,
        "requested_series_count": len(requested), "successful_series_count": successful,
        "failed_series_count": len([key for key in requested if key in errors]),
        "api_requests_used": used, "inserted_count": inserted, "updated_count": updated,
        "unchanged_count": unchanged, "errors": errors,
    }


def run_macro_sync_task(series_keys: list[str] | None = None, trigger_type: str = "scheduled") -> dict[str, Any]:
    with SessionLocal() as db:
        return asyncio.run(run_macro_sync(db, series_keys=series_keys, trigger_type=trigger_type))
