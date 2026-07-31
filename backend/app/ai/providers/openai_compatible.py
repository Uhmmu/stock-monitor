from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.enums import AIErrorCode
from app.ai.exceptions import ProviderError

from .base import BaseModelProvider
from .schemas import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderToolCall,
    ProviderUsage,
)


def _finish_reason(value: Any) -> str:
    return value if value in {"stop", "tool_calls", "length", "content_filter", "error"} else "unknown"


def _usage(value: dict[str, Any] | None) -> ProviderUsage | None:
    if not value:
        return None
    return ProviderUsage(
        input_tokens=value.get("prompt_tokens") or value.get("input_tokens"),
        output_tokens=value.get("completion_tokens") or value.get("output_tokens"),
        total_tokens=value.get("total_tokens"),
    )


class OpenAICompatibleProvider(BaseModelProvider):
    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        provider_name: str = "openai_compatible",
        max_output_tokens_field: str = "max_completion_tokens",
        request_timeout: float = 90,
        connect_timeout: float = 15,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.max_output_tokens_field = max_output_tokens_field
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.max_retries = max(0, min(max_retries, 3))
        timeout = httpx.Timeout(min(max(request_timeout, 1), 120), connect=min(max(connect_timeout, 1), 30))
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _message(message: ProviderMessage) -> dict[str, Any]:
        value: dict[str, Any] = {"role": message.role}
        if message.content is not None:
            value["content"] = message.content
        if message.name is not None:
            value["name"] = message.name
        if message.tool_call_id is not None:
            value["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            value["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":"))},
                }
                for call in message.tool_calls
            ]
        return value

    def _payload(self, request: ProviderRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [self._message(message) for message in request.messages],
            "stream": stream,
        }
        if request.tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}
                for tool in request.tools
            ]
            if request.tool_choice is not None:
                payload["tool_choice"] = request.tool_choice
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload[self.max_output_tokens_field] = request.max_output_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _error_for_status(status: int) -> ProviderError:
        if status in {401, 403}:
            return ProviderError(AIErrorCode.provider_auth, "Model provider authentication is not configured correctly.", status_code=503)
        if status == 429:
            return ProviderError(AIErrorCode.provider_rate_limited, "Model provider rate limit was reached.", retryable=True, status_code=503)
        if status >= 500:
            return ProviderError(AIErrorCode.provider_unavailable, "Model provider is temporarily unavailable.", retryable=True, status_code=503)
        return ProviderError(AIErrorCode.provider_bad_response, "Model provider rejected the request.", status_code=502)

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(f"{self.api_base}/chat/completions", headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 1))
                    continue
                raise ProviderError(AIErrorCode.provider_timeout, "Model provider timed out.", retryable=True, status_code=504) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 1))
                    continue
                raise ProviderError(AIErrorCode.provider_unavailable, "Model provider is unavailable.", retryable=True, status_code=503) from exc
            if response.status_code < 400:
                return response
            error = self._error_for_status(response.status_code)
            if error.retryable and attempt < self.max_retries:
                await asyncio.sleep(min(0.25 * (2**attempt), 1))
                continue
            raise error
        raise ProviderError(AIErrorCode.provider_unavailable, "Model provider is unavailable.", retryable=True, status_code=503)

    @staticmethod
    def _tool_calls(rows: list[dict[str, Any]]) -> list[ProviderToolCall]:
        calls = []
        for index, row in enumerate(rows):
            function = row.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            except (TypeError, json.JSONDecodeError) as exc:
                raise ProviderError(AIErrorCode.provider_bad_response, "Model provider returned invalid tool arguments.", status_code=502) from exc
            if not isinstance(arguments, dict) or not function.get("name"):
                raise ProviderError(AIErrorCode.provider_bad_response, "Model provider returned an invalid tool call.", status_code=502)
            calls.append(ProviderToolCall(id=str(row.get("id") or f"call_{index}"), name=function["name"], arguments=arguments))
        return calls

    async def create_response(self, request: ProviderRequest) -> ProviderResponse:
        response = await self._post(self._payload(request, stream=False))
        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
            return ProviderResponse(
                response_id=body.get("id"), content=content,
                tool_calls=self._tool_calls(message.get("tool_calls") or []),
                finish_reason=_finish_reason(choice.get("finish_reason")), usage=_usage(body.get("usage")),
                raw_metadata={"model": body.get("model")},
            )
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(AIErrorCode.provider_bad_response, "Model provider returned an invalid response.", status_code=502) from exc

    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        # Using a streamed HTTP request keeps response bodies bounded and makes
        # cancellation close the upstream connection promptly.
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = self._payload(request, stream=True)
        for attempt in range(self.max_retries + 1):
            # OpenAI identifies a streamed tool call by both its position and
            # its stable id. Some compatible gateways incorrectly reuse index
            # 0 for every parallel call, while still returning distinct ids.
            # Keep the most recent part for each index so standard continuation
            # chunks (which commonly omit the id) still work, but never merge
            # two calls that have different explicit ids.
            tool_parts: list[dict[str, str]] = []
            tool_part_by_id: dict[str, int] = {}
            current_tool_part_by_index: dict[int, int] = {}
            response_id = None
            emitted = False
            try:
                async with self._client.stream("POST", f"{self.api_base}/chat/completions", headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        raise self._error_for_status(response.status_code)
                    emitted = True
                    yield ProviderStreamEvent(type="response_started")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(AIErrorCode.stream_interrupted, "Model stream returned invalid data.", retryable=True, status_code=502) from exc
                        response_id = chunk.get("id") or response_id
                        if usage := _usage(chunk.get("usage")):
                            yield ProviderStreamEvent(type="usage", response_id=response_id, usage=usage)
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            if text := delta.get("content"):
                                yield ProviderStreamEvent(type="text_delta", response_id=response_id, text_delta=text)
                            for row in delta.get("tool_calls") or []:
                                try:
                                    index = int(row.get("index", 0))
                                except (TypeError, ValueError):
                                    index = 0
                                function = row.get("function") or {}
                                explicit_id = str(row.get("id") or "")
                                part_position = tool_part_by_id.get(explicit_id) if explicit_id else current_tool_part_by_index.get(index)
                                if part_position is None:
                                    part_position = len(tool_parts)
                                    part_id = explicit_id or f"call_{index}_{part_position}"
                                    tool_parts.append({"id": part_id, "name": "", "arguments": ""})
                                    if explicit_id:
                                        tool_part_by_id[explicit_id] = part_position
                                current_tool_part_by_index[index] = part_position
                                part = tool_parts[part_position]
                                name_delta = function.get("name") or ""
                                if name_delta and name_delta != part["name"]:
                                    part["name"] += name_delta
                                raw_argument_delta = function.get("arguments")
                                if raw_argument_delta is None:
                                    argument_delta = ""
                                elif isinstance(raw_argument_delta, str):
                                    argument_delta = raw_argument_delta
                                elif isinstance(raw_argument_delta, dict):
                                    argument_delta = json.dumps(raw_argument_delta, ensure_ascii=False, separators=(",", ":"))
                                else:
                                    raise ProviderError(AIErrorCode.provider_bad_response, "Model provider returned invalid tool arguments.", status_code=502)
                                part["arguments"] += argument_delta
                                if argument_delta:
                                    yield ProviderStreamEvent(type="tool_call_arguments_delta", response_id=response_id, tool_call_id=part["id"], tool_name=part["name"] or None, arguments_delta=argument_delta)
                    for part in tool_parts:
                        try:
                            arguments = json.loads(part["arguments"] or "{}")
                        except json.JSONDecodeError as exc:
                            raise ProviderError(AIErrorCode.provider_bad_response, "Model provider returned invalid tool arguments.", status_code=502) from exc
                        if not isinstance(arguments, dict) or not part["name"]:
                            raise ProviderError(AIErrorCode.provider_bad_response, "Model provider returned an invalid tool call.", status_code=502)
                        yield ProviderStreamEvent(type="tool_call_completed", response_id=response_id, tool_call_id=part["id"], tool_name=part["name"], arguments=arguments)
                    yield ProviderStreamEvent(type="response_completed", response_id=response_id)
                    return
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                if exc.retryable and not emitted and attempt < self.max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 1))
                    continue
                if emitted:
                    yield ProviderStreamEvent(type="error", response_id=response_id, error_code=exc.code.value, error_message=exc.message)
                    return
                raise
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if not emitted and attempt < self.max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 1))
                    continue
                code = AIErrorCode.provider_timeout if isinstance(exc, httpx.TimeoutException) else AIErrorCode.stream_interrupted
                message = "Model provider timed out." if code == AIErrorCode.provider_timeout else "Model stream was interrupted."
                if emitted:
                    yield ProviderStreamEvent(type="error", response_id=response_id, error_code=code.value, error_message=message)
                    return
                raise ProviderError(code, message, retryable=True, status_code=504 if code == AIErrorCode.provider_timeout else 502) from exc

    def supports_tools(self, model: str) -> bool:
        return bool(model)

    def supports_streaming(self, model: str) -> bool:
        return bool(model)
