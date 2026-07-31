from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.ai.schemas import Citation
from app.ai_rich_content.composer import compose_rich_content
from app.ai_rich_content.exceptions import BlockVersionError, UnknownBlockError
from app.ai_rich_content.factories import build_candidates
from app.ai_rich_content.prompting import build_candidate_prompt
from app.ai_rich_content.registry import rich_block_registry
from app.ai_rich_content.schemas import RichBlock, RichBlockCandidate
from app.ai_tools.enums import ToolStatus
from app.ai_tools.schemas import ToolExecutionResult, empty_stats


def _citation() -> Citation:
    return Citation(
        key="S1",
        source_id="price:MSFT",
        title="MSFT stored quote",
        source_type="price",
        provider="yahoo",
        url="https://example.test/msft",
    )


def _metric_candidate() -> RichBlockCandidate:
    block = RichBlock(
        block_id="block_metric_test",
        block_type="metric_grid",
        block_version=1,
        title="关键指标",
        data={
            "symbol": "MSFT",
            "columns": 2,
            "metrics": [
                {
                    "key": "revenue",
                    "label": "营收",
                    "value": "100",
                    "display_value": "100 USD",
                    "trend": "positive",
                }
            ],
        },
        citation_keys=["S1", "S999"],
        source_ids=["price:MSFT", "untrusted"],
        warnings=[],
        fallback_markdown="**关键指标**\n\n- 营收：100 USD",
    )
    return RichBlockCandidate(
        block_id=block.block_id,
        block_type=block.block_type,
        block_version=1,
        tool_name="get_financial_summary",
        tool_call_id="tool-1",
        relevance_hint="Key financial metrics",
        block=block,
    )


def test_registry_is_explicit_and_versioned():
    definitions = rich_block_registry.list_supported()
    assert len(definitions) == 12
    assert {(item.block_type, item.version) for item in definitions} == {
        ("stock_quote", 1),
        ("metric_grid", 1),
        ("mini_line_chart", 1),
        ("valuation_range", 1),
        ("comparison_table", 1),
        ("portfolio_allocation", 1),
        ("risk_panel", 1),
        ("catalyst_timeline", 1),
        ("news_cluster", 1),
        ("sec_filing", 1),
        ("investment_decision", 1),
        ("source_list", 1),
    }
    with pytest.raises(UnknownBlockError):
        rich_block_registry.get_schema("invented", 1)
    with pytest.raises(BlockVersionError):
        rich_block_registry.get_schema("stock_quote", 999)


