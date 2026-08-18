import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.models import (
    HistoricalPrice,
    IndustryPulseFocusSignal,
    IndustryPulseInstrument,
    IndustryPulseNode,
    IndustryPulseSnapshot,
    MarketDataSyncState,
    PortfolioPosition,
    Security,
    WatchlistItem,
)
from app.services.industry_pulse.provider import DailyBar, ProviderHistory
from app.services.market_calendar import expected_latest_market_session
from app.services.market_data_coordinator import collect_market_data_universe, sync_global_market_data


TABLES = (
    Security.__table__,
    WatchlistItem.__table__,
    PortfolioPosition.__table__,
    IndustryPulseNode.__table__,
    IndustryPulseInstrument.__table__,
    IndustryPulseSnapshot.__table__,
    IndustryPulseFocusSignal.__table__,
    HistoricalPrice.__table__,
    MarketDataSyncState.__table__,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    for table in TABLES:
        table.create(engine)
    return Session(engine)


def test_global_universe_deduplicates_by_current_provider_symbol_and_promotes_priority():
    with _db() as db:
        security = Security(display_symbol="AAA", yahoo_symbol="AAA")
        base = IndustryPulseNode(taxonomy="base", node_key="base.a", name="Base", level="leaf")
        ai = IndustryPulseNode(taxonomy="ai", node_key="ai.a", name="AI", level="leaf")
        db.add_all([security, base, ai]); db.flush()
        db.add_all([
            IndustryPulseInstrument(node_id=base.id, security_id=security.id, ticker="AAA", instrument_type="stock", mapping_type="primary_industry", role="reference", enabled=True, enabled_for_pulse=True),
            IndustryPulseInstrument(node_id=ai.id, security_id=security.id, ticker="OLD", provider_symbol="OLD", instrument_type="stock", mapping_type="theme_exposure", role="reference", enabled=True, enabled_for_pulse=True),
            WatchlistItem(security_id=security.id, ticker="AAA", enabled=True),
            PortfolioPosition(portfolio_id=1, security_id=security.id, symbol="AAA", total_quantity=1),
        ])
        db.flush()
        rows = collect_market_data_universe(db)
        aaa = [row for row in rows if row.symbol == "AAA"]
        assert len(aaa) == 1
        assert aaa[0].priority == "P0"
        assert {"industry_seed", "ai_theme", "watchlist", "portfolio"} <= aaa[0].reasons
        vix = next(row for row in rows if row.symbol == "^VIX")
        assert vix.priority == "P0" and vix.reasons == {"volatility_benchmark"}


def test_freshness_guard_skips_second_fetch_and_persists_adjusted_close():
    with _db() as db:
        now = datetime(2026, 8, 12, 23, tzinfo=UTC)
        expected = expected_latest_market_session(now)
        calls = []

        def fetch(symbols, days):
            calls.append((symbols, days))
            return {"AAA": ProviderHistory("AAA", [DailyBar(expected, 10, 11, 9, 10.5, 100, 10.25)], "yfinance", "success", volume_available=True)}

        first = sync_global_market_data(db, symbols={"AAA"}, now=now, fetcher=fetch)
        second = sync_global_market_data(db, symbols={"AAA"}, now=now, fetcher=fetch)
        assert first["fetched"] == first["valid"] == 1
        assert second["fetched"] == 0 and second["skipped_fresh"] == 1
        assert len(calls) == 1
        stored = db.query(HistoricalPrice).one()
        assert stored.source == "yahoo" and float(stored.adjusted_close) == 10.25
        assert db.get(MarketDataSyncState, "AAA").freshness_status == "FRESH"


def test_permission_denied_is_semantic_and_backed_off():
    with _db() as db:
        result = sync_global_market_data(
            db,
            symbols={"BAD"},
            now=datetime(2026, 8, 12, 23, tzinfo=UTC),
            fetcher=lambda symbols, days: {"BAD": ProviderHistory("BAD", error_code="PROVIDER_PERMISSION_DENIED")},
        )
        state = db.get(MarketDataSyncState, "BAD")
        assert result["failed"] == 1
        assert state.error_code == "PROVIDER_PERMISSION_DENIED"
        assert state.metadata_json["finnhub_permission_denied"] is True
        assert state.next_refresh_at is not None


def test_global_market_data_migration_round_trip():
    path = Path(__file__).parents[1] / "alembic/versions/0056_global_market_data.py"
    spec = importlib.util.spec_from_file_location("global_market_data_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE securities (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE historical_prices (id INTEGER PRIMARY KEY)"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            assert "adjusted_close" in {row["name"] for row in inspect(connection).get_columns("historical_prices")}
            assert "market_data_sync_states" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "market_data_sync_states" not in inspect(connection).get_table_names()
            assert "adjusted_close" not in {row["name"] for row in inspect(connection).get_columns("historical_prices")}
        finally:
            migration.op = original
