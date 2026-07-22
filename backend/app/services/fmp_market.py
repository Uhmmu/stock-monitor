"""Quota-safe FMP profile and EOD history synchronization.

All quota days are UTC. A request is durably reserved before network I/O, so
failures count exactly like upstream attempts and concurrent workers cannot
overspend the configured usable budget.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import CompanyProfile, FmpSyncState, HistoricalPrice

logger = logging.getLogger(__name__)
BUDGET_KEY = ("__budget__", "*", "quota")


class FmpError(RuntimeError):
    code = "upstream_error"


class FmpQuotaExhausted(FmpError):
    code = "quota_exhausted"


class FmpAuthenticationError(FmpError):
    code = "authentication_failure"


class FmpInvalidSymbol(FmpError):
    code = "invalid_symbol"


class FmpMalformedResponse(FmpError):
    code = "malformed_response"


@dataclass(frozen=True)
class BudgetStatus:
    quota_day: date
    used: int
    usable_limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.usable_limit - self.used)


def _usable_limit(config: Settings) -> int:
    return max(0, config.fmp_daily_request_limit - config.fmp_request_reserve)


def budget_status(
    db: Session, *, config: Settings | None = None, now: datetime | None = None
) -> BudgetStatus:
    config, now = config or get_settings(), now or datetime.now(UTC)
    row = db.scalar(
        select(FmpSyncState).where(
            FmpSyncState.task_name == BUDGET_KEY[0],
            FmpSyncState.symbol == BUDGET_KEY[1],
            FmpSyncState.sync_type == BUDGET_KEY[2],
        )
    )
    used = row.requests_used if row and row.quota_day == now.date() else 0
    return BudgetStatus(now.date(), used, _usable_limit(config))


def reserve_request(
    db: Session, *, config: Settings | None = None, now: datetime | None = None
) -> BudgetStatus:
    """Atomically reserve one attempt. Caller must own this short transaction."""
    config, now = config or get_settings(), now or datetime.now(UTC)
    identity = {
        "task_name": BUDGET_KEY[0],
        "symbol": BUDGET_KEY[1],
        "sync_type": BUDGET_KEY[2],
        "status": "ready",
        "quota_day": now.date(),
        "requests_used": 0,
    }
    dialect = db.bind.dialect.name if db.bind else ""
    if dialect == "postgresql":
        db.execute(
            pg_insert(FmpSyncState)
            .values(**identity)
            .on_conflict_do_nothing(index_elements=["task_name", "symbol", "sync_type"])
        )
    elif dialect == "sqlite":
        db.execute(
            sqlite_insert(FmpSyncState)
            .values(**identity)
            .on_conflict_do_nothing(index_elements=["task_name", "symbol", "sync_type"])
        )
    query = (
        select(FmpSyncState)
        .where(
            FmpSyncState.task_name == BUDGET_KEY[0],
            FmpSyncState.symbol == BUDGET_KEY[1],
            FmpSyncState.sync_type == BUDGET_KEY[2],
        )
        .with_for_update()
    )
    row = db.scalar(query)
    if row is None:
        row = FmpSyncState(**identity)
        db.add(row)
        db.flush()
    if row.quota_day != now.date():
        logger.info(
            "[FMP] quota reset quota_day=%s previous_used=%d",
            now.date(),
            row.requests_used,
        )
        row.quota_day, row.requests_used, row.status = now.date(), 0, "ready"
    limit = _usable_limit(config)
    if row.requests_used >= limit:
        row.status = "quota_exhausted"
        db.commit()
        raise FmpQuotaExhausted(f"FMP UTC daily usable budget exhausted ({limit})")
    row.requests_used += 1
    row.last_attempt_at = now
    row.status = "ready"
    db.commit()  # make reservation durable before HTTP
    status = BudgetStatus(now.date(), row.requests_used, limit)
    logger.info(
        "[FMP] request reserved used=%d remaining=%d quota_day=%s",
        status.used,
        status.remaining,
        status.quota_day,
    )
    return status


def request_json(
    db: Session,
    endpoint: str,
    symbol: str,
    *,
    params: dict[str, Any] | None = None,
    config: Settings | None = None,
    now: datetime | None = None,
    http_get: Callable[..., Any] = httpx.get,
) -> Any:
    config = config or get_settings()
    if not config.fmp_sync_enabled or not config.fmp_api_key.strip():
        raise FmpAuthenticationError(
            "FMP synchronization is disabled or API key is missing"
        )
    reserve_request(db, config=config, now=now)
    url = f"{config.fmp_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    safe_params = {**(params or {}), "symbol": symbol, "apikey": config.fmp_api_key}
    logger.info("[FMP] request issued endpoint=%s symbol=%s", endpoint, symbol)
    try:
        response = http_get(
            url, params=safe_params, timeout=config.fmp_request_timeout_seconds
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise FmpError(type(exc).__name__) from exc
    status = response.status_code
    if status in (401, 403):
        raise FmpAuthenticationError(f"FMP HTTP {status}")
    if status == 429:
        row = db.scalar(
            select(FmpSyncState)
            .where(
                FmpSyncState.task_name == BUDGET_KEY[0],
                FmpSyncState.symbol == BUDGET_KEY[1],
                FmpSyncState.sync_type == BUDGET_KEY[2],
            )
            .with_for_update()
        )
        if row:
            row.requests_used, row.status = _usable_limit(config), "quota_exhausted"
            db.commit()
        raise FmpQuotaExhausted("FMP upstream quota/rate limit reached")
    if status == 404:
        raise FmpInvalidSymbol(symbol)
    if status >= 500:
        raise FmpError(f"FMP HTTP {status}")
    if status >= 400:
        raise FmpInvalidSymbol(f"{symbol}: HTTP {status}")
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise FmpMalformedResponse("FMP returned invalid JSON") from exc


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_history(
    payload: Any, symbol: str, *, today: date | None = None
) -> list[dict]:
    rows = payload.get("historical") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise FmpMalformedResponse("historical response is not a list")
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=5 * 366 + 10)
    unique: dict[date, dict] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            day = date.fromisoformat(str(raw.get("date"))[:10])
        except ValueError:
            continue
        o, h, low, close = (
            _decimal(raw.get(key)) for key in ("open", "high", "low", "close")
        )
        volume = _decimal(raw.get("volume"))
        if (
            day < cutoff
            or None in (o, h, low, close)
            or min(o, h, low, close) <= 0
            or h < low
        ):
            continue
        if (
            o > h
            or o < low
            or close > h
            or close < low
            or (volume is not None and volume < 0)
        ):
            continue
        unique[day] = {
            "symbol": symbol.upper(),
            "date": day,
            "open": o,
            "high": h,
            "low": low,
            "close": close,
            "volume": int(volume) if volume is not None else None,
            "vwap": _decimal(raw.get("vwap")),
            "change": _decimal(raw.get("change")),
            "change_percent": _decimal(
                raw.get("changePercent", raw.get("change_percent"))
            ),
            "source": "fmp",
        }
    return [unique[key] for key in sorted(unique)]


def upsert_history(db: Session, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    changed = 0
    for values in rows:
        existing = db.scalar(
            select(HistoricalPrice).where(
                HistoricalPrice.symbol == values["symbol"],
                HistoricalPrice.date == values["date"],
                HistoricalPrice.source == "fmp",
            )
        )
        if existing is None:
            db.add(HistoricalPrice(**values))
            changed += 1
        else:
            different = any(
                getattr(existing, key) != value
                for key, value in values.items()
                if key not in {"symbol", "date", "source"}
            )
            if different:
                for key, value in values.items():
                    if key not in {"symbol", "date", "source"}:
                        setattr(existing, key, value)
                changed += 1
    db.flush()
    return len(rows), changed


def parse_profile(payload: Any, symbol: str) -> dict | None:
    row = (
        payload[0]
        if isinstance(payload, list) and payload
        else payload
        if isinstance(payload, dict)
        else None
    )
    if not row:
        return None
    ipo = None
    try:
        if row.get("ipoDate"):
            ipo = date.fromisoformat(str(row["ipoDate"])[:10])
    except ValueError:
        pass
    employees = row.get("fullTimeEmployees") or row.get("employees")
    try:
        employees = int(employees) if employees not in (None, "") else None
    except (ValueError, TypeError):
        employees = None
    return {
        "symbol": symbol.upper(),
        "company_name": row.get("companyName"),
        "logo_url": row.get("image"),
        "website": row.get("website"),
        "ceo": row.get("ceo"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "country": row.get("country"),
        "exchange": row.get("exchange"),
        "exchange_full_name": row.get("exchangeFullName"),
        "currency": row.get("currency"),
        "ipo_date": ipo,
        "employee_count": employees,
        "description_en": row.get("description"),
    }


def store_profile(
    db: Session, values: dict, *, now: datetime | None = None
) -> tuple[CompanyProfile, bool]:
    now = now or datetime.now(UTC)
    row = db.get(CompanyProfile, values["symbol"])
    created = row is None
    if row is None:
        row = CompanyProfile(symbol=values["symbol"])
        db.add(row)
    old_hash = row.description_source_hash
    for key, value in values.items():
        if key != "symbol":
            setattr(row, key, value)
    row.profile_source, row.profile_fetched_at = "fmp", now
    new_hash = (
        hashlib.sha256((row.description_en or "").encode()).hexdigest()
        if row.description_en
        else None
    )
    changed = new_hash != old_hash
    row.description_source_hash = new_hash
    if changed:
        row.description_zh = None
        row.translation_status = "pending" if new_hash else "unavailable"
        row.translation_attempts = 0
        row.translation_next_retry_at = None
    db.flush()
    return row, created or changed


def checkpoint(
    db: Session,
    task: str,
    symbol: str,
    sync_type: str,
    *,
    status: str,
    now: datetime,
    successful_date: date | None = None,
    error: Exception | None = None,
    position: int = 0,
) -> FmpSyncState:
    row = db.scalar(
        select(FmpSyncState).where(
            FmpSyncState.task_name == task,
            FmpSyncState.symbol == symbol,
            FmpSyncState.sync_type == sync_type,
        )
    )
    if row is None:
        row = FmpSyncState(
            task_name=task, symbol=symbol, sync_type=sync_type, quota_day=now.date()
        )
        db.add(row)
    row.quota_day = now.date()
    row.status, row.last_attempt_at, row.cursor_position = status, now, position
    if status == "completed":
        row.last_success_at, row.last_successful_date = now, successful_date
        (
            row.failure_count,
            row.retry_after,
            row.last_error_code,
            row.last_error_message,
        ) = 0, None, None, None
    elif error:
        # Older or externally-created checkpoint rows may have a NULL counter.
        # Treat that as the initial failure so one bad symbol cannot abort a batch.
        row.failure_count = (row.failure_count or 0) + 1
        row.last_error_code = getattr(error, "code", "temporary_failure")
        row.last_error_message = str(error)[:1000]
        if isinstance(error, FmpQuotaExhausted):
            row.status = "pending_quota"
            row.retry_after = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
            )
        else:
            row.retry_after = now + timedelta(
                minutes=min(360, 2 ** min(row.failure_count, 8))
            )
    db.commit()
    logger.info(
        "[FMP] checkpoint saved task=%s symbol=%s status=%s position=%d",
        task,
        symbol,
        row.status,
        position,
    )
    return row


def sync_history(
    db: Session,
    symbol: str,
    *,
    config: Settings | None = None,
    now: datetime | None = None,
    http_get: Callable[..., Any] = httpx.get,
) -> dict:
    config, now = config or get_settings(), now or datetime.now(UTC)
    latest = db.scalar(
        select(HistoricalPrice.date)
        .where(
            HistoricalPrice.symbol == symbol.upper(), HistoricalPrice.source == "fmp"
        )
        .order_by(HistoricalPrice.date.desc())
        .limit(1)
    )
    params = {}
    if latest:
        params["from"] = (latest - timedelta(days=14)).isoformat()
        params["to"] = now.date().isoformat()
    payload = request_json(
        db,
        "historical-price-eod/full",
        symbol.upper(),
        params=params,
        config=config,
        now=now,
        http_get=http_get,
    )
    rows = parse_history(payload, symbol, today=now.date())
    total, changed = upsert_history(db, rows)
    newest = rows[-1]["date"] if rows else latest
    db.commit()
    logger.info(
        "[FMP] price sync success symbol=%s rows=%d changed=%d latest=%s",
        symbol,
        total,
        changed,
        newest,
    )
    return {
        "received": len(rows),
        "upserted": total,
        "changed": changed,
        "latest": newest,
        "initial": latest is None,
    }


def sync_profile(
    db: Session,
    symbol: str,
    *,
    config: Settings | None = None,
    now: datetime | None = None,
    http_get: Callable[..., Any] = httpx.get,
) -> dict:
    config, now = config or get_settings(), now or datetime.now(UTC)
    payload = request_json(
        db, "profile", symbol.upper(), config=config, now=now, http_get=http_get
    )
    values = parse_profile(payload, symbol)
    if values is None:
        return {"status": "empty"}
    row, translation_needed = store_profile(db, values, now=now)
    db.commit()
    logger.info(
        "[FMP] profile stored symbol=%s translation_needed=%s",
        row.symbol,
        translation_needed,
    )
    return {
        "status": "completed",
        "translation_needed": translation_needed,
        "symbol": row.symbol,
    }
