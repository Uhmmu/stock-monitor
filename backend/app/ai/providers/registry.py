from __future__ import annotations

from app.ai.enums import AIErrorCode
from app.ai.exceptions import AIError

from .base import BaseModelProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseModelProvider] = {}

    def register(self, provider: BaseModelProvider) -> None:
        if provider.provider_name in self._providers:
            raise ValueError(f"duplicate provider name: {provider.provider_name}")
        self._providers[provider.provider_name] = provider

    def get(self, name: str) -> BaseModelProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise AIError(AIErrorCode.provider_not_found, "Configured model provider was not found.") from exc

    def list(self) -> list[str]:
        return sorted(self._providers)
