from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Portfolio, StockDiscoveryRun, User
from app.services.discovery.progress import (
    estimate_duration_seconds,
    run_progress_payload,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def owner(db):
    user = User(username="progress-user", password_hash="x", role="user", status="active")
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="持仓", base_currency="USD")
    db.add(portfolio); db.commit()
    return user, portfolio


def _run(db, owner, **overrides):
    user, portfolio = owner
    now = datetime.now(UTC)
    values = dict(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key=f"pg-{now.timestamp()}-{id(owner)}",
        trigger="manual", discovery_mode="pi_agent", status="running",
        stage="pi_planning", requested_at=now, started_at=now,
        model_requested="gpt-5.6-sol", portfolio_snapshot_hash="p" * 64,
    )
    values.update(overrides)
    run = StockDiscoveryRun(**values)
    db.add(run); db.commit()
    return run


def _history(db, owner, *, mode="pi_agent", durations, before, user_id=None):
    user, portfolio = owner
    requested = before - timedelta(seconds=3600)
    owner_id = user_id if user_id is not None else user.id
    for index, seconds in enumerate(durations):
        started = requested + timedelta(seconds=index)
        db.add(StockDiscoveryRun(
            user_id=owner_id,
            portfolio_id=portfolio.id,
            idempotency_key=f"hist-{mode}-{owner_id}-{index}-{id(owner)}",
            trigger="manual", discovery_mode=mode, status="completed", stage="completed",
            requested_at=started, started_at=started,
            completed_at=started + timedelta(seconds=seconds),
            model_requested="m", portfolio_snapshot_hash="h" * 64,
        ))
    db.commit()


def test_pending_run_reports_placeholder_progress(db, owner):
    run = _run(db, owner, status="pending", started_at=None)
    payload = run_progress_payload(db, run)
    assert payload["progress"] == 1
    assert payload["eta_seconds"] == 420  # pi_agent default, no history yet
    assert payload["expected_duration_seconds"] == 420


def test_completed_run_is_full_progress(db, owner):
    run = _run(db, owner, status="completed", stage="completed")
    payload = run_progress_payload(db, run)
    assert payload["progress"] == 100
    assert payload["eta_seconds"] == 0


def test_failed_run_has_no_percentage(db, owner):
    run = _run(db, owner, status="failed", stage="failed")
    payload = run_progress_payload(db, run)
    assert payload["progress"] is None
    assert payload["eta_seconds"] is None


def test_progress_uses_stage_base_and_time_blend(db, owner):
    started = datetime.now(UTC) - timedelta(seconds=42)
    run = _run(db, owner, stage="pi_planning", started_at=started, requested_at=started)
    payload = run_progress_payload(db, run)
    # time component 42/420 = 10% > stage base 5
    assert payload["progress"] == 10
    assert payload["eta_seconds"] == 378

    # stage advancing must never move the percentage backwards
    later = started + timedelta(seconds=200)
    advanced = _run(db, owner, stage="pi_synthesizing", started_at=started, requested_at=started)
    advanced.stage = "pi_synthesizing"
    payload_later = run_progress_payload(db, advanced, now=later)
    assert payload_later["progress"] >= payload["progress"]
    assert payload_later["progress"] >= 90  # synthesizing stage base


def test_progress_monotonic_across_polls_with_frozen_history(db, owner):
    started = datetime.now(UTC) - timedelta(seconds=10)
    run = _run(db, owner, stage="pi_discovering", started_at=started, requested_at=started)
    previous = 0
    for elapsed in (10, 60, 120, 300, 600, 1200):
        payload = run_progress_payload(db, run, now=started + timedelta(seconds=elapsed))
        assert payload["progress"] >= previous
        assert payload["progress"] <= 95  # running cap: no fake 99%
        previous = payload["progress"]


def test_history_median_drives_eta(db, owner):
    current_requested = datetime.now(UTC)
    _history(db, owner, durations=[100, 200, 300], before=current_requested - timedelta(seconds=1))
    run = _run(db, owner, requested_at=current_requested, started_at=current_requested - timedelta(seconds=50))
    payload = run_progress_payload(db, run)
    assert payload["expected_duration_seconds"] == 200
    assert payload["eta_seconds"] == 150
    assert payload["progress"] == 25  # 50/200


def test_history_after_current_run_is_ignored(db, owner):
    user, portfolio = owner
    current_requested = datetime.now(UTC) - timedelta(seconds=600)
    _history(db, owner, durations=[100], before=current_requested - timedelta(seconds=1))
    # these runs were requested AFTER the current run started; the frozen
    # history snapshot must not see them even though they already completed
    later = datetime.now(UTC) - timedelta(seconds=30)
    for index in range(2):
        started = later + timedelta(seconds=index)
        db.add(StockDiscoveryRun(
            user_id=user.id, portfolio_id=portfolio.id,
            idempotency_key=f"late-{index}-{id(owner)}",
            trigger="manual", discovery_mode="pi_agent", status="completed", stage="completed",
            requested_at=started, started_at=started,
            completed_at=started + timedelta(seconds=3000),
            model_requested="m", portfolio_snapshot_hash="l" * 64,
        ))
    db.commit()
    estimate = estimate_duration_seconds(db, user_id=user.id, discovery_mode="pi_agent", before=current_requested)
    # only one eligible sample -> falls back to the default
    assert estimate == 420.0


def test_user_history_preferred_over_global(db, owner):
    user, _portfolio = owner
    other = User(username="other-progress-user", password_hash="x", role="user", status="active")
    db.add(other); db.commit()
    cutoff = datetime.now(UTC) - timedelta(seconds=1)
    _history(db, owner, durations=[100, 120], before=cutoff)
    _history(db, owner, durations=[900, 900], before=cutoff, user_id=other.id)
    estimate = estimate_duration_seconds(db, user_id=user.id, discovery_mode="pi_agent", before=cutoff)
    assert estimate == 110.0


def test_funnel_stats_refine_screening_stage(db, owner):
    started = datetime.now(UTC) - timedelta(seconds=1)
    run = _run(db, owner, stage="pi_internal_verification", started_at=started, requested_at=started)
    run.funnel_stats = {"candidates_discovered": 40, "candidates_screened": 20}
    db.commit()
    payload = run_progress_payload(db, run)
    # base 38 + span 20 * (20/40) = 48, dominating the tiny time component
    assert payload["progress"] == 48


def test_latest_payload_carries_progress_fields(db, owner, monkeypatch):
    from app.services.discovery import service as service_module

    started = datetime.now(UTC) - timedelta(seconds=30)
    _run(db, owner, stage="pi_external_research", started_at=started, requested_at=started)
    payload = service_module.latest_discovery_payload(db, owner[0].id)
    current = payload["current_run"]
    assert current is not None
    assert isinstance(current["progress"], int)
    assert isinstance(current["eta_seconds"], int)
    assert current["progress"] >= 58  # external research stage base
