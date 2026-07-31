from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from ..enums import AgentRunStatus
from ..schemas import (
    AgentRun,
    AgentRunCreateRequest,
    AgentRunEvent,
    SearchProviderRequest,
    SearchProviderResponse,
)
from .base import BaseExternalSearchProvider


class MockExternalSearchProvider(BaseExternalSearchProvider):
    provider_name = "mock"

    def __init__(self):
        self.runs: dict[str, AgentRun] = {}

    async def search(self, request: SearchProviderRequest) -> SearchProviderResponse:
        return SearchProviderResponse(results=[], request_id=f"mock-{uuid4()}", search_type=request.search_type.value, cost_usd=Decimal(0))

    async def create_agent_run(self, request: AgentRunCreateRequest, *, stream: bool) -> AgentRun | AsyncIterator[AgentRunEvent]:
        run = AgentRun(id=f"mock-run-{uuid4()}", status=AgentRunStatus.queued, created_at=datetime.now(UTC), cost_usd=Decimal(0))
        self.runs[run.id] = run
        if not stream:
            return run

        async def events():
            yield AgentRunEvent(event_id="1", event_type="agent_run.created", status=run.status, run=run)
        return events()

    async def get_agent_run(self, run_id: str) -> AgentRun:
        return self.runs[run_id]

    async def list_agent_run_events(self, run_id: str, *, after_event_id: str | None = None) -> list[AgentRunEvent]:
        del after_event_id
        run = await self.get_agent_run(run_id)
        return [AgentRunEvent(event_id="1", event_type=f"agent_run.{run.status.value}", status=run.status, run=run)]

    async def cancel_agent_run(self, run_id: str) -> AgentRun:
        run = (await self.get_agent_run(run_id)).model_copy(update={"status": AgentRunStatus.cancelled})
        self.runs[run_id] = run
        return run
