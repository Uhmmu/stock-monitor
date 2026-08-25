"""Authenticated read-only crypto identity APIs (crypto/quant program WP 1.3).

List/detail/search over persisted canonical identities only. No endpoint
triggers a provider fetch; search results are search hints (typed stable
IDs), never symbol-based resolution authority.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.auth import get_current_user
from app.database import get_db
from app.models import CryptoAsset, CryptoInstrument, CryptoProviderMapping, CryptoSyncState
from app.services.crypto import candles as candle_service
from app.services.crypto import latest as latest_service
from app.services.crypto.identity import (
    asset_display_label,
    instrument_display_label,
)

router = APIRouter(prefix="/api/crypto", dependencies=[Depends(get_current_user)])

MAX_LIST_LIMIT = 100
MAX_SEARCH_RESULTS = 20


class AssetRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    symbol: str
    display_name: str
    asset_kind: str
    status: str


class ProviderMappingEvidence(BaseModel):
    provider: str
    provider_id: str
    method: str
    confidence: float | None = None
    verified_at: str | None = None


class InstrumentOut(BaseModel):
    id: int
    venue: str
    market: str
    provider_symbol: str
    kind: str
    status: str
    calendar: str
    display_label: str
    base_asset: AssetRef
    quote_asset: AssetRef
    settlement_asset: AssetRef | None = None
    tick_size: str | None = None
    step_size: str | None = None
    min_notional: str | None = None
    contract_size: str | None = None
    price_precision: int | None = None
    quantity_precision: int | None = None
    listing_at: str | None = None
    delisting_at: str | None = None


class InstrumentDetailOut(InstrumentOut):
    filters: dict
    provider_mappings: list[ProviderMappingEvidence]


class InstrumentListOut(BaseModel):
    items: list[InstrumentOut]
    total: int
    limit: int
    offset: int


class AssetSearchItem(BaseModel):
    object_type: str = "asset"
    id: int
    slug: str
    symbol: str
    display_name: str
    asset_kind: str
    status: str
    display_label: str


class InstrumentSearchItem(BaseModel):
    object_type: str = "instrument"
    id: int
    venue: str
    market: str
    provider_symbol: str
    kind: str
    status: str
    display_label: str
    base_asset_symbol: str
    quote_asset_symbol: str


class SearchOut(BaseModel):
    query: str
    instruments: list[InstrumentSearchItem]
    assets: list[AssetSearchItem]
    note: str


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _asset_ref(asset: CryptoAsset | None) -> AssetRef | None:
    if asset is None:
        return None
    return AssetRef(
        id=asset.id,
        slug=asset.slug,
        symbol=asset.symbol,
        display_name=asset.display_name,
        asset_kind=asset.asset_kind,
        status=asset.status,
    )


def _instrument_out(instrument: CryptoInstrument, base: CryptoAsset, quote: CryptoAsset, settlement: CryptoAsset | None) -> InstrumentOut:
    return InstrumentOut(
        id=instrument.id,
        venue=instrument.venue,
        market=instrument.market,
        provider_symbol=instrument.provider_symbol,
        kind=instrument.kind,
        status=instrument.status,
        calendar=instrument.calendar,
        display_label=instrument_display_label(instrument, base, quote),
        base_asset=_asset_ref(base),
        quote_asset=_asset_ref(quote),
        settlement_asset=_asset_ref(settlement),
        tick_size=_dec(instrument.tick_size),
        step_size=_dec(instrument.step_size),
        min_notional=_dec(instrument.min_notional),
        contract_size=_dec(instrument.contract_size),
        price_precision=instrument.price_precision,
        quantity_precision=instrument.quantity_precision,
        listing_at=_iso(instrument.listing_at),
        delisting_at=_iso(instrument.delisting_at),
    )


def _instrument_row(db: Session, instrument: CryptoInstrument) -> InstrumentOut:
    return _instrument_out(
        instrument,
        db.get(CryptoAsset, instrument.base_asset_id),
        db.get(CryptoAsset, instrument.quote_asset_id),
        db.get(CryptoAsset, instrument.settlement_asset_id) if instrument.settlement_asset_id else None,
    )


@router.get("/instruments", response_model=InstrumentListOut)
def list_instruments(
    venue: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=20, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(CryptoInstrument)
    if venue:
        query = query.where(CryptoInstrument.venue == venue)
    if kind:
        query = query.where(CryptoInstrument.kind == kind)
    if status:
        query = query.where(CryptoInstrument.status == status)
    if search:
        needle = f"%{search.strip().upper()}%"
        query = query.where(CryptoInstrument.provider_symbol.like(needle))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(CryptoInstrument.venue, CryptoInstrument.kind, CryptoInstrument.provider_symbol).limit(limit).offset(offset)
    )
    return InstrumentListOut(
        items=[_instrument_row(db, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/instruments/{instrument_id}", response_model=InstrumentDetailOut)
def instrument_detail(instrument_id: int, db: Session = Depends(get_db)):
    instrument = db.get(CryptoInstrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument not found")
    base = db.get(CryptoAsset, instrument.base_asset_id)
    quote = db.get(CryptoAsset, instrument.quote_asset_id)
    settlement = db.get(CryptoAsset, instrument.settlement_asset_id) if instrument.settlement_asset_id else None
    mappings = db.scalars(
        select(CryptoProviderMapping).where(
            CryptoProviderMapping.object_type == "instrument",
            CryptoProviderMapping.instrument_id == instrument.id,
        )
    )
    detail = _instrument_out(instrument, base, quote, settlement)
    return InstrumentDetailOut(
        **detail.model_dump(),
        filters=instrument.filters or {},
        provider_mappings=[
            ProviderMappingEvidence(
                provider=m.provider,
                provider_id=m.provider_id,
                method=m.method,
                confidence=m.confidence,
                verified_at=_iso(m.verified_at),
            )
            for m in mappings
        ],
    )


@router.get("/search", response_model=SearchOut)
def search_identities(
    q: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db),
):
    """Typed identity search: stable IDs plus object kind, never resolution."""
    needle = f"%{q.strip().lower()}%"
    symbol_needle = f"{q.strip().upper()}%"

    instruments = db.scalars(
        select(CryptoInstrument)
        .where(
            or_(
                CryptoInstrument.provider_symbol.like(symbol_needle),
                CryptoInstrument.venue.like(needle),
            )
        )
        .order_by(CryptoInstrument.venue, CryptoInstrument.kind, CryptoInstrument.provider_symbol)
        .limit(MAX_SEARCH_RESULTS)
    )
    instrument_items = []
    for instrument in instruments:
        base = db.get(CryptoAsset, instrument.base_asset_id)
        quote = db.get(CryptoAsset, instrument.quote_asset_id)
        instrument_items.append(
            InstrumentSearchItem(
                id=instrument.id,
                venue=instrument.venue,
                market=instrument.market,
                provider_symbol=instrument.provider_symbol,
                kind=instrument.kind,
                status=instrument.status,
                display_label=instrument_display_label(instrument, base, quote),
                base_asset_symbol=base.symbol,
                quote_asset_symbol=quote.symbol,
            )
        )

    assets = db.scalars(
        select(CryptoAsset)
        .where(or_(CryptoAsset.symbol.like(symbol_needle), CryptoAsset.slug.like(needle), CryptoAsset.display_name.like(needle)))
        .order_by(CryptoAsset.slug)
        .limit(MAX_SEARCH_RESULTS)
    )
    asset_items = [
        AssetSearchItem(
            id=asset.id,
            slug=asset.slug,
            symbol=asset.symbol,
            display_name=asset.display_name,
            asset_kind=asset.asset_kind,
            status=asset.status,
            display_label=asset_display_label(asset),
        )
        for asset in assets
    ]
    return SearchOut(
        query=q,
        instruments=instrument_items,
        assets=asset_items,
        note="search results are hints with stable typed IDs; symbols are never identity authority",
    )


class CandleOut(BaseModel):
    open_time_ms: int
    close_time_ms: int
    open: str
    high: str
    low: str
    close: str
    base_volume: str
    quote_volume: str
    taker_buy_base_volume: str | None = None
    taker_buy_quote_volume: str | None = None
    trades: int | None = None
    final: bool
    provider: str
    feed: str
    price_type: str


class CandlesOut(BaseModel):
    instrument_id: int
    interval: str
    items: list[CandleOut]
    coverage: dict
    limit: int


class InstrumentCoverageOut(BaseModel):
    instrument_id: int
    display_label: str
    intervals: dict


class MarketStatusOut(BaseModel):
    instruments: list[InstrumentCoverageOut]
    note: str


@router.get("/market/candles", response_model=CandlesOut)
def read_market_candles(
    instrument_id: int,
    interval: str = Query(pattern="^(1h|4h|1d)$"),
    start_time_ms: int | None = Query(default=None, ge=0),
    end_time_ms: int | None = Query(default=None, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """Bounded chronological read of persisted closed candles only."""
    instrument = db.get(CryptoInstrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument not found")
    rows = candle_service.read_candles(
        db,
        instrument_id=instrument_id,
        interval=interval,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        limit=limit,
    )
    coverage = candle_service.candle_coverage(db, instrument_id=instrument_id, interval=interval)
    return CandlesOut(
        instrument_id=instrument_id,
        interval=interval,
        items=[
            CandleOut(
                open_time_ms=row.open_time_ms,
                close_time_ms=row.close_time_ms,
                open=str(row.open),
                high=str(row.high),
                low=str(row.low),
                close=str(row.close),
                base_volume=str(row.base_volume),
                quote_volume=str(row.quote_volume),
                taker_buy_base_volume=str(row.taker_buy_base_volume) if row.taker_buy_base_volume is not None else None,
                taker_buy_quote_volume=str(row.taker_buy_quote_volume) if row.taker_buy_quote_volume is not None else None,
                trades=row.trades,
                final=row.final,
                provider=row.provider,
                feed=row.feed,
                price_type=row.price_type,
            )
            for row in rows
        ],
        coverage={
            "earliest_open_ms": coverage.earliest_open_ms,
            "latest_open_ms": coverage.latest_open_ms,
            "candle_count": coverage.candle_count,
            "expected_count": coverage.expected_count,
            "missing_count": coverage.missing_count,
        },
        limit=limit,
    )


@router.get("/market/status", response_model=MarketStatusOut)
def market_status(db: Session = Depends(get_db)):
    """Coverage/sync health per instrument; read-only over persisted data."""
    instruments = db.scalars(
        select(CryptoInstrument).where(CryptoInstrument.status == "trading").order_by(CryptoInstrument.id)
    )
    payload = []
    for instrument in instruments:
        base = db.get(CryptoAsset, instrument.base_asset_id)
        quote = db.get(CryptoAsset, instrument.quote_asset_id)
        intervals = {}
        for interval in ("1h", "4h", "1d"):
            coverage = candle_service.candle_coverage(db, instrument_id=instrument.id, interval=interval)
            state = db.scalar(
                select(CryptoSyncState).where(
                    CryptoSyncState.instrument_id == instrument.id,
                    CryptoSyncState.data_kind == "candles",
                    CryptoSyncState.interval == interval,
                )
            )
            intervals[interval] = {
                "candle_count": coverage.candle_count,
                "expected_count": coverage.expected_count,
                "missing_count": coverage.missing_count,
                "earliest_open_ms": coverage.earliest_open_ms,
                "latest_open_ms": coverage.latest_open_ms,
                "last_success_at": _iso(state.last_success_at) if state else None,
                "last_error": state.last_error if state else None,
            }
        payload.append(
            InstrumentCoverageOut(
                instrument_id=instrument.id,
                display_label=instrument_display_label(instrument, base, quote),
                intervals=intervals,
            )
        )
    return MarketStatusOut(
        instruments=payload,
        note="coverage reflects persisted closed candles only; gaps stay explicit",
    )


@router.get("/market/latest")
def latest_market(
    instrument_id: int,
    interval: str = Query(default="1h", pattern="^(1h|4h|1d)$"),
    db: Session = Depends(get_db),
):
    """Latest view with explicit source/age/staleness; cache first, closed-candle fallback."""
    instrument = db.get(CryptoInstrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument not found")
    settings = get_settings()
    return latest_service.latest_market_payload(
        db, instrument=instrument, interval=interval,
        stale_seconds=settings.crypto_latest_stale_seconds,
    )


@router.get("/market/technical")
def crypto_technical(
    instrument_id: int,
    interval: str = Query(default="1d", pattern="^(1h|4h|1d)$"),
    db: Session = Depends(get_db),
):
    """Deterministic indicators over persisted closed candles; gaps stay explicit."""
    from app.services.crypto import technical as crypto_technical_service

    instrument = db.get(CryptoInstrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="instrument not found")
    payload = crypto_technical_service.crypto_technical_payload(
        db, instrument_id=instrument_id, interval=interval
    )
    if payload.get("status") == "invalid":
        raise HTTPException(status_code=422, detail=payload["reason"])
    return payload
