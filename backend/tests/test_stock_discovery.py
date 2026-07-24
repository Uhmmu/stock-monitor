from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    Portfolio,
    StockDiscoveryCandidate,
    StockDiscoveryCandidateGroup,
    StockDiscoveryCandidateGroupMembership,
    StockDiscoveryCandidateMetric,
    StockDiscoveryRun,
    StockDiscoverySettings,
    StockDiscoverySource,
    User,
)
from app.services.discovery.context import build_portfolio_context
from app.services.discovery.locks import discovery_lock
from app.services.discovery.normalization import apply_filters, enrich_candidate, normalize_ticker
from app.services.discovery.perplexity import PerplexityResponseError, build_request, parse_agent_response, response_schema
from app.services.discovery.schemas import DiscoveryResult
from app.services.discovery.service import (
    _persist_annotations,
    _persist_candidates,
    _persist_tool_sources,
    create_discovery_run,
    latest_discovery_payload,
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
    user = User(username="discovery-user", password_hash="x", role="user", status="active")
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, slug="default", name="我的持仓", base_currency="USD")
    db.add(portfolio); db.commit()
    return user, portfolio


def _structured_result():
    return {
        "analysis_date": "2026-07-24",
        "market_context": {"summary": "市场分化", "risk_regime": "mixed", "liquidity_or_flow_summary": "参与度分化", "important_market_drivers": [], "data_limitations": []},
        "portfolio_diagnosis": {"overall_summary": "组合集中", "overweight_exposures": [], "underweight_or_missing_exposures": [], "portfolio_strengths": [], "portfolio_vulnerabilities": []},
        "capital_flow_directions": {"strong_current_flows": [], "weak_or_early_flows": []},
        "candidate_groups": [{"group_id": "core", "group_name": "Quality", "group_type": "quality_core", "group_summary": "高质量",
            "candidates": [{"ticker": "SPGI", "company_name": "S&P Global", "exchange": "NYSE", "country": "US", "sector": "Financial Services", "industry": "Financial Data", "market_cap": 150_000_000_000, "currency": "USD",
                "discovery_reason": "组合补缺", "portfolio_fit": "增加金融数据敞口", "diversification_effect": "positive", "overlap_with_existing_holdings": [],
                "business_quality_summary": "经常性收入", "investment_thesis": ["定价权"], "capital_flow_context": "参与度改善", "valuation_context": "合理", "why_now": "关注度改善",
                "financial_snapshot": {"price": 500, "market_cap": 150_000_000_000, "pe_trailing": 35, "pe_forward": 30, "price_to_sales": 10, "ev_to_ebitda": None, "revenue_growth": .1, "earnings_growth": .12, "gross_margin": None, "operating_margin": .45, "free_cash_flow": 4_000_000_000, "free_cash_flow_margin": .3, "return_on_invested_capital": .18, "net_debt_or_cash": None, "analyst_consensus": None, "data_periods": ["FY2025"]},
                "quality_level": "high", "valuation_level": "reasonable", "momentum_state": "neutral", "candidate_priority": "high", "confidence": .8,
                "major_risks": ["估值"], "thesis_breakers": ["利润率恶化"], "facts_to_verify_locally": ["预期 PE"], "sources": []}]}],
        "avoid_or_overheated": [], "portfolio_actions_for_research": [], "limitations": [],
    }


def test_request_uses_agent_structured_output_and_finance_search():
    request = build_request(context={"holdings": []}, model="openai/gpt-5.4-mini", max_steps=5, max_output_tokens=12000, enable_web_search=True)
    assert request["tools"] == [{"type": "finance_search"}, {"type": "web_search"}]
    assert request["response_format"]["type"] == "json_schema"
    assert request["store"] is False
    assert "$ref" not in str(response_schema())


def test_agent_response_parser_walks_output_and_preserves_tool_results():
    payload = {"status": "completed", "model": "openai/gpt-5.4-mini",
        "output": [
            {"type": "finance_results", "results": [{"category": "quote", "tickers": ["SPGI"], "sources": ["https://www.perplexity.ai/finance/SPGI"]}]},
            {"type": "search_results", "results": [{"title": "Flow", "url": "https://example.com/flow"}]},
            {"type": "message", "content": [{"type": "output_text", "text": __import__("json").dumps(_structured_result())}]},
        ], "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
            "cost": {"input_cost": .001, "output_cost": .002, "tool_calls_cost": .01, "total_cost": .013}}}
    result = parse_agent_response(payload)
    assert result.parsed.candidate_groups[0].candidates[0].ticker == "SPGI"
    assert result.finance_search_calls == 1 and result.web_search_calls == 1
    assert len(result.tool_results) == 2
    assert result.model_cost_usd == pytest.approx(.003)
    assert result.total_cost_usd == pytest.approx(.013)