def test_composer_validates_placeholders_citations_and_fallback(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_rich_content_auto_insert_enabled", False)
    candidate = _metric_candidate()
    answer = (
        "先看结论。[S1]\n\n"
        "[[BLOCK:block_metric_test]]\n\n"
        "`[[BLOCK:block_metric_test]]` 保持为代码。\n\n"
        "[[BLOCK:block_metric_test]]\n"
        "[[BLOCK:missing_block]]"
    )
    result = compose_rich_content(
        answer_markdown=answer,
        candidates=[candidate],
        citations=[_citation()],
        user_message="分析营收",
    )
    blocks = [
        part.block
        for part in result.document.parts
        if part.type == "block"
    ]
    assert [block.block_type for block in blocks] == ["metric_grid", "source_list"]
    assert blocks[0].citation_keys == ["S1"]
    assert blocks[0].source_ids == ["price:MSFT"]
    assert result.duplicate_placeholder_count == 1
    assert result.invalid_placeholder_count == 1
    assert "`[[BLOCK:block_metric_test]]`" in result.document.fallback_markdown
    assert "missing_block" not in result.document.fallback_markdown
    assert result.document.fallback_markdown.startswith("先看结论。[S1]")
    assert "**信息来源**" in result.document.fallback_markdown


def test_factory_is_deterministic_and_prompt_never_contains_payload():
    now = datetime(2026, 7, 31, 8, 30, tzinfo=UTC)
    result = ToolExecutionResult(
        tool_call_id="call-price-1",
        tool_name="get_latest_price",
        tool_version="1.0.0",
        status=ToolStatus.success,
        data={
            "symbol": "MSFT",
            "price": 512.36,
            "currency": "USD",
            "change_percent": 0.83,
            "quote_time": now.isoformat(),
        },
        sources=[],
        freshness={"as_of": now.isoformat(), "status": "fresh"},
        stats=empty_stats(),
    )
    first, warnings = build_candidates(result, [_citation()])
    second, _ = build_candidates(result, [_citation()])
    assert warnings == []
    assert len(first) == 1
    assert first[0].block_id == second[0].block_id
    assert first[0].block.model_dump(mode="json") == second[0].block.model_dump(mode="json")
    prompt = build_candidate_prompt(first)
    assert first[0].block_id in prompt
    assert "512.36" not in prompt
    assert '"price"' not in prompt


def test_all_domain_factories_produce_registry_validated_blocks():
    now = datetime(2026, 7, 31, 8, 30, tzinfo=UTC)
    samples = [
        (
            "get_latest_price",
            {
                "symbol": "MSFT",
                "price": 512.36,
                "currency": "USD",
                "quote_time": now.isoformat(),
            },
        ),
        (
            "get_financial_summary",
            {
                "symbol": "MSFT",
                "periods": [
                    {
                        "period": "2026Q2",
                        "as_of": now.isoformat(),
                        "metrics": {
                            "revenue": {"value": 100, "unit": "USD"},
                            "net_income": {"value": 25, "unit": "USD"},
                        },
                    },
                    {
                        "period": "2026Q1",
                        "as_of": "2026-03-31T00:00:00Z",
                        "metrics": {
                            "revenue": {"value": 90, "unit": "USD"},
                            "net_income": {"value": 20, "unit": "USD"},
                        },
                    },
                ],
            },
        ),
        (
            "get_latest_valuation",
            {
                "snapshot_id": 1,
                "symbol": "MSFT",
                "snapshot_date": "2026-07-31",
                "valuation": {
                    "currency": "USD",
                    "price": 512.36,
                    "dcf_scenarios": {"bear": 420, "base": 510, "bull": 600},
                },
            },
        ),
        (
            "compare_financial_metrics",
            [
                {
                    "symbol": "MSFT",
                    "series": [
                        {"metrics": {"revenue": {"value": 100, "unit": "USD"}}}
                    ],
                },
                {
                    "symbol": "GOOG",
                    "series": [
                        {"metrics": {"revenue": {"value": 110, "unit": "USD"}}}
                    ],
                },
            ],
        ),
        (
            "get_portfolio_positions",
            {
                "portfolio_id": 1,
                "base_currency": "USD",
                "positions": [
                    {
                        "symbol": "MSFT",
                        "portfolio_weight": 60,
                        "base_currency_market_value": 6000,
                    },
                    {
                        "symbol": "GOOG",
                        "portfolio_weight": 40,
                        "base_currency_market_value": 4000,
                    },
                ],
            },
        ),
        (
            "get_technical_levels",
            {
                "symbol": "MSFT",
                "support_levels": [{"price": 490}],
                "resistance_levels": [{"price": 525}],
            },
        ),
        (
            "get_calendar_events",
            {
                "events": [
                    {
                        "event_id": "event-1",
                        "symbol": "MSFT",
                        "title": "季度财报",
                        "event_type": "earnings",
                        "event_time": "2026-08-15T20:00:00Z",
                        "status": "upcoming",
                    }
                ]
            },
        ),
        (
            "get_latest_news",
            [
                {
                    "news_id": "news-1",
                    "symbol": "MSFT",
                    "title": "Microsoft update",
                    "summary": "A bounded stored-news summary.",
                    "published_at": now.isoformat(),
                }
            ],
        ),
        (
            "get_sec_filings",
            [
                {
                    "filing_id": "filing-1",
                    "symbol": "MSFT",
                    "form_type": "10-Q",
                    "filed_at": now.isoformat(),
                    "report_period": "2026-06-30",
                    "summary": "Quarterly filing.",
                    "official_url": "https://www.sec.gov/Archives/example",
                }
            ],
        ),
        (
            "get_investment_decision",
            {
                "id": 1,
                "title": "保持核心仓位",
                "symbols": ["MSFT"],
                "decision_type": "hold",
                "status": "active",
                "decision_date": "2026-07-31",
                "action": "继续观察。",
                "invalidation_conditions": ["增长明显放缓"],
                "risks": ["估值偏高"],
            },
        ),
    ]
    seen: set[str] = set()
    for index, (tool_name, data) in enumerate(samples):
        result = ToolExecutionResult(
            tool_call_id=f"call-{index}",
            tool_name=tool_name,
            tool_version="1.0.0",
            status=ToolStatus.success,
            data=data,
            sources=[],
            freshness={"as_of": now.isoformat(), "status": "fresh"},
            stats=empty_stats(),
        )
        candidates, warnings = build_candidates(result, [_citation()])
        assert warnings == [], (tool_name, warnings)
        assert candidates, tool_name
        for candidate in candidates:
            validated = rich_block_registry.validate_block(candidate.block)
            assert validated.fallback_markdown
            seen.add(candidate.block_type)
    assert seen == {
        "stock_quote",
        "metric_grid",
        "mini_line_chart",
        "valuation_range",
        "comparison_table",
        "portfolio_allocation",
        "risk_panel",
        "catalyst_timeline",
        "news_cluster",
        "sec_filing",
        "investment_decision",
    }


def test_auto_insertion_uses_central_intent_allowlist(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_rich_content_auto_insert_enabled", True)
    monkeypatch.setattr(settings, "ai_rich_content_auto_insert_max_blocks", 1)
    now = datetime(2026, 7, 31, 8, 30, tzinfo=UTC)
    tool_result = ToolExecutionResult(
        tool_call_id="call-auto",
        tool_name="get_latest_price",
        tool_version="1.0.0",
        status=ToolStatus.success,
        data={
            "symbol": "MSFT",
            "price": 512.36,
            "currency": "USD",
            "quote_time": now.isoformat(),
        },
        sources=[],
        stats=empty_stats(),
    )
    candidates, _ = build_candidates(tool_result, [_citation()])
    matching = compose_rich_content(
        answer_markdown="当前入库报价如下。[S1]",
        candidates=candidates,
        citations=[_citation()],
        user_message="MSFT 现在股价是多少？",
    )
    unrelated = compose_rich_content(
        answer_markdown="这是普通回答。",
        candidates=candidates,
        citations=[_citation()],
        user_message="解释一下什么是护城河",
    )
    assert matching.auto_inserted_count == 1
    assert any(
        part.type == "block" and part.block.block_type == "stock_quote"
        for part in matching.document.parts
    )
    assert unrelated.auto_inserted_count == 0
    assert all(
        part.type != "block" or part.block.block_type != "stock_quote"
        for part in unrelated.document.parts
    )
