from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    Portfolio,
    OpportunityHistory,
    NewsItem,
    StockDiscoveryCandidate,
    StockDiscoveryCandidateGroup,
    StockDiscoveryCandidateGroupMembership,
    StockDiscoveryCandidateMetric,
    StockDiscoveryRun,
    StockDiscoveryPortfolioSnapshot,
    StockDiscoverySettings,
    StockDiscoverySource,
    StockDiscoveryUsage,
    User,
    WatchlistItem,
)
from app.services.discovery.context import build_portfolio_context
from app.services.discovery.analysis import parse_opportunity_output
from app.services.discovery.locks import discovery_lock
from app.services.discovery.normalization import apply_filters, enrich_candidate, normalize_ticker
from app.services.discovery.schemas import DiscoveryResult, OpportunityBatch
from app.services.discovery.exa import (
    ExaAgentResult,
    build_request as build_exa_request,
    parse_agent_response as parse_exa_agent_response,
)
from app.services.discovery.perplexity import AgentResult, build_request
from app.services.discovery.search import build_search_queries, run_search
from app.services.discovery.service import (
    _as_legacy_result,
    _persist_annotations,
    _persist_candidates,
    _persist_tool_sources,
    create_discovery_run,
    execute_discovery_run,
    estimate_max_cost,
    latest_discovery_payload,
    opportunity_history_detail,
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


def _opportunity_batch():
    return {
        "market_condition": "市场分化，事件驱动机会增加",
        "opportunities": [{
            "title": "支付数据需求改善",
            "ticker": "SPGI",
            "category": ["盈利改善", "长期成长"],
            "summary": "评级与数据业务需求改善，值得进一步研究",
            "why_now": ["近期管理层指引与分析师预期改善"],
            "evidence": [
                {"type": "news", "content": "公司更新了业务展望"},
                {"type": "financial", "content": "本地现金流快照保持正值"},
            ],
            "catalysts": ["下一次财报确认利润率改善"],
            "risks": ["估值仍可能偏高"],
            "valuation_view": "需以本地估值快照进一步核对",
            "confidence": 78,
            "action": ["深入研究"],
        }],
    }


def test_local_engine_normalizes_endpoint_shape_seen_in_production():
    payload = {
        "market_condition": "市场分化",
        "excluded_current_holdings": ["META"],
        "limitations": ["部分数据不足"],
        "opportunities": [{
            "ticker": "WM",
            "company_name": "Waste Management",
            "sector": "Industrials",
            "thesis": {"fact": "现金流保持正值", "inference": "防御属性值得研究"},
            "why_now": "工业板块关注度改善",
            "evidence": [
                {"type": "market", "fact": "资金关注上升", "source": "search"},
                {"type": "financial", "fact": "本地自由现金流为正", "source": "local_data"},
            ],
            "key_risks": ["估值偏高"],
            "research_questions": ["利润率能否维持"],
            "confidence": .8,
            "action": "深入研究",
        }],
    }
    parsed = parse_opportunity_output(json.dumps(payload, ensure_ascii=False))
    item = parsed.opportunities[0]
    assert item.ticker == "WM"
    assert item.confidence == 80
    assert item.why_now == ["工业板块关注度改善"]
    assert item.evidence[0].content == "资金关注上升"
    assert item.action == ["深入研究"]


def test_search_queries_exclude_existing_fundamental_lookups():
    queries = build_search_queries({"current_watchlist": ["SPGI"], "portfolio_summary": {}})
    text = " ".join(queries).lower()
    assert "why-now" in text
    assert "quantitative fundamentals are provided locally" in text
    assert "current price" not in text and "market cap" not in text
    assert len(queries) == 5


def test_agent_mode_keeps_finance_search_and_gpt54():
    request = build_request(
        context={"local_news_summaries": [{"title": "Event", "summary": "概要"}]},
        model="openai/gpt-5.4",
        max_steps=5,
        max_output_tokens=12000,
        enable_web_search=True,
    )
    assert request["model"] == "openai/gpt-5.4"
    assert request["tools"] == [{"type": "finance_search"}, {"type": "web_search"}]
    assert "概要" in request["input"]


def test_exa_mode_uses_agent_and_financial_datasets():
    request = build_exa_request(
        context={"local_news_summaries": [{"title": "Event", "summary": "概要"}]},
        effort="high",
    )
    assert request["effort"] == "high"
    assert request["dataSources"] == [{"provider": "financial_datasets"}]
    assert request["outputSchema"]["title"] == "DiscoveryResult"
    assert "概要" in request["query"]
    assert "Financial Datasets" in request["systemPrompt"]
    assert "finance_search" not in request["systemPrompt"]


def test_exa_agent_response_preserves_grounding_usage_and_exact_cost():
    payload = {
        "status": "completed",
        "output": {
            "structured": _structured_result(),
            "grounding": [{"field": "candidate_groups[0]", "citations": [
                {"title": "SEC filing", "url": "https://www.sec.gov/example"},
            ]}],
        },
        "usage": {
            "searches": 4,
            "dataSources": {"financial_datasets": 3},
            "inputTokens": 100,
            "outputTokens": 200,
            "totalTokens": 300,
        },
        "costDollars": {"total": .56, "agentCompute": .51, "search": .02, "dataSources": {"financial_datasets": .03}},
    }
    result = parse_exa_agent_response(payload)
    assert result.model == "exa-agent"
    assert result.finance_data_calls == 3
    assert result.web_search_calls == 4
    assert result.total_tokens == 300
    assert result.tool_cost_usd == pytest.approx(.05)
    assert result.model_cost_usd == pytest.approx(.51)
    assert result.total_cost_usd == pytest.approx(.56)
    assert result.grounding[0]["citations"][0]["url"].startswith("https://www.sec.gov")


def test_mode_specific_cost_estimate():
    local = StockDiscoverySettings(
        user_id=1, discovery_mode="search_local", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    agent = StockDiscoverySettings(
        user_id=1, discovery_mode="agent_finance", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    exa = StockDiscoverySettings(
        user_id=1, discovery_mode="exa_finance", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    assert estimate_max_cost({"holdings": []}, local) == pytest.approx(.005)
    assert estimate_max_cost({"holdings": []}, agent) > .1
    assert estimate_max_cost({"holdings": []}, exa) == pytest.approx(.65)


def test_raw_search_api_request_contains_no_model(monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            return {"results": [{"title": "Event", "url": "https://example.com/event", "snippet": "why now"}]}
    captured = {}
    monkeypatch.setattr("app.services.discovery.search.get_settings", lambda: type("S", (), {
        "perplexity_api_key": "key", "perplexity_search_url": "https://api.perplexity.ai/search",
        "perplexity_request_timeout_seconds": 10,
    })())
    monkeypatch.setattr("app.services.discovery.search.httpx.post",
        lambda *args, **kwargs: (captured.update(kwargs.get("json") or {}) or Response()))
    result = run_search(["recent event"])
    assert result.results[0]["url"] == "https://example.com/event"
    assert "model" not in captured and "tools" not in captured
    assert result.cost_usd == pytest.approx(.005)


def test_fixed_opportunity_schema_adapts_to_local_verification_pipeline():
    batch = OpportunityBatch.model_validate(_opportunity_batch())
    parsed = _as_legacy_result(batch)
    candidate = parsed.candidate_groups[0].candidates[0]
    assert candidate.ticker == "SPGI"
    assert candidate.confidence == pytest.approx(.78)
    assert candidate.financial_snapshot.price is None
    assert "管理层指引" in candidate.why_now


def test_portfolio_context_is_compact_and_excludes_identifiers(db, owner):
    user, portfolio = owner
    context, digest = build_portfolio_context(db, portfolio, user.id)
    assert context["holdings"] == []
    assert context["investment_preferences"]["strategy_type"] == "quality_growth"
    assert "user_id" not in str(context) and "account" not in str(context)
    __import__("json").dumps(context)
    assert len(digest) == 64


def test_local_news_title_and_summary_are_in_analysis_context(db, owner):
    user, portfolio = owner
    db.add(WatchlistItem(ticker="SPGI", enabled=True))
    db.add(NewsItem(
        ticker="SPGI", provider="finnhub", fingerprint="news-summary",
        scope="company", title="Original title", translated_title="中文标题",
        url="https://example.com/news", summary="供应商概要", ai_summary="AI 新闻概要",
        ai_summary_status="completed", published_at=datetime.now(UTC),
    ))
    db.commit()
    context, _ = build_portfolio_context(db, portfolio, user.id)
    from app.services.discovery.context import build_local_research_context
    enriched = build_local_research_context(db, context)
    news = enriched["local_news_summaries"][0]
    assert news["title"] == "中文标题"
    assert news["summary"] == "AI 新闻概要"


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


def test_opportunity_history_is_persistent_and_user_scoped(db, owner):
    user, portfolio = owner
    run = StockDiscoveryRun(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key="history-run",
        status="completed", stage="completed", requested_at=datetime.now(UTC),
        completed_at=datetime.now(UTC), analysis_date=date.today(),
        model_requested="gpt-5.6-sol", model_used="gpt-5.6-sol",
        portfolio_snapshot_hash="h" * 64,
    )
    db.add(run); db.flush()
    row = OpportunityHistory(
        user_id=user.id, run_id=run.id,
        query_context={"queries": ["recent events"]},
        market_condition="市场分化",
        result_json=_opportunity_batch(),
        model_version="gpt-5.6-sol",
        search_source="perplexity_search",
    )
    db.add(row); db.commit()
    history = opportunity_history_list(db, user.id)
    assert history[0]["tickers"] == ["SPGI"]
    assert history[0]["max_confidence"] == 78
    assert opportunity_history_detail(db, user.id, row.id)["opportunities"][0]["category"] == ["盈利改善", "长期成长"]
    assert opportunity_history_detail(db, user.id + 999, row.id) is None


def test_finance_agent_mode_executes_original_pipeline_and_writes_history(db, owner, monkeypatch):
    user, portfolio = owner
    settings = StockDiscoverySettings(
        user_id=user.id, discovery_mode="agent_finance", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    run = StockDiscoveryRun(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key="agent-run",
        trigger="manual", discovery_mode="agent_finance", status="pending",
        stage="preparing_portfolio", requested_at=datetime.now(UTC),
        model_requested="openai/gpt-5.4", portfolio_snapshot_hash="z" * 64,
    )
    db.add_all([settings, run]); db.flush()
    db.add(StockDiscoveryPortfolioSnapshot(
        run_id=run.id, context_hash="z" * 64, payload={"holdings": [], "current_watchlist": []},
    ))
    db.commit()
    parsed = DiscoveryResult.model_validate(_structured_result())
    result = AgentResult(
        parsed=parsed, raw_response={"status": "completed"}, output_text="{}",
        tool_results=[], model="openai/gpt-5.4", usage={},
        finance_search_calls=2, web_search_calls=1,
        input_tokens=100, output_tokens=200, total_tokens=300,
        tool_cost_usd=.015, model_cost_usd=.1, total_cost_usd=.115,
    )
    monkeypatch.setattr("app.services.discovery.service.build_local_research_context", lambda _db, context: context)
    monkeypatch.setattr("app.services.discovery.service.run_agent", lambda request: result)
    monkeypatch.setattr("app.services.discovery.service._persist_candidates", lambda *_: [])
    completed = execute_discovery_run(db, run.id)
    assert completed.status == "completed"
    assert completed.model_used == "openai/gpt-5.4"
    history = opportunity_history_list(db, user.id)[0]
    assert history["search_source"] == "perplexity_finance_agent"
    assert history["tickers"] == ["SPGI"]


def test_exa_finance_mode_executes_agent_connect_pipeline(db, owner, monkeypatch):
    user, portfolio = owner
    settings = StockDiscoverySettings(
        user_id=user.id, discovery_mode="exa_finance", model="openai/gpt-5.4",
        max_steps=5, max_output_tokens=12000, enable_web_search=True,
    )
    run = StockDiscoveryRun(
        user_id=user.id, portfolio_id=portfolio.id, idempotency_key="exa-agent-run",
        trigger="manual", discovery_mode="exa_finance", status="pending",
        stage="preparing_portfolio", requested_at=datetime.now(UTC),
        model_requested="exa-agent", portfolio_snapshot_hash="e" * 64,
    )
    db.add_all([settings, run]); db.flush()
    db.add(StockDiscoveryPortfolioSnapshot(
        run_id=run.id, context_hash="e" * 64, payload={"holdings": [], "current_watchlist": []},
    ))
    db.commit()
    parsed = DiscoveryResult.model_validate(_structured_result())
    result = ExaAgentResult(
        parsed=parsed,
        raw_response={"id": "agent_run_1", "status": "completed"},
        output_text="{}",
        grounding=[{"field": "candidate_groups[0]", "citations": [
            {"title": "SEC filing", "url": "https://www.sec.gov/example"},
        ]}],
        usage={"searches": 2},
        finance_data_calls=3,
        web_search_calls=2,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        tool_cost_usd=.05,
        model_cost_usd=.50,
        total_cost_usd=.55,
    )
    monkeypatch.setattr("app.services.discovery.service.build_local_research_context", lambda _db, context: context)
    monkeypatch.setattr("app.services.discovery.service.run_exa_agent", lambda request: result)
    monkeypatch.setattr("app.services.discovery.service._persist_candidates", lambda *_, **__: [])
    completed = execute_discovery_run(db, run.id)
    assert completed.status == "completed"
    assert completed.model_used == "exa-agent"
    history = opportunity_history_list(db, user.id)[0]
    assert history["search_source"] == "exa_agent_financial_datasets"
    usage = db.scalar(select(StockDiscoveryUsage).where(StockDiscoveryUsage.run_id == run.id))
    assert usage.finance_search_calls == 3
    assert usage.web_search_calls == 2
    assert usage.total_cost_usd == pytest.approx(.55)
    source = db.scalar(select(StockDiscoverySource).where(StockDiscoverySource.run_id == run.id))
    assert source.source_origin == "exa_grounding"


def test_candidate_persistence_deduplicates_groups_and_applies_local_verification(db, owner, monkeypatch):
    user, portfolio = owner
    config = StockDiscoverySettings(user_id=user.id)
    run = StockDiscoveryRun(user_id=user.id, portfolio_id=portfolio.id, idempotency_key="candidate-run",
        status="running", stage="local_verification", requested_at=datetime.now(UTC),
        model_requested="model", portfolio_snapshot_hash="c" * 64)
    db.add_all([config, run]); db.commit(); db.refresh(run)
    payload = _structured_result()
    payload["candidate_groups"][0]["candidates"][0]["financial_snapshot"]["data_periods"] = [
        "price/marketCap as of 2026-07-24",
        "local research financial period 2026-03-31 / 2025-09-30",
    ]
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
    assert all(row.data_period is None or len(row.data_period) <= 64 for row in pe_rows)


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
