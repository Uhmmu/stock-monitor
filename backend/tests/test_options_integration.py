from datetime import UTC, date, datetime, timedelta
import importlib.util
from pathlib import Path
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.tool_selector import DOMAIN_RULES, PREFERRED
from app.api.options_routes import options_history, options_overview, options_symbol
from app.models import (
    IndustryPulseInstrument, IndustryPulseNode, OptionsChainCache, OptionsSnapshot,
    OptionsSyncRun, Security, StockGroup, StockProfile, WatchlistItem,
)
from app.services.options.service import overview_payload, semantic_options_context, symbol_payload

tasks = importlib.import_module("app.tasks.celery_app")


TABLES = [
    Security.__table__, StockGroup.__table__, WatchlistItem.__table__, StockProfile.__table__,
    IndustryPulseNode.__table__, IndustryPulseInstrument.__table__, OptionsSnapshot.__table__,
    OptionsChainCache.__table__, OptionsSyncRun.__table__,
]


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in TABLES:
        table.create(engine)
    return Session(engine)


def test_overview_detail_and_semantic_tool_share_persisted_aggregate():
    db = _db()
    sector = IndustryPulseNode(taxonomy="base", node_key="base.technology", name="TECHNOLOGY", level="sector")
    db.add(sector); db.flush()
    db.add(IndustryPulseInstrument(node_id=sector.id, ticker="XLK", instrument_type="equity_etf", mapping_type="etf_proxy", role="primary", enabled=True))
    db.add(WatchlistItem(ticker="NVDA", enabled=True))
    now = datetime.now(UTC)
    for symbol, asset_type, score in (("SPY", "market_etf", 80), ("XLK", "sector_etf", 70), ("NVDA", "watchlist_stock", 90)):
        db.add(OptionsSnapshot(symbol=symbol, trading_date=date.today(), asset_type=asset_type, sector_node_id=sector.id if symbol != "SPY" else None, status="OK", provider="yfinance", underlying_price=100, nearest_expiration=date.today() + timedelta(days=7), active_contracts=2, call_volume=10, put_volume=5, call_open_interest=20, put_open_interest=10, put_call_volume_ratio=.5, put_call_oi_ratio=.5, atm_iv=.3, activity_score=score, activity_status="insufficient_history", quality_score=.8, coverage=.9, sample_size=2, warnings=[], metrics_json={"skew_method": "moneyness_proxy"}, fetched_at=now))
    db.add(OptionsChainCache(symbol="NVDA", expiration=date.today() + timedelta(days=7), calls_json=[{"strike": 100}], puts_json=[{"strike": 90}], contract_count=2, expires_at=now + timedelta(hours=1), fetched_at=now))
    db.commit()

    overview = overview_payload(db)
    assert overview["market"][0]["symbol"] == "SPY"
    assert overview["sectors"][0]["primary"]["symbol"] == "XLK"
    assert overview["rankings"]["activity"][0]["symbol"] == "NVDA"
    detail = symbol_payload(db, "NVDA")
    assert {row["option_type"] for row in detail["chain"]} == {"call", "put"}
    semantic = semantic_options_context(db, symbol="NVDA")
    assert "chain" not in semantic and semantic["quality"]["level"] == "HIGH"
    assert options_overview(ranking="activity", db=db, user=None)["market"][0]["symbol"] == "SPY"
    assert options_symbol("NVDA", db=db, user=None)["selected_expiration"] is not None
    assert options_history("NVDA", days=365, db=db, user=None)["count"] == 1


def test_chat_selector_has_options_semantic_tools():
    assert "期权" in DOMAIN_RULES["options"]
    assert PREFERRED["options"] == ["get_options_overview", "get_symbol_options_summary"]


def test_options_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions/0058_options_analytics.py"
    spec = importlib.util.spec_from_file_location("options_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE securities (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE industry_pulse_nodes (id INTEGER PRIMARY KEY)")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        tables = set(connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars())
        assert {"options_snapshots", "options_chain_cache", "options_sync_runs"} <= tables
        migration.downgrade()
        tables = set(connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars())
        assert "options_snapshots" not in tables


class _Lock:
    def acquire(self, **_kwargs):
        return True

    def release(self):
        return None


class _Redis:
    @staticmethod
    def from_url(*_args, **_kwargs):
        return type("Client", (), {"lock": lambda *_args, **_kwargs: _Lock()})()


def test_sync_options_blocks_duplicate_active_run(monkeypatch):
    db = _db()
    db.add(OptionsSyncRun(status="running", started_at=datetime.now(UTC), trigger_type="scheduled"))
    db.commit()
    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    monkeypatch.setitem(sys.modules, "redis", type("RedisModule", (), {"Redis": _Redis}))
    monkeypatch.setattr(tasks, "_options_jobs", lambda _db: (_ for _ in ()).throw(AssertionError("must not enumerate")))

    assert tasks.sync_options.run()["status"] == "running"


def test_sync_options_isolates_per_symbol_failures(monkeypatch):
    db = _db()
    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    monkeypatch.setitem(sys.modules, "redis", type("RedisModule", (), {"Redis": _Redis}))
    monkeypatch.setattr(tasks, "_options_jobs", lambda _db: [{"symbol": "BAD"}, {"symbol": "GOOD"}])

    def persist(_db, job):
        if job["symbol"] == "BAD":
            raise RuntimeError("provider failed")
        return {"status": "OK", "quality_score": .9}, 12, 8

    monkeypatch.setattr(tasks, "_persist_options_symbol", persist)
    result = tasks.sync_options.run()
    assert result["status"] == "completed"
    assert (result["symbols_requested"], result["symbols_success"], result["symbols_failed"]) == (2, 1, 1)
    with factory() as verify:
        run = verify.get(OptionsSyncRun, result["run_id"])
        assert run.error_summary_json == {"BAD": ["RuntimeError"]}
