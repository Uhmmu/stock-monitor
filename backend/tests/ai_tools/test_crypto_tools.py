from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.ai.tool_selector import ToolSelector
from app.ai_tools import tool_registry
from app.ai_tools.catalog import (
    CryptoNewsArguments,
    CryptoReportsArguments,
    CryptoResearchContextArguments,
    dispatch,
)
from app.research.enums import FreshnessStatus
from app.research.schemas import ResearchFreshness, ResearchMeta, ResearchResponse


def response(data):
    now = datetime.now(UTC)
    return ResearchResponse(
        data=data,
        freshness=ResearchFreshness(as_of=now, status=FreshnessStatus.fresh, age_seconds=0, ttl_seconds=300, reason="stored"),
        meta=ResearchMeta(request_id="crypto-test", generated_at=now),
    )


def test_crypto_registry_is_read_only_bounded_and_persisted():
    definitions = {item.name: item for item in tool_registry.list(domain="crypto", enabled_only=False)}
    assert set(definitions) == {"get_crypto_research_context", "get_crypto_news", "get_crypto_reports"}
    for definition in definitions.values():
        assert definition.read_only is True
        assert definition.input_schema["additionalProperties"] is False
        assert "stored" in definition.description
        assert "read-only" in definition.description
        assert "provider" in definition.description
        assert "orders" in definition.description


def test_crypto_arguments_reject_unbounded_or_ambiguous_requests():
    assert CryptoResearchContextArguments(instrument_id=42).instrument_id == 42
    exact = CryptoResearchContextArguments(provider="binance_usdm", provider_id="BTCUSDT")
    assert (exact.provider, exact.provider_id) == ("binance_usdm", "BTCUSDT")
    assert CryptoNewsArguments(asset_id=7, instrument_id=42, limit=20).limit == 20
    with pytest.raises(ValidationError): CryptoResearchContextArguments(instrument_id=0)
    with pytest.raises(ValidationError): CryptoResearchContextArguments(provider_id="BTCUSDT")
    with pytest.raises(ValidationError): CryptoResearchContextArguments(instrument_id=42, provider="binance_usdm", provider_id="BTCUSDT")
    with pytest.raises(ValidationError): CryptoNewsArguments(asset_id=7, limit=21)
    with pytest.raises(ValidationError): CryptoReportsArguments(limit=20)
    with pytest.raises(ValidationError): CryptoNewsArguments(asset_id=7, provider="defillama")


def test_crypto_dispatch_calls_only_persisted_gateway_methods():
    calls = []
    gateway = SimpleNamespace(
        crypto_research_context=lambda instrument_id: (calls.append(("context", instrument_id)) or response({"instrument_id": instrument_id})),
        crypto_research_context_by_provider=lambda provider, provider_id: (calls.append(("context_provider", provider, provider_id)) or response({"provider": provider, "provider_id": provider_id})),
        crypto_news=lambda asset_id, instrument_id, limit: (calls.append(("news", asset_id, instrument_id, limit)) or response({"items": []})),
        crypto_reports=lambda asset_id, instrument_id, limit: (calls.append(("reports", asset_id, instrument_id, limit)) or response({"items": []})),
    )

    context = dispatch("get_crypto_research_context", CryptoResearchContextArguments(instrument_id=42), gateway)
    exact = dispatch("get_crypto_research_context", CryptoResearchContextArguments(provider="binance_usdm", provider_id="BTCUSDT"), gateway)
    news = dispatch("get_crypto_news", CryptoNewsArguments(asset_id=7, instrument_id=42, limit=5), gateway)
    reports = dispatch("get_crypto_reports", CryptoReportsArguments(asset_id=7, limit=3), gateway)

    assert [row[0] for row in calls] == ["context", "context_provider", "news", "reports"]
    assert context.data["instrument_id"] == 42
    assert exact.data["provider_id"] == "BTCUSDT"
    assert news.data == {"items": []}
    assert reports.data == {"items": []}
    assert all("provider fetch" in result.summary for result in (context, news, reports))


def test_selector_routes_crypto_questions_without_polluting_equity_selection():
    selector = ToolSelector(tool_registry)
    crypto = selector.select(
        message="BTC funding、OI 和 basis 怎么样？最近有什么 news 和 FDV 报告？",
        page_context=None,
        active_symbol="BTC",
        allowed_tools=None,
        denied_tools=set(),
    )
    assert {"get_crypto_research_context", "get_crypto_news", "get_crypto_reports"}.issubset(crypto.tool_names)
    assert not {"submit_signal", "place_paper_order", "place_test_order", "place_live_order"}.intersection(crypto.tool_names)

    equity = selector.select(
        message="MSFT 的财务和新闻怎么样？",
        page_context=None,
        active_symbol="MSFT",
        allowed_tools=None,
        denied_tools=set(),
    )
    assert not {"get_crypto_research_context", "get_crypto_news", "get_crypto_reports"}.intersection(equity.tool_names)

    ordinary = selector.select(
        message="Whether the resolution should change the market view is unclear.",
        page_context=None,
        active_symbol=None,
        allowed_tools=None,
        denied_tools=set(),
    )
    assert not {"get_crypto_research_context", "get_crypto_news", "get_crypto_reports"}.intersection(ordinary.tool_names)
