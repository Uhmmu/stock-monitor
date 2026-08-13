from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.services.options.service import RANK_FIELDS, history_payload, overview_payload, symbol_payload


class QualityOut(BaseModel):
    level: Literal["HIGH", "MEDIUM", "LOW"]
    score: float
    coverage: float
    warnings: list[str]


class OptionSummaryOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    asset_type: str
    status: str
    provider: str
    quality: QualityOut


class OptionsOverviewOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    market: list[OptionSummaryOut]
    sectors: list[dict]
    watchlist: list[OptionSummaryOut]
    rankings: dict[str, list[OptionSummaryOut]]


class OptionDetailOut(OptionSummaryOut):
    expirations: list[date]
    selected_expiration: date | None
    chain: list[dict]
    history: list[dict]


router = APIRouter(prefix="/api/options", dependencies=[Depends(get_current_user)])


@router.get("/overview", response_model=OptionsOverviewOut)
def options_overview(ranking: str = Query("activity"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if ranking not in RANK_FIELDS:
        raise HTTPException(422, "Unsupported options ranking")
    return overview_payload(db, ranking)


@router.get("/symbols/{symbol}", response_model=OptionDetailOut)
def options_symbol(symbol: str, expiration: date | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = symbol_payload(db, symbol, expiration)
    if result is None:
        raise HTTPException(404, "No stored options data for this symbol")
    return result


@router.get("/symbols/{symbol}/history")
def options_history(symbol: str, days: int = Query(365, ge=7, le=730), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return history_payload(db, symbol, days)


__all__ = ["router"]
