"""Crypto collection jobs (crypto/quant program WP 2.2+).

Domain logic for durable, idempotent provider syncs. Thin Celery task
declarations live in ``app.tasks.celery_app``; everything here is plain
Python + Session so tests run without a broker.

Identity rules from WP 0.3 still apply: base/quote assets resolve only
through explicit provider mappings seeded in ``CORE_IDENTITY_SEEDS`` (an
audited, reviewable list). Anything outside it stays unresolved and the
instrument is skipped — never guessed from symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CryptoCollectionRun, CryptoInstrument
from app.services.crypto import identity
from app.services.crypto.providers.binance import (
    BinancePublicClient,
    BinancePublicError,
    ExchangeInfoSymbol,
)

PROVIDER_BINANCE = "binance"
PROVIDER_BINANCE_USDM = identity.PROVIDER_BINANCE_USDM

# Explicit, audited seed of canonical assets used by the configured spot
# universe. Provider asset ids (binance_spot:BTC) map to exactly these
# canonical rows; anything else remains unresolved until manually mapped.
CORE_IDENTITY_SEEDS = [
    {"slug": "bitcoin", "symbol": "BTC", "display_name": "Bitcoin", "asset_kind": "coin",
     "aliases": [{"symbol": "XBT", "reason": "ISO 4217-style historical ticker"}]},
    {"slug": "ethereum", "symbol": "ETH", "display_name": "Ether", "asset_kind": "coin", "aliases": []},
    {"slug": "cardano", "symbol": "ADA", "display_name": "Cardano", "asset_kind": "coin", "aliases": []},
    {"slug": "tether-usd", "symbol": "USDT", "display_name": "Tether USD", "asset_kind": "token", "aliases": []},
]

DEFAULT_EXCHANGE_INFO_REFRESH = timedelta(hours=6)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_spot_universe(raw: str) -> list[str]:
    """Comma-separated venue symbols, uppercased, deduplicated, bounded."""
    seen: list[str] = []
    for token in raw.split(","):
        symbol = token.strip().upper()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return seen[:50]


def parse_usdm_universe(raw: str) -> list[str]:
    """Bounded USD-M symbol list; kept separate to avoid spot/product mixing."""
    return parse_spot_universe(raw)


def ensure_core_identity_seed(db: Session) -> dict:
    """Idempotently create the audited core assets and their Binance mappings."""
    created_assets = 0
    created_mappings = 0
    for seed in CORE_IDENTITY_SEEDS:
        asset, created = identity.get_or_create_asset(
            db,
            slug=seed["slug"],
            symbol=seed["symbol"],
            display_name=seed["display_name"],
            asset_kind=seed["asset_kind"],
        )
        created_assets += int(created)
        for alias in seed["aliases"]:
            identity.set_symbol_alias(db, symbol=alias["symbol"], asset=asset, reason=alias["reason"])
        _, mapping_created = identity._seed_provider_mapping(
            db, provider=identity.PROVIDER_BINANCE_SPOT, provider_id=seed["symbol"], asset=asset
        )
        created_mappings += int(mapping_created)
    db.flush()
    return {"assets_created": created_assets, "mappings_created": created_mappings}


def ensure_usdm_identity_seed(db: Session) -> dict:
    """Seed the same audited assets in the distinct USD-M namespace."""
    assets_created = 0
    mappings_created = 0
    for seed in CORE_IDENTITY_SEEDS:
        asset = identity.get_asset_by_slug(db, seed["slug"])
        if asset is None:
            asset, created = identity.get_or_create_asset(
                db,
                slug=seed["slug"],
                symbol=seed["symbol"],
                display_name=seed["display_name"],
                asset_kind=seed["asset_kind"],
            )
            assets_created += int(created)
        _, created = identity._seed_provider_mapping(
            db,
            provider=PROVIDER_BINANCE_USDM,
            provider_id=seed["symbol"],
            asset=asset,
        )
        mappings_created += int(created)
    db.flush()
    return {"assets_created": assets_created, "mappings_created": mappings_created}


@dataclass
class SyncResult:
    status: str
    items_seen: int
    items_created: int
    items_updated: int
    unresolved_count: int
    excluded: list
    unresolved: list
    error: str | None = None


def _claim_run(db: Session, *, provider: str, domain: str, bucket: str) -> CryptoCollectionRun | None:
    """Claim this bucket's run row; None when the bucket is already claimed."""
    existing = db.scalar(
        select(CryptoCollectionRun).where(
            CryptoCollectionRun.provider == provider,
            CryptoCollectionRun.domain == domain,
            CryptoCollectionRun.bucket == bucket,
        )
    )
    if existing is not None:
        return None
    run = CryptoCollectionRun(
        provider=provider,
        domain=domain,
        bucket=bucket,
        status="running",
        heartbeat_at=_utcnow(),
    )
    db.add(run)
    db.flush()
    return run


def _finish_run(
    db: Session,
    run: CryptoCollectionRun,
    result: SyncResult,
) -> CryptoCollectionRun:
    run.status = result.status
    run.finished_at = _utcnow()
    run.items_seen = result.items_seen
    run.items_created = result.items_created
    run.items_updated = result.items_updated
    run.unresolved_count = result.unresolved_count
    run.error_message = result.error
    run.details = {
        "excluded": result.excluded,
        "unresolved": result.unresolved,
    }
    return run


