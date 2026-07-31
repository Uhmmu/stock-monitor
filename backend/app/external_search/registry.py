from __future__ import annotations

from functools import lru_cache

from app.config import get_settings

from .exceptions import ExternalSearchError
from .providers.base import BaseExternalSearchProvider
from .providers.exa import ExaExternalSearchProvider


class ExternalSearchProviderRegistry:
    def __init__(self):
        self._providers: dict[str, BaseExternalSearchProvider] = {}

    def register(self, provider: BaseExternalSearchProvider) -> None:
        if provider.provider_name in self._providers:
            raise ValueError(f"duplicate external search provider: {provider.provider_name}")
        self._providers[provider.provider_name] = provider

    def get(self, name: str = "exa") -> BaseExternalSearchProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ExternalSearchError("WEB_SEARCH_PROVIDER_NOT_CONFIGURED", "External search provider is not configured.", status_code=503) from exc

    def list(self) -> list[str]:
        return sorted(self._providers)


@lru_cache
def get_external_search_registry() -> ExternalSearchProviderRegistry:
    settings = get_settings()
    registry = ExternalSearchProviderRegistry()
    registry.register(ExaExternalSearchProvider(
        api_base=settings.exa_api_base,
        api_key=settings.exa_api_key,
        search_timeout=min(max(settings.exa_search_timeout_seconds, 1), 60),
        agent_timeout=min(max(settings.exa_agent_timeout_seconds, 30), 3600),
        max_retries=min(max(settings.exa_search_max_retries, 0), 2),
        search_qps=min(max(settings.exa_search_max_qps, 0.1), 10),
        agent_concurrency=min(max(settings.exa_agent_max_concurrency, 1), 10),
    ))
    return registry


async def close_external_search_registry() -> None:
    registry = get_external_search_registry()
    for name in registry.list():
        await registry.get(name).aclose()
    get_external_search_registry.cache_clear()
