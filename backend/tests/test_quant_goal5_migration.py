from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"

SIGNAL_TABLES = {
    "quant_strategy_deployments",
    "quant_signals",
    "quant_signal_runs",
}
PAPER_TABLES = {
    "paper_accounts",
    "paper_orders",
    "paper_fills",
    "paper_funding_entries",
    "paper_positions",
    "paper_reconciliations",
}


def load_migration(filename: str):
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), VERSIONS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_goal5_migrations_round_trip_additive_tables():
    engine = create_engine("sqlite:///:memory:")
    signals = load_migration("0077_quant_signals.py")
    paper = load_migration("0078_quant_paper.py")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        signals.op = Operations(context)
        signals.upgrade()
        inspector = inspect(connection)
        assert SIGNAL_TABLES.issubset(set(inspector.get_table_names()))
        assert "uq_quant_signals_idempotency_key" in {
            item["name"] for item in inspector.get_unique_constraints("quant_signals")
        }
        assert "uq_quant_signal_runs_deployment_boundary" in {
            item["name"] for item in inspector.get_unique_constraints("quant_signal_runs")
        }
        paper.op = Operations(context)
        paper.upgrade()
        inspector = inspect(connection)
        assert PAPER_TABLES.issubset(set(inspector.get_table_names()))
        assert "uq_paper_orders_client_order_id" in {
            item["name"] for item in inspector.get_unique_constraints("paper_orders")
        }
        assert "uq_paper_accounts_user_env" in {
            item["name"] for item in inspector.get_unique_constraints("paper_accounts")
        }
        paper.downgrade()
        assert not (PAPER_TABLES & set(inspect(connection).get_table_names()))
        signals.downgrade()
        remaining = set(inspect(connection).get_table_names())
        assert not (SIGNAL_TABLES & remaining)


def test_goal5_revision_chain():
    signals = load_migration("0077_quant_signals.py")
    paper = load_migration("0078_quant_paper.py")
    assert signals.revision == "0077_quant_signals"
    assert signals.down_revision == "0076_quant_backtesting"
    assert paper.revision == "0078_quant_paper"
    assert paper.down_revision == "0077_quant_signals"
