import importlib.util
from datetime import date, timedelta
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.models import IndustryPulseInstrument, IndustryPulseNode, IndustrySyntheticIndex, Security
from app.services.industry_pulse.synthetic import calculate_equal_weight_index, persist_leaf_indexes


def _history(symbol_index: int, count: int = 30):
    return [
        {"date": date(2026, 1, 1) + timedelta(days=index), "open": 100, "high": 101, "low": 99, "close": 100 + index, "adjusted_close": 100 + index + symbol_index, "volume": 1000}
        for index in range(count)
    ]


def test_equal_weight_index_allows_four_but_not_three_constituents():
    full = {f"S{i}": _history(i) for i in range(5)}
    full["S4"] = full["S4"][:-1]
    points = calculate_equal_weight_index(full)
    assert points[-1]["valid_constituents"] == 4
    assert points[-1]["calculation_status"] == "DEGRADED"
    assert points[-1]["coverage_quality"] == .8

    full["S3"] = full["S3"][:-1]
    points = calculate_equal_weight_index(full)
    assert points[-1]["calculation_status"] == "INSUFFICIENT_COVERAGE"
    assert points[-1]["index_value"] is None


def test_leaf_indexes_persist_idempotently_with_equal_weights():
    engine = create_engine("sqlite:///:memory:")
    for table in (Security.__table__, IndustryPulseNode.__table__, IndustryPulseInstrument.__table__, IndustrySyntheticIndex.__table__):
        table.create(engine)
    with Session(engine) as db:
        leaf = IndustryPulseNode(taxonomy="base", node_key="base.test", name="Test", level="leaf")
        db.add(leaf); db.flush()
        histories = {}
        for index in range(5):
            symbol = f"S{index}"
            security = Security(display_symbol=symbol, yahoo_symbol=symbol)
            db.add(security); db.flush()
            db.add(IndustryPulseInstrument(node_id=leaf.id, security_id=security.id, ticker=symbol, instrument_type="stock", mapping_type="primary_industry", role="reference", classification_source="MANUAL_CURATED_SEED", seed_version=1, enabled=index < 4, enabled_for_pulse=index < 4, valid_to=date(2026, 1, 29) if index == 4 else None))
            histories[symbol] = _history(index)
        first = persist_leaf_indexes(db, histories)
        second = persist_leaf_indexes(db, histories)
        assert first["leaf_count"] == second["leaf_count"] == 1
        assert db.query(IndustrySyntheticIndex).count() == 30
        assert db.query(IndustrySyntheticIndex).order_by(IndustrySyntheticIndex.trading_date).first().index_value == 100
        latest = db.query(IndustrySyntheticIndex).order_by(IndustrySyntheticIndex.trading_date.desc()).first()
        assert latest.calculation_status == "DEGRADED" and latest.valid_constituents == 4


def test_leaf_index_persists_explicit_insufficient_coverage():
    engine = create_engine("sqlite:///:memory:")
    for table in (Security.__table__, IndustryPulseNode.__table__, IndustryPulseInstrument.__table__, IndustrySyntheticIndex.__table__):
        table.create(engine)
    with Session(engine) as db:
        leaf = IndustryPulseNode(taxonomy="base", node_key="base.insufficient", name="Insufficient", level="leaf")
        db.add(leaf); db.flush()
        histories = {}
        for index in range(5):
            symbol = f"S{index}"
            security = Security(display_symbol=symbol, yahoo_symbol=symbol)
            db.add(security); db.flush()
            db.add(IndustryPulseInstrument(node_id=leaf.id, security_id=security.id, ticker=symbol, instrument_type="stock", mapping_type="primary_industry", role="reference", classification_source="MANUAL_CURATED_SEED", seed_version=1))
            histories[symbol] = _history(index) if index < 3 else []

        result = persist_leaf_indexes(db, histories, as_of=date(2026, 2, 1))
        latest = db.query(IndustrySyntheticIndex).one()

        assert result["insufficient"] == 1
        assert latest.calculation_status == "INSUFFICIENT_COVERAGE"
        assert latest.valid_constituents == 3 and latest.coverage_quality == .6


def test_synthetic_index_migration_round_trip():
    path = Path(__file__).parents[1] / "alembic/versions/0057_industry_synthetic_indexes.py"
    spec = importlib.util.spec_from_file_location("industry_synthetic_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE industry_pulse_nodes (id INTEGER PRIMARY KEY)"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            assert "industry_synthetic_indexes" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "industry_synthetic_indexes" not in inspect(connection).get_table_names()
        finally:
            migration.op = original
