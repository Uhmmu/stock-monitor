import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from app.external_search.enums import DeepSearchEffort, SearchFreshness, SearchType
from app.external_search.exceptions import ExternalSearchError
from app.external_search.providers.exa import ExaExternalSearchProvider
from app.external_search.schemas import AgentRunCreateRequest, SearchProviderRequest


def provider_with(handler, *, retries=0):
    client = httpx.AsyncClient(
        base_url="https://api.exa.ai",
        headers={"x-api-key": "test-only-key", "Content-Type": "application/json"},
        transport=httpx.MockTransport(handler),
    )
    return ExaExternalSearchProvider(
        api_base="https://api.exa.ai", api_key="test-only-key", client=client,
        max_retries=retries, search_qps=100,
    )


def test_search_contract_camel_case_highlights_and_response_parsing():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        assert request.url.path == "/search"
        assert request.headers["x-api-key"] == "test-only-key"
        return httpx.Response(200, json={
            "requestId": "req_123", "resolvedSearchType": "auto",
            "results": [{
                "id": "r1", "title": "Official update",
                "url": "https://www.sec.gov/news?a=1&utm_source=test#fragment",
                "publishedDate": "2026-07-30T10:00:00Z", "author": "SEC",
                "highlights": ["Material public fact"],
            }],
            "costDollars": {"total": 0.007}, "usage": {"searches": 1},
        })

    provider = provider_with(handler)
    response = asyncio.run(provider.search(SearchProviderRequest(
        query="latest filing", search_type=SearchType.auto, category="news",
        include_domains=["sec.gov"], exclude_domains=["example.com"],
        content_mode="highlights", max_age_hours=1, livecrawl_timeout_ms=10000,
        freshness=SearchFreshness.fresh,
    )))
    asyncio.run(provider.aclose())

    assert captured == {
        "query": "latest filing", "type": "auto", "numResults": 8,
        "moderation": True, "category": "news", "includeDomains": ["sec.gov"],
        "excludeDomains": ["example.com"],
        "contents": {"highlights": True, "maxAgeHours": 1, "livecrawlTimeout": 10000},
    }
    assert response.request_id == "req_123"
    assert response.cost_usd == Decimal("0.007")
    assert response.results[0].normalized_url == "https://www.sec.gov/news?a=1"
    assert response.results[0].authority_tier == "official"


def test_search_text_mode_limits_content_and_supports_all_current_types():
    for search_type in SearchType:
        payload = ExaExternalSearchProvider.search_payload(SearchProviderRequest(
            query="q", search_type=search_type, num_results=5,
            content_mode="text", max_content_characters=15000,
        ))
        assert payload["type"] == search_type.value
        assert payload["contents"] == {"text": {"maxCharacters": 15000}}
        for retired in ("neural", "useAutoprompt", "tokensNum", "livecrawl"):
            assert retired not in payload


@pytest.mark.parametrize("effort", list(DeepSearchEffort))
def test_agent_create_contract_fixes_each_supported_effort(effort):
    payload = ExaExternalSearchProvider.agent_payload(AgentRunCreateRequest(
        query="public research question", effort=effort,
        output_schema={"type": "object", "properties": {}},
        system_prompt="Prefer official sources.", metadata={"application": "stock-monitor"},
    ))
    assert payload == {
        "query": "public research question", "effort": effort.value,
        "outputSchema": {"type": "object", "properties": {}},
        "systemPrompt": "Prefer official sources.",
        "metadata": {"application": "stock-monitor"},
    }
    assert "input" not in payload


