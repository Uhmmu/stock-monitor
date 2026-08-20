from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    Portfolio,
    OpportunityHistory,
    StockDiscoveryAgentEvent,
    StockDiscoveryPortfolioSnapshot,
    StockDiscoveryRun,
    StockDiscoverySettings,
    StockDiscoverySource,
    StockDiscoveryUsage,
    User,
)
from app.services.discovery.schemas import DiscoveryResult
from app.services.discovery.pi_agent import (
    PiAgentError,
    PiAgentResult,
    build_request as build_pi_request,
    parse_response as parse_pi_response,
)
from app.services.discovery.progress import record_agent_event
from app.services.discovery.service import (
    execute_discovery_run,
    estimate_max_cost,
    latest_discovery_payload,
    opportunity_history_list,
    settings_payload,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def owner(db):
    user = User(username="pi-agent-user", password_hash="x", role="user", status="active")
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="我的持仓", base_currency="USD")
    db.add(portfolio); db.commit()
    return user, portfolio


def _pi_result_payload():
    return {
        "analysis_date": "2026-08-20",
        "market_context": {"summary": "震荡", "risk_regime": "mixed", "liquidity_or_flow_summary": "分化", "important_market_drivers": [], "data_limitations": []},
        "portfolio_diagnosis": {"overall_summary": "AI 敞口集中", "overweight_exposures": [], "underweight_or_missing_exposures": [], "portfolio_strengths": [], "portfolio_vulnerabilities": []},
        "capital_flow_directions": {"strong_current_flows": [], "weak_or_early_flows": []},
        "candidate_groups": [{"group_id": "complement", "group_name": "组合补缺", "group_type": "portfolio_complement", "group_summary": "补充缺失敞口",
            "candidates": [{"ticker": "ANET", "company_name": "Arista Networks", "exchange": None, "country": "US", "sector": "Technology", "industry": "Networking", "market_cap": None, "currency": "USD",
                "discovery_reason": "AI 网络链补缺", "portfolio_fit": "与现有 AI 算力敞口低重叠", "diversification_effect": "positive", "overlap_with_existing_holdings": ["NVDA"],
                "business_quality_summary": "高利润率网络设备", "investment_thesis": ["数据中心网络需求"], "bear_case": ["云厂商自研芯片白盒交换机替代"], "evidence": [
                    {"claim": "营收增速维持高位", "source_type": "internal_data", "url_or_reference": None, "date": None, "confidence": .8},
                    {"claim": "白盒交换机竞争加剧", "source_type": "web_source", "url_or_reference": "https://example.com/anet-risk", "date": "2026-08-01", "confidence": .6},
                ], "research_depth": "deep_researched",
                "capital_flow_context": "资金关注改善", "valuation_context": "估值偏高", "why_now": "财报确认需求",
                "financial_snapshot": {"price": None, "market_cap": None, "pe_trailing": None, "pe_forward": None, "price_to_sales": None, "ev_to_ebitda": None, "revenue_growth": None, "earnings_growth": None, "gross_margin": None, "operating_margin": None, "free_cash_flow": None, "free_cash_flow_margin": None, "return_on_invested_capital": None, "net_debt_or_cash": None, "analyst_consensus": None, "data_periods": []},
                "quality_level": "high", "valuation_level": "elevated", "momentum_state": "strong", "candidate_priority": "medium", "confidence": .7,
                "major_risks": ["估值"], "thesis_breakers": ["云资本开支收缩"], "facts_to_verify_locally": [], "sources": []}]}],
        "avoid_or_overheated": [], "portfolio_actions_for_research": [], "limitations": ["外部检索部分受限"],
    }


