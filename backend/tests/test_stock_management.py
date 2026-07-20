from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import PeerExclusion, PeerRelation, PriceSnapshot, StockGroup, StockProfile, ValuationSnapshot, WatchlistItem
from app.services.stock_management import cache_official_relations, merge_peer_symbols, stock_management_payload, valuation_tickers


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[StockGroup.__table__, StockProfile.__table__, WatchlistItem.__table__, PeerRelation.__table__, PeerExclusion.__table__, PriceSnapshot.__table__, ValuationSnapshot.__table__])
    with Session(engine) as session:
        yield session


def _watch(ticker: str, **kwargs) -> WatchlistItem:
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("alert_enabled", True)
    return WatchlistItem(ticker=ticker, **kwargs)


def test_unwatched_manual_peer_appears_in_matched_section(db):
    db.add_all([_watch("AMZN"), StockProfile(ticker="ORCL", official_sector="Technology", official_industry="Software"), PeerRelation(base_ticker="AMZN", peer_ticker="ORCL")])
    db.commit()
    payload = stock_management_payload(db)
    assert [row["ticker"] for row in payload["matched"]] == ["ORCL"]
    assert payload["matched"][0]["peer_referenced_by"] == ["AMZN"]


def test_watched_peer_is_not_duplicated_and_relationship_is_retained(db):
    db.add_all([_watch("AMZN"), _watch("MSFT"), PeerRelation(base_ticker="AMZN", peer_ticker="MSFT")])
    db.commit()
    payload = stock_management_payload(db)
    assert {row["ticker"] for row in payload["watchlisted"]} == {"AMZN", "MSFT"}
    assert payload["matched"] == []
    assert db.query(PeerRelation).count() == 1


def test_removing_watchlist_item_demotes_referenced_stock(db):
    msft = _watch("MSFT")
    db.add_all([_watch("AMZN"), msft, PeerRelation(base_ticker="AMZN", peer_ticker="MSFT")])
    db.commit()
    db.delete(msft)
    db.commit()
    assert [row["ticker"] for row in stock_management_payload(db)["matched"]] == ["MSFT"]


def test_deleting_last_reference_hides_unwatched_stock(db):
    relation = PeerRelation(base_ticker="AMZN", peer_ticker="ORCL")
    db.add_all([_watch("AMZN"), relation])
    db.commit()
    db.delete(relation)
    db.commit()
    assert stock_management_payload(db)["matched"] == []


def test_relations_from_a_removed_base_do_not_keep_matched_stocks_visible(db):
    base = _watch("AMZN")
    db.add_all([base, PeerRelation(base_ticker="AMZN", peer_ticker="ORCL")])
    db.commit()
    db.delete(base)
    db.commit()
    assert stock_management_payload(db)["matched"] == []
    assert valuation_tickers(db) == []


def test_peer_with_multiple_references_survives_one_deletion(db):
    first = PeerRelation(base_ticker="AMZN", peer_ticker="ORCL")
    second = PeerRelation(base_ticker="MSFT", peer_ticker="ORCL")
    db.add_all([_watch("AMZN"), _watch("MSFT"), first, second])
    db.commit()
    db.delete(first)
    db.commit()
    matched = stock_management_payload(db)["matched"]
    assert matched[0]["peer_referenced_by"] == ["MSFT"]


