from app.ai.config import (
    allowed_models,
    endpoint_for_model,
    model_catalog,
    provider_name_for_model,
)
from app.config import Settings


def test_project_model_catalog_groups_every_assistant_compatible_model():
    settings = Settings(
        _env_file=None,
        openai_api_key="gpt-key",
        translation_api_key="claude-key",
        ai_allowed_models="",
    )

    assert allowed_models(settings) == [
        "claude-haiku-4-5-20251001",
        "claude-opus-5",
        "claude-sonnet-4-6",
        "gpt-5.4-mini",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    ]
    assert [(item["id"], item["family"]) for item in model_catalog(settings)] == [
        ("claude-haiku-4-5-20251001", "claude"),
        ("claude-opus-5", "claude"),
        ("claude-sonnet-4-6", "claude"),
        ("gpt-5.4-mini", "gpt"),
        ("gpt-5.6-luna", "gpt"),
        ("gpt-5.6-sol", "gpt"),
        ("gpt-5.6-terra", "gpt"),
    ]
    assert provider_name_for_model("claude-haiku-4-5-20251001", settings) == "claude_compatible"
    assert provider_name_for_model("claude-opus-5", settings) == "claude_compatible"
    assert provider_name_for_model("claude-sonnet-4-6", settings) == "claude_compatible"
    assert provider_name_for_model("gpt-5.6-sol", settings) == "openai_compatible"
    assert provider_name_for_model("gpt-5.6-terra", settings) == "openai_compatible"
    assert endpoint_for_model("gpt-5.6-terra", settings) == (settings.openai_base_url, settings.openai_api_key)
    assert endpoint_for_model("claude-opus-5", settings) == (settings.translation_base_url, settings.translation_api_key)
    assert endpoint_for_model("claude-sonnet-4-6", settings) == (settings.translation_base_url, settings.translation_api_key)


def test_explicit_allowlist_restricts_selector_without_adding_discovery_models():
    settings = Settings(
        _env_file=None,
        ai_allowed_models="gpt-5.4-mini,claude-haiku-4-5-20251001",
    )

    assert allowed_models(settings) == ["claude-haiku-4-5-20251001", "gpt-5.4-mini"]
    assert "openai/gpt-5.4" not in allowed_models(settings)