def test_invalid_structured_output_is_not_accepted():
    with pytest.raises(PerplexityResponseError):
        parse_agent_response({"status": "completed", "model": "x", "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]})


def test_portfolio_context_is_compact_and_excludes_identifiers(db, owner):
    user, portfolio = owner
    context, digest = build_portfolio_context(db, portfolio, user.id)
    assert context["holdings"] == []
    assert context["investment_preferences"]["strategy_type"] == "quality_growth"
    assert "user_id" not in str(context) and "account" not in str(context)
    __import__("json").dumps(context)
    assert len(digest) == 64


@pytest.mark.parametrize("raw,exchange,expected", [
    ("nasdaq:nvda", None, "NVDA"), ("BRK.B", "NYSE", "BRK-B"),
    ("7203", "Tokyo", "7203.T"), ("1578.T", "Tokyo", "1578.T"),
])
def test_symbol_normalization(raw, exchange, expected):
    assert normalize_ticker(raw, exchange)[0] == expected


def test_filter_flags_holdings_and_extreme_valuation():
    settings = StockDiscoverySettings(user_id=1, exclude_current_holdings=True, exclude_watchlist=False,
        require_positive_fcf=True, min_market_cap=2_000_000_000, max_trailing_pe=80, max_forward_pe=60,
        max_price_to_sales=25, filter_extreme_momentum=True, missing_data_policy="warn")
    held = apply_filters(raw={"financial_snapshot": {}}, local={}, ticker="NVDA", settings=settings,
        held_symbols={"NVDA"}, watched_symbols=set(), symbol_valid=True)
    assert held.status == "already_held"
    extreme = apply_filters(raw={"quality_level": "low", "momentum_state": "euphoric", "valuation_level": "extreme",
        "financial_snapshot": {"market_cap": 10_000_000_000, "pe_trailing": 300, "free_cash_flow": -1}},
        local={}, ticker="APP", settings=settings, held_symbols=set(), watched_symbols=set(), symbol_valid=True)
    assert extreme.status == "rejected"
    assert "自由现金流为负" in extreme.reasons


def test_budget_protection_blocks_manual_run(db, owner, monkeypatch):
    user, portfolio = owner
    monkeypatch.setattr("app.services.discovery.service.build_portfolio_context", lambda *_: ({"holdings": []}, "a" * 64))
    config = StockDiscoverySettings(user_id=user.id, max_run_cost_usd=.00001, monthly_budget_usd=10,
        model="openai/gpt-5.4-mini", max_steps=5, max_output_tokens=12000)
    db.add(config); db.commit()
    blocked, queued = create_discovery_run(db, portfolio, user.id)
    assert blocked.status == "blocked_by_budget" and queued is False
    assert blocked.trigger == "manual"
    assert blocked.next_scheduled_at is None


def test_discovery_runs_are_manual_only_and_have_no_beat_schedule(db, owner, monkeypatch):
    from app.tasks.celery_app import celery_app

    user, portfolio = owner
    monkeypatch.setattr("app.services.discovery.service.build_portfolio_context", lambda *_: ({"holdings": []}, "m" * 64))
    db.add(StockDiscoverySettings(user_id=user.id, max_run_cost_usd=1, monthly_budget_usd=10,
        model="openai/gpt-5.4-mini", max_steps=5, max_output_tokens=12000))
    db.commit()

    run, queued = create_discovery_run(db, portfolio, user.id)
    duplicate, queued_again = create_discovery_run(db, portfolio, user.id)

    assert queued is True
    assert duplicate.id == run.id and queued_again is False
    assert run.trigger == "manual"
    assert run.next_scheduled_at is None
    assert "schedule-stock-discovery" not in celery_app.conf.beat_schedule
    assert "app.tasks.celery_app.schedule_stock_discovery" not in celery_app.tasks


def test_discovery_settings_no_longer_expose_automatic_cadence(db, owner):
    user, _portfolio = owner
    payload = settings_payload(db, user.id)
    assert "auto_update_enabled" not in payload
    assert "interval_days" not in payload


def test_failed_run_keeps_previous_success_visible(db, owner):
    user, portfolio = owner
    db.add(StockDiscoverySettings(user_id=user.id))
    success = StockDiscoveryRun(user_id=user.id, portfolio_id=portfolio.id, idempotency_key="success", status="completed",
        stage="completed", requested_at=datetime(2026, 7, 20, tzinfo=UTC), completed_at=datetime(2026, 7, 20, 1, tzinfo=UTC),
        analysis_date=date(2026, 7, 20), model_requested="model", model_used="model", portfolio_snapshot_hash="a" * 64)
    db.add(success); db.flush()
    failed = StockDiscoveryRun(user_id=user.id, portfolio_id=portfolio.id, previous_successful_run_id=success.id,
        idempotency_key="failed", status="failed", stage="failed", requested_at=datetime(2026, 7, 24, tzinfo=UTC), completed_at=datetime(2026, 7, 24, 1, tzinfo=UTC),
        model_requested="model", portfolio_snapshot_hash="b" * 64, failure_code="invalid_response", failure_reason="无法解析")
    db.add(failed); db.commit()
    payload = latest_discovery_payload(db, user.id)
    assert payload["result"]["id"] == success.id
    assert payload["current_run"]["id"] == failed.id
    assert payload["using_previous_result"] is True
    assert "is_fresh" not in payload


def test_candidate_persistence_deduplicates_groups_and_applies_local_verification(db, owner, monkeypatch):
    user, portfolio = owner
    config = StockDiscoverySettings(user_id=user.id)
    run = StockDiscoveryRun(user_id=user.id, portfolio_id=portfolio.id, idempotency_key="candidate-run",
        status="running", stage="local_verification", requested_at=datetime.now(UTC),
        model_requested="model", portfolio_snapshot_hash="c" * 64)
    db.add_all([config, run]); db.commit(); db.refresh(run)
    payload = _structured_result()
    duplicate_group = {**payload["candidate_groups"][0], "group_name": "重复分组"}
    payload["candidate_groups"].append(duplicate_group)
    parsed = DiscoveryResult.model_validate(payload)
    monkeypatch.setattr("app.services.discovery.service.enrich_candidate", lambda *_: ({
        "company_name": "S&P Global Inc.", "market_cap": 160_000_000_000,
        "pe_trailing": 50, "pe_forward": 31, "price_to_sales": 10,
        "free_cash_flow": 4_100_000_000, "as_of": "2026-07-24T00:00:00Z",
        "sources": ["yfinance"],
    }, "verified"))

    warnings = _persist_candidates(db, run, parsed, config)

    candidate = db.scalar(select(StockDiscoveryCandidate).where(StockDiscoveryCandidate.run_id == run.id))
    assert candidate.normalized_ticker == "SPGI"
    assert candidate.verification_status == "verified"
    assert candidate.final_rank == 1
    assert warnings == []
    assert len(db.scalars(select(StockDiscoveryCandidateGroup).where(
        StockDiscoveryCandidateGroup.run_id == run.id)).all()) == 2
    assert len(db.scalars(select(StockDiscoveryCandidateGroupMembership).where(
        StockDiscoveryCandidateGroupMembership.candidate_id == candidate.id)).all()) == 1
    pe_rows = db.scalars(select(StockDiscoveryCandidateMetric).where(
        StockDiscoveryCandidateMetric.candidate_id == candidate.id,
        StockDiscoveryCandidateMetric.metric_key == "pe_trailing",
    )).all()
    assert {row.source for row in pe_rows if row.is_preferred} == {"yfinance"}
    assert all(row.has_discrepancy for row in pe_rows)


def test_source_extraction_preserves_finance_tools_and_message_annotations(db, owner):
    user, portfolio = owner
    run = StockDiscoveryRun(user_id=user.id, portfolio_id=portfolio.id, idempotency_key="sources",
        status="running", stage="searching_finance", requested_at=datetime.now(UTC),
        model_requested="model", portfolio_snapshot_hash="d" * 64)
    db.add(run); db.flush()
    _persist_tool_sources(db, run.id, [{"type": "finance_results", "results": [{
        "sources": [{"title": "Finance", "url": "https://www.perplexity.ai/finance/SPGI"}],
    }]}])
    db.flush()
    _persist_annotations(db, run.id, {"output": [{"type": "message", "content": [{
        "type": "output_text", "text": "{}", "annotations": [
            {"title": "Filing", "url": "https://www.sec.gov/example"},
        ],
    }]}]})
    db.commit()
    sources = db.scalars(select(StockDiscoverySource).where(StockDiscoverySource.run_id == run.id)).all()
    assert {(row.source_origin, row.url) for row in sources} == {
        ("perplexity_finance", "https://www.perplexity.ai/finance/SPGI"),
        ("perplexity_web", "https://www.sec.gov/example"),
    }


def test_local_provider_failure_falls_back_to_agent_financials(db, monkeypatch):
    monkeypatch.setattr("app.services.discovery.normalization.fetch_stock_profile", lambda *_: {})
    local, status = enrich_candidate(db, "SPGI", {"financial_snapshot": {"pe_forward": 30}})
    assert status == "partial"
    assert local["fallback_to_perplexity"] is True


def test_lock_reports_redis_outage_without_claiming_exclusivity(monkeypatch):
    monkeypatch.setattr("app.services.discovery.locks.redis.Redis.from_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(__import__("redis").RedisError("offline")))
    with discovery_lock(1) as acquired:
        assert acquired is None