def test_pi_agent_mode_executes_pipeline_and_persists_evidence(db, owner, monkeypatch):
    user, portfolio = owner
    settings = StockDiscoverySettings(
        user_id=user.id, discovery_mode="pi_agent", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    run = StockDiscoveryRun(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key="pi-agent-run",
        trigger="manual", discovery_mode="pi_agent", status="pending",
        stage="preparing_portfolio", requested_at=datetime.now(UTC),
        model_requested="gpt-5.6-sol", portfolio_snapshot_hash="p" * 64,
    )
    db.add_all([settings, run]); db.flush()
    db.add(StockDiscoveryPortfolioSnapshot(
        run_id=run.id, context_hash="p" * 64, payload={"holdings": [], "current_watchlist": []},
    ))
    db.commit()
    parsed = DiscoveryResult.model_validate(_pi_result_payload())
    result = PiAgentResult(
        parsed=parsed,
        raw_response={"status": "completed"},
        output_text="",
        tool_results=[{"tool_name": "get_portfolio_summary", "status": "completed"}],
        model="gpt-5.6-sol",
        usage={"input_tokens": 5000, "output_tokens": 3000},
        events=[{"event_type": "candidate_discovered", "detail": "ANET"}],
        web_search_calls=6,
        deep_search_calls=1,
        input_tokens=5000,
        output_tokens=3000,
        total_tokens=8000,
        tool_cost_usd=.142,
        model_cost_usd=0.0,
        total_cost_usd=.142,
    )
    monkeypatch.setattr("app.services.discovery.service.build_local_research_context", lambda _db, context: context)
    monkeypatch.setattr("app.services.discovery.service.run_pi_agent", lambda request: result)
    monkeypatch.setattr("app.services.discovery.service._persist_candidates", lambda *_, **__: [])
    completed = execute_discovery_run(db, run.id)
    assert completed.status == "completed"
    assert completed.model_used == "gpt-5.6-sol"
    history = opportunity_history_list(db, user.id)[0]
    assert history["search_source"] == "pi_agent"
    usage = db.scalar(select(StockDiscoveryUsage).where(StockDiscoveryUsage.run_id == run.id))
    assert usage.web_search_calls == 6
    assert usage.finance_search_calls == 1  # deep runs land in the legacy finance column
    assert usage.total_cost_usd == pytest.approx(.142)
    assert usage.raw_usage["engine"] == "pi_agent"
    source = db.scalar(select(StockDiscoverySource).where(
        StockDiscoverySource.run_id == run.id, StockDiscoverySource.source_origin == "pi_agent_evidence"))
    assert source is not None
    assert source.url == "https://example.com/anet-risk"
    # raw payload preserves funnel events for observability
    raw = db.scalar(select(OpportunityHistory).where(OpportunityHistory.run_id == run.id))
    assert raw is not None


def test_pi_agent_parse_response_rejects_incomplete_status():
    with pytest.raises(PiAgentError) as excinfo:
        parse_pi_response({"status": "failed", "error": "sidecar crashed", "retryable": True})
    assert excinfo.value.retryable is True


def test_pi_agent_parse_response_validates_schema():
    payload = {"status": "completed", "result": {"unexpected": True}, "usage": {}}
    with pytest.raises(PiAgentError):
        parse_pi_response(payload)


def test_pi_agent_build_request_carries_limits_and_schema(monkeypatch):
    monkeypatch.setattr("app.services.discovery.pi_agent.get_settings", lambda: type("S", (), {
        "pi_agent_timeout_seconds": 900,
    }))
    request = build_pi_request(
        run_id=3, user_id=1, context={"holdings": []}, model="gpt-5.6-sol",
        max_turns=40, max_web_search_calls=15, deep_effort="medium", max_output_tokens=12000,
    )
    assert request["run_id"] == 3
    assert request["limits"]["max_web_search_calls"] == 15
    assert request["limits"]["deep_effort"] == "medium"
    assert "DiscoveryResult" in str(request["output_schema"].get("title", "")) or "candidate_groups" in request["output_schema"]["properties"]


def test_pi_agent_cost_estimate_is_budget_friendly(db, owner):
    user, _ = owner
    settings = StockDiscoverySettings(
        user_id=user.id, discovery_mode="pi_agent", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    estimate = estimate_max_cost({"holdings": []}, settings)
    # 15 searches * $0.007 + medium deep run $0.10
    assert estimate == pytest.approx(.205)


def test_progress_events_advance_funnel_stage_and_merge_stats(db, owner):
    user, portfolio = owner
    run = StockDiscoveryRun(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key="progress-run",
        trigger="manual", discovery_mode="pi_agent", status="running",
        stage="pi_planning", requested_at=datetime.now(UTC),
        model_requested="gpt-5.6-sol", portfolio_snapshot_hash="q" * 64,
    )
    db.add(run); db.commit()
    record_agent_event(db, run, "candidate_discovered", "ANET", {"candidates_discovered": 1})
    record_agent_event(db, run, "candidate_screened", "ANET", {"candidates_screened": 1})
    db.refresh(run)
    assert run.stage == "pi_internal_verification"
    assert run.funnel_stats == {"candidates_discovered": 1, "candidates_screened": 1}
    events = db.scalars(select(StockDiscoveryAgentEvent).where(StockDiscoveryAgentEvent.run_id == run.id)).all()
    assert [event.event_type for event in events] == ["candidate_discovered", "candidate_screened"]


def test_settings_payload_reports_pi_readiness(db, owner, monkeypatch):
    user, _ = owner
    monkeypatch.setattr("app.services.discovery.service.get_settings", lambda: type("S", (), {
        "perplexity_api_key": "k", "exa_api_key": "k", "openai_api_key": "k",
        "perplexity_agent_model": "openai/gpt-5.4",
        "perplexity_enable_web_search": True, "perplexity_max_steps": 5,
        "perplexity_max_output_tokens": 12000,
        "perplexity_max_monthly_budget_usd": 10.0, "perplexity_max_run_cost_usd": 1.0,
        "model_important": "gpt-5.6-sol", "exa_agent_effort": "high",
        "agent_gateway_token": "t", "pi_agent_model": "",
        "pi_agent_max_turns": 40, "pi_agent_max_web_search_calls": 15, "pi_agent_deep_effort": "medium",
    }))
    payload = settings_payload(db, user.id)
    assert payload["pi_agent_ready"] is True
    assert payload["pi_agent_model"] == "gpt-5.6-sol"
    assert payload["pi_agent_deep_effort"] == "medium"


def test_latest_payload_includes_agent_events_for_pi_runs(db, owner, monkeypatch):
    user, portfolio = owner
    settings = StockDiscoverySettings(
        user_id=user.id, discovery_mode="pi_agent", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    run = StockDiscoveryRun(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key="events-run",
        trigger="manual", discovery_mode="pi_agent", status="completed",
        stage="completed", requested_at=datetime.now(UTC), completed_at=datetime.now(UTC),
        model_requested="gpt-5.6-sol", model_used="gpt-5.6-sol", portfolio_snapshot_hash="r" * 64,
    )
    db.add_all([settings, run]); db.commit()
    record_agent_event(db, run, "research_started", "start")
    payload = latest_discovery_payload(db, user.id)
    assert payload["result"]["agent_events"][0]["event_type"] == "research_started"


def test_default_settings_now_exclude_watchlist(db, owner):
    """Discovery must surface NEW names; watched tickers default to watch_only."""
    from app.services.discovery.service import discovery_settings
    user, _ = owner
    settings = discovery_settings(db, user.id)
    assert settings.exclude_watchlist is True
    assert settings.exclude_current_holdings is True


def test_pi_prompt_requires_novelty_over_watchlist():
    from app.services.discovery.prompt import PI_SYSTEM_INSTRUCTIONS
    assert "NOVELTY RULE" in PI_SYSTEM_INSTRUCTIONS
    assert "OUTSIDE current_watchlist" in PI_SYSTEM_INSTRUCTIONS
    assert "failed batch" in PI_SYSTEM_INSTRUCTIONS


def test_watched_candidates_downgrade_to_watch_only(db, owner):
    from app.services.discovery.normalization import apply_filters
    from app.models import StockDiscoverySettings
    settings = StockDiscoverySettings(
        user_id=1, exclude_current_holdings=True, exclude_watchlist=True,
        require_positive_fcf=True, min_market_cap=2_000_000_000,
        max_trailing_pe=80, max_forward_pe=60, max_price_to_sales=25,
        filter_extreme_momentum=True, missing_data_policy="warn",
    )
    decision = apply_filters(
        raw={"financial_snapshot": {"market_cap": 10_000_000_000, "pe_trailing": 20}},
        local={}, ticker="NFLX", settings=settings,
        held_symbols=set(), watched_symbols={"NFLX"}, symbol_valid=True,
    )
    assert decision.status == "already_watched"
    assert "已在自选股" in decision.reasons
