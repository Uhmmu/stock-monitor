import asyncio
import json

import httpx
import pytest
from app.ai.enums import AIErrorCode
from app.ai.exceptions import AIError, ProviderError
from app.ai.providers import openai_compatible as openai_compatible_module
from app.ai.providers.mock import MockProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.ai.providers.registry import ProviderRegistry
from app.ai.providers.schemas import ProviderMessage, ProviderRequest


def request(stream=False):
    return ProviderRequest(model="test-model", messages=[ProviderMessage(role="user", content="hello")], stream=stream)


def provider(handler, retries=0):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(api_base="https://models.test/v1", api_key="top-secret", max_retries=retries, client=client), client


def test_provider_registry_and_mock():
    registry = ProviderRegistry(); mock = MockProvider(); registry.register(mock)
    assert registry.get("mock") is mock and registry.list() == ["mock"]
    with pytest.raises(ValueError): registry.register(MockProvider())
    with pytest.raises(AIError): registry.get("missing")
    assert mock.supports_tools("x") and mock.supports_streaming("x")


def test_openai_non_stream_text_tool_usage_and_no_secret_in_error():
    bodies = [
        {"id":"r1","model":"m","choices":[{"message":{"content":"answer"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}},
        {"id":"r2","choices":[{"message":{"content":None,"tool_calls":[{"id":"c1","type":"function","function":{"name":"get_latest_price","arguments":"{\"symbol\":\"MSFT\"}"}}]},"finish_reason":"tool_calls"}]},
    ]
    def handler(req):
        assert req.headers["authorization"] == "Bearer top-secret"
        payload = json.loads(req.content); assert "messages" in payload
        return httpx.Response(200, json=bodies.pop(0))
    item, client = provider(handler)
    try:
        first = asyncio.run(item.create_response(request())); second = asyncio.run(item.create_response(request()))
        assert first.content == "answer" and first.usage.total_tokens == 5
        assert second.tool_calls[0].arguments == {"symbol":"MSFT"}
    finally: asyncio.run(client.aclose())


def test_compatible_provider_can_use_claude_max_tokens_field():
    def handler(req):
        payload = json.loads(req.content)
        assert payload["max_tokens"] == 2048
        assert "max_completion_tokens" not in payload
        return httpx.Response(200, json={"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    item = OpenAICompatibleProvider(
        api_base="https://claude.test/v1",
        api_key="secret",
        provider_name="claude_compatible",
        max_output_tokens_field="max_tokens",
        client=client,
    )
    try:
        value = request().model_copy(update={"max_output_tokens": 2048})
        assert asyncio.run(item.create_response(value)).content == "ok"
    finally:
        asyncio.run(client.aclose())


def test_openai_status_mapping_retry_and_invalid_json():
    attempts = 0
    def retry_handler(req):
        nonlocal attempts; attempts += 1
        return httpx.Response(500 if attempts == 1 else 200, json={"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]})
    item, client = provider(retry_handler, retries=1)
    try:
        assert asyncio.run(item.create_response(request())).content == "ok" and attempts == 2
    finally: asyncio.run(client.aclose())
    for status, code in [(401,AIErrorCode.provider_auth),(429,AIErrorCode.provider_rate_limited)]:
        item, client = provider(lambda req, status=status: httpx.Response(status, text="secret upstream body"))
        try:
            with pytest.raises(ProviderError) as exc: asyncio.run(item.create_response(request()))
            assert exc.value.code == code and "top-secret" not in exc.value.message and "upstream" not in exc.value.message
        finally: asyncio.run(client.aclose())


def test_openai_stream_text_tools_and_usage():
    chunks = [
        {"id":"r","choices":[{"delta":{"content":"你"}}]},
        {"id":"r","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"get_latest_price","arguments":"{\"symbol\":"}}]}}]},
        {"id":"r","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"MSFT\"}"}}]}}]},
        {"id":"r","choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}},
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    item, client = provider(lambda req: httpx.Response(200, text=body, headers={"content-type":"text/event-stream"}))
    async def collect(): return [event async for event in item.stream_response(request(True))]
    try:
        events = asyncio.run(collect())
        assert any(event.type == "text_delta" and event.text_delta == "你" for event in events)
        completed = next(event for event in events if event.type == "tool_call_completed")
        assert completed.arguments == {"symbol":"MSFT"}
        assert next(event for event in events if event.type == "usage").usage.total_tokens == 3
    finally: asyncio.run(client.aclose())


def test_openai_stream_keeps_distinct_tool_ids_when_gateway_reuses_index():
    chunks = [
        {"id":"r","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"get_latest_price","arguments":"{\"symbol\":\"MSFT\"}"}}]}}]},
        {"id":"r","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c2","function":{"name":"get_company_profile","arguments":"{\"symbol\":\"META\"}"}}]}}]},
        {"id":"r","choices":[{"delta":{},"finish_reason":"stop"}]},
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    item, client = provider(lambda req: httpx.Response(200, text=body, headers={"content-type":"text/event-stream"}))
    async def collect(): return [event async for event in item.stream_response(request(True))]
    try:
        events = asyncio.run(collect())
        completed = [event for event in events if event.type == "tool_call_completed"]
        assert [(event.tool_call_id, event.tool_name, event.arguments) for event in completed] == [
            ("c1", "get_latest_price", {"symbol":"MSFT"}),
            ("c2", "get_company_profile", {"symbol":"META"}),
        ]
    finally: asyncio.run(client.aclose())


def test_openai_stream_retries_recoverable_status_before_emitting():
    attempts = 0
    body = 'data: {"id":"r","choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    def handler(req):
        nonlocal attempts
        attempts += 1
        return httpx.Response(500) if attempts == 1 else httpx.Response(200, text=body, headers={"content-type":"text/event-stream"})
    item, client = provider(handler, retries=1)
    async def collect(): return [event async for event in item.stream_response(request(True))]
    try:
        events=asyncio.run(collect())
        assert attempts==2 and [event.type for event in events].count("response_started")==1
        assert next(event for event in events if event.type=="text_delta").text_delta=="ok"
    finally: asyncio.run(client.aclose())


def test_openai_stream_fails_fast_on_slow_upstream_errors(monkeypatch):
    # A gateway 5xx that only arrives after long processing must not be
    # retried on the same model; the orchestrator's model fallback owns
    # recovery. Simulate a slow failure by disabling the fast-retry window.
    monkeypatch.setattr(openai_compatible_module, "STREAM_FAST_RETRY_SECONDS", -1.0)
    attempts = 0
    def handler(req):
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)
    item, client = provider(handler, retries=2)
    async def collect():
        with pytest.raises(ProviderError):
            async for _ in item.stream_response(request(True)):
                pass
    try:
        asyncio.run(collect())
        assert attempts == 1
    finally: asyncio.run(client.aclose())


def test_openai_stream_caps_total_attempts_even_with_fast_failures():
    # Streaming never runs more than one same-model retry regardless of the
    # configured non-streaming retry budget.
    attempts = 0
    def handler(req):
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)
    item, client = provider(handler, retries=3)
    async def collect():
        with pytest.raises(ProviderError):
            async for _ in item.stream_response(request(True)):
                pass
    try:
        asyncio.run(collect())
        assert attempts == 2
    finally: asyncio.run(client.aclose())
