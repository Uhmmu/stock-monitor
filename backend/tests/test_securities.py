import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Security, SecuritySymbolAlias
from app.services import securities


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.setattr(securities, "_redis_get", lambda *_: None)
    monkeypatch.setattr(securities, "_redis_set", lambda *_: None)
    securities.clear_search_cache()
    yield
    securities.clear_search_cache()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Security.__table__.create(engine)
    SecuritySymbolAlias.__table__.create(engine)
    with Session(engine) as session:
        yield session


def yahoo(symbol="AAPL", name="Apple Inc.", quote_type="EQUITY", exchange="NMS"):
    return securities.yahoo_result({"symbol": symbol, "longname": name, "quoteType": quote_type, "exchange": exchange})


def test_empty_query_returns_empty_without_remote(db, monkeypatch):
    remote = Mock()
    monkeypatch.setattr(securities, "yahoo_search", remote)
    assert securities.search_securities(db, "   ") == []
    remote.assert_not_called()


def test_exact_ticker_ranks_first():
    rows = [yahoo("APP", "AppLovin Corporation"), yahoo("AAPL", "Apple Inc.")]
    assert securities.dedupe_and_sort(rows, "aapl", 12)[0]["display_symbol"] == "AAPL"


def test_company_name_fuzzy_search_sorting():
    rows = [yahoo("TM", "Toyota Motor Corporation ADR"), yahoo("7203.T", "Toyota Motor Corporation", exchange="JPX")]
    result = securities.dedupe_and_sort(rows, "toyota", 12)
    assert {row["display_symbol"] for row in result} == {"TM", "7203.T"}


def test_dedupe_prefers_local_security():
    remote = yahoo()
    local = {**remote, "source": "local", "provider_key": "security:1", "security_id": 1, "is_local": True}
    result = securities.dedupe_and_sort([remote, local], "apple", 12)
    assert len(result) == 1
    assert result[0]["is_local"] is True


def test_missing_yahoo_fields_are_safe():
    result = securities.yahoo_result({"symbol": "AAPL"})
    assert result["display_name"] == "AAPL"
    assert result["instrument_type"] == "EQUITY"


def test_yahoo_success_does_not_require_finnhub(db, monkeypatch):
    monkeypatch.setattr(securities, "yahoo_search", lambda *_: [yahoo()])
    fallback = Mock(side_effect=RuntimeError)
    monkeypatch.setattr(securities, "finnhub_search", fallback)
    assert securities.search_securities(db, "apple")[0]["display_symbol"] == "AAPL"
    fallback.assert_not_called()


def test_yahoo_failure_uses_finnhub_fallback(db, monkeypatch):
    monkeypatch.setattr(securities, "yahoo_search", Mock(side_effect=RuntimeError))
    monkeypatch.setattr(securities, "finnhub_search", lambda *_: [{
        "provider_key": "finnhub:AAPL", "security_id": None, "display_symbol": "AAPL",
        "display_name": "Apple Inc.", "local_symbol": "AAPL", "exchange": None,
        "exchange_code": None, "market": "US", "country_code": "US", "currency": "USD",
        "instrument_type": "EQUITY", "yahoo_symbol": None, "finnhub_symbol": "AAPL",
        "source": "finnhub", "is_local": False,
    }])
    assert securities.search_securities(db, "apple")[0]["source"] == "finnhub"


def test_adr_and_local_listing_are_not_merged():
    rows = [yahoo("TM", "Toyota Motor Corporation ADR", "ADR", "NYQ"), yahoo("7203.T", "Toyota Motor Corporation", "EQUITY", "JPX")]
    assert len(securities.dedupe_and_sort(rows, "toyota", 12)) == 2


def test_japanese_suffix_is_never_guessed_as_finnhub_symbol(db, monkeypatch):
    monkeypatch.setattr(securities, "fetch_stock_profile", lambda *_: {"longName": "Toyota Motor Corporation", "exchange": "JPX", "quoteType": "EQUITY", "currency": "JPY"})
    fallback = Mock(return_value=[{"finnhub_symbol": "7203", "display_name": "Toyota Motor Corporation"}])
    monkeypatch.setattr(securities, "finnhub_search", fallback)
    row = securities.resolve_security(db, source="yahoo", yahoo_symbol="7203.T")
    assert row.finnhub_symbol is None
    fallback.assert_not_called()


def test_remote_cache_hits(db, monkeypatch):
    remote = Mock(return_value=[yahoo()])
    monkeypatch.setattr(securities, "yahoo_search", remote)
    securities.search_securities(db, "apple", 12)
    securities.search_securities(db, "apple", 12)
    assert remote.call_count == 1


def test_resolve_reuses_existing_security(db, monkeypatch):
    row = Security(display_symbol="AAPL", display_name="Apple Inc.", local_symbol="AAPL", yahoo_symbol="AAPL", yahoo_status="available", finnhub_status="unsupported", mapping_method="unresolved")
    db.add(row); db.commit()
    monkeypatch.setattr(securities, "fetch_stock_profile", lambda *_: {"longName": "Apple Inc."})
    resolved = securities.resolve_security(db, source="yahoo", yahoo_symbol="AAPL")
    assert resolved.id == row.id
    assert db.query(Security).count() == 1


def test_historical_alias_resolves_current_provider_symbol(db, monkeypatch):
    row = Security(display_symbol="FISV", yahoo_symbol="FISV", yahoo_status="available", finnhub_status="unsupported", mapping_method="unresolved")
    db.add(row); db.flush()
    db.add(SecuritySymbolAlias(security_id=row.id, provider="yahoo", symbol="FI", change_reason="TICKER_CHANGED"))
    db.commit()
    assert securities.provider_symbol(db, "FI", "yahoo") == "FISV"
    monkeypatch.setattr(securities, "fetch_stock_profile", lambda symbol: {"longName": "Fiserv", "symbol": symbol})
    assert securities.resolve_security(db, source="yahoo", yahoo_symbol="FI").id == row.id


def test_symbol_alias_migration_round_trip():
    path = Path(__file__).parents[1] / "alembic/versions/0054_security_symbol_aliases.py"
    spec = importlib.util.spec_from_file_location("security_symbol_alias_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Security.__table__.create(connection)
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            assert "security_symbol_aliases" in migration.sa.inspect(connection).get_table_names()
            migration.downgrade()
            assert "security_symbol_aliases" not in migration.sa.inspect(connection).get_table_names()
        finally:
            migration.op = original
