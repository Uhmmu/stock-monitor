from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

import httpx

from ..domains import authority_tier
from ..exceptions import ExternalSearchError
from ..schemas import (
    AgentRun,
    AgentRunCreateRequest,
    AgentRunEvent,
    ExternalGroundingSource,
    ExternalSearchResult,
    SearchProviderRequest,
    SearchProviderResponse,
)
from ..security import normalize_public_url
from .base import BaseExternalSearchProvider


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


class ExaExternalSearchProvider(BaseExternalSearchProvider):
    provider_name = "exa"

    def __init__(
        self, *, api_base: str, api_key: str, search_timeout: float = 30,
        agent_timeout: float = 900, max_retries: int = 2, search_qps: float = 5,
        agent_concurrency: int = 2, client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.max_retries = min(max(max_retries, 0), 2)
        self.search_timeout = httpx.Timeout(search_timeout, connect=min(search_timeout, 15))
        self.agent_timeout = httpx.Timeout(agent_timeout, connect=min(agent_timeout, 15))
        self.agent_request_timeout = httpx.Timeout(min(max(agent_timeout, 10), 45), connect=min(agent_timeout, 15))
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=self.api_base,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._search_interval = 1 / max(0.1, min(search_qps, 10))
        self._search_lock = asyncio.Lock()
        self._last_search = 0.0
        self._agent_semaphore = asyncio.Semaphore(max(1, min(agent_concurrency, 10)))

    async def _rate_limit_search(self) -> None:
        async with self._search_lock:
            wait = self._search_interval - (monotonic() - self._last_search)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_search = monotonic()

    @staticmethod
    async def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ExternalSearchError("WEB_SEARCH_BAD_RESPONSE", "External search returned an invalid response.") from exc
        if not isinstance(value, dict):
            raise ExternalSearchError("WEB_SEARCH_BAD_RESPONSE", "External search returned an invalid response.")
        return value

    @staticmethod
    def _http_error(response: httpx.Response, *, deep: bool = False) -> ExternalSearchError:
        prefix = "DEEP_SEARCH" if deep else "WEB_SEARCH"
        mapping = {
            400: (f"{prefix}_INVALID_REQUEST", 422, False),
            401: ("WEB_SEARCH_AUTH_FAILED", 503, False),
            402: ("WEB_SEARCH_PAYMENT_REQUIRED", 402, False),
            403: ("WEB_SEARCH_FORBIDDEN", 403, False),
            404: ("DEEP_SEARCH_RUN_NOT_FOUND" if deep else "WEB_SEARCH_BAD_RESPONSE", 404 if deep else 502, False),
            422: (f"{prefix}_INVALID_REQUEST", 422, False),
            429: ("WEB_SEARCH_RATE_LIMITED" if not deep else "DEEP_SEARCH_CONCURRENCY_LIMIT", 429, True),
        }
        code, status, retryable = mapping.get(response.status_code, (f"{prefix}_PROVIDER_UNAVAILABLE", 503, response.status_code >= 500))
        return ExternalSearchError(code, "External search provider rejected the request." if response.status_code < 500 else "External search provider is unavailable.", status_code=status, retryable=retryable)

    async def _json_request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None,
        deep: bool = False, retry: bool = True,
    ) -> dict[str, Any]:
        attempts = self.max_retries + 1 if retry else 1
        timeout = self.agent_request_timeout if deep else self.search_timeout
        for attempt in range(attempts):
            try:
                response = await self.client.request(method, path, json=payload, timeout=timeout)
            except httpx.TimeoutException as exc:
                if attempt + 1 >= attempts:
                    raise ExternalSearchError("DEEP_SEARCH_SYNC_FAILED" if deep else "WEB_SEARCH_TIMEOUT", "External search timed out.", status_code=504, retryable=True) from exc
            except httpx.HTTPError as exc:
                if attempt + 1 >= attempts:
                    raise ExternalSearchError("DEEP_SEARCH_SYNC_FAILED" if deep else "WEB_SEARCH_PROVIDER_UNAVAILABLE", "External search provider is unavailable.", status_code=503, retryable=True) from exc
            else:
                if response.is_success:
                    return await self._safe_json(response)
                error = self._http_error(response, deep=deep)
                if not error.retryable or attempt + 1 >= attempts:
                    raise error
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 5.0) if retry_after else min(0.5 * (2 ** attempt) + random.random() * 0.2, 5.0)
                except ValueError:
                    delay = min(0.5 * (2 ** attempt) + random.random() * 0.2, 5.0)
                await asyncio.sleep(delay)
        raise ExternalSearchError("WEB_SEARCH_PROVIDER_UNAVAILABLE", "External search provider is unavailable.")

    @staticmethod
    def search_payload(request: SearchProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": request.query,
            "type": request.search_type.value,
            "numResults": request.num_results,
            "moderation": request.moderation,
        }
        for key, value in (
            ("category", request.category),
            ("includeDomains", request.include_domains or None),
            ("excludeDomains", request.exclude_domains or None),
            ("startPublishedDate", request.start_published_date.isoformat() if request.start_published_date else None),
            ("endPublishedDate", request.end_published_date.isoformat() if request.end_published_date else None),
        ):
            if value is not None:
                payload[key] = value
        contents: dict[str, Any] = {}
        if request.content_mode == "text":
            contents["text"] = {"maxCharacters": min(request.max_content_characters or 8000, 15000)}
        else:
            contents["highlights"] = True if request.max_content_characters is None else {"maxCharacters": request.max_content_characters}
        if request.max_age_hours is not None:
            contents["maxAgeHours"] = request.max_age_hours
        if request.livecrawl_timeout_ms is not None:
            contents["livecrawlTimeout"] = request.livecrawl_timeout_ms
        payload["contents"] = contents
        return payload

    async def search(self, request: SearchProviderRequest) -> SearchProviderResponse:
        if not self.api_key:
            raise ExternalSearchError("WEB_SEARCH_PROVIDER_NOT_CONFIGURED", "External search is not configured.", status_code=503)
        await self._rate_limit_search()
        payload = await self._json_request("POST", "/search", payload=self.search_payload(request), retry=True)
        request_id = payload.get("requestId") if isinstance(payload.get("requestId"), str) else None
        now = datetime.now(UTC)
        results = []
        for raw in payload.get("results") or []:
            if not isinstance(raw, dict):
                continue
            try:
                normalized = normalize_public_url(str(raw.get("url") or raw.get("id") or ""))
            except ExternalSearchError:
                continue
            highlights = raw.get("highlights") or []
            if isinstance(highlights, str):
                highlights = [highlights]
            results.append(ExternalSearchResult(
                result_id=str(raw.get("id") or normalized)[:512],
                title=str(raw.get("title") or normalized)[:500],
                url=normalized,
                normalized_url=normalized,
                domain=httpx.URL(normalized).host or "",
                published_at=_dt(raw.get("publishedDate")),
                author=(str(raw["author"])[:300] if raw.get("author") else None),
                highlights=[str(item)[:6000] for item in highlights if isinstance(item, str)][:20],
                text=(str(raw["text"])[:15000] if raw.get("text") else None),
                provider_request_id=request_id,
                retrieved_at=now,
                authority_tier=authority_tier(normalized),
                freshness_mode=request.freshness.value,
            ))
        cost = payload.get("costDollars")
        if isinstance(cost, dict):
            cost = cost.get("total")
        return SearchProviderResponse(
            results=results,
            request_id=request_id,
            search_type=str(payload.get("resolvedSearchType") or payload.get("searchType") or request.search_type.value),
            cost_usd=_decimal(cost),
            cost_estimated=cost is None,
            usage=dict(payload.get("usage") or {}),
        )

    @staticmethod
    def agent_payload(request: AgentRunCreateRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": request.query, "effort": request.effort.value}
        if request.output_schema is not None:
            payload["outputSchema"] = request.output_schema
        if request.system_prompt:
            payload["systemPrompt"] = request.system_prompt
        if request.metadata:
            payload["metadata"] = request.metadata
        return payload

    @staticmethod
    def _grounding(raw: Any) -> list[ExternalGroundingSource]:
        now = datetime.now(UTC)
        values: list[ExternalGroundingSource] = []
        seen = set()
        for group in raw if isinstance(raw, list) else []:
            if not isinstance(group, dict):
                continue
            citations = group.get("citations") if isinstance(group.get("citations"), list) else [group]
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                try:
                    url = normalize_public_url(str(citation.get("url") or ""))
                except ExternalSearchError:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                values.append(ExternalGroundingSource(
                    source_id="web:" + __import__("hashlib").sha256(url.encode()).hexdigest(),
                    title=str(citation.get("title") or url)[:500],
                    url=url,
                    normalized_url=url,
                    domain=httpx.URL(url).host or "",
                    field=(str(group.get("field"))[:500] if group.get("field") else None),
                    published_at=_dt(citation.get("publishedDate")),
                    retrieved_at=now,
                    authority_tier=authority_tier(url),
                ))
        return values

    @classmethod
    def parse_agent_run(cls, raw: dict[str, Any]) -> AgentRun:
        output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
        error = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        cost = raw.get("costDollars")
        if isinstance(cost, dict):
            cost = cost.get("total")
        structured = output.get("structured")
        if structured is not None and not isinstance(structured, (dict, list)):
            structured = {"value": structured}
        return AgentRun(
            id=str(raw.get("id") or ""),
            status=str(raw.get("status") or "failed"),
            stop_reason=(str(raw["stopReason"]) if raw.get("stopReason") else None),
            output_text=(str(output["text"])[:100000] if output.get("text") else None),
            output_structured=structured,
            grounding=cls._grounding(output.get("grounding")),
            usage=dict(raw.get("usage") or {}),
            cost_usd=_decimal(cost),
            created_at=_dt(raw.get("createdAt")),
            completed_at=_dt(raw.get("completedAt")),
            error_code=(str(error.get("code"))[:64] if error.get("code") else None),
            error_message_safe=("External research failed." if error else None),
        )

    @classmethod
    def parse_event(cls, event_id: str | None, event_type: str, data: dict[str, Any]) -> AgentRunEvent:
        run = cls.parse_agent_run(data) if event_type == "agent_run.completed" else None
        status = data.get("status")
        return AgentRunEvent(
            event_id=event_id,
            event_type=event_type[:64],
            status=status if status in {"queued", "running", "completed", "failed", "cancelled"} else None,
            run=run,
            source_count=1 if event_type == "agent_run.source.added" else None,
            created_at=_dt(data.get("createdAt")),
        )

    @classmethod
    async def _parse_sse(cls, response: httpx.Response) -> AsyncIterator[AgentRunEvent]:
        event_id = None
        event_type = "message"
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if not line:
                if data_lines:
                    try:
                        data = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        data = None
                    if isinstance(data, dict):
                        yield cls.parse_event(event_id, event_type, data)
                event_id, event_type, data_lines = None, "message", []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.lstrip()
            if field == "id": event_id = value
            elif field == "event": event_type = value
            elif field == "data": data_lines.append(value)

    async def create_agent_run(self, request: AgentRunCreateRequest, *, stream: bool) -> AgentRun | AsyncIterator[AgentRunEvent]:
        if not self.api_key:
            raise ExternalSearchError("WEB_SEARCH_PROVIDER_NOT_CONFIGURED", "External search is not configured.", status_code=503)
        payload = self.agent_payload(request)
        if not stream:
            # Creating a paid run is deliberately not retried automatically.
            async with self._agent_semaphore:
                raw = await self._json_request("POST", "/agent/runs", payload=payload, deep=True, retry=False)
            return self.parse_agent_run(raw)

        async def events():
            async with self._agent_semaphore:
                try:
                    async with self.client.stream("POST", "/agent/runs", json=payload, headers={"Accept": "text/event-stream"}, timeout=self.agent_timeout) as response:
                        if not response.is_success:
                            raise self._http_error(response, deep=True)
                        async for event in self._parse_sse(response):
                            yield event
                except httpx.TimeoutException as exc:
                    raise ExternalSearchError("DEEP_SEARCH_CREATE_FAILED", "Deep research creation timed out.", status_code=504, retryable=True) from exc
        return events()

    async def get_agent_run(self, run_id: str) -> AgentRun:
        async with self._agent_semaphore:
            raw = await self._json_request("GET", f"/agent/runs/{run_id}", deep=True, retry=True)
        return self.parse_agent_run(raw)

    async def list_agent_run_events(self, run_id: str, *, after_event_id: str | None = None) -> list[AgentRunEvent]:
        headers = {"Accept": "text/event-stream"}
        if after_event_id:
            headers["Last-Event-ID"] = after_event_id
        async with self._agent_semaphore, self.client.stream(
            "GET", f"/agent/runs/{run_id}/events", headers=headers, timeout=self.agent_timeout
        ) as response:
            if not response.is_success:
                raise self._http_error(response, deep=True)
            return [event async for event in self._parse_sse(response)]

    async def cancel_agent_run(self, run_id: str) -> AgentRun:
        async with self._agent_semaphore:
            raw = await self._json_request("POST", f"/agent/runs/{run_id}/cancel", deep=True, retry=False)
        return self.parse_agent_run(raw)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()
