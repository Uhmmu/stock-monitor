from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from .schemas import ProviderRequest, ProviderResponse, ProviderStreamEvent


class BaseModelProvider(ABC):
    provider_name: str

    @abstractmethod
    async def create_response(self, request: ProviderRequest) -> ProviderResponse: ...

    @abstractmethod
    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]: ...

    @abstractmethod
    def supports_tools(self, model: str) -> bool: ...

    @abstractmethod
    def supports_streaming(self, model: str) -> bool: ...
