"""CoinGecko identity enrichment and persisted market fundamentals (WP 5.1/5.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CryptoAsset,
    CryptoAssetFundamentalSnapshot,
    CryptoAssetReference,
    CryptoCollectionRun,
    CryptoProviderMapping,
)

from . import identity
from .providers.coingecko import CoinGeckoError, CoinGeckoMarket, PROVIDER

PRIMARY_FIELDS = (
    "market_cap",
    "fully_diluted_valuation",
    "circulating_supply",
    "total_supply",
    "max_supply",
    "market_cap_rank",
)

# These are explicit canonical mappings, not a symbol heuristic.  Additional
# mappings must be supplied through the manual mapping setting or an existing
# verified provider row.
KNOWN_CANONICAL_MAPPINGS = {"bitcoin": "bitcoin", "ethereum": "ethereum"}
COINGECKO_DOMAIN = "asset_fundamentals"
DEFAULT_COINGECKO_REFRESH = timedelta(hours=24)


class FundamentalPayloadError(ValueError):
    """Provider payload is malformed or contains an invalid nonnegative fact."""


@dataclass(frozen=True)
class MappingDecision:
    status: str
    asset: CryptoAsset | None = None
    method: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ReferenceSyncResult:
    status: str
    provider_id: str
    asset_id: int | None = None
    method: str | None = None
    revision: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FundamentalSyncResult:
    status: str
    asset_id: int
    provider_id: str
    revision: int
    coverage: float


@dataclass
class SyncSummary:
    status: str = "success"
    requested: int = 0
    fetched: int = 0
    mapped: int = 0
    snapshots_created: int = 0
    snapshots_updated: int = 0
    snapshots_unchanged: int = 0
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _coingecko_provider_ids(raw: str | list[str] | None) -> list[str]:
    values = raw.split(",") if isinstance(raw, str) else (raw or [])
    result: list[str] = []
    for value in values:
        provider_id = str(value).strip()
        if provider_id and provider_id not in result:
            result.append(provider_id)
    return result[:50]


def coingecko_assets_for_universe(
    db: Session,
    provider_ids: str | list[str] | None,
    *,
    manual_mappings: Mapping[str, str] | None = None,
) -> tuple[list[CryptoAsset], list[dict[str, Any]]]:
    """Resolve the bounded configured CoinGecko universe without symbols."""
    clean_ids = _coingecko_provider_ids(provider_ids)
    if not clean_ids:
        return [], []
    mappings = db.scalars(
        select(CryptoProviderMapping).where(
            CryptoProviderMapping.provider == PROVIDER,
            CryptoProviderMapping.object_type == "asset",
            CryptoProviderMapping.provider_id.in_(clean_ids),
        )
    ).all()
    mapped = {mapping.provider_id: mapping for mapping in mappings}
    canonical = dict(KNOWN_CANONICAL_MAPPINGS)
    canonical.update(manual_mappings or {})
    assets: list[CryptoAsset] = []
    seen_asset_ids: set[int] = set()
    unresolved: list[dict[str, Any]] = []
    for provider_id in clean_ids:
        mapping = mapped.get(provider_id)
        asset = db.get(CryptoAsset, mapping.asset_id) if mapping and mapping.asset_id else None
        if asset is None:
            slug = canonical.get(provider_id)
            asset = db.scalar(select(CryptoAsset).where(CryptoAsset.slug == slug)) if slug else None
        if asset is None:
            unresolved.append({"provider_id": provider_id, "reason": "no verified canonical asset mapping"})
            continue
        if asset.id not in seen_asset_ids:
            assets.append(asset)
            seen_asset_ids.add(asset.id)
    return assets, unresolved


def latest_successful_coingecko_run(db: Session) -> CryptoCollectionRun | None:
    return db.scalar(
        select(CryptoCollectionRun)
        .where(
            CryptoCollectionRun.provider == PROVIDER,
            CryptoCollectionRun.domain == COINGECKO_DOMAIN,
            CryptoCollectionRun.status == "success",
        )
        .order_by(CryptoCollectionRun.started_at.desc())
        .limit(1)
    )


def coingecko_fundamentals_due(
    db: Session,
    *,
    refresh_interval: timedelta = DEFAULT_COINGECKO_REFRESH,
) -> bool:
    latest = latest_successful_coingecko_run(db)
    if latest is None or latest.finished_at is None:
        return True
    finished = _as_utc(latest.finished_at) or _utcnow()
    return _utcnow() - finished >= refresh_interval


def finish_coingecko_run(db: Session, run: CryptoCollectionRun, summary: SyncSummary) -> None:
    """Write bounded run health after the provider service returns."""
    run.status = summary.status if summary.status in {"success", "partial", "failed"} else "failed"
    run.finished_at = _utcnow()
    run.heartbeat_at = run.finished_at
    run.items_seen = summary.fetched
    run.items_created = summary.snapshots_created
    run.items_updated = summary.snapshots_updated
    run.unresolved_count = len(summary.unresolved)
    run.error_message = "; ".join(
        str(error.get("message") or error.get("kind") or "provider error")
        for error in summary.errors
    )[:1000] or None
    run.details = {
        "requested": summary.requested,
        "fetched": summary.fetched,
        "mapped": summary.mapped,
        "snapshots_unchanged": summary.snapshots_unchanged,
        "unresolved": summary.unresolved[:50],
        "errors": summary.errors[:50],
    }


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_manual_mappings(raw: str | None) -> dict[str, str]:
    """Parse ``provider_id:canonical_slug`` pairs; malformed entries are ignored."""
    result: dict[str, str] = {}
    for item in (raw or "").split(","):
        provider_id, separator, slug = item.partition(":")
        if separator and provider_id.strip() and slug.strip():
            result[provider_id.strip()] = slug.strip()
    return result


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def source_hash(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _provider_timestamp(payload: Mapping[str, Any]) -> datetime | None:
    value = payload.get("last_updated")
    if value is None and isinstance(payload.get("market_data"), Mapping):
        value = payload["market_data"].get("last_updated")
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError as exc:
        raise FundamentalPayloadError("invalid CoinGecko provider timestamp") from exc


def _raw_value(payload: Mapping[str, Any], field_name: str) -> Any:
    if field_name in payload:
        return payload.get(field_name)
    market_data = payload.get("market_data")
    if isinstance(market_data, Mapping):
        value = market_data.get(field_name)
        if isinstance(value, Mapping):
            return value.get("usd")
        return value
    return None


def _decimal(payload: Mapping[str, Any], field_name: str) -> Decimal | None:
    raw = _raw_value(payload, field_name)
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise FundamentalPayloadError(f"invalid CoinGecko value for {field_name}") from exc
    if not value.is_finite() or value < 0:
        raise FundamentalPayloadError(f"negative or non-finite CoinGecko value for {field_name}")
    return value


def _rank(payload: Mapping[str, Any]) -> int | None:
    raw = _raw_value(payload, "market_cap_rank")
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise FundamentalPayloadError("invalid CoinGecko market-cap rank") from exc
    if value < 1:
        raise FundamentalPayloadError("market-cap rank must be positive")
    return value


def _freshness(provider_timestamp: datetime | None, fetched_at: datetime) -> str:
    if provider_timestamp is None:
        return "unknown"
    age_hours = max(0.0, (_as_utc(fetched_at) - provider_timestamp).total_seconds() / 3600)
    if age_hours <= 48:
        return "fresh"
    if age_hours <= 24 * 7:
        return "stale"
    return "expired"


def normalize_fundamentals(payload: Mapping[str, Any], *, fetched_at: datetime | None = None) -> dict[str, Any]:
    provider_id = str(payload.get("id") or "").strip()
    if not provider_id:
        raise FundamentalPayloadError("CoinGecko payload has no provider id")
    fetched = _as_utc(fetched_at) or _utcnow()
    provider_timestamp = _provider_timestamp(payload)
    values = {field_name: _decimal(payload, field_name) for field_name in PRIMARY_FIELDS[:-1]}
    values["market_cap_rank"] = _rank(payload)
    coverage = sum(value is not None for value in values.values()) / len(PRIMARY_FIELDS)
    return {
        "provider_id": provider_id,
        **values,
        "observed_at": provider_timestamp or fetched,
        "provider_timestamp": provider_timestamp,
        "fetched_at": fetched,
        "freshness_status": _freshness(provider_timestamp, fetched),
        "coverage": coverage,
        "quality": "ok" if coverage == 1 else ("partial" if coverage else "unavailable"),
        "source_hash": source_hash(payload),
    }


def _reference_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    links = payload.get("links") if isinstance(payload.get("links"), Mapping) else {}
    categories = payload.get("categories") if isinstance(payload.get("categories"), list) else []
    platforms = payload.get("platforms") if isinstance(payload.get("platforms"), Mapping) else {}
    websites = []
    for value in [*(links.get("homepage") or []), *(links.get("blockchain_site") or [])]:
        if value is None:
            continue
        value = str(value).strip()
        if value and value not in websites:
            websites.append(value)
    metadata = {
        key: payload[key]
        for key in ("asset_platform_id", "last_updated", "description")
        if key in payload and key != "description"
    }
    return {
        "canonical_name": str(payload.get("name") or "").strip() or None,
        "symbol": str(payload.get("symbol") or "").strip().upper() or None,
        "categories": [str(value).strip() for value in categories[:50] if value is not None and str(value).strip()],
        "website_urls": websites[:50],
        "contract_references": {
            str(key): str(value).strip()
            for key, value in list(platforms.items())[:100]
            if value is not None and str(value).strip()
        },
        "reference_metadata": metadata,
        "provider_timestamp": _provider_timestamp(payload),
    }


def resolve_asset_for_payload(
    db: Session,
    payload: Mapping[str, Any],
    *,
    known_mappings: Mapping[str, str] | None = None,
    manual_mappings: Mapping[str, str] | None = None,
) -> MappingDecision:
    """Resolve by provider id, chain+contract, known mapping, then manual mapping.

    A symbol-only match intentionally returns unresolved.  This ordering keeps
    the provider enrichment safe when symbols collide across canonical assets.
    """
    provider_id = str(payload.get("id") or "").strip()
    if not provider_id:
        return MappingDecision("unresolved", reason="missing provider id")
    mapped_assets: list[CryptoAsset] = []
    for object_type in ("asset", "token"):
        resolved = identity.resolve_provider_id(
            db, provider=PROVIDER, object_type=object_type, provider_id=provider_id
        )
        if resolved.resolved and resolved.asset is not None:
            mapped_assets.append(resolved.asset)
    if mapped_assets:
        unique = {asset.id: asset for asset in mapped_assets}
        if len(unique) == 1:
            return MappingDecision("resolved", next(iter(unique.values())), "provider_id")
        return MappingDecision("conflict", reason="provider id has conflicting canonical targets")

    platforms = payload.get("platforms") if isinstance(payload.get("platforms"), Mapping) else {}
    contract_assets: dict[int, CryptoAsset] = {}
    for chain_slug, address in platforms.items():
        chain = identity.get_blockchain_by_slug(db, str(chain_slug))
        if chain is None or not str(address).strip():
            continue
        token = identity.get_token_by_chain_address(db, chain, str(address))
        if token is not None:
            asset = db.get(CryptoAsset, token.asset_id)
            if asset is not None:
                contract_assets[asset.id] = asset
    if contract_assets:
        if len(contract_assets) == 1:
            return MappingDecision("resolved", next(iter(contract_assets.values())), "chain_contract")
        return MappingDecision("conflict", reason="provider contracts point to conflicting canonical assets")

    known = dict(KNOWN_CANONICAL_MAPPINGS)
    known.update(known_mappings or {})
    slug = known.get(provider_id)
    if slug:
        asset = identity.get_asset_by_slug(db, slug)
        if asset is not None:
            return MappingDecision("resolved", asset, "known_canonical_mapping")

    manual = (manual_mappings or {}).get(provider_id)
    if manual:
        asset = identity.get_asset_by_slug(db, manual)
        if asset is not None:
            return MappingDecision("resolved", asset, "manual_mapping")

    return MappingDecision(
        "unresolved",
        reason="provider id has no verified, chain-contract, canonical, or manual mapping; symbol-only matching is not authoritative",
    )


def _ensure_asset_mapping(db: Session, asset: CryptoAsset, provider_id: str, method: str) -> None:
    existing = identity.get_provider_mapping(
        db, provider=PROVIDER, object_type="asset", provider_id=provider_id
    )
    if existing is not None and existing.asset_id != asset.id:
        raise identity.MappingConflictError(
            f"{PROVIDER}:asset:{provider_id} already targets a different canonical asset"
        )
    identity.set_provider_mapping(
        db,
        provider=PROVIDER,
        provider_id=provider_id,
        target=asset,
        confidence=1.0,
        method=method,
        verified=True,
    )


def sync_asset_reference(
    db: Session,
    payload: Mapping[str, Any],
    *,
    asset: CryptoAsset | None = None,
    known_mappings: Mapping[str, str] | None = None,
    manual_mappings: Mapping[str, str] | None = None,
    fetched_at: datetime | None = None,
) -> ReferenceSyncResult:
    provider_id = str(payload.get("id") or "").strip()
    if not provider_id:
        return ReferenceSyncResult("unresolved", "", reason="missing provider id")
    decision = resolve_asset_for_payload(
        db, payload, known_mappings=known_mappings, manual_mappings=manual_mappings
    )
    if asset is not None and decision.asset is not None and decision.asset.id != asset.id:
        return ReferenceSyncResult("conflict", provider_id, asset.id, reason="payload mapping disagrees with requested canonical asset")
    target = asset or decision.asset
    if target is None or decision.status in {"unresolved", "conflict"}:
        return ReferenceSyncResult(decision.status, provider_id, reason=decision.reason)
    now = _as_utc(fetched_at) or _utcnow()
    values = _reference_values(payload)
    values.update({"source": PROVIDER, "source_hash": source_hash(payload), "fetched_at": now, "freshness_status": _freshness(values["provider_timestamp"], now)})
    reference = db.scalar(select(CryptoAssetReference).where(
        CryptoAssetReference.provider == PROVIDER,
        CryptoAssetReference.provider_id == provider_id,
    ))
    by_asset = db.scalar(select(CryptoAssetReference).where(
        CryptoAssetReference.asset_id == target.id,
        CryptoAssetReference.provider == PROVIDER,
    ))
    if reference is not None and reference.asset_id != target.id:
        return ReferenceSyncResult("conflict", provider_id, target.id, reason="provider reference already targets another asset")
    if by_asset is not None and by_asset.provider_id != provider_id:
        return ReferenceSyncResult("conflict", provider_id, target.id, reason="canonical asset already has a different provider id")
    try:
        _ensure_asset_mapping(db, target, provider_id, decision.method or "provider_id")
    except identity.MappingConflictError as exc:
        return ReferenceSyncResult("conflict", provider_id, target.id, reason=str(exc))
    reference = reference or by_asset
    if reference is None:
        reference = CryptoAssetReference(asset_id=target.id, provider=PROVIDER, provider_id=provider_id, **values)
        db.add(reference)
        db.flush()
        return ReferenceSyncResult("created", provider_id, target.id, decision.method, 0)
    changed = reference.source_hash != values["source_hash"]
    for key, value in values.items():
        setattr(reference, key, value)
    if changed:
        reference.revision += 1
    db.flush()
    return ReferenceSyncResult("updated" if changed else "unchanged", provider_id, target.id, decision.method, reference.revision)


def persist_fundamental_snapshot(
    db: Session,
    *,
    asset: CryptoAsset,
    payload: Mapping[str, Any],
    fetched_at: datetime | None = None,
) -> FundamentalSyncResult:
    values = normalize_fundamentals(payload, fetched_at=fetched_at)
    provider_id = values.pop("provider_id")
    source_hash_value = values.pop("source_hash")
    snapshot = db.scalar(select(CryptoAssetFundamentalSnapshot).where(
        CryptoAssetFundamentalSnapshot.asset_id == asset.id,
        CryptoAssetFundamentalSnapshot.provider == PROVIDER,
        CryptoAssetFundamentalSnapshot.observed_at == values["observed_at"],
    ))
    if snapshot is None:
        snapshot = CryptoAssetFundamentalSnapshot(
            asset_id=asset.id,
            provider=PROVIDER,
            source=PROVIDER,
            source_hash=source_hash_value,
            revision=0,
            **values,
        )
        db.add(snapshot)
        db.flush()
        return FundamentalSyncResult("created", asset.id, provider_id, 0, values["coverage"])
    changed = snapshot.source_hash != source_hash_value
    for key, value in values.items():
        setattr(snapshot, key, value)
    snapshot.source_hash = source_hash_value
    if changed:
        snapshot.revision += 1
    db.flush()
    return FundamentalSyncResult("updated" if changed else "unchanged", asset.id, provider_id, snapshot.revision, values["coverage"])


def sync_coingecko_assets(
    db: Session,
    *,
    client,
    assets: list[CryptoAsset],
    known_mappings: Mapping[str, str] | None = None,
    manual_mappings: Mapping[str, str] | None = None,
    fetched_at: datetime | None = None,
) -> SyncSummary:
    """Fetch a bounded asset set; one bad row never erases another's last-good data."""
    summary = SyncSummary(requested=len(assets))
    provider_ids: dict[str, CryptoAsset] = {}
    known = dict(KNOWN_CANONICAL_MAPPINGS)
    known.update(known_mappings or {})
    manual = dict(manual_mappings or {})
    for asset in assets[:50]:
        mapping = db.scalar(select(CryptoProviderMapping).where(
            CryptoProviderMapping.provider == PROVIDER,
            CryptoProviderMapping.object_type == "asset",
            CryptoProviderMapping.asset_id == asset.id,
        ))
        provider_id = mapping.provider_id if mapping else next(
            (key for key, value in {**known, **manual}.items() if value == asset.slug), None
        )
        if provider_id:
            provider_ids[provider_id] = asset
        else:
            summary.unresolved.append({"asset_id": asset.id, "reason": "no CoinGecko provider id mapping"})
    if not provider_ids:
        summary.status = "partial" if summary.unresolved else "success"
        return summary
    try:
        rows = client.markets(list(provider_ids))
    except CoinGeckoError as exc:
        summary.status = "failed"
        summary.errors.append({"kind": exc.kind, "message": exc.message})
        return summary
    summary.fetched = len(rows)
    rows_by_id = {row.provider_id: row for row in rows}
    for provider_id, asset in provider_ids.items():
        row = rows_by_id.get(provider_id)
        if row is None:
            summary.unresolved.append({"asset_id": asset.id, "provider_id": provider_id, "reason": "provider row missing"})
            continue
        try:
            with db.begin_nested():
                reference_payload = row.payload
                detail = getattr(client, "asset_detail", None)
                if callable(detail):
                    try:
                        candidate = detail(provider_id)
                        if isinstance(candidate, Mapping) and candidate.get("id") == provider_id:
                            reference_payload = candidate
                    except CoinGeckoError as exc:
                        summary.errors.append({
                            "asset_id": asset.id,
                            "provider_id": provider_id,
                            "kind": f"reference_{exc.kind}",
                            "message": exc.message,
                        })
                reference_result = sync_asset_reference(
                    db, reference_payload, asset=asset, known_mappings=known, manual_mappings=manual_mappings, fetched_at=fetched_at
                )
                if reference_result.status == "conflict":
                    summary.errors.append({"asset_id": asset.id, "provider_id": provider_id, "kind": "mapping_conflict", "message": reference_result.reason})
                    continue
                if reference_result.status == "unresolved":
                    summary.unresolved.append({"asset_id": asset.id, "provider_id": provider_id, "reason": reference_result.reason})
                    continue
                snapshot_result = persist_fundamental_snapshot(db, asset=asset, payload=row.payload, fetched_at=fetched_at)
                summary.mapped += 1
                if snapshot_result.status == "created":
                    summary.snapshots_created += 1
                elif snapshot_result.status == "updated":
                    summary.snapshots_updated += 1
                else:
                    summary.snapshots_unchanged += 1
        except (FundamentalPayloadError, ValueError, TypeError) as exc:
            summary.errors.append({"asset_id": asset.id, "provider_id": provider_id, "kind": "invalid_payload", "message": str(exc)[:200]})
    db.commit()
    summary.status = "success" if not summary.unresolved and not summary.errors else "partial"
    return summary


