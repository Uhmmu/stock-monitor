"""Canonical crypto identity repository (crypto/quant program WP 1.1-1.2).

Rules frozen by the WP 0.3 fixtures (``identity_cases.json``):

- symbols are search hints only; identity comes from provider mappings,
  chain+address tokens or explicit symbol aliases;
- a provider id maps to exactly one typed target and is never retargeted
  implicitly;
- provider namespaces carry the market (``binance_spot``/``binance_usdm``);
  bare ``binance`` is not a valid namespace;
- token addresses are normalized per chain rule (EVM lowercase) and never
  guessed across chains.

No function here infers assets from ticker suffixes or names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Blockchain,
    CryptoAsset,
    CryptoInstrument,
    CryptoProtocol,
    CryptoProtocolAsset,
    CryptoProviderMapping,
    CryptoSymbolAlias,
    CryptoToken,
)

PROVIDER_BINANCE_SPOT = "binance_spot"
PROVIDER_BINANCE_USDM = "binance_usdm"
PROVIDER_COINGECKO = "coingecko"

OBJECT_TYPES = ("asset", "token", "protocol", "instrument")

# provider mapping target column per object type
_TARGET_COLUMNS = {
    "asset": "asset_id",
    "token": "token_id",
    "protocol": "protocol_id",
    "instrument": "instrument_id",
}

# display label fragments frozen by the WP 0.3 fixture
VENUE_LABELS = {"binance": "Binance"}
KIND_LABELS = {"spot": "Spot", "perpetual": "Perpetual", "future": "Future"}
MARKET_PROVIDER_NAMESPACES = {
    "spot": PROVIDER_BINANCE_SPOT,
    "usdm_futures": PROVIDER_BINANCE_USDM,
}


def instrument_display_label(instrument: CryptoInstrument, base: CryptoAsset, quote: CryptoAsset) -> str:
    """Stable display label, e.g. ``BTC/USDT · Binance · Perpetual``."""
    venue = VENUE_LABELS.get(instrument.venue, instrument.venue.title())
    kind = KIND_LABELS.get(instrument.kind, instrument.kind.title())
    return f"{base.symbol}/{quote.symbol} · {venue} · {kind}"


def asset_display_label(asset: CryptoAsset) -> str:
    """Stable asset label, e.g. ``BTC · Bitcoin``."""
    return f"{asset.symbol} · {asset.display_name}"


class MappingConflictError(ValueError):
    """Raised when a provider id would be silently retargeted to a new object."""


@dataclass(frozen=True)
class IdentityResolution:
    status: str  # "resolved" | "resolved_via_alias" | "search_hint_only" | "unresolved"
    object_type: str | None = None
    asset: CryptoAsset | None = None
    token: CryptoToken | None = None
    protocol: CryptoProtocol | None = None
    instrument: CryptoInstrument | None = None
    mapping: CryptoProviderMapping | None = None
    reason: str | None = None
    candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status in ("resolved", "resolved_via_alias")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _target_ref(object_type: str, target) -> tuple[str, int]:
    if object_type not in _TARGET_COLUMNS:
        raise ValueError(f"unsupported mapping object_type {object_type!r}")
    if target is None or not isinstance(target.id, int):
        raise ValueError(f"target for {object_type!r} must be a persisted model instance")
    return _TARGET_COLUMNS[object_type], target.id


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------


def get_asset_by_slug(db: Session, slug: str) -> CryptoAsset | None:
    return db.scalar(select(CryptoAsset).where(CryptoAsset.slug == slug))


def get_or_create_asset(
    db: Session,
    *,
    slug: str,
    symbol: str,
    display_name: str,
    asset_kind: str = "coin",
    wraps_asset_slug: str | None = None,
) -> tuple[CryptoAsset, bool]:
    """Idempotent canonical asset creation keyed by slug only."""
    existing = get_asset_by_slug(db, slug)
    if existing is not None:
        return existing, False
    wraps = get_asset_by_slug(db, wraps_asset_slug) if wraps_asset_slug else None
    asset = CryptoAsset(
        slug=slug,
        symbol=symbol,
        display_name=display_name,
        asset_kind=asset_kind,
        wraps_asset_id=wraps.id if wraps else None,
    )
    db.add(asset)
    db.flush()
    return asset, True


def find_assets_by_symbol(db: Session, symbol: str) -> list[CryptoAsset]:
    """All active assets carrying this symbol; more than one means ambiguous."""
    return list(
        db.scalars(
            select(CryptoAsset).where(CryptoAsset.symbol == symbol, CryptoAsset.status == "active")
        )
    )


def resolve_symbol(db: Session, symbol: str) -> IdentityResolution:
    """Search-layer symbol lookup: explicit alias, then symbol candidates.

    A unique symbol match is still only a ``search_hint_only`` result: symbols
    are never identity authority. Two assets sharing a symbol stay unresolved
    with their candidate slugs; no ranked pick is ever returned.
    """
    alias = db.scalar(select(CryptoSymbolAlias).where(CryptoSymbolAlias.symbol == symbol))
    if alias is not None:
        asset = db.get(CryptoAsset, alias.asset_id)
        if asset is not None:
            return IdentityResolution(status="resolved_via_alias", object_type="asset", asset=asset)
    matches = find_assets_by_symbol(db, symbol)
    if len(matches) == 1:
        return IdentityResolution(
            status="search_hint_only",
            object_type="asset",
            asset=matches[0],
            reason="symbols are search hints; identity requires a provider mapping, chain+address, or manual verification",
        )
    if len(matches) > 1:
        return IdentityResolution(
            status="unresolved",
            reason="symbol is ambiguous across canonical assets; a provider mapping or manual verification is required",
            candidates=tuple(sorted(a.slug for a in matches)),
        )
    return IdentityResolution(
        status="unresolved",
        reason="no canonical asset carries this symbol; symbols alone are never identity",
    )


def set_symbol_alias(db: Session, *, symbol: str, asset: CryptoAsset, reason: str | None = None) -> CryptoSymbolAlias:
    """Link an alternative ticker (XBT) to exactly one asset; unique per symbol."""
    existing = db.scalar(select(CryptoSymbolAlias).where(CryptoSymbolAlias.symbol == symbol))
    if existing is not None:
        if existing.asset_id != asset.id:
            raise MappingConflictError(
                f"alias {symbol!r} already targets asset id {existing.asset_id}; retargeting requires explicit removal"
            )
        return existing
    alias = CryptoSymbolAlias(symbol=symbol, asset_id=asset.id, reason=reason)
    db.add(alias)
    db.flush()
    return alias


# ---------------------------------------------------------------------------
# chains and tokens
# ---------------------------------------------------------------------------


def get_blockchain_by_slug(db: Session, slug: str) -> Blockchain | None:
    return db.scalar(select(Blockchain).where(Blockchain.slug == slug))


def get_or_create_blockchain(
    db: Session,
    *,
    slug: str,
    name: str,
    namespace: str,
    reference: str,
    native_asset_slug: str | None = None,
) -> tuple[Blockchain, bool]:
    """Idempotent chain creation keyed by slug; namespace/reference stay unique."""
    existing = get_blockchain_by_slug(db, slug)
    if existing is not None:
        return existing, False
    native = get_asset_by_slug(db, native_asset_slug) if native_asset_slug else None
    chain = Blockchain(
        slug=slug,
        name=name,
        namespace=namespace,
        reference=reference,
        native_asset_id=native.id if native else None,
    )
    db.add(chain)
    db.flush()
    return chain, True


def normalize_token_address(chain: Blockchain, address: str) -> str:
    """Per-chain address normalization; only rules proven for supported chains."""
    if chain.namespace == "eip155":
        return address.strip().lower()
    return address


def get_token_by_chain_address(db: Session, chain: Blockchain, address: str) -> CryptoToken | None:
    normalized = normalize_token_address(chain, address)
    return db.scalar(
        select(CryptoToken).where(
            CryptoToken.chain_id == chain.id, CryptoToken.normalized_address == normalized
        )
    )


def get_or_create_token(
    db: Session,
    *,
    asset: CryptoAsset,
    chain: Blockchain,
    address: str,
    decimals: int | None = None,
    bridged_from_token: CryptoToken | None = None,
) -> tuple[CryptoToken, bool]:
    """Idempotent token deployment keyed by exact (chain, normalized address)."""
    existing = get_token_by_chain_address(db, chain, address)
    if existing is not None:
        return existing, False
    token = CryptoToken(
        asset_id=asset.id,
        chain_id=chain.id,
        normalized_address=normalize_token_address(chain, address),
        decimals=decimals,
        bridged_from_token_id=bridged_from_token.id if bridged_from_token else None,
    )
    db.add(token)
    db.flush()
    return token, True


def resolve_token(db: Session, *, chain_slug: str, address: str) -> IdentityResolution:
    """Resolve a token deployment by exact chain + address; no cross-chain guess."""
    chain = get_blockchain_by_slug(db, chain_slug)
    if chain is None:
        return IdentityResolution(
            status="unresolved", object_type="token", reason="unknown chain; no address rule is assumed"
        )
    token = get_token_by_chain_address(db, chain, address)
    if token is None:
        return IdentityResolution(
            status="unresolved",
            object_type="token",
            reason="no token row matches; never create an asset or token by guess from the address alone",
        )
    return IdentityResolution(
        status="resolved",
        object_type="token",
        token=token,
        asset=db.get(CryptoAsset, token.asset_id),
    )


# ---------------------------------------------------------------------------
# protocols
# ---------------------------------------------------------------------------


def get_protocol_by_slug(db: Session, slug: str) -> CryptoProtocol | None:
    return db.scalar(select(CryptoProtocol).where(CryptoProtocol.slug == slug))


def get_or_create_protocol(
    db: Session,
    *,
    slug: str,
    name: str,
    category: str | None = None,
    website: str | None = None,
) -> tuple[CryptoProtocol, bool]:
    """Idempotent protocol creation; a protocol may exist without any token."""
    existing = get_protocol_by_slug(db, slug)
    if existing is not None:
        return existing, False
    protocol = CryptoProtocol(slug=slug, name=name, category=category, website=website)
    db.add(protocol)
    db.flush()
    return protocol, True


def link_protocol_asset(
    db: Session, *, protocol: CryptoProtocol, asset: CryptoAsset, role: str
) -> tuple[CryptoProtocolAsset, bool]:
    """Idempotent protocol/asset role link (governance, fee token, ...)."""
    existing = db.scalar(
        select(CryptoProtocolAsset).where(
            CryptoProtocolAsset.protocol_id == protocol.id,
            CryptoProtocolAsset.asset_id == asset.id,
            CryptoProtocolAsset.role == role,
        )
    )
    if existing is not None:
        return existing, False
    link = CryptoProtocolAsset(protocol_id=protocol.id, asset_id=asset.id, role=role)
    db.add(link)
    db.flush()
    return link, True


# ---------------------------------------------------------------------------
# instruments
# ---------------------------------------------------------------------------


def get_instrument(
    db: Session, *, venue: str, provider_symbol: str, kind: str
) -> CryptoInstrument | None:
    return db.scalar(
        select(CryptoInstrument).where(
            CryptoInstrument.venue == venue,
            CryptoInstrument.provider_symbol == provider_symbol,
            CryptoInstrument.kind == kind,
        )
    )


def get_instrument_by_id(db: Session, instrument_id: int) -> CryptoInstrument | None:
    return db.get(CryptoInstrument, instrument_id)


def upsert_instrument(
    db: Session,
    *,
    venue: str,
    market: str,
    provider_symbol: str,
    kind: str,
    base_asset: CryptoAsset,
    quote_asset: CryptoAsset,
    settlement_asset: CryptoAsset | None = None,
    contract_size=None,
    tick_size=None,
    step_size=None,
    min_notional=None,
    price_precision: int | None = None,
    quantity_precision: int | None = None,
    filters: dict | None = None,
    status: str = "trading",
    listing_at=None,
    delisting_at=None,
) -> tuple[CryptoInstrument, bool]:
    """Idempotent instrument creation keyed by (venue, provider_symbol, kind).

    Re-running a metadata sync updates trade-rule fields and statuses in
    place; identity is never recreated. Delisted rows are preserved.
    """
    existing = get_instrument(db, venue=venue, provider_symbol=provider_symbol, kind=kind)
    if existing is not None:
        existing.market = market
        existing.base_asset_id = base_asset.id
        existing.quote_asset_id = quote_asset.id
        existing.settlement_asset_id = settlement_asset.id if settlement_asset else existing.settlement_asset_id
        existing.contract_size = contract_size if contract_size is not None else existing.contract_size
        existing.tick_size = tick_size if tick_size is not None else existing.tick_size
        existing.step_size = step_size if step_size is not None else existing.step_size
        existing.min_notional = min_notional if min_notional is not None else existing.min_notional
        if price_precision is not None:
            existing.price_precision = price_precision
        if quantity_precision is not None:
            existing.quantity_precision = quantity_precision
        if filters is not None:
            existing.filters = filters
        existing.status = status
        if listing_at is not None:
            existing.listing_at = listing_at
        if delisting_at is not None:
            existing.delisting_at = delisting_at
        return existing, False
    instrument = CryptoInstrument(
        venue=venue,
        market=market,
        provider_symbol=provider_symbol,
        kind=kind,
        base_asset_id=base_asset.id,
        quote_asset_id=quote_asset.id,
        settlement_asset_id=settlement_asset.id if settlement_asset else None,
        contract_size=contract_size,
        tick_size=tick_size,
        step_size=step_size,
        min_notional=min_notional,
        price_precision=price_precision,
        quantity_precision=quantity_precision,
        filters=filters or {},
        status=status,
        listing_at=listing_at,
        delisting_at=delisting_at,
    )
    db.add(instrument)
    db.flush()
    return instrument, True


def resolve_instrument(
    db: Session, *, venue: str, provider_symbol: str, kind: str
) -> IdentityResolution:
    """Resolve one exact instrument by (venue, provider_symbol, kind)."""
    instrument = get_instrument(db, venue=venue, provider_symbol=provider_symbol, kind=kind)
    if instrument is None:
        return IdentityResolution(
            status="unresolved",
            object_type="instrument",
            reason="instrument kind is required: the same venue symbol exists as spot and perpetual",
        )
    return IdentityResolution(
        status="resolved",
        object_type="instrument",
        instrument=instrument,
        asset=db.get(CryptoAsset, instrument.base_asset_id),
    )


# ---------------------------------------------------------------------------
# provider mappings
# ---------------------------------------------------------------------------


def get_provider_mapping(
    db: Session, *, provider: str, object_type: str, provider_id: str
) -> CryptoProviderMapping | None:
    return db.scalar(
        select(CryptoProviderMapping).where(
            CryptoProviderMapping.provider == provider,
            CryptoProviderMapping.object_type == object_type,
            CryptoProviderMapping.provider_id == provider_id,
        )
    )


def set_provider_mapping(
    db: Session,
    *,
    provider: str,
    provider_id: str,
    target: CryptoAsset | CryptoToken | CryptoProtocol,
    confidence: float | None = None,
    method: str = "manual",
    verified: bool = False,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> CryptoProviderMapping:
    """Create or refresh the mapping for one exact provider id.

    The object type is derived from the target model. Existing mappings keep
    their target; pointing the same provider id at a different object raises
    instead of silently rewriting history.
    """
    if isinstance(target, CryptoAsset):
        object_type = "asset"
    elif isinstance(target, CryptoToken):
        object_type = "token"
    elif isinstance(target, CryptoProtocol):
        object_type = "protocol"
    elif isinstance(target, CryptoInstrument):
        object_type = "instrument"
    else:
        raise ValueError(f"unsupported mapping target type {type(target)!r}")
    column, target_id = _target_ref(object_type, target)

    existing = get_provider_mapping(db, provider=provider, object_type=object_type, provider_id=provider_id)
    if existing is not None:
        if getattr(existing, column) != target_id:
            raise MappingConflictError(
                f"{provider}:{object_type}:{provider_id} already targets a different object; "
                "use retarget_provider_mapping for an explicit, audited change"
            )
        existing.confidence = confidence
        existing.method = method
        existing.verified_at = _utcnow() if verified else existing.verified_at
        existing.valid_from = valid_from
        existing.valid_to = valid_to
        return existing
    mapping = CryptoProviderMapping(
        provider=provider,
        object_type=object_type,
        provider_id=provider_id,
        confidence=confidence,
        method=method,
        verified_at=_utcnow() if verified else None,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    setattr(mapping, column, target_id)
    db.add(mapping)
    db.flush()
    return mapping


def retarget_provider_mapping(
    db: Session,
    *,
    provider: str,
    provider_id: str,
    target: CryptoAsset | CryptoToken | CryptoProtocol,
    method: str = "manual_retarget",
) -> CryptoProviderMapping:
    """Explicit audited retarget of a provider id to a new canonical object."""
    if isinstance(target, CryptoAsset):
        object_type = "asset"
    elif isinstance(target, CryptoToken):
        object_type = "token"
    elif isinstance(target, CryptoProtocol):
        object_type = "protocol"
    elif isinstance(target, CryptoInstrument):
        object_type = "instrument"
    else:
        raise ValueError(f"unsupported mapping target type {type(target)!r}")
    column, target_id = _target_ref(object_type, target)
    existing = get_provider_mapping(db, provider=provider, object_type=object_type, provider_id=provider_id)
    if existing is None:
        return set_provider_mapping(db, provider=provider, provider_id=provider_id, target=target, method=method)
    existing.asset_id = None if column != "asset_id" else target_id
    existing.token_id = None if column != "token_id" else target_id
    existing.protocol_id = None if column != "protocol_id" else target_id
    existing.instrument_id = None if column != "instrument_id" else target_id
    existing.method = method
    existing.verified_at = _utcnow()
    return existing


def verify_provider_mapping(db: Session, mapping: CryptoProviderMapping) -> CryptoProviderMapping:
    """Mark a mapping as manually verified; never changes its target."""
    mapping.verified_at = _utcnow()
    return mapping


def resolve_provider_id(
    db: Session, *, provider: str, object_type: str, provider_id: str
) -> IdentityResolution:
    """Resolve an exact provider id to its single canonical target."""
    mapping = get_provider_mapping(db, provider=provider, object_type=object_type, provider_id=provider_id)
    if mapping is None:
        reason = "no mapping for the exact provider id"
        if provider == "binance":
            reason = (
                "provider namespace must include the market (binance_spot vs binance_usdm); "
                "the raw venue symbol exists on multiple markets with different semantics"
            )
        return IdentityResolution(status="unresolved", object_type=object_type, reason=reason)
    result = IdentityResolution(status="resolved", object_type=mapping.object_type, mapping=mapping)
    if mapping.asset_id:
        return IdentityResolution(
            status="resolved", object_type="asset", mapping=mapping, asset=db.get(CryptoAsset, mapping.asset_id)
        )
    if mapping.token_id:
        token = db.get(CryptoToken, mapping.token_id)
        return IdentityResolution(
            status="resolved",
            object_type="token",
            mapping=mapping,
            token=token,
            asset=db.get(CryptoAsset, token.asset_id) if token else None,
        )
    if mapping.protocol_id:
        return IdentityResolution(
            status="resolved",
            object_type="protocol",
            mapping=mapping,
            protocol=db.get(CryptoProtocol, mapping.protocol_id),
        )
    if mapping.instrument_id:
        instrument = db.get(CryptoInstrument, mapping.instrument_id)
        return IdentityResolution(
            status="resolved",
            object_type="instrument",
            mapping=mapping,
            instrument=instrument,
            asset=db.get(CryptoAsset, instrument.base_asset_id) if instrument else None,
        )
    return result
