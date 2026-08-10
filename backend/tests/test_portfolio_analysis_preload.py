from datetime import UTC, datetime, timedelta
import importlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Portfolio, PortfolioAnalysisRun, PortfolioPosition, User
from app.services.portfolio_analysis import jobs
from app.services.portfolio_analysis.scenario_presets import VISIBLE_SCENARIO_CODES
from app.services.portfolio_analysis.service import run_metrics_analysis
from app.services.portfolio_analysis.schemas import PortfolioAnalysisRequest


TABLES = [User.__table__, Portfolio.__table__, PortfolioPosition.__table__, PortfolioAnalysisRun.__table__]


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def _portfolio(db: Session, name: str = "preload", *, with_position: bool = True) -> Portfolio:
    user = User(username=name, password_hash="x", status="active")
    db.add(user)
    db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name=name)
    db.add(portfolio)
    db.flush()
    if with_position:
        db.add(PortfolioPosition(portfolio_id=portfolio.id, symbol="AAA", total_quantity=1))
    db.commit()
    db.refresh(portfolio)
    return portfolio


def _run(
    db: Session,
    portfolio: Portfolio,
    *,
    status: str,
    completed_at: datetime | None,
    analysis_type: str = "metrics",
    preload: bool = False,
):
    row = PortfolioAnalysisRun(
        portfolio_id=portfolio.id,
        analysis_type=analysis_type,
        status=status,
        input_snapshot_json={"preload": {"scheduled": True}} if preload else {},
        assumptions_json={},
        result_json={},
        model_version="test",
        completed_at=completed_at,
    )
    db.add(row)
    db.commit()
    return row


def test_preload_specs_match_frontend_defaults():
    specs = jobs.preload_specs(9)
    assert [analysis_type for analysis_type, _ in specs] == [
        "metrics",
        "stress_test",
        *(["scenario_analysis"] * 9),
        "optimization",
        "monte_carlo",
    ]
    requests = [request for _, request in specs]
    assert requests[0]["mode"] == "common_start"
    assert requests[1] == {
        **jobs.STRESS_PRELOAD_REQUEST,
        "portfolio_id": 9,
    }
    assert [request["scenario_code"] for request in requests[2:11]] == list(VISIBLE_SCENARIO_CODES)
    monte = requests[-1]
    assert {
        key: monte[key]
        for key in ("horizon_years", "simulations", "method", "rebalance_frequency", "random_seed", "force_refresh")
    } == {
        "horizon_years": 1,
        "simulations": 5000,
        "method": "block_bootstrap",
        "rebalance_frequency": "quarterly",
        "random_seed": 42,
        "force_refresh": True,
    }
    optimization = requests[-2]
    assert optimization["objective"] == "balanced"
    assert optimization["constraints"] == jobs.OPTIMIZATION_PRELOAD_REQUEST["constraints"]


def test_due_selection_respects_fresh_active_and_failed_windows(db):
    now = datetime(2026, 8, 10, 8, tzinfo=UTC)
    fresh = _portfolio(db, "fresh")
    active = _portfolio(db, "active")
    failed_recent = _portfolio(db, "failed_recent")
    failed_old = _portfolio(db, "failed_old")
    manual_fresh = _portfolio(db, "manual_fresh")
    _run(db, fresh, status="completed", completed_at=now - timedelta(days=1), preload=True)
    _run(db, active, status="pending", completed_at=None)
    _run(db, failed_recent, status="failed", completed_at=now - timedelta(hours=2), preload=True)
    _run(db, failed_old, status="failed", completed_at=now - timedelta(hours=25), preload=True)
    _run(db, manual_fresh, status="completed", completed_at=now - timedelta(days=1))
    due = jobs.preload_due_portfolio_ids(db, now=now)
    assert fresh.id not in due
    assert active.id not in due
    assert failed_recent.id not in due
    assert failed_old.id in due
    assert manual_fresh.id in due


def test_due_selection_skips_portfolios_without_holdings(db):
    empty = _portfolio(db, "empty", with_position=False)
    assert empty.id not in jobs.preload_due_portfolio_ids(db, now=datetime(2026, 8, 10, 8, tzinfo=UTC))


def test_claim_snapshots_positions_once_and_attaches_all_rows(db, monkeypatch):
    portfolio = _portfolio(db, "snapshot")
    stale = PortfolioAnalysisRun(
        portfolio_id=portfolio.id,
        analysis_type="monte_carlo",
        status="running",
        input_snapshot_json={"preload": {"scheduled": True}},
        assumptions_json={},
        result_json={},
        model_version="old",
        created_at=datetime(2026, 8, 8, 8, tzinfo=UTC),
    )
    db.add(stale)
    db.commit()
    calls = 0

    def snapshot(_db, _portfolio):
        nonlocal calls
        calls += 1
        return ([{"symbol": "AAA", "market_value": 100.0}], ["warning"])

    monkeypatch.setattr("app.services.portfolio_analysis.service._position_snapshot", snapshot)
    run_ids = jobs.claim_preload_batch(db, portfolio.id, now=datetime(2026, 8, 10, 8, tzinfo=UTC))
    assert len(run_ids) == 13
    assert calls == 1
    assert db.get(PortfolioAnalysisRun, stale.id).status == "failed"
    rows = db.scalars(select(PortfolioAnalysisRun).where(PortfolioAnalysisRun.id.in_(run_ids)).order_by(PortfolioAnalysisRun.id)).all()
    assert {row.input_snapshot_json["preload"]["batch_id"] for row in rows}.__len__() == 1
    assert all(row.input_snapshot_json["portfolio"] == rows[0].input_snapshot_json["portfolio"] for row in rows)
    assert all(row.input_snapshot_json["snapshot_warnings"] == ["warning"] for row in rows)


