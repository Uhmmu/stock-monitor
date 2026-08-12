from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from openai import OpenAI

from app.config import get_settings


MODEL_FALLBACKS = {
    "gpt-5.6-luna": "claude-haiku-4-5-20251001",
    "gpt-5.6-sol": "claude-opus-5",
    "gpt-5.6-terra": "claude-sonnet-4-6",
}

T = TypeVar("T")
logger = logging.getLogger(__name__)


def fallback_model(model: str) -> str | None:
    return MODEL_FALLBACKS.get(model.strip().lower())


def model_candidates(model: str) -> tuple[str, ...]:
    fallback = fallback_model(model)
    return (model, fallback) if fallback else (model,)


def model_matches(requested: str, actual: str | None) -> bool:
    return actual in model_candidates(requested)


def claude_client() -> OpenAI:
    settings = get_settings()
    if not settings.translation_api_key:
        raise RuntimeError("尚未配置 TRANSLATION_API_KEY")
    return OpenAI(
        api_key=settings.translation_api_key,
        base_url=settings.translation_base_url,
        timeout=60,
        max_retries=0,
    )


def run_with_fallback(model: str, client: OpenAI, operation: Callable[[OpenAI, str], T]) -> tuple[T, str]:
    try:
        return operation(client, model), model
    except Exception as exc:
        fallback = fallback_model(model)
        if not fallback:
            raise
        logger.warning("model_fallback primary=%s fallback=%s error=%s", model, fallback, type(exc).__name__)
        return operation(claude_client(), fallback), fallback
