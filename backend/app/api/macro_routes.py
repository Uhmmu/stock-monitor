from __future__ import annotations

import asyncio
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_admin_user, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import MacroSyncRun, User
from app.services.macro.definitions import RAW_SERIES
from app.services.macro.provider import AlphaVantageError, AlphaVantageMacroProvider
from app.services.macro.sync import (
    MacroQuotaExceeded,
    MacroSyncAlreadyRunning,
    can_start_sync,
    mark_request_result,
    reserve_request,
    usage_status,
)
from app.services.macro.views import (
    build_explanation,
    build_overview,
    build_series_detail,
    build_series_list,
    build_sync_status,
    build_yield_curve,
)


router = APIRouter(prefix="/api/fundamentals/macro/us", dependencies=[Depends(get_current_user)])
admin_router = APIRouter(prefix="/api/admin/integrations/alpha-vantage", dependencies=[Depends(get_admin_user)])


class MacroSyncRequest(BaseModel):
    mode: str = Field(default="full", pattern="^(full|selected)$")
    series_keys: list[str] = Field(default_factory=list, max_length=14)
    force: bool = False

    @model_validator(mode="after")
    def validate_keys(self):
        if self.mode == "selected" and not self.series_keys:
            raise ValueError("selected mode requires at least one series key")
        self.series_keys = list(dict.fromkeys(value.strip() for value in self.series_keys if value.strip()))
        return self


@router.get("/overview")
def macro_overview(db: Session = Depends(get_db)):
    return build_overview(db)


@router.get("/series")
def macro_series(
    category: str | None = Query(default=None, max_length=32),
    frequency: str | None = Query(default=None, max_length=16),
    enabled: bool | None = None,
    db: Session = Depends(get_db),
):
    return build_series_list(db, category=category, frequency=frequency, enabled=enabled)


@router.get("/series/{series_key}")
def macro_series_detail(
    series_key: str,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=2500),
    db: Session = Depends(get_db),
):
    result = build_series_detail(db, series_key, start_date=start_date, end_date=end_date, limit=limit)
    if result is None:
        raise HTTPException(404, "未知宏观指标")
    return result


@router.get("/yield-curve")
def macro_yield_curve(db: Session = Depends(get_db)):
    return build_yield_curve(db)


@router.get("/series/{series_key}/explanation")
def macro_explanation(series_key: str, db: Session = Depends(get_db)):
    result = build_explanation(db, series_key)
    if result is None:
        raise HTTPException(404, "未知宏观指标")
    return result


@router.get("/sync-status")
def macro_sync_status(db: Session = Depends(get_db)):
    return build_sync_status(db)


async def _test_provider() -> dict:
    async with AlphaVantageMacroProvider() as provider:
        return await provider.test_connection()


@admin_router.post("/test")
def test_alpha_vantage_connection(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    del admin
    settings = get_settings()
    if not settings.alpha_vantage_enabled or not settings.alpha_vantage_api_key.strip():
        raise HTTPException(400, "Alpha Vantage 未启用或 API key 未配置")
    try:
        reserve_request(db, settings, trigger_type="manual")
        db.commit()
    except MacroQuotaExceeded as exc:
        db.rollback()
        raise HTTPException(429, "今日 Alpha Vantage 项目侧额度不足") from exc
    started = time.monotonic()
    try:
        result = asyncio.run(_test_provider())
        mark_request_result(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        code = getattr(exc, "code", "provider_error")
        # The reservation was committed before the network call. Re-open the
        # session state so failed test calls remain counted.
        try:
            mark_request_result(db, error_code=code)
            db.commit()
        except Exception:
            db.rollback()
        if isinstance(exc, AlphaVantageError):
            raise HTTPException(502, {"status": "failed", "error_code": code, "message": str(exc)}) from exc
        raise HTTPException(502, "Alpha Vantage 连接测试失败") from exc
    return {"status": "ok", "response_ms": round((time.monotonic() - started) * 1000), "provider": "alpha_vantage", "result": result, "usage": usage_status(db, settings).as_dict()}


@admin_router.post("/macro/sync", status_code=status.HTTP_202_ACCEPTED)
def queue_macro_sync(payload: MacroSyncRequest, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    del admin
    settings = get_settings()
    requested = payload.series_keys if payload.mode == "selected" else None
    valid_keys = {row["series_key"] for row in RAW_SERIES}
    if requested and any(key not in valid_keys for key in requested):
        raise HTTPException(422, "series_keys 包含未知宏观指标")
    count = len(requested or RAW_SERIES)
    allowed, reason = can_start_sync(db, count, trigger_type="manual", settings=settings)
    if not allowed:
        if reason == MacroSyncAlreadyRunning.code:
            raise HTTPException(409, "宏观同步任务正在运行")
        raise HTTPException(429, "今日 Alpha Vantage 项目侧额度不足")
    from app.tasks.celery_app import sync_us_macro

    task = sync_us_macro.delay(requested, "manual")
    return {"status": "queued", "task_id": task.id, "requested_series_count": count, "force": payload.force, "usage": usage_status(db, settings).as_dict()}
