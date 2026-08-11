import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_constituent_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions/0052_industry_pulse_constituents.py"
    spec = importlib.util.spec_from_file_location("industry_pulse_constituent_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE industry_pulse_instruments (id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL, ticker VARCHAR(32) NOT NULL, mapping_type VARCHAR(32) NOT NULL, role VARCHAR(32) NOT NULL, enabled BOOLEAN NOT NULL)"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(industry_pulse_instruments)"))}
            assert {"classification_source", "enabled_for_pulse", "valid_to"} <= columns
            migration.downgrade()
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(industry_pulse_instruments)"))}
            assert "classification_source" not in columns
        finally:
            migration.op = original