def test_agent_create_get_cancel_and_grounding_contract():
    paths = []

    def handler(request: httpx.Request):
        paths.append((request.method, request.url.path))
        status = "cancelled" if request.url.path.endswith("/cancel") else "completed" if request.method == "GET" else "running"
        return httpx.Response(200, json={
            "id": "agent_run_1", "status": status,
            "stopReason": "cancelled" if status == "cancelled" else "schema_satisfied" if status == "completed" else None,
            "createdAt": "2026-07-30T10:00:00Z",
            "completedAt": "2026-07-30T10:01:00Z" if status != "running" else None,
            "output": {
                "text": "Verified research", "structured": {"executive_summary": "ok"},
                "grounding": [{"field": "structured.executive_summary", "citations": [{"title": "SEC", "url": "https://sec.gov/a"}]}],
            },
            "usage": {"agentComputeUnits": 1, "searches": 2},
            "costDollars": {"total": 0.1},
        })

    provider = provider_with(handler)
    created = asyncio.run(provider.create_agent_run(AgentRunCreateRequest(query="q", effort=DeepSearchEffort.medium), stream=False))
    completed = asyncio.run(provider.get_agent_run(created.id))
    cancelled = asyncio.run(provider.cancel_agent_run(created.id))
    asyncio.run(provider.aclose())

    assert paths == [
        ("POST", "/agent/runs"), ("GET", "/agent/runs/agent_run_1"),
        ("POST", "/agent/runs/agent_run_1/cancel"),
    ]
    assert completed.output_text == "Verified research"
    assert completed.output_structured == {"executive_summary": "ok"}
    assert completed.grounding[0].domain == "sec.gov"
    assert completed.cost_usd == Decimal("0.1")
    assert cancelled.status.value == "cancelled"


def test_agent_event_replay_sends_last_event_id_and_parses_safe_events():
    def handler(request: httpx.Request):
        assert request.url.path == "/agent/runs/agent_run_1/events"
        assert request.headers["last-event-id"] == "evt_1"
        body = (
            "id: evt_2\nevent: agent_run.running\ndata: {\"status\":\"running\",\"createdAt\":\"2026-07-30T10:00:01Z\"}\n\n"
            "id: evt_3\nevent: agent_run.source.added\ndata: {\"status\":\"running\"}\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = provider_with(handler)
    events = asyncio.run(provider.list_agent_run_events("agent_run_1", after_event_id="evt_1"))
    asyncio.run(provider.aclose())
    assert [event.event_id for event in events] == ["evt_2", "evt_3"]
    assert events[0].status.value == "running"
    assert events[1].source_count == 1


@pytest.mark.parametrize("status,code", [
    (400, "WEB_SEARCH_INVALID_REQUEST"), (401, "WEB_SEARCH_AUTH_FAILED"),
    (402, "WEB_SEARCH_PAYMENT_REQUIRED"), (403, "WEB_SEARCH_FORBIDDEN"),
    (429, "WEB_SEARCH_RATE_LIMITED"), (500, "WEB_SEARCH_PROVIDER_UNAVAILABLE"),
])
def test_search_http_errors_are_sanitized(status, code):
    provider = provider_with(lambda request: httpx.Response(status, json={"error": {"message": "secret provider body"}}))
    with pytest.raises(ExternalSearchError) as raised:
        asyncio.run(provider.search(SearchProviderRequest(query="q")))
    asyncio.run(provider.aclose())
    assert raised.value.code == code
    assert "secret provider body" not in raised.value.message


def test_search_retries_finite_5xx_and_timeout_does_not_leak_key():
    calls = 0

    def retry_handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(500 if calls == 1 else 200, json={"results": [], "requestId": "ok"})

    provider = provider_with(retry_handler, retries=1)
    response = asyncio.run(provider.search(SearchProviderRequest(query="q")))
    asyncio.run(provider.aclose())
    assert calls == 2 and response.request_id == "ok"

    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("test-only-key", request=request)

    provider = provider_with(timeout_handler)
    with pytest.raises(ExternalSearchError) as raised:
        asyncio.run(provider.search(SearchProviderRequest(query="q")))
    asyncio.run(provider.aclose())
    assert raised.value.code == "WEB_SEARCH_TIMEOUT"
    assert "test-only-key" not in raised.value.message