def latest_fundamental_snapshot(db: Session, asset_id: int, *, provider: str = PROVIDER) -> CryptoAssetFundamentalSnapshot | None:
    return db.scalar(select(CryptoAssetFundamentalSnapshot).where(
        CryptoAssetFundamentalSnapshot.asset_id == asset_id,
        CryptoAssetFundamentalSnapshot.provider == provider,
    ).order_by(CryptoAssetFundamentalSnapshot.observed_at.desc()).limit(1))


def fundamental_snapshot_payload(snapshot: CryptoAssetFundamentalSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {"status": "unavailable", "coverage": 0, "source": None}
    return {
        "status": snapshot.quality,
        "market_cap": str(snapshot.market_cap) if snapshot.market_cap is not None else None,
        "fully_diluted_valuation": str(snapshot.fully_diluted_valuation) if snapshot.fully_diluted_valuation is not None else None,
        "circulating_supply": str(snapshot.circulating_supply) if snapshot.circulating_supply is not None else None,
        "total_supply": str(snapshot.total_supply) if snapshot.total_supply is not None else None,
        "max_supply": str(snapshot.max_supply) if snapshot.max_supply is not None else None,
        "market_cap_rank": snapshot.market_cap_rank,
        "currency": snapshot.currency,
        "source": snapshot.source,
        "provider_timestamp": snapshot.provider_timestamp,
        "observed_at": snapshot.observed_at,
        "fetched_at": snapshot.fetched_at,
        "freshness": snapshot.freshness_status,
        "coverage": snapshot.coverage,
    }
