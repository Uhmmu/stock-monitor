from __future__ import annotations

from collections.abc import AsyncIterator

from .base import BaseModelProvider
from .schemas import ProviderRequest, ProviderResponse, ProviderStreamEvent


class MockProvider(BaseModelProvider):
    provider_name = "mock"

    def __init__(self, responses: list[ProviderResponse] | None = None):
        self.responses = list(responses or [])
        self.requests: list[ProviderRequest] = []

    async def create_response(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request.model_copy(deep=True))
        return self.responses.pop(0) if self.responses else ProviderResponse(content="Mock response", finish_reason="stop")

    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        response = await self.create_response(request)
        yield ProviderStreamEvent(type="response_started", response_id=response.response_id)
        if response.content:
            yield ProviderStreamEvent(type="text_delta", text_delta=response.content)
        for call in response.tool_calls:
            yield ProviderStreamEvent(type="tool_call_completed", tool_call_id=call.id, tool_name=call.name, arguments=call.arguments)
        if response.usage:
            yield ProviderStreamEvent(type="usage", usage=response.usage)
        yield ProviderStreamEvent(type="response_completed", response_id=response.response_id)

    def supports_tools(self, model: str) -> bool:
        return True

    def supports_streaming(self, model: str) -> bool:
        return True
