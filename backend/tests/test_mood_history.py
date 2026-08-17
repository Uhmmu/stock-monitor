from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import MoodDailyRun, MoodSnapshot
from app.services import mood_history
from app.services.market_calendar import expected_latest_market_session, market_sessions


DAY = date(2026, 8, 17)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _signal(category: str, source_as_of: date, *, source: str = "stored", status: str = "READY", score=50):
    return {
        "signal_id": category,
        "source": source,
        "scope_type": "market",
        "scope_key": "US",
        "category": category,
        "metric": category,
        "as_of": DAY.isoformat(),
        "source_as_of": source_as_of.isoformat(),
        "normalized_score": score,
        "status": status,
    }


def _payload(signals, input_hash="first"):
    return {
        "scope_type": "market",
        "scope_key": "US",
        "trading_date": DAY,
        "state": "DORMANT",
        "candidate_state": "DORMANT",
        "mood_score": 50,
        "confidence": .8,
        "quality": .8,
        "coverage": .8,
        "calculation_version": "mood_v1",
        "input_hash": input_hash,
        "signals": signals,
        "evidence": {},
        "divergences": [],
        "transition": {},
        "missing_sources": [],
        "stale_sources": [],
        "input_manifest": {},
    }


def _single_market(monkeypatch, payload):
    monkeypatch.setattr(mood_history, "_expected", lambda db, scopes=None: [
        {"scope_type": "market", "scope_key": "US", "node_id": None, "scope_id": "market:US"},
    ])
    monkeypatch.setattr(mood_history, "_latest_prior", lambda *args, **kwargs: (None, []))
    monkeypatch.setattr(mood_history, "_scope_payload", lambda *args, **kwargs: dict(payload))


def test_optional_stale_does_not_block_and_eod_is_immutable(db, monkeypatch):
    payload = _payload([
        _signal("price", DAY),
        _signal("breadth", DAY),
        _signal("options", date(2026, 8, 14), source="options_snapshot"),
    ])
    _single_market(monkeypatch, payload)
    waiting = mood_history.run_daily_mood(db, DAY, now=datetime(2026, 8, 18, tzinfo=UTC), finalize=False)
    assert waiting["status"] == "PENDING" and db.query(MoodSnapshot).count() == 0
    first = mood_history.run_daily_mood(db, DAY, now=datetime(2026, 8, 18, tzinfo=UTC), finalize=True)
    assert first["status"] == "COMPLETED"
    row = db.query(MoodSnapshot).one()
    assert row.snapshot_type == "EOD" and "options_snapshot:STALE" in row.warnings
    original_hash = row.input_hash
    payload["input_hash"] = "late-upstream-change"
    second = mood_history.run_daily_mood(db, DAY, finalize=True)
    assert second["status"] == "COMPLETED"
    assert db.query(MoodSnapshot).count() == 1
    assert db.query(MoodSnapshot).one().input_hash == original_hash
    refused = mood_history.recover_missing_mood(db, DAY, ["market:US", "watchlist:NVDA"], "mixed retry")
    assert refused["status"] == "REJECTED"


def test_required_missing_waits_then_recovers_without_overwrite(db, monkeypatch):
    payload = _payload([_signal("price", DAY)])
    _single_market(monkeypatch, payload)
    waiting = mood_history.run_daily_mood(db, DAY, finalize=False)
    assert waiting["status"] == "PENDING" and waiting["insufficient_scopes"] == ["market:US"]
    assert db.query(MoodSnapshot).count() == 0
    payload["signals"].append(_signal("breadth", DAY))
    recovered = mood_history.run_daily_mood(db, DAY, finalize=True)
    assert recovered["status"] == "COMPLETED" and db.query(MoodSnapshot).count() == 1
    refused = mood_history.recover_missing_mood(db, DAY, ["market:US"], "operator retry")
    assert refused["status"] == "REJECTED"


def test_holiday_is_rejected_and_weekends_are_not_gaps(db, monkeypatch):
    with pytest.raises(ValueError, match="not an XNYS"):
        mood_history.run_daily_mood(db, date(2026, 7, 4), finalize=True)
    db.add_all([
        MoodDailyRun(trading_date=date(2026, 8, 14), calculation_version="mood_v1", status="PARTIAL", expected_scopes=[], completed_scopes=[], health={"coverage": .5}),
        MoodDailyRun(trading_date=DAY, calculation_version="mood_v1", status="COMPLETED", expected_scopes=[], completed_scopes=[], health={"coverage": 1}),
    ])
    db.commit()
    health = mood_history.history_health_payload(db, trading_date=DAY, days=5)
    days = {item["trading_date"] for item in health["calendar"]}
    assert "2026-08-15" not in days and "2026-08-16" not in days
    assert not [item for item in health["calendar"] if item["status"] == "MISSING"]
    monkeypatch.setattr(mood_history, "expected_latest_market_session", lambda: DAY)
    gaps = mood_history.history_gaps_payload(db, days=5)
    assert gaps["status"] == "DEGRADED" and gaps["gaps"][0]["trading_date"] == "2026-08-14"


def test_future_evidence_is_not_fresh_and_raw_date_fallback_is_used():
    future = _payload([_signal("price", date(2026, 8, 18)), _signal("breadth", DAY)])
    assert mood_history._readiness(future)["freshness"]["price"] == "STALE"
    fallback = _signal("price", DAY)
    fallback["source_as_of"] = None
    fallback["raw_evidence"] = {"trading_date": DAY.isoformat()}
    assert mood_history._source_status(fallback, DAY) == "FRESH"


@pytest.mark.parametrize("moment,expected", [
    (datetime(2026, 1, 5, 20, 59, tzinfo=UTC), date(2026, 1, 2)),
    (datetime(2026, 1, 5, 21, 1, tzinfo=UTC), date(2026, 1, 5)),
    (datetime(2026, 3, 9, 19, 59, tzinfo=UTC), date(2026, 3, 6)),
    (datetime(2026, 3, 9, 20, 1, tzinfo=UTC), date(2026, 3, 9)),
])
def test_latest_closed_session_tracks_new_york_dst(moment, expected):
    assert expected_latest_market_session(moment) == expected
    assert market_sessions(date(2026, 7, 3), date(2026, 7, 5)) == []