def test_duplicate_and_self_peer_relations_are_rejected(db):
    db.add(PeerRelation(base_ticker="AMZN", peer_ticker="ORCL"))
    db.commit()
    db.add(PeerRelation(base_ticker="AMZN", peer_ticker="ORCL"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(PeerRelation(base_ticker="AMZN", peer_ticker="AMZN"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_manual_group_does_not_replace_official_classification(db):
    group = StockGroup(name="AI Software")
    db.add(group)
    db.flush()
    db.add_all([StockProfile(ticker="MSFT", official_sector="Technology", official_industry="Software - Infrastructure"), _watch("MSFT", user_group_id=group.id)])
    db.commit()
    row = stock_management_payload(db)["watchlisted"][0]
    assert row["user_group_id"] == group.id
    assert row["official_sector"] == "Technology"
    assert row["official_industry"] == "Software - Infrastructure"


def test_existing_snapshot_supplies_classification_before_profile_backfill(db):
    db.add_all([_watch("AMZN"), ValuationSnapshot(ticker="AMZN", snapshot_date=date.today(), payload={"company": "Amazon", "classification": {"sector": "Consumer Cyclical", "industry": "Internet Retail"}})])
    db.commit()
    row = stock_management_payload(db)["watchlisted"][0]
    assert row["company_name"] == "Amazon"
    assert row["official_sector"] == "Consumer Cyclical"
    assert row["official_industry"] == "Internet Retail"


def test_effective_peers_merge_manual_and_exclusions_without_duplicates():
    assert merge_peer_symbols(["MSFT", "ORCL", "AMD"], ["GOOGL", "MSFT"], ["ORCL"], "AMZN") == ["MSFT", "AMD", "GOOGL"]
    assert merge_peer_symbols(["AMZN"], [], [], "AMZN") == []


def test_official_peer_cache_respects_exclusion_and_can_be_restored(db):
    db.add(PeerExclusion(base_ticker="AMZN", peer_ticker="ORCL"))
    db.commit()
    cache_official_relations(db, "AMZN", ["MSFT", "ORCL"])
    db.commit()
    rows = {row.peer_ticker: row for row in db.query(PeerRelation).all()}
    assert rows["MSFT"].source == "official" and rows["MSFT"].enabled is True
    assert rows["ORCL"].enabled is False
    db.query(PeerExclusion).delete()
    cache_official_relations(db, "AMZN", ["MSFT", "ORCL"])
    db.commit()
    assert db.query(PeerRelation).filter_by(peer_ticker="ORCL").one().enabled is True


def test_valuation_sync_scope_includes_watched_and_referenced_only_once(db):
    db.add_all([_watch("AMZN"), _watch("MSFT"), PeerRelation(base_ticker="AMZN", peer_ticker="ORCL"), PeerRelation(base_ticker="MSFT", peer_ticker="ORCL")])
    db.commit()
    assert valuation_tickers(db) == ["AMZN", "MSFT", "ORCL"]


def test_stock_payload_keeps_latest_quote_and_alert_settings(db):
    db.add_all([_watch("AMZN", alert_enabled=False, threshold_day=7), PriceSnapshot(ticker="AMZN", quote_time=datetime.now(UTC), price=107, previous_close=100, volume=1, source="test")])
    db.commit()
    row = stock_management_payload(db)["watchlisted"][0]
    assert row["alert_enabled"] is False
    assert row["threshold_day"] == 7
    assert row["change_percent"] == 7


def test_full_watchlist_sync_queues_all_existing_capabilities(monkeypatch):
    import importlib
    tasks = importlib.import_module("app.tasks.celery_app")

    called = []
    for name in ("sync_ticker_financials", "sync_ticker_filings", "sync_ticker_sec_all", "sync_ticker_congress", "sync_ticker_valuation", "poll_news"):
        monkeypatch.setattr(getattr(tasks, name), "delay", lambda ticker, name=name: called.append((name, ticker)))
    result = tasks.sync_ticker_full.run("msft")
    assert result["status"] == "queued_full_sync"
    assert {name for name, _ in called} == {"sync_ticker_financials", "sync_ticker_filings", "sync_ticker_sec_all", "sync_ticker_congress", "sync_ticker_valuation", "poll_news"}


def test_peer_sync_uses_only_quote_financial_and_valuation_dependencies(monkeypatch):
    import importlib
    tasks = importlib.import_module("app.tasks.celery_app")

    calls = []

    class FakeDb:
        def add(self, value): calls.append("quote_saved")
        def commit(self): calls.append("commit")

    class FakeContext:
        def __enter__(self): return FakeDb()
        def __exit__(self, *args): return False

    monkeypatch.setattr(tasks, "SessionLocal", lambda: FakeContext())
    monkeypatch.setattr(tasks, "_sync_ticker_financials", lambda db, ticker: calls.append("financials") or True)
    monkeypatch.setattr(tasks, "_sync_ticker_valuation", lambda db, ticker, explain=False: calls.append(("valuation", explain)) or True)
    monkeypatch.setattr(tasks, "fetch_quotes", lambda tickers: [])
    result = tasks.sync_peer_valuation_data.run("orcl")
    assert result == {"ticker": "ORCL", "financials": True, "valuation": True, "quotes": 0}
    assert calls == ["financials", ("valuation", False), "commit"]
