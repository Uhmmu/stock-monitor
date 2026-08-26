"""Evidence-backed crypto news associations.

The existing ``NewsItem`` table and its equity collection pipeline remain the
source of article content, deduplication, clustering, summaries and archives.
This module only writes an additive association row; it never changes the
equity ticker/scope fields and never calls a news provider.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CryptoAsset,
    CryptoInstrument,
    CryptoNewsAssociation,
    CryptoSymbolAlias,
    NewsItem,
)

CRYPTO_NEWS_SCOPES = ("crypto_asset", "crypto_instrument", "crypto_market")
EVIDENCE_METHODS = (
    "provider_id",
    "asset_id",
    "instrument_exact",
    "asset_name",
    "validated_alias",
    "market_scope",
)
_METHOD_ALIASES = {
    "exact_provider_id": "provider_id",
    "provider_entity_id": "provider_id",
    "canonical_asset_id": "asset_id",
    "exact_instrument": "instrument_exact",
    "full_name": "asset_name",
    "alias": "validated_alias",
    "market": "market_scope",
}
_TICKER_ONLY_METHODS = {"ticker", "ticker_only", "symbol", "symbol_only"}
DEFAULT_ASSOCIATION_LOOKBACK = timedelta(hours=48)
DEFAULT_ASSOCIATION_LIMIT = 500
CRYPTO_MARKET_MARKERS = (
    "crypto market",
    "cryptocurrency market",
    "digital asset market",
    "digital assets market",
    "crypto sector",
    "cryptocurrency industry",
)


class CryptoNewsAssociationError(ValueError):
    """Association lacks enough explicit identity evidence."""


def _safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(_safe(value), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_method(method: str) -> str:
    normalized = str(method or "").strip().lower().replace("-", "_")
    if normalized in _TICKER_ONLY_METHODS:
        raise CryptoNewsAssociationError(
            "ticker-only evidence cannot authoritatively associate crypto news"
        )
    normalized = _METHOD_ALIASES.get(normalized, normalized)
    if normalized not in EVIDENCE_METHODS:
        raise CryptoNewsAssociationError(
            "crypto news requires provider ID, canonical ID, exact instrument, "
            "full asset name, validated alias, or market-scope evidence"
        )
    return normalized


def _news_item(db: Session, value: NewsItem | int) -> NewsItem:
    item = value if isinstance(value, NewsItem) else db.get(NewsItem, int(value))
    if item is None or item.id is None:
        raise CryptoNewsAssociationError("news item must already be persisted")
    return item


def _validate_evidence(
    db: Session,
    *,
    scope_type: str,
    scope_key: str,
    provider: str,
    method: str,
    asset_id: int | None,
    instrument_id: int | None,
    provider_entity_id: str | None,
    evidence: Mapping[str, Any],
) -> None:
    if scope_type not in CRYPTO_NEWS_SCOPES:
        raise CryptoNewsAssociationError(f"unsupported crypto news scope {scope_type!r}")
    if not scope_key:
        raise CryptoNewsAssociationError("crypto news scope_key is required")
    if not provider:
        raise CryptoNewsAssociationError("crypto news provider is required")

    if scope_type == "crypto_asset":
        if asset_id is None or instrument_id is not None:
            raise CryptoNewsAssociationError("crypto_asset associations require exactly one asset_id")
        if db.get(CryptoAsset, asset_id) is None:
            raise CryptoNewsAssociationError("asset_id does not identify a persisted crypto asset")
    elif scope_type == "crypto_instrument":
        if instrument_id is None or asset_id is not None:
            raise CryptoNewsAssociationError(
                "crypto_instrument associations require exactly one instrument_id"
            )
        instrument = db.get(CryptoInstrument, instrument_id)
        if instrument is None:
            raise CryptoNewsAssociationError("instrument_id does not identify a persisted crypto instrument")
    elif asset_id is not None or instrument_id is not None:
        raise CryptoNewsAssociationError("crypto_market associations cannot target an asset or instrument")

    if method == "provider_id" and not provider_entity_id:
        raise CryptoNewsAssociationError("provider_id evidence requires provider_entity_id")
    if method == "asset_id" and not evidence.get("asset_id"):
        raise CryptoNewsAssociationError("asset_id evidence must retain the canonical asset ID")
    if method == "instrument_exact":
        if scope_type != "crypto_instrument" or not provider_entity_id:
            raise CryptoNewsAssociationError(
                "instrument_exact evidence requires an exact Binance instrument ID"
            )
        if not provider.lower().startswith("binance"):
            raise CryptoNewsAssociationError("instrument_exact evidence must name a Binance provider")
        if not evidence.get("provider_symbol") or not evidence.get("venue"):
            raise CryptoNewsAssociationError(
                "instrument_exact evidence must retain venue and provider_symbol"
            )
    if method == "asset_name":
        matched_name = str(evidence.get("matched_name") or "").strip()
        if len(matched_name.split()) < 1 or len(matched_name) < 3:
            raise CryptoNewsAssociationError("asset_name evidence requires a reliable full asset name")
        asset = db.get(CryptoAsset, asset_id) if asset_id is not None else None
        # ``scope_key`` is normally a canonical slug (for example
        # ``bitcoin``), so matching it is still full-name evidence.  Only the
        # provider symbol itself is ticker-only evidence.
        if asset is not None and matched_name.casefold() == asset.symbol.casefold():
            raise CryptoNewsAssociationError("asset_name evidence cannot be ticker-only")
        if (
            asset is not None
            and matched_name.casefold() != asset.display_name.casefold()
            and evidence.get("verified") is not True
        ):
            raise CryptoNewsAssociationError(
                "asset_name evidence must match the canonical full asset name"
            )
    if method == "validated_alias":
        alias = str(evidence.get("alias") or "").strip()
        if not alias:
            raise CryptoNewsAssociationError("validated_alias evidence requires the validated alias")
        if asset_id is None:
            raise CryptoNewsAssociationError("validated_alias evidence requires an asset target")
        known_alias = db.scalar(
            select(CryptoSymbolAlias).where(
                CryptoSymbolAlias.symbol == alias,
                CryptoSymbolAlias.asset_id == asset_id,
            )
        )
        if known_alias is None and evidence.get("validated") is not True:
            raise CryptoNewsAssociationError(
                "validated_alias evidence must reference a stored validated alias"
            )
    if method == "market_scope":
        market = str(evidence.get("market") or "").strip().lower()
        if market not in {"crypto", "cryptocurrency", "digital_assets"}:
            raise CryptoNewsAssociationError("market_scope evidence must identify the crypto market")


def associate_news_item(
    db: Session,
    *,
    news_item: NewsItem | int,
    scope_type: str,
    scope_key: str,
    provider: str,
    evidence_method: str,
    confidence: float = 1.0,
    asset_id: int | None = None,
    instrument_id: int | None = None,
    provider_entity_type: str | None = None,
    provider_entity_id: str | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> CryptoNewsAssociation:
    """Create or refresh one explicit crypto association idempotently.

    Symbols in an article are never resolved here.  Callers must supply a
    canonical FK, an exact Binance instrument, a validated full-name/alias
    match, or an explicit market-wide classification with retained evidence.
    """

    item = _news_item(db, news_item)
    scope_type = str(scope_type or "").strip().lower()
    scope_key = str(scope_key or "").strip()
    provider = str(provider or "").strip()
    method = _canonical_method(evidence_method)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise CryptoNewsAssociationError("confidence must be a number between 0 and 1") from exc
    if not 0 <= confidence <= 1:
        raise CryptoNewsAssociationError("confidence must be between 0 and 1")
    evidence_payload = dict(_safe(dict(evidence or {})))
    _validate_evidence(
        db,
        scope_type=scope_type,
        scope_key=scope_key,
        provider=provider,
        method=method,
        asset_id=asset_id,
        instrument_id=instrument_id,
        provider_entity_id=provider_entity_id,
        evidence=evidence_payload,
    )

    entity_type = provider_entity_type or {
        "crypto_asset": "asset",
        "crypto_instrument": "instrument",
        "crypto_market": "market",
    }[scope_type]
    identity = {
        "news_item_id": item.id,
        "scope_type": scope_type,
        "scope_key": scope_key,
        "asset_id": asset_id,
        "instrument_id": instrument_id,
        "provider": provider,
        "provider_entity_type": entity_type,
        "provider_entity_id": provider_entity_id,
    }
    association_key = _digest(identity)
    association = db.scalar(
        select(CryptoNewsAssociation).where(
            CryptoNewsAssociation.association_key == association_key
        )
    )
    if association is None:
        association = CryptoNewsAssociation(
            news_item_id=item.id,
            scope_type=scope_type,
            scope_key=scope_key,
            asset_id=asset_id,
            instrument_id=instrument_id,
            provider=provider,
            provider_entity_type=entity_type,
            provider_entity_id=provider_entity_id,
            evidence_method=method,
            evidence=evidence_payload,
            confidence=confidence,
            association_key=association_key,
        )
        db.add(association)
    else:
        # Evidence may improve over time, but the identity target/key never
        # changes and a replay never creates a second association.
        association.evidence_method = method
        association.evidence = evidence_payload
        association.confidence = confidence
        association.provider_entity_type = entity_type
        association.provider_entity_id = provider_entity_id
    db.flush()
    return association


def list_crypto_news_associations(
    db: Session,
    *,
    scope_type: str | None = None,
    scope_key: str | None = None,
    news_item_id: int | None = None,
) -> list[CryptoNewsAssociation]:
    """Read additive associations without changing the underlying NewsItem."""

    query = select(CryptoNewsAssociation)
    if scope_type is not None:
        query = query.where(CryptoNewsAssociation.scope_type == scope_type)
    if scope_key is not None:
        query = query.where(CryptoNewsAssociation.scope_key == scope_key)
    if news_item_id is not None:
        query = query.where(CryptoNewsAssociation.news_item_id == news_item_id)
    return list(
        db.scalars(
            query.order_by(
                CryptoNewsAssociation.created_at.asc(),
                CryptoNewsAssociation.id.asc(),
            )
        )
    )


def _text_for_matching(item: NewsItem) -> str:
    """Bounded article text used only for deterministic persisted matching."""

    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for nested in value.values():
                collect(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                collect(nested)
        elif value is not None:
            values.append(str(value))

    for value in (
        item.title,
        item.summary,
        item.article_content,
        item.raw_content,
        item.provider_metadata,
        item.raw_payload,
    ):
        collect(value)
    # Keep matching bounded even when a raw article payload is unusually large.
    return " ".join(values)[:120_000]


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase or len(phrase.strip()) < 3:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase.strip())}(?!\w)", text, re.IGNORECASE) is not None


def _instrument_context_matches(text: str, instrument: CryptoInstrument) -> bool:
    """Require market/kind context when a Binance symbol has collisions."""

    symbol = instrument.provider_symbol.strip()
    match = re.search(rf"(?<!\w){re.escape(symbol)}(?!\w)", text, re.IGNORECASE)
    if match is None:
        return False
    context = text[max(0, match.start() - 48): min(len(text), match.end() + 48)].lower()
    if instrument.kind == "spot":
        return any(term in context for term in ("spot", "现货"))
    if instrument.kind == "perpetual":
        return any(term in context for term in ("perpetual", "perp", "futures", "future", "usd-m", "永续"))
    return any(term in context for term in ("future", "quarter", "delivery", "交割"))


def _asset_name_matches(text: str, assets: list[CryptoAsset]) -> list[CryptoAsset]:
    matches = [
        asset
        for asset in assets
        if asset.display_name
        and asset.display_name.casefold() != asset.symbol.casefold()
        and _contains_phrase(text, asset.display_name)
    ]
    # Identical names are not enough evidence to choose between assets that
    # share a symbol/name; keep the collision unresolved.
    names = {asset.display_name.casefold() for asset in matches}
    if len(matches) > 1 and len(names) != len(matches):
        return []
    return matches


def _instrument_matches(text: str, instruments: list[CryptoInstrument]) -> list[CryptoInstrument]:
    by_symbol: dict[str, list[CryptoInstrument]] = {}
    for instrument in instruments:
        by_symbol.setdefault(instrument.provider_symbol.casefold(), []).append(instrument)
    matches: list[CryptoInstrument] = []
    for symbol, candidates in by_symbol.items():
        if not re.search(rf"(?<!\w){re.escape(symbol)}(?!\w)", text, re.IGNORECASE):
            continue
        if len(candidates) == 1:
            candidate = candidates[0]
            if _instrument_context_matches(text, candidate):
                matches.append(candidate)
            continue
        # BTCUSDT exists as both spot and perpetual.  A bare provider symbol
        # is not authoritative; only an explicit kind/market context wins.
        matches.extend(
            candidate
            for candidate in candidates
            if _instrument_context_matches(text, candidate)
        )
    return matches


def _instrument_scope_key(instrument: CryptoInstrument) -> str:
    return ":".join(
        (instrument.venue, instrument.market, instrument.kind, instrument.provider_symbol)
    )


def associate_recent_crypto_news(
    db: Session,
    *,
    now: datetime | None = None,
    lookback: timedelta = DEFAULT_ASSOCIATION_LOOKBACK,
    limit: int = DEFAULT_ASSOCIATION_LIMIT,
) -> dict[str, Any]:
    """Associate a bounded persisted NewsItem window without provider calls.

    Matching deliberately uses only full canonical asset names, exact Binance
    symbols with spot/perpetual context, or explicit crypto-market language.
    Bare BTC/ETH (or bare BTCUSDT) never becomes an authoritative association.
    """

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    window_start = current - lookback
    bounded_limit = max(1, min(int(limit), DEFAULT_ASSOCIATION_LIMIT))
    rows = list(
        db.scalars(
            select(NewsItem)
            .where(
                or_(
                    NewsItem.published_at >= window_start,
                    NewsItem.found_at >= window_start,
                )
            )
            .order_by(
                func.coalesce(NewsItem.published_at, NewsItem.found_at).desc(),
                NewsItem.id.desc(),
            )
            .limit(bounded_limit)
        )
    )
    assets = list(
        db.scalars(
            select(CryptoAsset).where(CryptoAsset.status == "active").order_by(CryptoAsset.id.asc())
        )
    )
    instruments = list(
        db.scalars(
            select(CryptoInstrument).where(
                CryptoInstrument.venue == "binance",
                CryptoInstrument.status == "trading",
            ).order_by(CryptoInstrument.id.asc())
        )
    )
    summary: dict[str, Any] = {
        "status": "success",
        "scanned": len(rows),
        "associated": 0,
        "market_associations": 0,
        "asset_associations": 0,
        "instrument_associations": 0,
        "skipped": 0,
        "errors": [],
        "window_start": window_start.isoformat(),
        "window_end": current.isoformat(),
    }
    for item in rows:
        text = _text_for_matching(item)
        candidates: list[dict[str, Any]] = []
        asset_matches = _asset_name_matches(text, assets)
        for asset in asset_matches:
            candidates.append({
                "scope_type": "crypto_asset",
                "scope_key": asset.slug,
                "asset_id": asset.id,
                "provider": item.provider,
                "evidence_method": "asset_name",
                "confidence": 0.95,
                "evidence": {"matched_name": asset.display_name, "source": "persisted_news_text"},
            })
        for instrument in _instrument_matches(text, instruments):
            provider = "binance_spot" if instrument.market == "spot" else "binance_usdm"
            candidates.append({
                "scope_type": "crypto_instrument",
                "scope_key": _instrument_scope_key(instrument),
                "instrument_id": instrument.id,
                "provider": provider,
                "provider_entity_id": instrument.provider_symbol,
                "evidence_method": "instrument_exact",
                "confidence": 0.98,
                "evidence": {
                    "venue": instrument.venue,
                    "provider_symbol": instrument.provider_symbol,
                    "kind": instrument.kind,
                    "market": instrument.market,
                    "source": "persisted_news_text",
                },
            })
        if item.scope == "market" and any(marker in text.casefold() for marker in CRYPTO_MARKET_MARKERS):
            candidates.append({
                "scope_type": "crypto_market",
                "scope_key": "crypto",
                "provider": item.provider,
                "evidence_method": "market_scope",
                "confidence": 0.90,
                "evidence": {"market": "crypto", "source": "persisted_news_text"},
            })
        if not candidates:
            summary["skipped"] += 1
            continue
        for candidate in candidates:
            try:
                # One malformed candidate must not abort the bounded batch.
                with db.begin_nested():
                    associate_news_item(db, news_item=item, **candidate)
                summary["associated"] += 1
                summary[f"{candidate['scope_type'].removeprefix('crypto_')}_associations"] += 1
            except Exception as exc:
                summary["errors"].append({
                    "news_item_id": item.id,
                    "scope_type": candidate["scope_type"],
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                })
    db.commit()
    if summary["errors"]:
        summary["status"] = "partial"
    return summary


# Explicit aliases keep future worker naming independent from the repository
# helper while retaining one implementation.
create_crypto_news_association = associate_news_item
upsert_crypto_news_association = associate_news_item
