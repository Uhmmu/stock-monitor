from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0076_quant_backtesting.py"
TABLES = {
    "quant_strategy_definitions",
    "quant_feature_sets",
    "quant_feature_values",
    "backtest_runs",
    "backtest_equity_points",
    "backtest_trades",
}


def load_migration():
    spec = importlib.util.spec_from_file_location("quant_backtesting_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quant_migration_round_trips_additive_tables():
    engine = create_engine("sqlite:///:memory:")
    migration = load_migration()
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = inspect(connection)
        assert TABLES.issubset(set(inspector.get_table_names()))
        assert "uq_quant_feature_values_input_identity" in {
            item["name"] for item in inspector.get_unique_constraints("quant_feature_values")
        }
        assert "available_at" in {column["name"] for column in inspector.get_columns("quant_feature_values")}
        migration.downgrade()
        assert not (TABLES & set(inspect(connection).get_table_names()))


def test_migration_revision_chain_is_current():
    migration = load_migration()
    assert migration.revision == "0076_quant_backtesting"
    assert migration.down_revision == "0075_ibkr_cp_propagation"