def test_chain_uses_immutable_signatures_in_run_order(monkeypatch):
    captured = {}

    class FakeTask:
        def si(self, run_id):
            captured.setdefault("ids", []).append(run_id)
            return ("immutable", run_id)

    class FakeWorkflow:
        def apply_async(self):
            captured["queued"] = True
            return type("Result", (), {"id": "task-1"})()

    def fake_chain(*signatures):
        captured["signatures"] = signatures
        return FakeWorkflow()

    celery_module = importlib.import_module("app.tasks.celery_app")
    monkeypatch.setattr(celery_module, "run_portfolio_analysis", FakeTask())
    monkeypatch.setattr("celery.chain", fake_chain)
    result = jobs.queue_preload_chain([3, 4, 5])
    assert result.id == "task-1"
    assert captured["ids"] == [3, 4, 5]
    assert captured["signatures"] == (("immutable", 3), ("immutable", 4), ("immutable", 5))


def test_scheduled_metrics_completes_supplied_run_without_creating_another(db):
    portfolio = _portfolio(db, "metrics")
    row = PortfolioAnalysisRun(
        portfolio_id=portfolio.id,
        analysis_type="metrics",
        status="pending",
        input_snapshot_json={"request": {"mode": "common_start"}, "portfolio": [], "snapshot_warnings": []},
        assumptions_json={},
        result_json={},
        model_version="scheduled",
    )
    db.add(row)
    db.commit()
    result = jobs.execute_analysis_job(db, row.id)
    assert result["status"] == "insufficient_data"
    assert db.query(PortfolioAnalysisRun).count() == 1


def test_manual_metrics_still_creates_exactly_one_run(db, monkeypatch):
    portfolio = _portfolio(db, "manual")
    monkeypatch.setattr(
        "app.services.portfolio_analysis.service._position_snapshot",
        lambda _db, _portfolio: ([], []),
    )
    result = run_metrics_analysis(db, portfolio, PortfolioAnalysisRequest(portfolio_id=portfolio.id))
    assert result["status"] == "insufficient_data"
    assert db.query(PortfolioAnalysisRun).count() == 1


def test_force_only_bypasses_time_window(monkeypatch):
    off_window = datetime(2026, 8, 10, 12, tzinfo=UTC)  # 20:00 Asia/Shanghai
    monkeypatch.setattr(jobs, "read_system_capacity", lambda: (1.0, 800 * 1024 * 1024))
    assert jobs.capacity_guard(now=off_window) == (False, "outside_window")
    assert jobs.capacity_guard(now=off_window, force=True) == (True, None)
    monkeypatch.setattr(jobs, "read_system_capacity", lambda: (2.1, 800 * 1024 * 1024))
    assert jobs.capacity_guard(now=off_window, force=True) == (False, "load_high")
    monkeypatch.setattr(jobs, "read_system_capacity", lambda: (1.0, 699 * 1024 * 1024))
    assert jobs.capacity_guard(now=off_window, force=True) == (False, "memory_low")


def test_enqueue_failure_marks_claimed_rows_failed(db, monkeypatch):
    portfolio = _portfolio(db, "enqueue")
    monkeypatch.setattr(jobs, "capacity_guard", lambda **_kwargs: (True, None))
    monkeypatch.setattr(
        "app.services.portfolio_analysis.service._position_snapshot",
        lambda _db, _portfolio: ([{"symbol": "AAA", "market_value": 100.0}], []),
    )
    monkeypatch.setattr(jobs, "queue_preload_chain", lambda _run_ids: (_ for _ in ()).throw(RuntimeError("broker down")))
    result = jobs.schedule_due_preloads(db, now=datetime(2026, 8, 10, 8, tzinfo=UTC))
    assert result["status"] == "partial"
    rows = db.scalars(select(PortfolioAnalysisRun).where(PortfolioAnalysisRun.portfolio_id == portfolio.id)).all()
    assert len(rows) == 13
    assert {row.status for row in rows} == {"failed"}


def test_multiple_portfolios_share_one_flat_chain(db, monkeypatch):
    first = _portfolio(db, "first_chain")
    second = _portfolio(db, "second_chain")
    captured = []
    monkeypatch.setattr(jobs, "capacity_guard", lambda **_kwargs: (True, None))
    monkeypatch.setattr(
        "app.services.portfolio_analysis.service._position_snapshot",
        lambda _db, _portfolio: ([{"symbol": "AAA", "market_value": 100.0}], []),
    )
    monkeypatch.setattr(jobs, "queue_preload_chain", lambda run_ids: captured.append(run_ids) or type("Result", (), {"id": "chain"})())
    result = jobs.schedule_due_preloads(db, now=datetime(2026, 8, 10, 8, tzinfo=UTC))
    assert result["status"] == "queued"
    assert len(captured) == 1
    assert len(captured[0]) == 26
    assert [item["portfolio_id"] for item in result["queued"]] == [first.id, second.id]
