from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PeerExclusion, PeerRelation, PriceSnapshot, StockGroup, StockProfile, ValuationSnapshot, WatchlistItem
from app.services.price_snapshots import get_latest_persisted_price_snapshot


def normalize_ticker(value: str) -> str:
    ticker = (value or "").strip().upper()
    if not ticker or len(ticker) > 16 or not ticker.replace("-", "").replace(".", "").isalnum():
        raise ValueError("股票代码格式无效")
    return ticker


def merge_peer_symbols(official: Iterable[str], manual: Iterable[str], excluded: Iterable[str], base_ticker: str, limit: int = 10) -> list[str]:
    """官方同行优先、手动同行随后；排除只作用于官方项。"""
    base = normalize_ticker(base_ticker)
    exclusions = {normalize_ticker(item) for item in excluded}
    seen: set[str] = {base}
    result: list[str] = []
    for source, symbols in (("official", official), ("manual", manual)):
        for raw in symbols:
            try:
                symbol = normalize_ticker(raw)
            except ValueError:
                continue
            if symbol in seen or (source == "official" and symbol in exclusions):
                continue
            seen.add(symbol)
            result.append(symbol)
            if len(result) >= limit:
                return result
    return result


def effective_peer_symbols(db: Session, base_ticker: str, official: Iterable[str], limit: int = 10) -> list[str]:
    base = normalize_ticker(base_ticker)
    manual = db.scalars(
        select(PeerRelation.peer_ticker).where(PeerRelation.base_ticker == base, PeerRelation.source == "manual", PeerRelation.enabled.is_(True))
        .order_by(PeerRelation.display_order, PeerRelation.id)
    ).all()
    excluded = db.scalars(select(PeerExclusion.peer_ticker).where(PeerExclusion.base_ticker == base)).all()
    return merge_peer_symbols(official, manual, excluded, base, limit)


def referenced_tickers(db: Session) -> list[str]:
    return list(db.scalars(
        select(PeerRelation.peer_ticker)
        .join(WatchlistItem, WatchlistItem.ticker == PeerRelation.base_ticker)
        .where(PeerRelation.enabled.is_(True), WatchlistItem.enabled.is_(True)).distinct()
    ).all())


def valuation_tickers(db: Session) -> list[str]:
    watched = db.scalars(select(WatchlistItem.ticker).where(WatchlistItem.enabled.is_(True))).all()
    return list(dict.fromkeys([*watched, *referenced_tickers(db)]))


def upsert_profile(db: Session, ticker: str, info: dict) -> StockProfile:
    value = normalize_ticker(ticker)
    row = db.get(StockProfile, value)
    if not row:
        row = StockProfile(ticker=value)
        db.add(row)
    row.company_name = info.get("longName") or info.get("shortName") or row.company_name
    row.official_sector = info.get("sector") or row.official_sector
    row.official_industry = info.get("industry") or row.official_industry
    return row


def cache_official_relations(db: Session, base_ticker: str, official: Iterable[str]) -> None:
    """刷新官方同行引用，用于匹配股票视图；估值计算仍直接使用本次官方结果。"""
    base = normalize_ticker(base_ticker)
    excluded = set(db.scalars(select(PeerExclusion.peer_ticker).where(PeerExclusion.base_ticker == base)).all())
    symbols = [normalize_ticker(item) for item in official if normalize_ticker(item) != base]
    existing = {row.peer_ticker: row for row in db.scalars(select(PeerRelation).where(PeerRelation.base_ticker == base)).all()}
    official_set = set(symbols)
    for row in existing.values():
        if row.source == "official" and row.peer_ticker not in official_set:
            row.enabled = False
    for order, symbol in enumerate(symbols):
        row = existing.get(symbol)
        if row and row.source == "manual":
            continue
        if not row:
            row = PeerRelation(base_ticker=base, peer_ticker=symbol, source="official")
            db.add(row)
        row.source = "official"
        row.display_order = order
        row.enabled = symbol not in excluded


def stock_management_payload(db: Session) -> dict:
    watched_rows = db.scalars(select(WatchlistItem).order_by(WatchlistItem.display_order, WatchlistItem.ticker)).all()
    watched = {row.ticker: row for row in watched_rows}
    relations = db.scalars(
        select(PeerRelation).join(WatchlistItem, WatchlistItem.ticker == PeerRelation.base_ticker)
        .where(PeerRelation.enabled.is_(True), WatchlistItem.enabled.is_(True))
        .order_by(PeerRelation.base_ticker, PeerRelation.display_order, PeerRelation.id)
    ).all()
    references: dict[str, list[str]] = defaultdict(list)
    for relation in relations:
        references[relation.peer_ticker].append(relation.base_ticker)
    tickers = set(watched) | set(references)
    profiles = {row.ticker: row for row in db.scalars(select(StockProfile).where(StockProfile.ticker.in_(tickers))).all()} if tickers else {}
    snapshot_profiles: dict[str, dict] = {}
    for ticker in tickers - set(profiles):
        snapshot = db.scalar(select(ValuationSnapshot).where(ValuationSnapshot.ticker == ticker).order_by(ValuationSnapshot.snapshot_date.desc(), ValuationSnapshot.id.desc()).limit(1))
        if snapshot:
            snapshot_profiles[ticker] = snapshot.payload
    quotes: dict[str, PriceSnapshot] = {}
    for ticker in tickers:
        quote = get_latest_persisted_price_snapshot(db, ticker)
        if quote:
            quotes[ticker] = quote

    def serialize(ticker: str, kind: str) -> dict:
        profile, quote, item = profiles.get(ticker), quotes.get(ticker), watched.get(ticker)
        snapshot = snapshot_profiles.get(ticker, {})
        classification = snapshot.get("classification", {})
        change = (
            quote.price_change_percent
            if quote and quote.price_change_percent is not None
            else (
                (quote.last_price / quote.previous_close - 1) * 100
                if quote and quote.previous_close
                else None
            )
        )
        return {
            "ticker": ticker,
            "company_name": profile.company_name if profile else snapshot.get("company"),
            "official_sector": profile.official_sector if profile else classification.get("sector"),
            "official_industry": profile.official_industry if profile else classification.get("industry"),
            "user_group_id": item.user_group_id if item else None,
            "display_order": item.display_order if item else 0,
            "is_watchlisted": ticker in watched,
            "is_peer_referenced": ticker in references,
            "peer_referenced_by": sorted(set(references.get(ticker, []))),
            "stock_type": kind,
            "price": quote.last_price if quote else None,
            "change_percent": round(change, 2) if change is not None else None,
            "alert_enabled": item.alert_enabled if item else False,
            "threshold_20m": item.threshold_20m if item else None,
            "threshold_1h": item.threshold_1h if item else None,
            "threshold_day": item.threshold_day if item else None,
            "watchlist_id": item.id if item else None,
        }

    groups = db.scalars(select(StockGroup).order_by(StockGroup.display_order, StockGroup.id)).all()
    return {
        "groups": [{"id": row.id, "name": row.name, "display_order": row.display_order} for row in groups],
        "watchlisted": [serialize(row.ticker, "watchlist") for row in watched_rows],
        "matched": [serialize(ticker, "matched") for ticker in sorted(set(references) - set(watched))],
    }
