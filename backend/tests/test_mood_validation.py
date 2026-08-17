import importlib.util
from datetime import date, timedelta
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import HistoricalPrice, MoodSnapshot, MoodValidationResult, User
from app.services.mood_validation import (
    MIN_SAMPLE,
    confidence_bucket,
    create_run,
    execute_run,
    robust_stats,
    replay_snapshot_states,
    segment_episodes,
    _outcome,
    _price_series,
)


def _snapshot(day: date, state: str, index: int) -> MoodSnapshot:
    score = 70 if state == "EXPANSION" else 58
    signal = {
        "signal_id": f"price-{index}", "source": "test", "scope_type": "market", "scope_key": "US",
        "category": "price", "metric": "return", "as_of": day.isoformat(), "normalized_score": score,
        "status": "READY", "freshness": 1, "quality": 1, "confidence": 1, "coverage": 1,
    }
    return MoodSnapshot(
        scope_type="market", scope_key="US", trading_date=day, state=state, candidate_state=state,
        previous_state=None, mood_score=score, agreement_score=.8, confidence=.8, quality=.9, coverage=.9,
        input_hash=f"hash-{index}", calculation_version="mood_v1", signals=[signal], evidence={}, divergences=[],
        snapshot_type="EOD",
        transition={"changed": index == 5, "confirmed": True}, missing_sources=[], stale_sources=[],
        input_manifest={"symbols": ["SPY"], "evidence_type": "DIRECT"},
    )


def test_statistics_buckets_and_episode_segmentation_are_deterministic():
    values = [float(index) for index in range(MIN_SAMPLE)]
    assert robust_stats(values, "fixed") == robust_stats(values, "fixed")
    assert robust_stats(values, "fixed")["status"] == "READY"
    assert robust_stats(values[:2])["status"] == "INSUFFICIENT_SAMPLE"
    assert confidence_bucket(.2) == "0.0-0.4"
    assert confidence_bucket(.4) == "0.4-0.5"
    assert confidence_bucket(1) == "0.9-1.0"
    rows = [_snapshot(date(2026, 1, 1) + timedelta(days=index), "ACCUMULATION" if index < 2 else "EXPANSION", index) for index in range(4)]
    episodes = segment_episodes(rows)
    assert [(item["state"], item["duration"]) for item in episodes] == [("ACCUMULATION", 2), ("EXPANSION", 2)]
    assert episodes[1]["previous_state"] == "ACCUMULATION"


def test_price_source_ties_and_excursions_are_deterministic():
    day = date(2026, 1, 1)
    rows = [
        HistoricalPrice(id=1, symbol="AAA", date=day, open=100, high=100, low=100, close=100, adjusted_close=100, volume=1, source="yahoo"),
        HistoricalPrice(id=2, symbol="AAA", date=day, open=101, high=101, low=101, close=101, adjusted_close=101, volume=1, source="yfinance"),
        HistoricalPrice(symbol="AAA", date=day + timedelta(days=1), open=102, high=102, low=102, close=102, adjusted_close=102, volume=1, source="yahoo"),
    ]
    series = _price_series(reversed(rows))
    assert series["AAA"][1][0] == 101
    outcome = _outcome(series, "AAA", day, 1)
    assert outcome and outcome["mae"] == 0 and outcome["mfe"] > 0


def test_chronological_replay_confirms_twice_fast_breaks_and_ignores_future():
    start = date(2026, 2, 2)
    rows = [_snapshot(start + timedelta(days=index), "ACCUMULATION", index) for index in range(4)]
    rows[1].candidate_state = "EXPANSION"
    rows[2].candidate_state = "EXPANSION"; rows[2].state = "EXPANSION"
    rows[3].candidate_state = "BREAKDOWN"; rows[3].state = "BREAKDOWN"; rows[3].mood_score = 20
    replayed = replay_snapshot_states(rows)
    assert [state for _, state in replayed] == ["ACCUMULATION", "ACCUMULATION", "EXPANSION", "BREAKDOWN"]
    rows[3].candidate_state = "LEADERSHIP"
    assert [state for _, state in replay_snapshot_states(rows, cutoff=rows[2].trading_date)] == ["ACCUMULATION", "ACCUMULATION", "EXPANSION"]


def test_validation_run_is_append_only_and_outcomes_do_not_change_mood_rows():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="admin", password_hash="x", role="admin", status="active")
        db.add(user); db.flush()
        start = date(2026, 1, 1)
        states = ["ACCUMULATION"] * 5 + ["EXPANSION"] * 15
        db.add_all(_snapshot(start + timedelta(days=index), state, index) for index, state in enumerate(states))
        db.add_all(HistoricalPrice(
            symbol="SPY", date=start + timedelta(days=index), open=100 + index, high=101 + index,
            low=99 + index, close=100 + index, adjusted_close=100 + index, volume=1000,
            source="yahoo",
        ) for index in range(90))
        db.commit()
        before = [(row.id, row.state, row.input_hash) for row in db.query(MoodSnapshot).order_by(MoodSnapshot.id)]
        run = create_run(db, user.id, date_from=start, date_to=start + timedelta(days=19), scope_filter=["market"], horizons=[1, 5, 10, 20, 60])
        db.flush(); execute_run(db, run.id); db.commit()
        assert run.status == "completed" and run.progress == 100
        occupancy = db.query(MoodValidationResult).filter_by(run_id=run.id, study_type="state_occupancy").all()
        assert len(occupancy) == 10
        assert {row.state for row in occupancy if row.sample_count} == {"ACCUMULATION", "EXPANSION"}
        assert db.query(MoodValidationResult).filter_by(run_id=run.id, study_type="transition").count() == 1
        assert before == [(row.id, row.state, row.input_hash) for row in db.query(MoodSnapshot).order_by(MoodSnapshot.id)]
        assert "STRICT_REPLAY_USES_PERSISTED_SNAPSHOTS_ONLY" in run.warnings


def test_validation_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions/0060_mood_validation_lab.py"
    spec = importlib.util.spec_from_file_location("mood_validation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            assert {"mood_validation_runs", "mood_validation_results"} <= set(inspect(connection).get_table_names())
            migration.downgrade()
            assert "mood_validation_runs" not in inspect(connection).get_table_names()
        finally:
            migration.op = original