def latest_successful_run(db: Session, *, provider: str, domain: str) -> CryptoCollectionRun | None:
    return db.scalar(
        select(CryptoCollectionRun)
        .where(
            CryptoCollectionRun.provider == provider,
            CryptoCollectionRun.domain == domain,
            CryptoCollectionRun.status == "success",
        )
        .order_by(CryptoCollectionRun.started_at.desc())
        .limit(1)
    )


def spot_exchange_info_due(db: Session, *, refresh_interval: timedelta = DEFAULT_EXCHANGE_INFO_REFRESH) -> bool:
    latest = latest_successful_run(db, provider=PROVIDER_BINANCE, domain="spot_exchange_info")
    if latest is None or latest.finished_at is None:
        return True
    finished = latest.finished_at
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return _utcnow() - finished >= refresh_interval


def usdm_exchange_info_due(db: Session, *, refresh_interval: timedelta = DEFAULT_EXCHANGE_INFO_REFRESH) -> bool:
    latest = latest_successful_run(db, provider=PROVIDER_BINANCE_USDM, domain="usdm_exchange_info")
    if latest is None or latest.finished_at is None:
        return True
    finished = latest.finished_at
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return _utcnow() - finished >= refresh_interval


def _instrument_kwargs(raw: ExchangeInfoSymbol) -> dict:
    filters = raw.filters or {}
    price_filter = filters.get("PRICE_FILTER", {})
    lot_filter = filters.get("LOT_SIZE", {})
    notional = filters.get("MIN_NOTIONAL", {})
    return {
        "tick_size": price_filter.get("tickSize"),
        "step_size": lot_filter.get("stepSize"),
        "min_notional": notional.get("notional") or notional.get("minNotional"),
        "contract_size": raw.contract_size,
        "price_precision": raw.price_precision if raw.price_precision is not None else raw.quote_asset_precision,
        "quantity_precision": raw.quantity_precision if raw.quantity_precision is not None else raw.base_asset_precision,
        "filters": filters,
    }


def sync_spot_exchange_info(
    db: Session,
    *,
    client: BinancePublicClient,
    universe: list[str],
    bucket: str | None = None,
) -> SyncResult | None:
    """Create/update spot instruments from exchangeInfo, exactly once per bucket.

    Returns None when the bucket is already claimed (idempotent beat ticks).
    Assets resolve only through the seeded provider mappings; unresolved
    assets skip the instrument and are reported, never guessed.
    """
    if bucket is None:
        bucket = _utcnow().strftime("%Y%m%d%H")  # hourly claim bucket, due check throttles cadence
    run = _claim_run(db, provider=PROVIDER_BINANCE, domain="spot_exchange_info", bucket=bucket)
    if run is None:
        return None

    ensure_core_identity_seed(db)

    seen = created = updated = 0
    excluded: list[dict] = []
    unresolved: list[dict] = []
    try:
        info = client.exchange_info("spot")
    except BinancePublicError as exc:
        _finish_run(
            db, run,
            SyncResult("failed", 0, 0, 0, 0, [], [], error=f"{exc.kind}: {exc.message}"),
        )
        db.commit()
        return SyncResult("failed", 0, 0, 0, 0, [], [], error=f"{exc.kind}: {exc.message}")

    by_symbol = {s.provider_symbol: s for s in info.symbols}
    for symbol in universe:
        raw = by_symbol.get(symbol)
        if raw is None:
            excluded.append({"symbol": symbol, "reason": "not_present_in_exchange_info"})
            continue
        seen += 1
        base = identity.resolve_provider_id(
            db, provider=identity.PROVIDER_BINANCE_SPOT, object_type="asset", provider_id=raw.base_asset
        )
        quote = identity.resolve_provider_id(
            db, provider=identity.PROVIDER_BINANCE_SPOT, object_type="asset", provider_id=raw.quote_asset
        )
        if not (base.resolved and base.asset) or not (quote.resolved and quote.asset):
            unresolved.append(
                {
                    "symbol": symbol,
                    "reason": "base/quote asset mapping unresolved",
                    "base": raw.base_asset if not base.resolved else None,
                    "quote": raw.quote_asset if not quote.resolved else None,
                }
            )
            continue
        instrument, was_created = identity.upsert_instrument(
            db,
            venue="binance",
            market="spot",
            provider_symbol=symbol,
            kind="spot",
            base_asset=base.asset,
            quote_asset=quote.asset,
            status=raw.status,
            **_instrument_kwargs(raw),
        )
        created += int(was_created)
        updated += int(not was_created)
        identity._seed_provider_mapping(
            db, provider=identity.PROVIDER_BINANCE_SPOT, provider_id=symbol, instrument=instrument
        )

    status = "success" if not unresolved and not excluded else "partial"
    result = SyncResult(
        status=status,
        items_seen=seen,
        items_created=created,
        items_updated=updated,
        unresolved_count=len(unresolved),
        excluded=excluded,
        unresolved=unresolved,
    )
    _finish_run(db, run, result)
    db.commit()
    return result


