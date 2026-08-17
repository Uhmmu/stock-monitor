import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    HistoricalPrice,
    IndustryPulseNode,
    IndustryPulseSnapshot,
    MoodSnapshot,
    NewsItem,
    OptionsSnapshot,
    WatchlistItem,
)
from app.services.mood import (
    DIVERGENCE_TYPES,
    MoodSignal,
    aggregate_signals,
    calculate_divergences,
    classify_mood_state,
    classify_watchlist_state,
    dedupe_news_rows,
    mood_history_payload,
    mood_report_payload,
    rebuild_mood_history,
    sync_mood,
    _options_signals,
    _scope_specs,
    _transition,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _bars(symbol: str, count: int = 280, start: date = date(2025, 1, 1), slope: float = 1.0):
    return [
        HistoricalPrice(
            symbol=symbol, date=start + timedelta(days=index), open=100 + index * slope,
            high=101 + index * slope, low=99 + index * slope, close=100 + index * slope,
            adjusted_close=100 + index * slope, volume=1000 + index * 5, source="yahoo",
        )
        for index in range(count)
    ]


def _signal(metric: str, category: str, score: float, day: date = date(2026, 1, 30)):
    return MoodSignal(
        signal_id=metric, source="test", scope_type="market", scope_key="US", category=category,
        metric=metric, as_of=day, normalized_score=score, status="READY", freshness=1,
        quality=1, confidence=1, coverage=1,
    )


def test_signal_aggregation_preserves_missing_and_evidence_stances():
    summary = aggregate_signals([_signal("price", "price", 75), _signal("breadth", "breadth", 25), MoodSignal(
        signal_id="missing", source="options_snapshot", scope_type="market", scope_key="US", category="options", metric="risk", as_of=date(2026, 1, 30), status="UNAVAILABLE", missing_reason="provider_absent",
    )])
    assert 0 < summary["mood_score"] < 100
    assert summary["missing_sources"] == ["provider_absent"]
    assert summary["evidence"]["supporting"][0]["stance"] == "supporting"
    assert summary["evidence"]["contradicting"][0]["stance"] == "contradicting"


@pytest.mark.parametrize("score,categories,state", [
    (48, {"price": 48, "breadth": 50, "relative_strength": 50, "technical": 50}, "DORMANT"),
    (52, {"price": 55, "breadth": 50, "relative_strength": 55, "technical": 55}, "EARLY_IMPROVEMENT"),
    (60, {"price": 56, "breadth": 55, "relative_strength": 55, "technical": 55}, "ACCUMULATION"),
    (70, {"price": 70, "breadth": 75, "relative_strength": 70, "technical": 70}, "EXPANSION"),
    (70, {"price": 70, "breadth": 60, "relative_strength": 70, "technical": 70}, "LEADERSHIP"),
    (80, {"price": 80, "breadth": 40, "relative_strength": 70, "technical": 70, "options": 30}, "CROWDED"),
    (47, {"price": 60, "breadth": 30, "relative_strength": 55, "technical": 50, "options": 35}, "DISTRIBUTION"),
    (38, {"price": 35, "breadth": 35, "relative_strength": 40, "technical": 40}, "DETERIORATION"),
    (20, {"price": 20, "breadth": 20, "relative_strength": 20, "technical": 20}, "BREAKDOWN"),
])
def test_state_machine_covers_all_states(score, categories, state):
    assert classify_mood_state({"mood_score": score, "coverage": 1, "category_scores": categories}) == state


def test_state_transition_hysteresis_persistence_and_rapid_breakdown():
    previous = MoodSnapshot(
        scope_type="sector", scope_key="technology", trading_date=date(2026, 1, 29),
        state="DORMANT", candidate_state=None, mood_score=48, input_hash="x",
        state_started_on=date(2026, 1, 27), calculation_version="mood_v1",
    )
    state, transition, started, duration = _transition("EXPANSION", {"mood_score": 70, "as_of": date(2026, 1, 30)}, previous)
    assert state == "DORMANT" and not transition["confirmed"]
    assert started == date(2026, 1, 27) and duration == 4
    previous.candidate_state = "EXPANSION"
    state, transition, _, _ = _transition("EXPANSION", {"mood_score": 70, "as_of": date(2026, 2, 2)}, previous)
    assert state == "EXPANSION" and transition["changed"] and transition["confirmed"]
    state, transition, _, _ = _transition("BREAKDOWN", {"mood_score": 20, "as_of": date(2026, 1, 30)}, previous)
    assert state == "BREAKDOWN" and transition["fast_path"]


def test_state_machine_missing_and_conflicting_signals_are_not_leadership():
    assert classify_mood_state({"mood_score": None, "coverage": 0, "category_scores": {}}) == "INSUFFICIENT_DATA"
    state = classify_mood_state({"mood_score": 55, "coverage": 1, "category_scores": {"price": 80, "breadth": 20, "relative_strength": 30}})
    assert state not in {"LEADERSHIP", "EXPANSION"}


def test_watchlist_uses_light_state_vocabulary():
    result = classify_watchlist_state({"mood_score": 72, "coverage": 1, "category_scores": {"price": 75, "relative_strength": 75, "technical": 75, "options": 50}})
    assert result in {"TRENDING_UP", "STRETCHED"}
    assert result not in {"EXPANSION", "LEADERSHIP", "ACCUMULATION"}


def test_ai_chain_scope_includes_primary_secondary_and_leaf_nodes(db):
    db.add_all([
        IndustryPulseNode(taxonomy="ai", node_key="ai.compute", name="Compute", level="sector", enabled=True),
        IndustryPulseNode(taxonomy="ai", node_key="ai.compute.chips", name="Chips", level="group", enabled=True),
        IndustryPulseNode(taxonomy="ai", node_key="ai.compute.chips.gpu", name="GPU", level="leaf", enabled=True),
    ])
    db.commit()
    assert {key for scope, key, _ in _scope_specs(db, {"ai_chain"}) if scope == "ai_chain"} == {
        "ai.compute", "ai.compute.chips", "ai.compute.chips.gpu",
    }


def test_options_adapter_consumes_all_semantic_states_without_directional_bias(db):
    db.add(OptionsSnapshot(
        symbol="SPY", trading_date=date(2026, 1, 30), asset_type="etf", status="ready",
        quality_score=.9, coverage=.8, fetched_at=datetime(2026, 1, 30, tzinfo=UTC),
        metrics_json={"options_state": {
            "activity": {"status": "HIGH", "raw_metrics": {"percentile": 90}},
            "bias": {"status": "CALL_HEAVY"},
            "risk_pricing": {"status": "IV_HIGH"},
            "positioning": {"status": "CONCENTRATED", "raw_metrics": {"largest_oi_strikes": [{"strike": 100}]}},
            "historical_regime": {"status": "EXTREME"},
        }},
    ))
    db.commit()
    signals = _options_signals(db, "market", "US", ["SPY"], date(2026, 1, 30))
    by_metric = {signal.metric: signal for signal in signals}
    assert {"activity_percentile", "bias", "risk_pricing", "positioning", "historical_regime"} <= set(by_metric)
    assert by_metric["bias"].normalized_score is None
    assert by_metric["activity_percentile"].normalized_score is None
    assert by_metric["positioning"].normalized_score is None
    assert by_metric["risk_pricing"].normalized_score == pytest.approx(35)


def test_divergences_are_exactly_six_and_support_persistence_resolution():
    day = date(2026, 1, 30)
    signals = [_signal("price", "price", 80, day), _signal("breadth", "breadth", 20, day), _signal("rs", "relative_strength", 20, day), _signal("technical", "technical", 20, day), _signal("options", "options", 20, day), _signal("news", "news", 20, day)]
    first = calculate_divergences(signals, as_of=day)
    assert {item["type"] for item in first} == set(DIVERGENCE_TYPES)
    active = next(item for item in first if item["type"] == "PRICE_BREADTH")
    assert active["onset"] and active["duration_sessions"] == 1
    second = calculate_divergences(signals, previous=first, as_of=day + timedelta(days=1))
    active = next(item for item in second if item["type"] == "PRICE_BREADTH")
    assert active["persistence_sessions"] == 2
    resolved = calculate_divergences([_signal("price", "price", 50, day + timedelta(days=2)), _signal("breadth", "breadth", 50, day + timedelta(days=2))], previous=second, as_of=day + timedelta(days=2))
    assert next(item for item in resolved if item["type"] == "PRICE_BREADTH")["resolved"]
    neutral = calculate_divergences([_signal("price", "price", 50), _signal("breadth", "breadth", 50)])
    assert not any(item["active"] for item in neutral)


def test_news_dedup_prefers_quality_and_fingerprint_chain():
    now = datetime(2026, 1, 30, tzinfo=UTC)
    rows = [
        NewsItem(ticker="AAA", provider="a", fingerprint="f1", canonical_story_id="story", cluster_key="c1", title="one", url="https://a/1", published_at=now, found_at=now, quality_score=.2, sentiment_score=-1),
        NewsItem(ticker="AAA", provider="b", fingerprint="f2", canonical_story_id="story", cluster_key="c1", title="one", url="https://b/1", published_at=now, found_at=now, quality_score=.9, sentiment_score=1),
        NewsItem(ticker="AAA", provider="a", fingerprint="f3", cluster_key="c2", title="two", url="https://a/2", published_at=now, found_at=now),
    ]
    result = dedupe_news_rows(rows)
    assert len(result) == 2 and result[0].quality_score == pytest.approx(.9)


def test_sync_persists_versioned_snapshot_and_payload_shapes(db):
    db.add_all(_bars("SPY")); db.add(WatchlistItem(ticker="SPY", enabled=True)); db.commit()
    result = sync_mood(db, as_of=date(2025, 10, 7), scopes={"market", "watchlist"})
    assert result["created"] == 2
    row = db.query(MoodSnapshot).filter_by(scope_type="market", scope_key="US").one()
    assert row.input_manifest["evidence_type"] == "DIRECT"
    report = mood_report_payload(db)
    assert {"market", "sectors", "industries", "ai_chain", "watchlist", "movers", "divergences", "transitions", "report"} <= set(report)
    history = mood_history_payload(db, "market", "US", days=20)
    assert history["item"]["scope_key"] == "US"


def test_rebuild_uses_stored_dates_and_never_future_rows(db):
    db.add_all(_bars("SPY", count=5, start=date(2026, 1, 1))); db.commit()
    result = rebuild_mood_history(db, date(2026, 1, 1), date(2026, 1, 10))
    assert result["dates"] == 5
    assert db.query(MoodSnapshot).count() >= 5
    assert all(item.trading_date <= date(2026, 1, 10) for item in db.query(MoodSnapshot).all())


def test_mood_migration_round_trip_on_sqlite():
    path = Path(__file__).parents[1] / "alembic/versions/0059_ai_mood_engine.py"
    spec = importlib.util.spec_from_file_location("mood_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            assert "mood_snapshots" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "mood_snapshots" not in inspect(connection).get_table_names()
        finally:
            migration.op = original
