from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings

from .enums import AIErrorCode
from .exceptions import AIError
from .providers.openai_compatible import OpenAICompatibleProvider
from .providers.registry import ProviderRegistry

CLAUDE_PROVIDER = "claude_compatible"
ADDITIONAL_CLAUDE_MODELS = (
    "claude-opus-5",
    "claude-sonnet-4-6",
)
ADDITIONAL_GPT_MODELS = (
    "gpt-5.6-terra",
)


def model_family(model: str) -> str:
    value = model.strip().lower()
    if value.startswith("claude-"):
        return "claude"
    if value.startswith("gpt-"):
        return "gpt"
    return "other"


def project_models(settings: Settings | None = None) -> list[str]:
    """Assistant-compatible models backed by the project's chat endpoints.

    Perplexity ``openai/gpt-*`` models are intentionally excluded: they belong
    to the discovery Agent API and do not implement this orchestrator's
    OpenAI-compatible tool-calling contract.
    """
    settings = settings or get_settings()
    values = [
        settings.translation_model,
        *ADDITIONAL_CLAUDE_MODELS,
        settings.model_simple,
        settings.model_medium,
        settings.model_important,
        *ADDITIONAL_GPT_MODELS,
        settings.ai_model,
    ]
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def allowed_models(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    values = [value.strip() for value in settings.ai_allowed_models.split(",") if value.strip()]
    configured = project_models(settings)
    if not values:
        return configured
    allowed = set(values)
    # Keep project order so Claude/GPT grouping stays deterministic in clients.
    return [model for model in configured if model in allowed] + [model for model in values if model not in configured]


def provider_name_for_model(model: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return CLAUDE_PROVIDER if model_family(model) == "claude" else settings.ai_provider


def effective_api_base(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return settings.ai_api_base.strip() or settings.openai_base_url.strip()


def effective_api_key(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return settings.ai_api_key.strip() or settings.openai_api_key.strip()


def endpoint_for_model(model: str, settings: Settings | None = None) -> tuple[str, str]:
    settings = settings or get_settings()
    if model_family(model) == "claude":
        return settings.translation_base_url.strip(), settings.translation_api_key.strip()
    return effective_api_base(settings), effective_api_key(settings)


def model_catalog(settings: Settings | None = None) -> list[dict[str, str | bool]]:
    settings = settings or get_settings()
    return [
        {
            "id": model,
            "label": model,
            "family": model_family(model),
            "is_default": model == settings.ai_model,
            "available": all(endpoint_for_model(model, settings)),
        }
        for model in allowed_models(settings)
    ]


def validate_configuration(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.ai_enabled:
        raise AIError(AIErrorCode.disabled, "AI responses are disabled.", status_code=503)
    if settings.ai_model not in allowed_models(settings):
        raise AIError(AIErrorCode.model_not_allowed, "Configured model is not allowed.", status_code=503)
    if not all(endpoint_for_model(settings.ai_model, settings)):
        raise AIError(AIErrorCode.configuration, "AI model credentials are not configured.", status_code=503)


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    settings = get_settings()
    registry = ProviderRegistry()
    registry.register(OpenAICompatibleProvider(
        api_base=effective_api_base(settings), api_key=effective_api_key(settings),
        provider_name=settings.ai_provider,
        request_timeout=min(max(settings.ai_request_timeout_seconds, 1), 120),
        connect_timeout=min(max(settings.ai_connect_timeout_seconds, 1), 30),
        max_retries=min(max(settings.ai_max_retries, 0), 3),
    ))
    claude_base, claude_key = endpoint_for_model(settings.translation_model, settings)
    if claude_base and claude_key and settings.ai_provider != CLAUDE_PROVIDER:
        registry.register(OpenAICompatibleProvider(
            api_base=claude_base,
            api_key=claude_key,
            provider_name=CLAUDE_PROVIDER,
            max_output_tokens_field="max_tokens",
            request_timeout=min(max(settings.ai_request_timeout_seconds, 1), 120),
            connect_timeout=min(max(settings.ai_connect_timeout_seconds, 1), 30),
            max_retries=min(max(settings.ai_max_retries, 0), 3),
        ))
    return registry


async def close_provider_registry() -> None:
    registry = get_provider_registry()
    for name in registry.list():
        provider = registry.get(name)
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()
    get_provider_registry.cache_clear()