def sync_usdm_exchange_info(
    db: Session,
    *,
    client: BinancePublicClient,
    universe: list[str] | None = None,
    bucket: str | None = None,
) -> SyncResult | None:
    """Synchronize exact USD-M perpetual products without touching Spot rows."""
    if bucket is None:
        bucket = _utcnow().strftime("%Y%m%d%H")
    run = _claim_run(
        db,
        provider=PROVIDER_BINANCE_USDM,
        domain="usdm_exchange_info",
        bucket=bucket,
    )
    if run is None:
        return None

    try:
        info = client.exchange_info("usdm")
    except BinancePublicError as exc:
        result = SyncResult("failed", 0, 0, 0, 0, [], [], error=f"{exc.kind}: {exc.message}")
        _finish_run(db, run, result)
        db.commit()
        return result

    ensure_usdm_identity_seed(db)
    by_symbol = {s.provider_symbol: s for s in info.symbols}
    requested: list[str] = []
    for value in universe or []:
        symbol = value.strip().upper()
        if symbol and symbol not in requested:
            requested.append(symbol)
    requested = requested[:50]
    if not requested:
        requested = [s.provider_symbol for s in info.symbols if s.kind == "perpetual"]

    seen = created = updated = 0
    excluded: list[dict] = []
    unresolved: list[dict] = []
    for symbol in requested:
        raw = by_symbol.get(symbol)
        if raw is None:
            excluded.append({"symbol": symbol, "reason": "not_present_in_exchange_info"})
            continue
        if raw.kind != "perpetual":
            excluded.append({"symbol": symbol, "reason": "not_perpetual"})
            continue
        seen += 1

        base = identity.resolve_provider_id(
            db,
            provider=PROVIDER_BINANCE_USDM,
            object_type="asset",
            provider_id=raw.base_asset,
        )
        quote = identity.resolve_provider_id(
            db,
            provider=PROVIDER_BINANCE_USDM,
            object_type="asset",
            provider_id=raw.quote_asset,
        )
        settlement_id = raw.margin_asset
        settlement = (
            identity.resolve_provider_id(
                db,
                provider=PROVIDER_BINANCE_USDM,
                object_type="asset",
                provider_id=settlement_id,
            )
            if settlement_id
            else None
        )
        missing = {
            label: value
            for label, value in (
                ("base", raw.base_asset if not base.resolved else None),
                ("quote", raw.quote_asset if not quote.resolved else None),
                ("settlement", settlement_id if settlement is None or not settlement.resolved else None),
            )
            if value is not None
        }
        if missing:
            unresolved.append(
                {
                    "symbol": symbol,
                    "reason": "base/quote/settlement asset mapping unresolved",
                    **missing,
                }
            )
            continue

        instrument, was_created = identity.upsert_instrument(
            db,
            venue="binance",
            market="usdm_futures",
            provider_symbol=symbol,
            kind="perpetual",
            base_asset=base.asset,
            quote_asset=quote.asset,
            settlement_asset=settlement.asset if settlement else None,
            listing_at=(
                datetime.fromtimestamp(raw.onboard_date_ms / 1000, tz=timezone.utc)
                if raw.onboard_date_ms is not None
                else None
            ),
            delisting_at=(
                datetime.fromtimestamp(raw.delivery_date_ms / 1000, tz=timezone.utc)
                if raw.delivery_date_ms is not None
                else None
            ),
            **_instrument_kwargs(raw),
            status=raw.status,
        )
        created += int(was_created)
        updated += int(not was_created)
        identity._seed_provider_mapping(
            db,
            provider=PROVIDER_BINANCE_USDM,
            provider_id=symbol,
            instrument=instrument,
        )

    status = "success" if not unresolved and not excluded else "partial"
    result = SyncResult(
        status=status,
        items_seen=seen,
        items_created=created,
        items_updated=updated,
        unresolved_count=len(unresolved),
        excluded=excluded,
        unresolved=unresolved,
    )
    _finish_run(db, run, result)
    db.commit()
    return result


def instrument_sync_state(db: Session, instrument_id: int, *, provider: str, data_kind: str, interval: str = ""):
    from app.models import CryptoSyncState

    return db.scalar(
        select(CryptoSyncState).where(
            CryptoSyncState.instrument_id == instrument_id,
            CryptoSyncState.provider == provider,
            CryptoSyncState.data_kind == data_kind,
            CryptoSyncState.interval == interval,
        )
    )


def instrument_universe(
    db: Session,
    *,
    kind: str = "spot",
    venue: str = "binance",
    market: str | None = None,
) -> list[CryptoInstrument]:
    """Active instruments eligible for collection."""
    query = select(CryptoInstrument).where(
        CryptoInstrument.venue == venue,
        CryptoInstrument.kind == kind,
        CryptoInstrument.status == "trading",
    )
    if market is not None:
        query = query.where(CryptoInstrument.market == market)
    return list(db.scalars(query.order_by(CryptoInstrument.provider_symbol)))
