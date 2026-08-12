import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.models import IndustryPulseInstrument, IndustryPulseNode, IndustrySeedReplacementReview, Security, SecuritySymbolAlias
from app.services.industry_pulse.definitions import BASE_LEAVES
from app.services.industry_pulse.seed_registry import seed_base_industry_registry


DATA = Path(__file__).parents[1] / "app/services/industry_pulse/data"


def test_canonical_seed_registry_and_lifecycle_invariants():
    registry = json.loads((DATA / "leaf_industry_seed_registry.v1.json").read_text())
    replacements = json.loads((DATA / "replacement_required.v1.json").read_text())
    leaves = registry["leaves"]
    memberships = [member for leaf in leaves for member in leaf["memberships"]]
    taxonomy = {row["code"]: row["id"] for row in BASE_LEAVES}

    assert len(taxonomy) == len(leaves) == 229
    assert {leaf["leaf_code"]: leaf["taxonomy_node_id"] for leaf in leaves} == taxonomy
    assert all(len(leaf["memberships"]) == 5 for leaf in leaves)
    assert all(len({member["ticker"] for member in leaf["memberships"]}) == 5 for leaf in leaves)
    assert len(memberships) == 1145
    assert all(member["source"] == "MANUAL_CURATED_SEED" for member in memberships)
    assert len(registry["unique_universe"]) == registry["statistics"]["unique_ticker_count"] == 861
    assert all({"previous_symbol", "current_symbol", "symbol_change_date", "change_reason"} <= row.keys() for row in registry["symbol_lifecycle"])
    assert len(replacements["items"]) == replacements["count"] == 21
    assert all(len(row["current_other_4_constituents"]) == 4 for row in replacements["items"])


def test_seed_registry_persistence_is_idempotent_and_preserves_disabled_history():
    engine = create_engine("sqlite:///:memory:")
    for table in (Security.__table__, SecuritySymbolAlias.__table__, IndustryPulseNode.__table__, IndustryPulseInstrument.__table__, IndustrySeedReplacementReview.__table__):
        table.create(engine)
    with Session(engine) as db:
        old_bowl = Security(display_symbol="BOWL", local_symbol="BOWL", yahoo_symbol="BOWL", finnhub_symbol="BOWL")
        db.add(old_bowl)
        db.add_all(IndustryPulseNode(taxonomy="base", node_key=row["id"], name=row["name"], level="leaf") for row in BASE_LEAVES)
        db.flush()
        first = seed_base_industry_registry(db)
        second = seed_base_industry_registry(db)

        assert first["created_memberships"] == 1145 and second["created_memberships"] == 0
        assert first["created_securities"] == 860 and second["created_securities"] == 0
        assert first["created_aliases"] == 12 and second["created_aliases"] == 0
        assert first["created_reviews"] == 21 and second["created_reviews"] == 0
        assert db.query(IndustryPulseInstrument).count() == 1145
        assert db.query(IndustryPulseInstrument).filter_by(enabled=False).count() == 21
        assert db.query(IndustrySeedReplacementReview).filter_by(status="PENDING_REVIEW").count() == 21
        db.refresh(old_bowl)
        assert old_bowl.yahoo_symbol == old_bowl.finnhub_symbol == "LUCK"
        assert db.query(Security).filter_by(yahoo_symbol="LUCK").count() == 1
        lc = db.query(SecuritySymbolAlias).filter_by(provider="yahoo", symbol="LC").one()
        assert db.get(Security, lc.security_id).yahoo_symbol == "HAPN"


def test_seed_registry_migration_round_trip():
    path = Path(__file__).parents[1] / "alembic/versions/0055_industry_seed_registry.py"
    spec = importlib.util.spec_from_file_location("industry_seed_registry_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE industry_pulse_instruments (id INTEGER PRIMARY KEY)"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            assert {"seed_version", "slot", "basket_quality"} <= {row["name"] for row in inspect(connection).get_columns("industry_pulse_instruments")}
            assert "industry_seed_replacement_reviews" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "industry_seed_replacement_reviews" not in inspect(connection).get_table_names()
            assert "seed_version" not in {row["name"] for row in inspect(connection).get_columns("industry_pulse_instruments")}
        finally:
            migration.op = original
