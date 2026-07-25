from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.routes import _require_watched_ticker
from app.auth import get_current_user
from app.database import get_db
from app.services.adanos import get_stock_sentiment_insights


router = APIRouter(prefix="/api/sentiment", dependencies=[Depends(get_current_user)])


@router.get("/{ticker}")
async def stock_sentiment(
    ticker: str,
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    symbol = _require_watched_ticker(db, ticker, "sentiment")
    return await get_stock_sentiment_insights(symbol, days)
