import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_pi_agent_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions/0064_discovery_pi_agent.py"
    spec = importlib.util.spec_from_file_location("discovery_pi_agent_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        # Minimal post-0063 baseline of the runs table.
        connection.execute(text("""CREATE TABLE stock_discovery_runs (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            portfolio_id INTEGER NOT NULL, idempotency_key VARCHAR(160) NOT NULL,
            trigger VARCHAR(16), discovery_mode VARCHAR(32), status VARCHAR(32),
            stage VARCHAR(48), requested_at DATETIME, warnings JSON,
            failure_code VARCHAR(48), failure_reason TEXT)"""))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(stock_discovery_runs)"))}
            assert "funnel_stats" in columns
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "stock_discovery_agent_events" in tables
            migration.downgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(stock_discovery_runs)"))}
            assert "funnel_stats" not in columns
            tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
            assert "stock_discovery_agent_events" not in tables
        finally:
            migration.op = original
