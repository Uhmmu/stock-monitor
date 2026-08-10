from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.services.stock_compare import compare_history, compare_symbols, metric_catalog

router = APIRouter(prefix="/api/compare", dependencies=[Depends(get_current_user)])


class CompareRequest(BaseModel):
    symbols: list[str] = Field(min_length=2, max_length=6)


class CompareHistoryRequest(CompareRequest):
    metric_key: str = Field(min_length=1, max_length=64)


@router.get("/metrics")
def compare_metrics():
    return metric_catalog()


@router.post("")
def run_compare(payload: CompareRequest, db: Session = Depends(get_db)):
    try:
        return compare_symbols(db, payload.symbols)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/history")
def run_compare_history(payload: CompareHistoryRequest, db: Session = Depends(get_db)):
    try:
        return compare_history(db, payload.symbols, payload.metric_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
