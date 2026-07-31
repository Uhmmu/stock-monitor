from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..schemas import (
    AgentRun,
    AgentRunCreateRequest,
    AgentRunEvent,
    SearchProviderRequest,
    SearchProviderResponse,
)


class BaseExternalSearchProvider(ABC):
    provider_name: str

    @abstractmethod
    async def search(self, request: SearchProviderRequest) -> SearchProviderResponse: ...

    @abstractmethod
    async def create_agent_run(
        self, request: AgentRunCreateRequest, *, stream: bool
    ) -> AgentRun | AsyncIterator[AgentRunEvent]: ...

    @abstractmethod
    async def get_agent_run(self, run_id: str) -> AgentRun: ...

    @abstractmethod
    async def list_agent_run_events(
        self, run_id: str, *, after_event_id: str | None = None
    ) -> list[AgentRunEvent]: ...

    @abstractmethod
    async def cancel_agent_run(self, run_id: str) -> AgentRun: ...

    async def aclose(self) -> None:
        return None
