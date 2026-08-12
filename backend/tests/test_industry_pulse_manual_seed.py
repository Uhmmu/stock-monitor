import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import IndustryPulseInstrument, IndustryPulseNode, Security
from app.services.industry_pulse.constituents import (
    SymbolClassification,
    _persist_result,
    classification_source_priority,
    seed_manual_curated_memberships,
)
from app.services.industry_pulse.definitions import (
    AI_TAXONOMY_BY_ID,
    MANUAL_CURATED_SEED,
    MANUAL_CURATED_SEED_SOURCE,
    MANUAL_SEED_UNIVERSE,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Security.__table__, IndustryPulseNode.__table__, IndustryPulseInstrument.__table__])
    with Session(engine) as session:
        for node_id in MANUAL_CURATED_SEED:
            row = AI_TAXONOMY_BY_ID[node_id]
            session.add(IndustryPulseNode(taxonomy="ai", node_key=node_id, name=row["name"], level="group"))
        session.commit()
        yield session


def test_seed_is_canonical_idempotent_and_preserves_cross_node_roles(db):
    first = seed_manual_curated_memberships(db)
    db.commit()
    second = seed_manual_curated_memberships(db)
    db.commit()
    rows = db.query(IndustryPulseInstrument).filter_by(classification_source=MANUAL_CURATED_SEED_SOURCE).all()
    assert first["memberships"] == second["memberships"] == 250
    assert first["created"] == 250 and second["created"] == 0
    assert len(rows) == 250
    assert len({row.ticker for row in rows}) == len({ticker for tickers in MANUAL_SEED_UNIVERSE.values() for ticker in tickers})
    assert all(row.enabled and row.enabled_for_pulse and row.valid_from is None for row in rows)
    assert all((row.metadata_json or {}).get("historical_membership_mode") == "MONTHLY_ROLE_WEIGHT_RECONSTRUCTION" for row in rows)
    assert classification_source_priority(MANUAL_CURATED_SEED_SOURCE) > classification_source_priority("AI_CLASSIFIED")

    by_node = {node.node_key: node.id for node in db.query(IndustryPulseNode).all()}
    def role(node: str, ticker: str) -> str:
        return db.query(IndustryPulseInstrument).filter_by(node_id=by_node[node], ticker=ticker).one().constituent_role

    assert role("ai.compute.accelerators", "NVDA") == "CORE"
    assert role("ai.applications.robotics", "NVDA") == "ENABLER"
    assert role("ai.infrastructure.cloud", "MSFT") == "CORE"
    assert role("ai.applications.consumer_ai", "MSFT") == "SECONDARY"
    assert role("ai.infrastructure.data_centers", "NBIS") == "SECONDARY"
    assert role("ai.infrastructure.cloud", "NBIS") == "SECONDARY"
    assert role("ai.power.power_generation", "AES") == "SECONDARY"
    assert role("ai.power.energy_storage", "AES") == "SECONDARY"
    nuclear = db.query(IndustryPulseInstrument).filter_by(node_id=by_node["ai.power.nuclear_fuel_cycle"], ticker="BWXT").one()
    assert nuclear.metadata_json["sub_role"] == "nuclear_components"


def test_manual_seed_source_cannot_be_overwritten_by_luna(db):
    seed_manual_curated_memberships(db)
    db.flush()
    node = db.query(IndustryPulseNode).filter_by(node_key="ai.compute.accelerators").one()
    before = db.query(IndustryPulseInstrument).filter_by(node_id=node.id, ticker="NVDA").one()
    original = (before.constituent_role, before.purity, before.exposure, before.classification_source)
    _persist_result(
        db,
        {"symbol": "NVDA", "candidate_nodes": [node.node_key]},
        SymbolClassification.model_validate({"symbol": "NVDA", "memberships": [{"node": node.node_key, "role": "SECONDARY", "exposure_weight": .3, "confidence": .3, "short_reason": "fixture"}]}),
        metadata_hash="a" * 64,
        model="fixture",
        now=datetime.now(UTC),
    )
    db.flush()
    after = db.query(IndustryPulseInstrument).filter_by(node_id=node.id, ticker="NVDA").one()
    assert (after.constituent_role, after.purity, after.exposure, after.classification_source) == original


def test_manual_seed_migration_round_trip_and_source_check():
    path = Path(__file__).parents[1] / "alembic/versions/0053_manual_curated_seed.py"
    spec = importlib.util.spec_from_file_location("industry_pulse_manual_seed_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE industry_pulse_instruments (id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL, ticker VARCHAR(32) NOT NULL, instrument_type VARCHAR(16) NOT NULL, mapping_type VARCHAR(32) NOT NULL, role VARCHAR(32) NOT NULL, health_status VARCHAR(16) NOT NULL, classification_source VARCHAR(24) NOT NULL)"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            columns = {row[1]: row[2] for row in connection.execute(text("PRAGMA table_info(industry_pulse_instruments)"))}
            assert columns["health_status"] == "VARCHAR(32)"
            connection.execute(text("INSERT INTO industry_pulse_instruments (node_id,ticker,instrument_type,mapping_type,role,health_status,classification_source) VALUES (1,'NVDA','stock','theme_exposure','reference','TEMPORARY_DATA_FAILURE','MANUAL_CURATED_SEED')"))
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO industry_pulse_instruments (node_id,ticker,instrument_type,mapping_type,role,health_status,classification_source) VALUES (1,'BAD','stock','theme_exposure','reference','UNAVAILABLE','NOT_ALLOWED')"))
            migration.downgrade()
            columns = {row[1]: row[2] for row in connection.execute(text("PRAGMA table_info(industry_pulse_instruments)"))}
            assert columns["health_status"] == "VARCHAR(16)"
            assert connection.execute(text("SELECT classification_source FROM industry_pulse_instruments WHERE ticker='NVDA'" )).scalar_one() == "MANUAL"
        finally:
            migration.op = original
